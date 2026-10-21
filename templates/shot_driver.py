#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多镜头链式生成 · 单镜执行器模板（端脑云 lucy.run Workbench 路线，8 镜全链实跑验证）

用法: python3 shot_driver.py <shot_id>
- 从 spec 读每镜参数（提示词/seed 以 json 为准，不改写）
- 首镜 t2v 直提交；后续镜取上一镜尾帧上传作 first_frame 做 i2v 链式
- 提交后 --wait 轮询到完成，下载产物 + sha256 校验，抽头/中/尾三帧供质检
- ledger.json 记账（run_id/扣费/文件），预算守护超线即停

复制后按项目调整下方「三个常量」。配套纪律见 references/lucy-workflow-api.md 的
「链式多镜任务单执行纪律」（尾帧门 / 余额差值对账 / 重抽机制）。
"""
import sys, os, json, subprocess, time
from pathlib import Path

# ===== 复制后按项目调整这三个常量 =====
ROOT = Path(os.environ.get("SHOTS_WORKDIR", "./baimei_ep1"))  # 本任务工作/输出目录（env 可覆盖）
SPEC_PATH = Path(os.environ.get("SHOTS_SPEC", "./baimei_ep1_shots_spec.json"))  # 镜头参数 spec（shots[].id/mode/seed/positive/negative）
TOKEN_FILE = Path(os.environ.get("LUCY_TOKEN_FILE", "./lucy_state/token.txt"))  # lucy Workbench JWT（lucy_run.py login 产出）
# ====================================
SCRIPTS = os.environ.get("LUCY_RUN_DIR", str(Path(__file__).resolve().parent.parent / "scripts"))  # lucy_run.py 所在目录
LEDGER_PATH = ROOT / "ledger.json"
BUDGET_CAP_CEP = 80.0   # 任务单预算红线（CEP）；5.0 为单镜实价（5s 档）

def load_ledger():
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return {"shots": {}, "total_cep": 0.0, "run_ids": []}

def save_ledger(l):
    LEDGER_PATH.write_text(json.dumps(l, ensure_ascii=False, indent=1))

def spent_cep():
    l = load_ledger()
    return sum(s.get("cep", 0) for s in l["shots"].values())

def run_lucy(args, timeout=320):
    env = dict(os.environ)
    if TOKEN_FILE.exists():
        env["LUCY_UC_TOKEN"] = TOKEN_FILE.read_text().strip()
    r = subprocess.run(["python3", f"{SCRIPTS}/lucy_run.py"] + args,
                       capture_output=True, text=True, timeout=timeout, env=env, cwd=SCRIPTS)
    return r.returncode, r.stdout, r.stderr

def extract_tail(mp4: Path, jpg: Path):
    # 尾帧：JPG（勿用 PNG），取最后一帧作下一镜首帧
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
                    "-i", str(mp4), "-frames:v", "1", "-q:v", "2", str(jpg)],
                   check=True, timeout=60)

def extract_frames(mp4: Path, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    # 头/中/尾三帧供质检
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4),
                    "-vf", "select=eq(n\\,0)+eq(n\\,60)+eq(n\\,118)",
                    "-vsync", "0", "-q:v", "2", str(outdir / "f_%d.jpg")],
                   check=True, timeout=60)

def main():
    shot_id = int(sys.argv[1])
    ROOT.mkdir(parents=True, exist_ok=True)
    SPEC = json.load(open(SPEC_PATH))
    spec_shots = {s["id"]: s for s in SPEC["shots"]}
    sh = dict(spec_shots[shot_id])
    # seed 覆盖（坏镜重抽 seed+1，原 spec 不改写）
    _ov_path = ROOT / "retry_seeds.json"
    if _ov_path.exists():
        _ov = json.loads(_ov_path.read_text())
        if str(shot_id) in _ov:
            sh["seed"] = _ov[str(shot_id)]
            print(f"seed override -> {sh['seed']}")
    ledger = load_ledger()

    # 幂等：本镜已成功则跳过（重抽前先把该镜 status 改为非 completed）
    if ledger["shots"].get(str(shot_id), {}).get("status") == "completed":
        print(f"SHOT{shot_id} 已完成，跳过")
        return

    # 预算守护
    spent = spent_cep()
    if spent + 5.0 > BUDGET_CAP_CEP:
        print(f"BUDGET_STOP: 已花 {spent:.2f} CEP，下一镜将超 {BUDGET_CAP_CEP} 上限")
        sys.exit(2)

    mp4 = ROOT / f"shot{shot_id}.mp4"
    # 模式判定：t2v 或 i2v（以上一镜尾帧为首帧）
    args = ["submit", "--template", sh["mode"], "--seconds", "5",
            "--ratio", "1609", "--resolution", "480", "--seed", str(sh["seed"]),
            "--prompt", sh["positive"], "--yes", "--wait", "270"]
    if sh["mode"] == "i2v":
        prev = shot_id - 1
        tail = ROOT / f"tail_shot{prev}.jpg"
        if not tail.exists():
            prev_mp4 = ROOT / f"shot{prev}.mp4"
            extract_tail(prev_mp4, tail)
        print(f"上传首帧 {tail} ...")
        rc, out, err = run_lucy(["upload", str(tail)])
        if rc != 0:
            print(f"UPLOAD_FAIL: {out} {err}")
            sys.exit(3)
        # 输出格式: "asset_id: {aid}"
        asset_id = None
        for line in out.splitlines():
            if line.startswith("asset_id:"):
                asset_id = line.split(":", 1)[1].strip()
        if not asset_id:
            print(f"ASSET_PARSE_FAIL: {out[:300]}")
            sys.exit(3)
        print("asset_id:", asset_id)
        args += ["--image", f"first_frame={asset_id}"]

    print(f"提交 SHOT{shot_id} ({sh['mode']}, seed={sh['seed']}) ...")
    t0 = time.time()
    rc, out, err = run_lucy(args, timeout=340)
    print(out)
    if rc != 0:
        print(f"SUBMIT_FAIL rc={rc}: {err[:400]}")
        sys.exit(4)

    # 解析输出: "已提交: run_id={run_id} status=..." 与 "报价: {amount} units = {cep} CEP"
    run_id, cep = None, None
    for line in out.splitlines():
        if "run_id=" in line:
            run_id = line.split("run_id=")[1].split()[0].strip()
        if "CEP" in line and "units" in line:
            try:
                cep = float(line.split("=")[1].split("CEP")[0].strip())
            except Exception:
                pass
    if not run_id:
        # 从状态文件兑底
        runs_dir = Path(SCRIPTS) / "lucy_state" / "runs"
        if runs_dir.exists():
            newest = max(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
            d = json.loads(newest.read_text())
            run_id = d.get("run_id") or newest.stem
    print(f"run_id={run_id} cep={cep} elapsed={time.time()-t0:.0f}s")

    # 下载（-o 指定输出目录，文件名 {run_id[:12]}_0.mp4）
    print("下载产物...")
    rc, out, err = run_lucy(["download", run_id, "-o", str(ROOT)], timeout=240)
    print(out[:600])
    if rc != 0:
        print(f"DOWNLOAD_FAIL: {err[:300]}")
        sys.exit(5)
    expected = ROOT / f"{run_id[:12]}_0.mp4"
    if not expected.exists():
        cands = sorted(ROOT.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        expected = cands[0] if cands else None
    if not expected:
        print("NO_MP4_FOUND")
        sys.exit(6)
    subprocess.run(["mv", str(expected), str(mp4)], check=True)
    size = mp4.stat().st_size
    print(f"saved {mp4} ({size/1e6:.2f} MB)")

    # 抽帧
    extract_frames(mp4, ROOT / f"frames_shot{shot_id}")
    extract_tail(mp4, ROOT / f"tail_shot{shot_id}.jpg")

    # 记账（重抽镜请另建 attempts 数组逐 run 记，避免同键覆盖漏账）
    rec = ledger["shots"].get(str(shot_id), {"retries": 0})
    rec.update({"status": "completed", "run_id": run_id,
                "cep": (cep or rec.get("cep") or 5.0),
                "file": str(mp4), "size": size})
    ledger["shots"][str(shot_id)] = rec
    if run_id not in ledger["run_ids"]:
        ledger["run_ids"].append(run_id)
    ledger["total_cep"] = sum(s.get("cep", 0) for s in ledger["shots"].values())
    save_ledger(ledger)
    print(f"SHOT{shot_id} DONE | 扣费 {rec['cep']} CEP | 累计 {ledger['total_cep']:.2f} CEP")

if __name__ == "__main__":
    main()

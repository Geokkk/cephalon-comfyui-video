#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雨后森林小木屋 · 治愈系日系手绘动画 — 8 镜头链式生成流水线。

用法:
  python run_fairy_pipeline.py create              # 创建/复用实例，等待就绪
  python run_fairy_pipeline.py shot1               # 镜1 T2V（含尾帧提取）
  python run_fairy_pipeline.py shot <n>            # 镜 n I2V（用镜 n-1 尾帧）
  python run_fairy_pipeline.py download <n>        # 补下载镜 n 产物
  python run_fairy_pipeline.py close               # 关闭实例停止计费
  python run_fairy_pipeline.py status              # 查看实例状态

每镜头产物: <工作目录>/outputs/shotNN_*.mp4 + tail_shotNN.png
全部完成后用 concat_fairy.py 拼接成片。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

socket.setdefaulttimeout(180)  # 隧道不稳：所有请求/下载默认 180s 超时，防止无限挂起

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "cephalon_state.json")
OUT_DIR = os.path.join(HERE, "outputs")
SPEC = os.path.join(HERE, "shots_spec.json")
POLL = 20
MAX_WAIT = 3600
VIDEO_EXT = (".mp4", ".webm", ".mov", ".gif", ".mkv")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def http_json(url, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get_urls(mid):
    st = mission_status(mid)
    d = st.get("data") or {}
    urls_raw = d.get("urls")
    if isinstance(urls_raw, str) and urls_raw.strip():
        try:
            arr = json.loads(urls_raw)
            if isinstance(arr, list) and arr:
                return [u for u in arr if u], d
        except Exception:
            pass
    try:
        r = mission_access(mid)
        if isinstance(r.get("data"), dict):
            pair = [u for u in (r["data"].get("frpc_address", ""),
                                r["data"].get("fb_address", "")) if u]
            if pair:
                return pair, d
    except Exception:
        pass
    return [], d


def wait_ready(mid):
    deadline = time.time() + MAX_WAIT
    last = ""
    while time.time() < deadline:
        st = mission_status(mid)
        d = st.get("data") or {}
        state = str(d.get("state") or d.get("status") or st)
        if state != last:
            print(f"[{time.strftime('%H:%M:%S')}] state = {state}", flush=True)
            last = state
        if state in ("supplying", "doing"):
            return d
        if state in ("failed", "canceled", "cancelled", "closed", "expired"):
            raise SystemExit(f"任务异常结束: {json.dumps(st, ensure_ascii=False)[:400]}")
        time.sleep(POLL)
    raise SystemExit("等待实例就绪超时，可重新运行 create")


def cmd_create():
    from cephalon_api import mission_create, mission_status, mission_access
    globals()["mission_status"] = mission_status
    globals()["mission_access"] = mission_access
    st = load_state()
    mid = None
    if st.get("mission_id"):
        d_old = mission_status(st["mission_id"]).get("data") or {}
        old_state = str(d_old.get("state") or "")
        if old_state in ("waiting", "doing", "supplying"):
            print(f"发现未完成实例 {st['mission_id']}（state={old_state}），复用而不新建", flush=True)
            mid = st["mission_id"]
    if mid is None:
        print("== 创建 comfyui_time 实例（RTX4090 x1）==", flush=True)
        r = mission_create("comfyui_time", gpu_num=1, batch_size=1)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        ids = r.get("data") or []
        if not ids:
            raise SystemExit("创建失败，见上方返回")
        mid = str(ids[0])
        save_state({"mission_id": mid, "urls": None, "base": None})
        print(f"mission_id = {mid}（已立即落盘，防孤儿）", flush=True)
    print("== 等待实例就绪（waiting → supplying）==", flush=True)
    wait_ready(mid)
    urls, d = [], {}
    for attempt in range(10):
        urls, d = get_urls(mid)
        if urls:
            break
        print(f"[{time.strftime('%H:%M:%S')}] urls 未下发（第 {attempt + 1} 次重试，doing 时序属正常）",
              flush=True)
        time.sleep(30)
    if not urls:
        raise SystemExit(f"未取到访问地址: {json.dumps(d, ensure_ascii=False)[:400]}")
    base = urls[0].rstrip("/")
    print(f"访问地址: {urls}", flush=True)
    st = load_state()
    st.update({"mission_id": mid, "urls": urls, "base": base})
    save_state(st)
    print(f"状态已保存: {STATE_FILE}", flush=True)
    # 记录进度文件
    prog = os.path.join(HERE, "fairy_progress.json")
    if not os.path.exists(prog):
        with open(prog, "w") as f:
            json.dump({"shot1": None, "chain": {}}, f)


def cmd_shot1():
    from cephalon_api import mission_status
    globals()["mission_status"] = mission_status
    st = load_state()
    base, mid = st.get("base"), st.get("mission_id")
    if not base or not mid:
        raise SystemExit("无实例状态，先运行 create")
    d_now = mission_status(mid).get("data") or {}
    if str(d_now.get("state") or "") not in ("supplying", "doing"):
        raise SystemExit(f"实例状态 {d_now.get('state')}（不在计费中），不提交")
    os.makedirs(OUT_DIR, exist_ok=True)
    # 构建镜1 T2V 工作流
    out_wf = os.path.join(OUT_DIR, "wf_shot1.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_ti2v_t2v.py"),
                        SPEC, "1", out_wf], capture_output=True, text=True)
    print(r.stdout, flush=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    # 提交
    with open(out_wf) as f:
        wf = json.load(f)
    print(f"== 提交镜1 T2V → {base}/prompt ==", flush=True)
    r = http_json(f"{base}/prompt", method="POST", body=wf, timeout=300)
    pid = r.get("prompt_id") if isinstance(r, dict) else None
    if not pid:
        raise SystemExit(f"提交失败: {json.dumps(r, ensure_ascii=False)[:600]}")
    print(f"prompt_id = {pid}", flush=True)
    # 轮询
    deadline = time.time() + MAX_WAIT
    history = None
    while time.time() < deadline:
        h = http_json(f"{base}/history/{pid}")
        if isinstance(h, dict) and h.get(pid):
            history = h[pid]
            status = history.get("status", {}) or {}
            print(f"[{time.strftime('%H:%M:%S')}] status={status.get('status_str')} "
                  f"completed={status.get('completed')}", flush=True)
            if status.get("completed") or history.get("outputs"):
                break
        time.sleep(POLL)
    if not history:
        raise SystemExit("镜1 生成超时")
    outputs = history.get("outputs", {})
    video_file = None
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for item in node_out.values():
            if not isinstance(item, list):
                continue
            for it in item:
                if isinstance(it, dict) and it.get("filename"):
                    fn, sub, typ = it["filename"], it.get("subfolder", ""), it.get("type", "output")
                    url = (f"{base}/view?filename={urllib.parse.quote(fn)}"
                           f"&subfolder={urllib.parse.quote(sub)}&type={typ}")
                    dest = os.path.join(OUT_DIR, fn)
                    urllib.request.urlretrieve(url, dest)
                    print(f"已下载: {dest}", flush=True)
                    if fn.lower().endswith(VIDEO_EXT):
                        video_file = dest
    if not video_file:
        raise SystemExit("镜1 未取到视频产物")
    # 提取尾帧（JPG：链式条件用，体积小上传快；PNG 留作存档）
    tail = os.path.join(OUT_DIR, "tail_shot01.jpg")
    ff = subprocess.run(["ffmpeg", "-y", "-sseof", "-0.15", "-i", video_file,
                         "-frames:v", "1", "-q:v", "2", tail], capture_output=True, text=True)
    if ff.returncode != 0 or not os.path.exists(tail):
        print(ff.stderr[-500:], flush=True)
        raise SystemExit("尾帧提取失败")
    size = os.path.getsize(tail)
    print(f"尾帧已提取: {tail}（{size} 字节）", flush=True)
    prog = os.path.join(HERE, "fairy_progress.json")
    with open(prog) as f:
        p = json.load(f)
    p["shot1"] = {"video": video_file, "tail": tail, "prompt_id": pid}
    with open(prog, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    print("镜1 完成 ✓", flush=True)


def cmd_shot(n):
    from cephalon_api import mission_status
    globals()["mission_status"] = mission_status
    st = load_state()
    base, mid = st.get("base"), st.get("mission_id")
    if not base or not mid:
        raise SystemExit("无实例状态，先运行 create")
    d_now = mission_status(mid).get("data") or {}
    if str(d_now.get("state") or "") not in ("supplying", "doing"):
        raise SystemExit(f"实例状态 {d_now.get('state')}（不在计费中），不提交")
    os.makedirs(OUT_DIR, exist_ok=True)
    prev_tail = os.path.join(OUT_DIR, f"tail_shot{n-1:02d}.jpg")
    if not os.path.exists(prev_tail):
        # 兼容早期 PNG 尾帧
        prev_tail = os.path.join(OUT_DIR, f"tail_shot{n-1:02d}.png")
    if not os.path.exists(prev_tail):
        raise SystemExit(f"上一镜尾帧不存在: {prev_tail}（先完成镜 {n-1}）")
    out_wf = os.path.join(OUT_DIR, f"wf_shot{n}.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_ti2v_i2v.py"),
                        SPEC, str(n), prev_tail, out_wf], capture_output=True, text=True)
    print(r.stdout, flush=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    with open(out_wf) as f:
        wf = json.load(f)
    print(f"== 提交镜{n} I2V → {base}/prompt ==", flush=True)
    pid = None
    for attempt in range(5):
        try:
            r = http_json(f"{base}/prompt", method="POST", body=wf, timeout=300)
            pid = r.get("prompt_id") if isinstance(r, dict) else None
            if pid:
                print(f"prompt_id = {pid}（第 {attempt + 1} 次尝试成功）", flush=True)
                break
            raise SystemExit(f"提交失败: {json.dumps(r, ensure_ascii=False)[:600]}")
        except SystemExit:
            raise
        except Exception as e:
            # 隧道不稳：POST 上传被打断时重试（若实际已入队，重提交会被服务端拒绝，无重复生成风险）
            print(f"[{time.strftime('%H:%M:%S')}] 第 {attempt + 1} 次提交失败（{type(e).__name__}），"
                  f"20s 后重试", flush=True)
            time.sleep(20)
    if not pid:
        print(f"[{time.strftime('%H:%M:%S')}] 提交 5 次均失败，转扫 history 确认是否已入队", flush=True)
    deadline = time.time() + MAX_WAIT
    history = None
    prefix = f"shot{n:02d}_"
    while time.time() < deadline:
        try:
            if pid:
                h = http_json(f"{base}/history/{pid}")
                entry = h.get(pid) if isinstance(h, dict) else None
            else:
                h = http_json(f"{base}/history")
                entry = None
                if isinstance(h, dict):
                    for ep in h.values():
                        outs = ep.get("outputs", {}) or {}
                        found = any(
                            isinstance(it, dict) and str(it.get("filename", "")).startswith(prefix)
                            for no in outs.values() if isinstance(no, dict)
                            for v in no.values() if isinstance(v, list)
                            for it in v)
                        if found:
                            entry = ep
                            break
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] 查询异常 {type(e).__name__}，继续轮询", flush=True)
            time.sleep(POLL)
            continue
        if entry:
            history = entry
            status = history.get("status", {}) or {}
            print(f"[{time.strftime('%H:%M:%S')}] status={status.get('status_str')} "
                  f"completed={status.get('completed')}", flush=True)
            if status.get("completed") or history.get("outputs"):
                break
        time.sleep(POLL)
    if not history:
        raise SystemExit(f"镜{n} 生成超时")
    outputs = history.get("outputs", {})
    video_file = None
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for item in node_out.values():
            if not isinstance(item, list):
                continue
            for it in item:
                if isinstance(it, dict) and it.get("filename"):
                    fn, sub, typ = it["filename"], it.get("subfolder", ""), it.get("type", "output")
                    url = (f"{base}/view?filename={urllib.parse.quote(fn)}"
                           f"&subfolder={urllib.parse.quote(sub)}&type={typ}")
                    dest = os.path.join(OUT_DIR, fn)
                    urllib.request.urlretrieve(url, dest)
                    print(f"已下载: {dest}", flush=True)
                    if fn.lower().endswith(VIDEO_EXT):
                        video_file = dest
    if not video_file:
        raise SystemExit(f"镜{n} 未取到视频产物")
    tail = os.path.join(OUT_DIR, f"tail_shot{n:02d}.jpg")
    ff = subprocess.run(["ffmpeg", "-y", "-sseof", "-0.15", "-i", video_file,
                         "-frames:v", "1", "-q:v", "2", tail], capture_output=True, text=True)
    if ff.returncode != 0 or not os.path.exists(tail):
        print(ff.stderr[-500:], flush=True)
        raise SystemExit("尾帧提取失败")
    size = os.path.getsize(tail)
    print(f"尾帧已提取: {tail}（{size} 字节）", flush=True)
    prog = os.path.join(HERE, "fairy_progress.json")
    with open(prog) as f:
        p = json.load(f)
    p["chain"][str(n)] = {"video": video_file, "tail": tail, "prompt_id": pid}
    with open(prog, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    print(f"镜{n} 完成 ✓", flush=True)


def cmd_download(n):
    """按 fairy_progress.json 里的 prompt_id 补下载产物（用于中断恢复）。"""
    st = load_state()
    base = st.get("base")
    if not base:
        raise SystemExit("无实例状态，先运行 create")
    prog = os.path.join(HERE, "fairy_progress.json")
    with open(prog) as f:
        p = json.load(f)
    if n == 1:
        entry = p.get("shot1")
    else:
        entry = p.get("chain", {}).get(str(n))
    if not entry or not entry.get("prompt_id"):
        raise SystemExit(f"镜{n} 无 prompt_id 记录")
    pid = entry["prompt_id"]
    h = http_json(f"{base}/history/{pid}")
    if not (isinstance(h, dict) and h.get(pid)):
        raise SystemExit(f"history 无 {pid}")
    outputs = h[pid].get("outputs", {})
    os.makedirs(OUT_DIR, exist_ok=True)
    video_file = None
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for item in node_out.values():
            if not isinstance(item, list):
                continue
            for it in item:
                if isinstance(it, dict) and it.get("filename"):
                    fn, sub, typ = it["filename"], it.get("subfolder", ""), it.get("type", "output")
                    url = (f"{base}/view?filename={urllib.parse.quote(fn)}"
                           f"&subfolder={urllib.parse.quote(sub)}&type={typ}")
                    dest = os.path.join(OUT_DIR, fn)
                    urllib.request.urlretrieve(url, dest)
                    print(f"已下载: {dest}", flush=True)
                    if fn.lower().endswith(VIDEO_EXT):
                        video_file = dest
    print(f"镜{n} 补下载完成，视频: {video_file}", flush=True)


def cmd_close():
    from cephalon_api import mission_close, mission_status
    st = load_state()
    mid = st.get("mission_id")
    if not mid:
        raise SystemExit("无实例状态，先运行 create")
    d = mission_status(mid).get("data") or {}
    print(f"== 关闭实例 {mid}（当前 state={d.get('state')}）==", flush=True)
    print(json.dumps(mission_close([mid]), ensure_ascii=False), flush=True)
    st["state"] = "closed_by_script"
    st["closed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    save_state(st)
    print("state 已标记 closed_by_script，下次 create 会新建实例", flush=True)


def cmd_status():
    from cephalon_api import mission_status
    st = load_state()
    mid = st.get("mission_id")
    if not mid:
        raise SystemExit("无实例状态")
    print(json.dumps(mission_status(mid), ensure_ascii=False, indent=2))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "create":
        cmd_create()
    elif cmd == "shot1":
        cmd_shot1()
    elif cmd == "shot":
        if len(args) < 2:
            raise SystemExit("用法: python run_fairy_pipeline.py shot <n>")
        cmd_shot(int(args[1]))
    elif cmd == "download":
        if len(args) < 2:
            raise SystemExit("用法: python run_fairy_pipeline.py download <n>")
        cmd_download(int(args[1]))
    elif cmd == "close":
        cmd_close()
    elif cmd == "status":
        cmd_status()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

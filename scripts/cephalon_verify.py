#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端脑云 → ComfyUI 视频生成链路验证脚本。

子命令:
  python cephalon_verify.py create            # 创建 comfyui_time 实例, 等待就绪, 检查可用模型, 保存状态
  python cephalon_verify.py submit <wf.json>  # 提交 API 工作流, 轮询 history, 下载产物到 outputs/
  python cephalon_verify.py status            # 查看当前实例状态
  python cephalon_verify.py close             # 关闭实例停止计费
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from cephalon_api import mission_create, mission_status, mission_close, mission_access

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "cephalon_state.json")
OUT_DIR = os.path.join(HERE, "outputs")
POLL = 20
MAX_WAIT = 1800
VIDEO_EXT = (".mp4", ".webm", ".mov", ".gif", ".mkv")


def http_json(url, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def get_urls(mid):
    """直连任务: urls 在 mission 状态里; 负载均衡服务: 走 access-address 接口。"""
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


def inspect_comfyui(base):
    print("== 检查 ComfyUI 可用模型加载器 ==")
    for node in ("CheckpointLoaderSimple", "UNETLoader", "VAELoader", "CLIPLoader"):
        try:
            info = http_json(f"{base}/object_info/{node}")
            spec = info.get(node, {}).get("input", {}).get("required", {})
            choices = []
            for v in spec.values():
                if isinstance(v, list) and v and isinstance(v[0], list):
                    choices = v[0]
                    break
            print(f"{node}: {choices}")
        except Exception as e:
            print(f"{node}: 不可用 ({e})")
    print("-- 视频相关节点探测 --")
    for node in ("WanImageToVideo", "Wan22ImageToVideo", "SVD_img2vid_Conditioning",
                 "LTXVImgToVideo", "HunyuanImageToVideo", "AnimateDiffCombine",
                 "VHS_VideoCombine", "SaveVideo", "SaveWEBM", "SaveAnimatedWEBP"):
        try:
            http_json(f"{base}/object_info/{node}")
            print(f"{node}: 存在")
        except Exception:
            print(f"{node}: 不存在")


def cmd_create():
    # 防孤儿：先检查已有未完成实例，创建成功后立即落盘 mission_id 再等待
    st = load_state()
    mid = None
    if st.get("mission_id"):
        d_old = mission_status(st["mission_id"]).get("data") or {}
        old_state = str(d_old.get("state") or "")
        if old_state in ("waiting", "doing", "supplying"):
            print(f"发现未完成实例 {st['mission_id']}（state={old_state}），复用而不新建", flush=True)
            mid = st["mission_id"]
    if mid is None:
        print("== 1. 创建 comfyui_time 实例（RTX4090 x1）==", flush=True)
        r = mission_create("comfyui_time", gpu_num=1, batch_size=1)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        ids = r.get("data") or []
        if not ids:
            raise SystemExit("创建失败，见上方返回")
        mid = str(ids[0])
        # 关键：立即落盘。即使后续等待被中断/超时被杀，ID 也不会丢失成孤儿
        save_state({"mission_id": mid, "urls": None, "base": None})
        print(f"mission_id = {mid}（已立即落盘，防孤儿）", flush=True)
    print("== 2. 等待实例就绪（waiting → supplying）==", flush=True)
    wait_ready(mid)
    urls, d = get_urls(mid)
    if not urls:
        raise SystemExit(f"未取到访问地址: {json.dumps(d, ensure_ascii=False)[:400]}")
    base = urls[0].rstrip("/")
    print(f"访问地址: {urls}", flush=True)
    save_state({"mission_id": mid, "urls": urls, "base": base})
    print(f"状态已保存: {STATE_FILE}", flush=True)
    inspect_comfyui(base)


def cmd_submit(wf_path):
    st = load_state()
    base = st.get("base")
    mid = st.get("mission_id")
    if not base or not mid:
        raise SystemExit("无实例状态，先运行 create")
    # 防浪费：提交前确认实例仍在计费中（避免向已关闭实例提交后空等）
    d_now = mission_status(mid).get("data") or {}
    now_state = str(d_now.get("state") or "")
    if now_state not in ("supplying", "doing"):
        raise SystemExit(f"实例 {mid} 状态为 {now_state}（不在计费中），不提交。如需重新生成请先 create")
    with open(wf_path) as f:
        wf = json.load(f)
    if "prompt" not in wf:
        wf = {"prompt": wf}  # API 格式需包 prompt 外层
    print(f"== 3. 提交工作流 {os.path.basename(wf_path)} → {base}/prompt ==", flush=True)
    r = http_json(f"{base}/prompt", method="POST", body=wf)
    pid = None
    if isinstance(r, dict):
        pid = r.get("prompt_id")
        if not pid and isinstance(r.get("data"), dict):
            pid = r["data"].get("prompt_id")
    if not pid:
        raise SystemExit(f"提交失败: {json.dumps(r, ensure_ascii=False)[:600]}")
    print(f"prompt_id = {pid}", flush=True)
    print("== 4. 轮询 /history 等待生成完成 ==", flush=True)
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
        raise SystemExit("生成超时，可在浏览器打开实例 UI 查看队列")
    outputs = history.get("outputs", {})
    os.makedirs(OUT_DIR, exist_ok=True)
    downloaded = []
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for item in node_out.values():
            if not isinstance(item, list):
                continue
            for it in item:
                if isinstance(it, dict) and it.get("filename"):
                    fn = it["filename"]
                    sub = it.get("subfolder", "")
                    typ = it.get("type", "output")
                    url = (f"{base}/view?filename={urllib.parse.quote(fn)}"
                           f"&subfolder={urllib.parse.quote(sub)}&type={typ}")
                    dest = os.path.join(OUT_DIR, fn)
                    urllib.request.urlretrieve(url, dest)
                    downloaded.append(dest)
                    print(f"已下载: {dest}", flush=True)
    videos = [d for d in downloaded if d.lower().endswith(VIDEO_EXT)]
    print(f"共取回 {len(downloaded)} 个文件，其中视频 {len(videos)} 个", flush=True)
    for v in videos:
        print(f"  视频: {v}")
    st2 = mission_status(mid)
    print("实例状态:", json.dumps(st2.get("data", {}).get("state", st2), ensure_ascii=False), flush=True)


def cmd_close():
    st = load_state()
    mid = st.get("mission_id")
    if not mid:
        raise SystemExit("无实例状态，先运行 create")
    print(f"== 关闭实例 {mid} 停止计费 ==", flush=True)
    print(json.dumps(mission_close([mid]), ensure_ascii=False), flush=True)


def cmd_status():
    st = load_state()
    mid = st.get("mission_id")
    if not mid:
        raise SystemExit("无实例状态，先运行 create")
    print(json.dumps(mission_status(mid), ensure_ascii=False, indent=2))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "create":
        cmd_create()
    elif args[0] == "submit":
        if len(args) < 2:
            raise SystemExit("用法: python cephalon_verify.py submit <wf.json>")
        cmd_submit(args[1])
    elif args[0] == "close":
        cmd_close()
    elif args[0] == "status":
        cmd_status()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

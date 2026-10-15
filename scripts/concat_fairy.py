#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""8 镜头拼接成片 — ffmpeg xfade 柔和交叉过渡（0.5s）。

用法: python concat_fairy.py [out.mp4]
输入: outputs/shot01*.mp4 ... shot08*.mp4（fairy_progress.json 记录的顺序）
输出: 默认 ~/workspace/AI video/成品视频/fairy_after_rain.mp4（可用环境变量 CEPHALON_FAIRY_OUT 覆盖）
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")
PROG = os.path.join(HERE, "fairy_progress.json")
FADE = 0.5
FPS = 24


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CEPHALON_FAIRY_OUT") or \
        os.path.join(os.path.expanduser("~"), "workspace", "AI video", "成品视频", "fairy_after_rain.mp4")
    with open(PROG) as f:
        p = json.load(f)
    videos = []
    if p.get("shot1"):
        videos.append(p["shot1"]["video"])
    for i in range(2, 9):
        e = p.get("chain", {}).get(str(i))
        if e and e.get("video"):
            videos.append(e["video"])
    if len(videos) != 8:
        raise SystemExit(f"只有 {len(videos)} 个镜头视频（需 8 个），先完成全部镜头")
    for v in videos:
        if not os.path.exists(v):
            raise SystemExit(f"文件不存在: {v}")
        print(f"  {duration(v):6.2f}s  {v}")

    # 逐级 xfade：每两级合并，offset = 已累计时长 - fade
    # 为避免长 filter_complex 一步出错难排查，分两两合并成中间文件
    os.makedirs(os.path.join(OUT_DIR, "concat_tmp"), exist_ok=True)
    tmp = os.path.join(OUT_DIR, "concat_tmp")
    cur = videos[0]
    acc = duration(cur)
    for i, v in enumerate(videos[1:], start=2):
        nxt = v
        merged = os.path.join(tmp, f"merge_{i:02d}.mp4")
        offset = acc - FADE
        vf = (f"[0:v][1:v]xfade=transition=fade:duration={FADE}:offset={offset:.3f},"
              f"fps={FPS},format=yuv420p")
        r = subprocess.run(["ffmpeg", "-y", "-i", cur, "-i", nxt,
                            "-filter_complex", vf, "-c:v", "libx264",
                            "-preset", "medium", "-crf", "18", "-an", merged],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-800:], flush=True)
            raise SystemExit(f"合并第 {i} 段失败")
        cur = merged
        acc = duration(cur)
        print(f"  合并 {i}/8 完成: {acc:.2f}s", flush=True)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-i", cur, "-c", "copy", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-500:], flush=True)
        raise SystemExit("最终输出失败")
    print(f"\n成片完成: {out}（{duration(out):.2f}s）", flush=True)


if __name__ == "__main__":
    main()

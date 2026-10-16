#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wan2.2 TI2V 5B — T2V 工作流生成器（首镜用）。

参数: python build_ti2v_t2v.py <shots_spec.json> <shot_id> <out.json>
参数取自官方模板 video_wan2_2_5B_ti2v.json（20 步/cfg 5/uni_pc/shift 8/fps 24）。
"""
import json
import sys


def build(spec, shot):
    return {
        "11": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "12": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "device": "default", "type": "wan"}},
        "13": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "14": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["11", 0], "shift": 8.0}},
        "21": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["12", 0], "text": shot["positive"]}},
        "22": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["12", 0], "text": shot["negative"]}},
        "31": {"class_type": "Wan22ImageToVideoLatent", "inputs": {
            "vae": ["13", 0], "width": 1280, "height": 704,
            "length": int(shot["length"]), "batch_size": 1}},
        "41": {"class_type": "KSampler", "inputs": {
            "seed": int(shot["seed"]), "steps": 20, "cfg": 5.0,
            "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0,
            "model": ["14", 0], "positive": ["21", 0], "negative": ["22", 0],
            "latent_image": ["31", 0]}},
        "51": {"class_type": "VAEDecode", "inputs": {"samples": ["41", 0], "vae": ["13", 0]}},
        "61": {"class_type": "CreateVideo", "inputs": {"fps": 24.0, "images": ["51", 0]}},
        "71": {"class_type": "SaveVideo", "inputs": {
            "codec": "auto", "format": "auto",
            "filename_prefix": f"video/shot{int(shot['id']):02d}_t2v", "video": ["61", 0]}},
    }


def main():
    spec_path, shot_id, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    with open(spec_path) as f:
        spec = json.load(f)
    shot = next(s for s in spec["shots"] if s["id"] == shot_id)
    wf = {"prompt": build(spec, shot)}
    with open(out_path, "w") as f:
        json.dump(wf, f, ensure_ascii=False)
    print(f"已生成 {out_path}（{shot_id} 号镜头 T2V, {shot['length']} 帧）")


if __name__ == "__main__":
    main()

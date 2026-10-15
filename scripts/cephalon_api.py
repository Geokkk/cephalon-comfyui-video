#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cephalon Cloud（端脑云）API 签名工具与 CLI。

HMAC-SHA256 签名算法（按端脑云官方文档实现）：
  str_data = JSON( requestURI + 规范化body )
  Hmac = hex( HMAC-SHA256(str_data, secret) )
  请求头: Hmac-Key: <key>, Hmac: <hmac>

用法:
  python cephalon_api.py missions                # 列出我的任务
  python cephalon_api.py create                  # 创建 1 台 comfyui_time 实例
  python cephalon_api.py create <type> [gpu_num] # 指定类型/GPU数创建
  python cephalon_api.py status <mission_id>     # 查询任务状态
  python cephalon_api.py access <mission_id>     # 获取访问地址
  python cephalon_api.py close <id1,id2,...>     # 关闭任务
"""
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request

try:
    from cephalon_keys import KEY, SECRET
except (ImportError, RuntimeError):
    KEY = SECRET = None

USER_CENTER = "https://prod.unicorn.org.cn/cephalon/user-center"
CEPHALON = "https://cephalon.cloud"

# requestURI 是相对 user-center 的相对路径（参与 HMAC 签名，实测 /v1/load-balance 通过）
# 各接口的实际 URL 拼接：USER_CENTER + relative_path


def sign(request_uri: str, body=None) -> str:
    """requestURI 是相对 user-center 基础路径的相对路径（如 /v1/load-balance），
    实测验证：不带 /cephalon/user-center 前缀。body 规范化（排序）后拼接再整体 JSON 化。"""
    if not KEY or not SECRET:
        raise RuntimeError("缺少 HMAC 密钥：设置 CEPHALON_PUBLIC_KEY/CEPHALON_PRIVATE_KEY "
                           "环境变量，或创建 cephalon_keys_local.py（参考 cephalon_keys.py 模板）")
    data_str = request_uri
    if body:
        normalized = json.loads(json.dumps(body))
        data_str += json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    payload = json.dumps(data_str, separators=(",", ":")).encode()
    return hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


def _headers(request_uri: str, body=None) -> dict:
    return {
        "Hmac-Key": KEY,
        "Hmac": sign(request_uri, body),
        "Content-Type": "application/json",
    }


def _swap_keys():
    """公钥/私钥放反时自动对调重试一次。"""
    global KEY, SECRET
    KEY, SECRET = SECRET, KEY


def request(method: str, url: str, request_uri: str, body=None, timeout: int = 30,
            _swapped: bool = False):
    data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=_headers(request_uri, body), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        if e.code in (401, 403) and not _swapped:
            _swap_keys()
            return request(method, url, request_uri, body, timeout, _swapped=True)
        try:
            return json.loads(raw)
        except Exception:
            return {"code": e.code, "msg": raw[:300]}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def mission_list(page_index: int = 1, page_size: int = 20):
    uri = f"/v1/user/missions?PageIndex={page_index}&PageSize={page_size}"
    return request("GET", USER_CENTER + uri, uri)


def mission_create(mission_type: str = "comfyui_time", gpu_version: str = "RTX4090",
                   gpu_num: int = 1, batch_size: int = 1):
    uri = "/v1/user/missions/batch"
    body = {"batch_size": batch_size, "type": mission_type,
            "gpu_version": gpu_version, "gpu_num": gpu_num}
    return request("POST", USER_CENTER + uri, uri, body)


def mission_status(mission_id: str):
    uri = f"/v1/user/missions/{mission_id}"
    return request("GET", USER_CENTER + uri, uri)


def mission_access(mission_id: str):
    uri = f"/v1/load-balance/access-address/{mission_id}"
    return request("GET", USER_CENTER + uri, uri)


def mission_close(ids: list):
    uri = "/v1/user/missions/close/batch"
    return request("PUT", USER_CENTER + uri, uri, {"ids": ids})


def main():
    if KEY is None or SECRET is None:
        print("缺少密钥对：设置环境变量 CEPHALON_PUBLIC_KEY / CEPHALON_PRIVATE_KEY，")
        print("或创建 cephalon_keys_local.py（参考 cephalon_keys.py 模板说明）")
        sys.exit(1)
    args = sys.argv[1:]
    if not args or args[0] == "missions":
        print(json.dumps(mission_list(), ensure_ascii=False, indent=2))
    elif args[0] == "create":
        mtype = args[1] if len(args) > 1 else "comfyui_time"
        num = int(args[2]) if len(args) > 2 else 1
        print(json.dumps(mission_create(mtype, gpu_num=num), ensure_ascii=False, indent=2))
    elif args[0] == "status":
        print(json.dumps(mission_status(args[1]), ensure_ascii=False, indent=2))
    elif args[0] == "access":
        print(json.dumps(mission_access(args[1]), ensure_ascii=False, indent=2))
    elif args[0] == "close":
        print(json.dumps(mission_close([i.strip() for i in args[1].split(",") if i.strip()]),
                         ensure_ascii=False, indent=2))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

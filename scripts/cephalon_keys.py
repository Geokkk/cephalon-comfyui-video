#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cephalon Cloud HMAC 密钥配置模板
使用方法：
1. 复制为 cephalon_keys_local.py（已加入 .gitignore）
2. 填入你的真实公钥/私钥
3. 或直接设置环境变量 CEPHALON_PUBLIC_KEY / CEPHALON_PRIVATE_KEY
"""

# ⚠️ 请勿提交真实密钥到版本库！
# 运行时优先读环境变量，回退到本地文件

import os

# 从环境变量读取（推荐，CI/容器友好）
KEY = os.environ.get("CEPHALON_PUBLIC_KEY", "")
SECRET = os.environ.get("CEPHALON_PRIVATE_KEY", "")

# 回退：本地文件（需手动创建 cephalon_keys_local.py）
if not KEY or not SECRET:
    try:
        from cephalon_keys_local import KEY as K_KEY, SECRET as K_SECRET
        if not KEY: KEY = K_KEY
        if not SECRET: SECRET = K_SECRET
    except ImportError:
        pass

if not KEY or not SECRET:
    raise RuntimeError("请设置 CEPHALON_PUBLIC_KEY / CEPHALON_PRIVATE_KEY 环境变量，或创建 cephalon_keys_local.py")

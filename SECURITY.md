# 安全政策 / Security Policy

## 支持版本

仅 `main` 分支最新提交。

## 报告漏洞

**请勿在公开 Issue 中披露安全问题。** 请通过 GitHub 的 [Private vulnerability reporting](https://github.com/Geokkk/cephalon-comfyui-video/security/advisories/new) 私密报告，或通过仓库主页的个人联系方式联系作者。承诺 72 小时内首次响应。

### 受理范围

- 本仓库代码缺陷：凭据泄露、命令注入、不安全的默认配置、逻辑错误导致意外扣费
- 文档中与实际接口行为不符且可能造成损失的描述

### 不受理范围

- 端脑云 / Lucy 平台自身的漏洞 → 请报告给平台官方
- 因使用者自行泄露凭据、误操作产生的费用损失
- 针对平台的滥用类问题（本工具不提供绕过平台限制的能力，相关请求一律忽略）

## 凭据说明

本仓库不含任何真实凭据。运行所需的密钥（`CEPHALON_PUBLIC_KEY` / `CEPHALON_PRIVATE_KEY`）与会话 JWT 全部由使用者本地配置，运行时状态保存在 `lucy_state/`（已 gitignore）。如怀疑自己的密钥泄露，请立即在端脑云控制台重置密钥对。

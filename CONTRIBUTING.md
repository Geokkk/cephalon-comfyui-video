# 贡献指南

欢迎 Issue 和 PR。中文/英文均可。

## 提 Issue 前请确认

- 已用 `python scripts/lucy_run.py balance` 确认密钥与网络正常；
- 端点行为类问题请注明发生时间——平台接口随时可能调整（本项目实测基线为 2026-10）；
- **Issue/日志/截图里不要出现你的密钥、token、JWT、账号信息**。

## 提 PR 注意

- 不改动 `scripts/*.py` 的实测结论（计价数字、端点行为、踩坑结论均来自真实付费实测，改动需附新的实测证据）；
- 不引入任何真实凭据、token、本机路径；PR 会过 gitleaks 扫描；
- 新增依赖需说明理由——现有脚本保持纯标准库；
- 文档改动（README/SKILL.md）直接提，无需开 Issue。

## 本地跑通后再提

最小验证：`python scripts/cephalon_verify.py` 与 `python scripts/lucy_run.py balance` 通过。

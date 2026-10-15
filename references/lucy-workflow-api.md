# lucy-agent 工作流链路（2026-10-09 实测验证）

## 图片工作流目录（user-center，HMAC 密钥可用）

- `GET https://prod.unicorn.org.cn/cephalon/user-center/v1/lucy-agent?page_index=1&page_size=20`
- **参数必须小写**（page_index/page_size），PascalCase 会报 30000 参数校验错误
- 返回 35 条工作流（key 全部为 ImageGeneration），字段：workflow_id / tip / count（使用次数）/ preset_text / preset_work_flow_name / is_online
- 工作目录已存 `lucy_catalog.json`

## 运行端点

- `VITE_WORKFLOW_API_URL = .../user-center/v1/lucy-agent/workflows/run`（前端配置确认）
- **警告：POST 会真实运行工作流消耗 CEP，未确认单价前不要调用**

## 余额接口（HMAC 密钥可用）

- `GET /v1/user/balance?symbol_ids=1` → `{"balances": {"1": N}}`，symbol_ids 要**数字 ID**（CEP=1），多值逗号分隔
- 换算关系：100 units = 1 CEP（与 unit_cep=36/小时同体系）

## 换票链路（lucy 侧，需 Bearer JWT，HMAC 密钥不可用）

- 换票端点：`POST .../user-center/v1/platform/sso/tickets`，body `{"app_id":"comfyui_platform","redirect_uri":"https://video.lucy.run/auth/callback"}`，返回 `{redirect_url}`（自带 code）
- **必须 `Authorization: Bearer <JWT>`**（裸 JWT 报 40000 auth 格式错误）；HMAC-only 报 user_auth 错误
- 报错 `valid UC user credential required` = 需要登录后的 Bearer token

## 微信扫码登录（纯 HTTP，免浏览器，2026-10-13 验证）

1. `GET /v1/qr`（HMAC）→ `{ticket, url(weixin.qq.com/q/...), expire_seconds:300}`；用 url 本地生成二维码给用户扫
2. `GET /v1/is_ticket_exist?ticket=` (HMAC) 轮询 → `is_exist:true` 表示已扫码确认
3. `POST /v1/login {"way":"ticket","ticket":...,"app_type":"platform"}` → `data.token` = JWT（24h）
- QR 登录的 way 值就是 `"ticket"`；其他 way 值报 30000 非法登录方法
- 票过期报 40011 票已过期；过期后需重新 GET /v1/qr
- user-center 的 GET 端点 HMAC 与 Bearer 都可用；run 类 POST 端点两者都拒（40002）

## video.lucy.run Workbench（普通用户可用端点，2026-10-13 验证）

- 会话：跟随 redirect_url（带浏览器 cookie jar）→ `__Host-comfy_session`
- `GET /api/workbench` 列出 4 个 H3 视频模板（含完整 workflow JSON）；/api/templates 是作者专属（403 Author access required）
- **报价**：`POST /api/workbench/{id}/quote {"values":{...},"purpose":"rehearsal"}` 零消耗 → `{amount, revision, spec}`
- **计价（2026-10-14 全模板实测）：100 units/秒，线性**。5s=500、10s=1000、15s=1500 units，t2v/i2v/fl2v/r2v 四模板一致；quote 返回 `revision`，提交时必须携带
- 参数枚举：`seconds` 5/10/15；`ratio` 1609(16:9)/916/101/403/304/2109；`resolution` **仅 480/544**
- **resolution 命名陷阱**：480 → 1664×960（"960p 高度"），544 → 1920×1088（"1080p 高度"）。模板 UI 帮助文案「15 秒只能配 960P」指的是高度 960，即 **resolution=480**；`seconds=15 + resolution=544` 是 forbidden 组合，服务端 422
- 资产上传（i2v/fl2v/r2v 必用，2026-10-14 端到端验证）：
  1. `POST /api/assets/uploads {"filename","content_type","size"}` → 201 `{asset_id, upload_url, headers}`（upload_url 是 oss.myelin.cloud 预签名 S3 PUT）
  2. `PUT` 图片字节到 upload_url，请求头用响应里的 `headers` 字段
  3. `POST /api/assets/{asset_id}/complete` → `status: completed`
  4. values 里图片参数（first_frame/last_frame/ref1…ref9）**直接填 asset_id 字符串**
- `POST /api/balance` 与 user-center 余额同池

## video.lucy.run 真实运行（端到端跑通，2026-10-13 实测）

- 会话直连 urllib 即可，但 POST 必须带 `Origin: https://video.lucy.run` + `Referer: https://video.lucy.run/`（否则 403 Same-origin request required）；runs 还需 `Idempotency-Key` 头（uuid4 存盘复用，防重试重复扣费）
- 提交：`POST /api/workbench/{template_id}/runs` body `{"values":{...},"purpose":"raw","expected_amount":500,"revision":6}` → `{run_id, status:queued}`
- t2v values：prompt（结构化三段式 integrated_multimodal_description/overall_soundscape/non_diegetic_music）、seconds(5/10/15)、ratio(1609=16:9)、resolution(480/544)
- 轮询 `GET /api/runs/{run_id}`：queued→running→completed，t2v 5 秒档约 **107 秒**完成（worker cephalon12-prod）
- 产物在 `result.collected_outputs[]`：url=`/api/runs/{run_id}/outputs/{manifest_index}`（带 cookie GET 下载），含 size/sha256 自校验
- 实测账目：扣 500 units = 5 CEP 精确到 unit；i2v 用户真实跑单复核同扣 500 units（报价=实扣）；成片 h264 1664×960 24fps 5.167s 2.38MB
- 详见仓库 `scripts/lucy_run.py`（完整 CLI：登录/SSO/报价/锁价提交/轮询/下载校验/上传）

## 实战检验结论（2026-10-14，四模板全矩阵实跑）

- **账目**：单日 6 条实跑（t2v 5s/10s、i2v、fl2v、r2v、cancel 测试）全部报价=实扣、sha256 全部一致；10s 档 243 帧 / 5s 档 124 帧（24fps）
- **错误语义**（可直接做客户端校验依据）：
  - `422` 字段级：`{"detail":"prompt: value is required"}`、`{"detail":"ratio: not an allowed option"}`、`{"detail":"seconds=15 cannot be combined with resolution=544"}`
  - `409 价格已变化，请重新报价`：expected_amount/revision 与当前报价不符时拒绝，重新 quote 后重试即可
  - `403 Same-origin request required`：POST 缺 Origin/Referer 头
- **幂等已实测**：同 Idempotency-Key 重放 POST /runs 返回**同一 run_id**，不重复扣费；幂等键务必先落盘再发请求
- **扣费时点与 cancel**：扣费发生在**提交瞬间**；queued 态可取消，但模板启动 <3 秒即 running（409 cannot be cancelled），实战取消窗口几乎不存在 → 提交前必须用 rehearsal quote 确认价格
- **r2v 多参考图**：ref1 必填，ref2–ref9 可选；`ref_image_size` 取 `match`/`max`
- 时长参考：5s 档 ~107–200s 完成，10s 档 ~2 分钟内，并发提交互不阻塞

## lucy-agent 图片工作流计费（已定性，2026-10-13 用户实测）

- `POST /v1/lucy-agent/workflows/run` 对一切外部凭证返回 40002 非法凭证（HMAC 3 变体/Bearer/组合/异形 header）→ 只认内部服务调用（Lucy APP 后端、lucy.run Dify 后端、微信小程序）
- user-center 无 quote/estimate/price 端点（404）
- **实测：用户在 lucy.run/chat/comfyui-pilot 跑一次图片生成，端脑云 CEP 零扣费**（跑前跑后 [REDACTED] 不变）
- user-center 全币种枚举：symbol_ids=1(CEP)/2/3/4 均查过，跑后 2/3/4 仍为 0，5+ 报 not found → Lucy 消费不走 user-center 货币，是独立钱包/免费额度
- 入口注意：lucy.run 的工作室（Dify builder）不是消费入口，入口是 /chat/comfyui-pilot 脑花对话页；Lucy 站内单价待从 UI 确认
- **入口实测**：lucy.run 根路径跳 `/apps`（登录墙：微信扫码/免密/密码登录，首次注册需绑手机号）；cephalon.cloud/workflow 目前只挂 H3 视频四模板，图像工作流标「即将上线」
- **PascalCase 与小写路径的坑**：user-center 的 lucy-agent 是小写 query；lucy 侧 FastAPI 是标准 REST

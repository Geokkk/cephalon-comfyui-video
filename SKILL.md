---
name: cephalon-comfyui-video
description: Use when calling Cephalon Cloud (端脑云) compute for ComfyUI video/image
  generation via API — cloud GPU without a local graphics card. Covers lucy.run
  Workbench (t2v/i2v/fl2v/r2v, Wan2.2) and self-hosted ComfyUI instances,
  HMAC signing pitfalls, orphan-mission prevention, workflow adaptation.
  当用户要用端脑云 / 云端 GPU 跑 ComfyUI、文生视频、图生视频时使用。
version: 1.1.0
author: Geokkk
license: MIT
category: devops
metadata:
  hermes:
    tags: [comfyui, cephalon, video-generation, text-to-video, image-to-video, wan2-2, cloud-gpu]
---

# Cephalon Cloud（端脑云）→ ComfyUI 视频生成 API 链路

完整可运行脚本（本仓库 `scripts/`）：
- `lucy_run.py` — **Workbench 直连 CLI（推荐路线，免实例）**：微信扫码登录 → SSO 建会话 → 零消耗报价 → 锁价提交（幂等键防重复扣费）→ 轮询 → sha256 校验下载 → 图片素材上传。四模板（t2v/i2v/fl2v/r2v）2026-10-14 全部实跑验证。
- `cephalon_api.py` — user-center HMAC 签名 + 实例（missions）CLI
- `cephalon_verify.py` — 验证链路；`cephalon_keys.py` — 密钥模板（env 变量优先）
- `run_fairy_pipeline.py` / `concat_fairy.py` — 自建实例多镜头流水线（旧路线）

Lucy 工作流链路（lucy-agent 图片工作流、微信扫码登录、video.lucy.run Workbench 报价与真实运行）：见 `references/lucy-workflow-api.md`。

## Workbench 直连快速开始（lucy_run.py）

```bash
export CEPHALON_PUBLIC_KEY=<32位hex> CEPHALON_PRIVATE_KEY=<64位hex>
python scripts/lucy_run.py login                      # 微信扫码，JWT 存 lucy_state/token.txt
python scripts/lucy_run.py balance                    # 余额（100 units = 1 CEP）
python scripts/lucy_run.py upload 首帧.png            # i2v/fl2v/r2v 需要，返回 asset_id
python scripts/lucy_run.py submit --template t2v --seconds 5 --yes \
  --prompt "…… overall_soundscape: …… non_diegetic_music: None."
python scripts/lucy_run.py download <run_id>
```

红线：**计价 100 units/秒**（5s=5 CEP、10s=10 CEP、15s=15 CEP）；扣费在提交瞬间，running 后不可取消；提交前务必看脚本打印的报价。参数细节与踩坑见 reference。

## 认证（实测验证，文档有坑）

- HMAC-SHA256。签名串 = `JSON( relative_uri + 规范化body )`，密钥 = 私钥（64位hex），请求头 `Hmac-Key: 公钥(32位hex)` + `Hmac`。
- **关键坑：requestURI 是相对 user-center 基础路径的相对路径**（如 `/v1/load-balance`），**不是**文档链接里显示的 `/cephalon/user-center/v1/...` 前缀。带前缀必 401（空body传输层拒绝，无错误信息）。
- body 规范化：`json.dumps(..., sort_keys=True)`，与请求 body 完全一致。
- 401（空 msg）= HMAC 签名失败；`code 40000 登录状态已失效` = 无认证头；404 = 路径不存在。用这三点校准。
- 公钥/私钥放反也 401。脚本已加自动对调重试。
- GET 接口的 query 参数：**参数名用 snake_case**（page_index/page_size），但**双参数 query 必 401**（服务端限制，单参数 200）。mission_list 带查询参数不可用，跳过；直接用 create/status/access/close。
- POST/PUT 接口：签名串 = URI + 规范化 body JSON 字符串（实测通过）。

## API 端点（base: https://prod.unicorn.org.cn/cephalon/user-center）

- POST `/v1/user/missions/batch` body: `{batch_size, type, gpu_version, gpu_num}` → `data: [雪花ID]`
- GET `/v1/user/missions/{id}` → 状态/urls（无需分页参数，单 ID 查询可用）
- PUT `/v1/user/missions/close/batch` body: `{ids: [...]}`
- GET `/v1/load-balance`（无参数）→ 用户负载均衡服务列表
- GET `/v1/load-balance/access-address/{id}` → frpc_address/fb_address

## 实例生命周期（计费）

- waiting（不计费）→ doing（承接未运行）→ **supplying（计费中，RTX4090 实测 unit_cep=36 CEP/小时，2026-09-29 账单核实）** → succeed/failed/canceled。
- 就绪通常 5-8 分钟（waiting 约 5 分钟 + doing 约 2 分钟）。
- 创建后 `urls` 字段才出现（`["https://wp08.unicorn.org.cn:PORT", ".../fb"]`）。URL 是 HTTPS + 非标准端口，自签名证书（requests/urllib 需关闭证书校验）。
- **doing 阶段 urls 可能尚未下发**：create 脚本报"未取到访问地址"退出属正常时序，等 1-2 分钟重跑 create 即可（脚本防孤儿逻辑自动复用实例并补全 base），勿重复创建新实例。
- mission status 返回里含 `username`/`password` 字段（实例 Web UI 凭据，如 admin/cephalon），登录实例 UI 时用；与 HMAC 密钥无关。
- **用完必须调 close 接口**，否则空转烧 CEP。关闭后本地 cephalon_state.json 要同步更新为 succeed，避免下次误判孤儿实例。单次任务账单约 2124 单位（≈21.24 CEP）含约 1 小时 supplying + 模型加载生成；2026-09-30 二次验证：紧凑流程（生成完立即关）从创建到关闭仅约 24 分钟，估算约 14 CEP——省钱关键：生成完成后立刻 close。

## 防孤儿实例（踩过坑，2026-09-28 实际烧掉约 1 小时 CEP）

- **创建成功后立即落盘 mission_id 再做等待循环**。等待被 timeout/中断杀死时 ID 不会丢失成孤儿。
- create 开头先查 state 文件：已有 waiting/doing/supplying 实例则复用，不新建。
- submit 前查实例状态，非 supplying/doing 拒绝提交。
- 孤儿 ID 一旦丢失只能靠用户在端脑云控制台手动停用（雪花 ID 无法枚举遍历）。

## ComfyUI API（实例就绪后）

- POST `/prompt` body: `{"prompt": {API格式工作流}, "client_id": "..."}` → prompt_id
- GET `/history/{prompt_id}` → status.completed + outputs
- GET `/view?filename=...&subfolder=...&type=output` → 下载产物
- GET `/object_info`（11MB）→ 全部节点定义；GET `/object_info/{NodeName}` 单节点。
- API 格式：`{node_id: {class_type, inputs: {param: value 或 [from_node, slot]}}}`。
- **官方 Wan2.2 模板是新版 UI 嵌套子图格式**（definitions.subgraphs），服务器未注册子图类型会报错。需内联展开成打平 API 格式。模板解析：Wan2.2 T2V = 高噪模型(UNETLoader)+lightx2v LoRA+ModelSamplingSD3(shift 5)+KSamplerAdvanced(0→2步) → 低噪模型+LoRA+KSamplerAdvanced(2→4步) → VAEDecode → CreateVideo(fps 16) → SaveVideo。latent 用 EmptyHunyuanLatentVideo(480x480x73, batch 1)。文本编码器 umt5_xxl_fp8_e4m3fn_scaled.safetensors (CLIPLoader type=wan)。
- 4 步生成约 4.5 秒 480x480 16fps 视频（RTX4090 实测），从提交到完成约 3-4 分钟（含模型加载）。
- **TI2V 5B 官方参数与 14B 完全不同**（官方模板 video_wan2_2_5B_ti2v.json 实测解析）：单 KSampler 20 步 / cfg 5 / uni_pc / simple + ModelSamplingSD3 shift 8 + CreateVideo fps 24；5B 是单模型无双 UNET 高低噪。5B 无专属蒸馏 LoRA，4 步路线不适用。
- TI2V 5B 分辨率只能 1280x704 或 704x1280（Wan22ImageToVideoLatent 宽高步长 32，720 高度不合法；官方「720P」实为 704）。帧长约束 (n-1)%4==0。
- 官方模板默认 121 帧 = 5 秒训练长度；>121 帧有动态退化风险，长场景拆成 ≤121 帧多镜头。
- I2V：Wan22ImageToVideoLatent 的 optional `start_image` 接 IMAGE；首帧用 easy loadImageBase64（base64_data 字符串输入，免 multipart 上传）。

## 验证过的模型库（3755 节点）

- Wan2.2 全系（T2V/I2V 14B fp8、TI2V 5B fp16）、Wan2.1、LTX-2（19B/22B dev/distilled）、LTX-Video 0.9.5、HunyuanVideo 720p、SVD、Mochi、Hunyuan3D-2。TI2V 5B 无专属蒸馏 LoRA（357 个 LoRA 无 5b/ti2v），全质量 20 步采样单镜 720p 约 5-6 分钟。
- LoRA 357 个（含 wan2.2 lightx2v 4steps v1.1 high/low noise）。
- 探测脚本：下载 object_info.json 后本地解析 `CheckpointLoaderSimple/UNETLoader/VAELoader/CLIPLoader` choices + 视频节点存在性。

## 多镜头链式成片（2026-10-01 720p 实测跑通）

- 脚本：`scripts/run_fairy_pipeline.py`（create/shot1/shot N/download/close）+ `build_ti2v_t2v.py`/`build_ti2v_i2v.py`（工作流生成器）+ `concat_fairy.py`（xfade 拼接）。规格文件 shots_spec.json。
- 链式保连续：镜1 T2V → ffmpeg `-sseof -0.15` 提取尾帧（**JPG q2 ~200KB，勿用 PNG——900KB 经隧道上传必被打断**）→ 每镜以上一镜尾帧作 start_image。
- **隧道不稳三件套**：POST /prompt timeout 必须 300s（默认 60s 读超时扛不住 900KB 上传）；提交加重试循环 x5（重提交安全——已入队会被服务端拒绝）；`socket.setdefaulttimeout(180)` 防下载无限挂起。提交响应丢失时转扫 /history 按文件名前缀找产物。
- 镜3 教训：POST 在上传阶段被打断后工作流**根本没入队**（队列空 + history 无记录），后台轮询会无限空转烧 CEP——先查 /queue 和 /history 确认再重提。
- 20 步 720p 单镜约 5-6 分钟生成 + 1 分钟上传下载；8 镜全程（含故障空转 40 分钟）约 2 小时实例租期。
- xfade 拼接：逐级两两合并（长 filter_complex 一步错难排查），offset = 累计时长 - 0.5s，成片时长 = Σ单镜 - (N-1)×0.5s。

## 任务类型枚举（4.1 创建用）

comfyui_time（基础版）/ sd_time / sd_cmd_time（高级版）/ fooocus_time / sd_xl_time / jp_time / jp_conda_time / tabby_time / ascend_time / wt_time / ssh_time。专业版 ComfyUI 需在网页端确认类型值（文档评论区说 API 默认基础版）。

# cephalon-comfyui-video

> ⚠️ **Unofficial / 非官方第三方工具** —— 与端脑云（Cephalon Cloud）、Lucy（video.lucy.run）无任何隶属或背书关系。使用风险与费用自负，详见下方[免责声明](#️-免责声明-disclaimer)。

Hermes Agent 技能 + 独立 CLI：通过 API 调用 [端脑云 Cephalon Cloud](https://cephalon.cloud) 算力跑 ComfyUI 视频/图片生成。全程免浏览器、可脚本化。链路均为 2026-10 实测验证。

## 两条路线

| 路线 | 说明 | 计费 | 适用 |
|---|---|---|---|
| **Workbench 直连**（`scripts/lucy_run.py`，推荐） | 微信扫码登录 → SSO 换票 → video.lucy.run 提交 H3 模板（t2v/i2v/fl2v/r2v） | **100 units/秒**（5s=5 CEP、10s=10 CEP、15s=15 CEP），报价=实扣 | 单条/批量视频，秒级启动，免实例管理 |
| **自建实例**（`scripts/run_fairy_pipeline.py`） | 创建 ComfyUI GPU 实例（RTX 4090），直接调 ComfyUI API | 36 CEP/小时（按实例租期） | 长链路多镜头、自定义工作流 |

## 快速开始（Workbench 直连）

```bash
export CEPHALON_PUBLIC_KEY=<32位hex> CEPHALON_PRIVATE_KEY=<64位hex>
python scripts/lucy_run.py login                      # 微信扫码，JWT 存 lucy_state/token.txt
python scripts/lucy_run.py balance                    # 余额（100 units = 1 CEP）
python scripts/lucy_run.py upload 首帧.png            # i2v/fl2v/r2v 需要，返回 asset_id
python scripts/lucy_run.py submit --template t2v --seconds 5 --yes \
  --prompt "…… overall_soundscape: …… non_diegetic_music: None."
python scripts/lucy_run.py download <run_id>
```

内置安全机制：提交前强制零消耗报价并展示价格；`--yes` 才会真实扣费；幂等键先落盘再请求（网络重试不会重复扣费）；产物 sha256 自校验。

## 安装为 Hermes 技能

```bash
git clone https://github.com/Geokkk/cephalon-comfyui-video.git \
  ~/.hermes/skills/devops/cephalon-comfyui-video
```

## 文件

| 文件 | 说明 |
|---|---|
| `SKILL.md` | 技能主文件：HMAC 认证、实例生命周期、ComfyUI API、防孤儿、踩坑记录 |
| `references/lucy-workflow-api.md` | Lucy 工作流链路：登录、计价、资产上传、错误语义、lucy-agent 定性结论 |
| `scripts/lucy_run.py` | Workbench 直连 CLI（登录/报价/锁价提交/轮询/下载校验/上传） |
| `scripts/cephalon_api.py` | user-center HMAC 签名 + 实例（missions）CLI |
| `scripts/cephalon_verify.py` / `cephalon_keys.py` | 链路验证 / 密钥模板（环境变量优先） |
| `scripts/run_fairy_pipeline.py` / `concat_fairy.py` | 自建实例多镜头流水线与 ffmpeg 拼接 |

## 费用与安全红线

- **真实扣费**：视频生成按秒计费、GPU 实例按小时计费。扣费发生在提交瞬间，任务进入 running 后**不可取消**（模板启动 < 3 秒）。提交前务必确认报价。
- **实例用完必须 close**，否则空转烧 CEP；脚本有防孤儿逻辑但不保证万无一失，请自行核对控制台账单。
- **凭据自管**：本项目不内置、不分发任何账号/密钥/凭据。密钥走环境变量或本地文件（建议 `chmod 600`），会话 JWT 24 小时有效，全部保存在 `lucy_state/`（已被 `.gitignore` 排除）。
- **登录链路为逆向非官方实现（实验性）**：可能违反平台服务条款，账号风险（限流/封禁）由使用者自担。

## 使用者义务

- 通过网络发布 AI 生成/合成的视频或图片时，请按《人工智能生成合成内容标识办法》（2025-09-01 施行）**主动声明并使用平台提供的标识功能**进行标注；不得利用本工具去除或规避内容标识。
- 遵守端脑云服务条款与所在国家/地区法律法规；禁止用于生成违法违规内容、挖矿、滥用算力、批量注册、转售算力等场景。

## ⚠️ 免责声明（Disclaimer）

1. **本项目为非官方第三方工具**。本仓库与端脑云（Cephalon Cloud / unicorn.org.cn）、Lucy（video.lucy.run）及其关联方**无任何隶属、合作、代理或背书关系**；文中出现的第三方名称与商标仅用于描述用途，归各自权利人所有，不构成任何权利主张。
2. **本工具按"现状"提供，不提供任何明示或默示的担保**（包括但不限于可用性、准确性、适用性、不侵权）。作者不对因使用或无法使用本工具造成的任何直接或间接损失承担责任。
3. **费用与算力风险由使用者自行承担**。端脑云按实际用量实时计费（GPU 实例按小时计费、部分视频模型按秒计费），脚本异常、网络中断、实例未及时关闭均可能产生真实费用；使用前请自行理解平台计费规则并随时核对控制台账单，作者不对任何费用损失负责。
4. **账号风险由使用者自行承担**。通过非官方客户端访问平台服务可能违反平台服务条款，由此导致的限流、封禁、余额损失等后果由使用者自行承担。请仅使用使用者本人的账号与凭据；本项目不内置、不分发、不代理任何账号、密钥或凭据，所有凭据仅保存在使用者本地，泄露风险自行管理。
5. **合规义务由使用者承担**。使用者应遵守所在国家/地区的法律法规及平台服务条款，不得利用本工具从事任何违法或滥用行为（包括但不限于生成违法违规内容、挖矿、滥用算力、批量注册、转售算力）。
6. **AI 生成内容标识义务提示**：根据《人工智能生成合成内容标识办法》（2025 年 9 月 1 日施行），借助信息网络发布 AI 生成/合成内容时，发布者应主动声明并使用平台提供的标识功能进行标注；任何组织和个人不得恶意删除、篡改、伪造、隐匿内容标识，亦不得提供去标工具或服务。本工具不提供、亦不得被用于去除或规避内容标识，相关标识与合规责任由使用者自行承担。
7. 使用、复制、修改或分发本工具，即表示您已阅读、理解并同意上述全部条款。如不同意，请勿使用本项目。

> **English (summary)**: This is an unofficial third-party client, not affiliated with or endorsed by Cephalon Cloud / Lucy. Provided "as is", without warranty of any kind. You bear all costs (real metered billing), account risks (possible ToS violation), and compliance obligations (including AI-generated content labeling under applicable law). By using it you accept all terms above.

## 接口时效性

所有端点、单价、参数枚举基于 **2026-10-14** 实测，平台随时可能调整（价格表 revision 机制会拒绝旧价提交）。使用前建议先用零消耗 quote 核价；接口行为以端脑云官方文档为准。

## License

[MIT](LICENSE) —— 免责声明第 1-7 条独立于 MIT 许可证适用。

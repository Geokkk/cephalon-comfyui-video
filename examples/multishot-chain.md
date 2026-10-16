# 示例：自建实例 8 镜链式成片「雨后森林小木屋」

2026-10-01 真实跑通记录：RTX 4090 实例上 1 镜 T2V 起头 + 7 镜以上一镜尾帧作首帧链式 I2V，每镜 121 帧（1280×704 @ 24fps，Wan2.2 TI2V 5B，20 步/cfg 5/uni_pc/shift 8），最后 xfade 逐级拼接成 **36.6 秒 720p 成片**。

- 全部提示词与参数：[`scripts/shots_spec.json`](../scripts/shots_spec.json)（脚本开箱即用的规格文件）
- 成片：见 [Release v1.1.0 附件](https://github.com/Geokkk/cephalon-comfyui-video/releases/tag/v1.1.0)（fairy_after_rain.mp4）
- 实际花费：**约 72 CEP**（2 小时实例租期 × 36 CEP/小时；含一次隧道中断导致的约 40 分钟故障空转——顺利复跑可压到约 50 CEP 以内）

## 命令序列

```bash
export CEPHALON_PUBLIC_KEY=<你的32位hex公钥> CEPHALON_PRIVATE_KEY=<你的64位hex私钥>

python scripts/run_fairy_pipeline.py create        # 创建/复用实例，等就绪（mission_id 立即落盘防孤儿）
python scripts/run_fairy_pipeline.py shot1         # 镜1 T2V（完成自动提取尾帧）
python scripts/run_fairy_pipeline.py shot 2        # 镜2 I2V（用镜1尾帧作首帧）
python scripts/run_fairy_pipeline.py shot 3        # ……依次到镜8
python scripts/run_fairy_pipeline.py download <n>  # 某镜产物丢失时补下载
python scripts/run_fairy_pipeline.py close         # 全部完成后立即关闭实例停止计费！

python scripts/concat_fairy.py 成片输出路径.mp4     # xfade 逐级拼接（0.5s 叠化）
```

## 链式连续性原理

镜1 纯文生视频出画面 → ffmpeg `-sseof -0.15` 从每镜结尾提取尾帧（JPG q2 约 200KB）→ 下一镜以该尾帧作 `start_image`（easy loadImageBase64，base64 字符串直传免 multipart）→ 画面主体、画风、光线跨镜延续 → xfade 0.5s 叠化掩盖接缝。

## 实测踩坑（省钱与排障必读）

- **20 步 720p 单镜约 5-6 分钟生成** + 1 分钟上传下载；8 镜串行跑完不含故障约 1 小时。
- **隧道不稳三件套**（已内置于脚本）：POST /prompt 超时 300s、提交重试 ×5、全局 socket 超时 180s。
- **镜中断后先查 /queue 和 /history 再重提**：POST 在上传阶段被打断时工作流可能根本没入队，盲目重提会排队双份。
- **生成完立刻 close**：本次故障空转 40 分钟多烧约 24 CEP；紧凑流程（生成完立即关）全程约 24 分钟、约 14 CEP 可完成更短的链。
- 换自己的故事：改 `scripts/shots_spec.json` 的 positive/negative 提示词即可，链式机制与脚本不变。

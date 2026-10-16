# 示例：Workbench 直连文生视频（t2v，10 秒）

2026-10-14 真实跑通记录。产物为 480p、16:9、10 秒视频，**花费 10 CEP**（100 units/秒 × 10s，报价=实扣）。

## 命令

```bash
export CEPHALON_PUBLIC_KEY=<你的32位hex公钥> CEPHALON_PRIVATE_KEY=<你的64位hex私钥>

python scripts/lucy_run.py login      # 微信扫码，JWT 24 小时有效
python scripts/lucy_run.py balance    # 提交前先看余额（100 units = 1 CEP）

python scripts/lucy_run.py submit --template t2v --seconds 10 --yes \
  --prompt "A red paper lantern floats up into a deep blue night sky, camera tilts up slowly to follow. Fireworks bloom far away, lantern glow flickers. overall_soundscape: soft wind, distant festival drums. No speech. non_diegetic_music: None."

python scripts/lucy_run.py download <run_id>   # run_id 在 submit 输出里，sha256 自动校验
```

## 本次实跑参数

| 项 | 值 |
|---|---|
| run_id | `71f56068372841b5bb719bbc8f5b223f` |
| 模板 | t2v（H3 文生视频） |
| 时长 | 10 秒（124 帧 @ 24fps） |
| 画幅/分辨率 | ratio 1609（16:9）/ 480p |
| 花费 | 10 CEP（提交前零消耗报价确认，报价=实扣） |

## 要点

- 提示词结构：画面描述 + `overall_soundscape:`（环境音）+ `non_diegetic_music:`（配乐，None=不加）；说"No speech."避免出人声。
- 扣费发生在提交瞬间，running 后不可取消——`--yes` 之前看清脚本打印的报价。
- 想省钱先跑 5 秒版（5 CEP）验证画风，满意再上长时长。

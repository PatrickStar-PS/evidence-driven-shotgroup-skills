---
name: align-episode-dialogue-two-segment
description: Split one short-drama episode into two dialogue-safe overlapping clips, parse both clips concurrently through 中转站 using only the video and a character asset workbook, and merge them into one validated Chinese dialogue ledger with absolute timestamps, speaker identity, speech rate, intonation, timbre, emotion, rhythm, and pauses. Use when extracting complete episode dialogue from roughly one-to-three-minute MP4, MOV, MKV, WEBM, AVI, or M4V videos, especially when a single full-video pass misses short lines or loses attention.
---

# 双段并发台词解析

将一集视频安全切成两个带重叠区的片段，并发解析后合并为唯一的整集台词台账。把本 Skill 作为正式双段工作流使用；不要把两个片段的局部结果直接交付给下游。

## 输入

必须提供：

- 一集原始视频；
- 一份全剧或单集人物资产 XLSX、CSV、TSV 或 JSON；
- 中转站 密钥池文件；
- 含 TOS 凭据的环境文件。

人物资产至少要能识别资产类型和人物中文名。英文名、人物描述和出现集号可选。也可直接复用本 Skill 先前输出的标准化 `character_input.json`；入口必须保留其中人物、别名和服装态，不得回退读取其历史 `asset_source`。不要要求字幕表、剧本、镜头组、OCR、ASR 或人工台词。

运行环境需要 Python 3、FFmpeg/FFprobe、`requests`，读取 XLSX 时还需要 `openpyxl`。

## 正式工作流

优先运行完整入口：

```powershell
python scripts/run_two_segment_dialogue.py --video <episode.mp4> --assets-workbook <assets.xlsx> --episode <number> --output-dir <output> --key-pool-file <bai_keys.txt> --tos-env-file <tos.env>
```

入口会依次完成：

1. `normalize_character_assets.py`：按集号整理可匹配的人物身份。
2. `plan_two_segments.py`：在视频中点附近寻找静音边界，生成两个精确重编码、互有上下文的片段。
3. `tos_video_transport.py`：分别上传片段并生成限时访问 URL。
4. `bai_extract_dialogue_clip.py`：用两个工作线程并发调用 中转站；每段独立解析，不携带另一段的识别结果。
5. `merge_two_segment_ledgers.py`：把局部时间换算为整集绝对时间，在重叠区语义去重，并保留只被一段识别到的接缝台词。
6. `validate_dialogue_ledger.py`：校验人物、时间、字段和派生计数，并导出 CSV。

只有在需要替换 TOS 传输实现时才传 `--transport-script`。默认使用本 Skill 自带的传输脚本。

## 切分规则

- 默认在中点两侧各保留 3 秒上下文，因此共享重叠区约 6 秒。
- 优先选择距离视频中点 10 秒内、持续至少 0.45 秒的静音区中点。
- 没有合格静音时使用精确中点，并记录 `midpoint_fallback` 警告。
- 必须重编码，不能用流复制冒充精确切分。
- 重叠区只提供上下文，不代表归属。不能仅因台词起点落在某段逻辑核心之外就删除它。

## 解析规则

- 只依据当前视频片段的可听语音和人物资产识别台词。
- 保留短问候、称呼、应答、语气词、打断、画外音、低声和重复说话。
- 听不清的语音不靠字幕或剧情补写；文字清楚但说话人不确定时保留台词并使用 `speaker_id: unclear`。
- 反应镜头不能证明说话人改变；一句连续台词跨视觉切镜时仍保持一个事件。
- 每条台词必须包含语速、语调、音色、情绪、节奏停顿、句内停顿和置信度。
- 中转站 默认模型为 `gemini-3.6-flash`，除非用户明确指定其他已验证模型。

## 合并规则

- 仅当标准化文字相似且绝对时间吻合时，才把两段中的事件视为重叠副本。
- 合并时统一事件顶层与 `delivery` 内的置信度字段；任一层存在合法值时补齐另一层，不覆盖相互冲突的合法值。
- 优先保留距离片段边缘更远的副本，其次比较置信度，再比较文字完整度。
- 保留任一片段独有的事件，包括跨接缝台词。
- 只允许修正不超过 0.30 秒的微小时标越界；更大的不可能时间放入 `quarantined_events.json` 并使整次运行失败。
- 合并完成后再按时间排序，连续编号为 `EPxx-D0001`。

修改输出结构前必须阅读 `references/dialogue-ledger-schema.md`。

## 输出

正式输出目录至少包含：

- `dialogue_ledger.json`：整集唯一台词台账；
- `dialogue_ledger.csv`：与 JSON 事件一一对应的表格；
- `validation_report.json`：结构校验结果；
- `two_segment_manifest.json`：切分边界、偏移和源视频指纹；
- `run_manifest.json`：双段运行状态和结果路径；
- `quarantined_events.json`：必须为空才可正式交付；
- `part01/`、`part02/`：局部台账与原始响应，供审计和故障恢复。

## 完成标准

仅在以下条件全部满足时报告完成：两段均成功、合并成功、隔离区为空、验证状态为 `passed`、CSV 与 JSON 事件数一致。任一段失败时保留已有产物，在 `run_manifest.json` 标记 `partial`，不得把部分结果称为整集台词真值表。

正式化只保证工作流、结构和本地合并校验经过测试。没有针对用户视频完成真实 中转站 调用时，要明确说明未做线上内容质量验收。

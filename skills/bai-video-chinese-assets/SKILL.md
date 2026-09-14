---
name: bai-video-chinese-assets
description: Parse multiple short-drama episode videos concurrently through the 中转站 OpenAI-compatible multimodal relay, generate independent per-episode Chinese semantic candidates for characters, scenes, and props, then use Codex local semantic reasoning by default to merge and deduplicate the whole series into a five-column Chinese asset workbook for downstream British localization. An available 中转站 Pro model may be used as an optional merge mode. Use for MP4, MOV, MKV, WEBM, AVI, or M4V episode folders when cross-episode consistency must be decided from all episode descriptions together rather than carrying earlier assets into later episode prompts.
---

# 中转站中文资产解析

Analyze every episode independently with `gemini-3.6-flash`, then consolidate all structured candidates with Codex local semantic reasoning. Do not feed prior episode assets into later video requests. Do not perform English naming or British localization. Use 中转站 Pro only when the user explicitly requests remote Pro merge.

## Why the workflow changed

An earlier serial design injected episode 1's recognized characters into episode 2, keeping names stable but making each episode wait for the previous one. This version assigns episode-local IDs during concurrent extraction, then maps every local ID to one whole-series ID during the global merge. Independent extraction exposed missed minor characters, so the primary pass is followed by two same-episode character-only audits. Each audit receives the names already found and asks only for remaining speakers or independent actors; duplicate names and aliases are filtered locally. In the originating project's tests this brought character coverage to about 95%; the repository does not include a public labeled benchmark for that estimate.

## Required inputs

- Directory containing naturally sortable episode videos.
- Writable output directory.
- 中转站 credential in `BAI_API_KEY`, `--key-pool-file`, or `BAI_KEY_POOL_FILE`.
- Explicit authorization to transmit the selected videos and derived asset text to 中转站.

Use `BAI_API_ENDPOINT` when configured. Default the extraction model to `gemini-3.6-flash`. For optional remote merge, use `BAI_MERGE_MODEL` or `--merge-model` when supplied; otherwise query 中转站 `/v1/models` and select an available Pro model. Never invent an unavailable model ID.

## Read-on-demand resources

- Read [output-schema.md](references/output-schema.md) before changing columns, IDs, mappings, or localization handoff.
- Read [prompt-contract.md](references/prompt-contract.md) before changing character, scene, prop, state, extraction, or global-merge behavior.
- Read [bai-transport.md](references/bai-transport.md) before changing API fields, model discovery, concurrency, retries, limits, or secret handling.

## Workflow

### 1. Inspect and authorize

Confirm exact input/output directories and external-upload authorization. List naturally sorted videos, assigned `EPxx` labels, sizes, and extensions without displaying secrets. Treat videos as read-only.

### 2. Run independent concurrent extraction

```powershell
python scripts/bai_video_chinese_assets.py `
  --input-dir "D:\path\episodes" `
  --output-dir "D:\path\chinese_assets" `
  --key-pool-file "D:\path\bai_key_pool.txt" `
  --concurrency 5 `
  --character-audit-passes 2
```

The parser must:

- send one complete video per extraction request;
- run two sequential same-episode character coverage audits after the primary extraction by default;
- pass accumulated same-episode character-base names into each audit, make the second audit focus on the hardest brief/off-screen/group-scene roles, reject exact name/alias duplicates, and append only omitted character-base candidates;
- process episodes independently and concurrently, defaulting to five workers;
- never inject previously recognized assets into another episode prompt;
- assign stable episode-local IDs and save one structured candidate file per episode;
- describe identity and state separately for characters, scenes, and props;
- resume an episode only when its source hash, extraction model, and prompt version still match;
- preserve successful episode results if another episode fails;
- include the configured audit-pass count in resume compatibility so one-audit caches are not reused as two-audit results;
- never print or store API keys.

Use `--dry-run` to inspect ordering and size limits. Use `--mock-response-dir` and `--mock-merge-response` for offline testing.
Use `--character-audit-passes 2` as the production default. Lower it only when the user explicitly accepts reduced character coverage to save calls; values from 0 through 5 are supported.

### 3. Run one whole-series semantic merge

After all selected episodes have valid candidate files, concatenate them into `全剧_单集资产候选.json`. By default, use Codex local semantic reasoning as the sole semantic authority for:

- deciding whether people across episodes are the same identity;
- separating a person identity from wardrobe, disguise, injury, age-period, or persistent state;
- merging equivalent narrative spaces while preserving materially different scene states;
- merging unique and generic props while preserving plot-significant states;
- selecting canonical Chinese names, descriptions, aliases, and episode appearances.

Require a complete `local_asset_id -> global_asset_id` mapping. Judge identity from the complete semantic descriptions, narrative roles, relationships, appearance, wardrobe/state boundaries, spaces, prop function, episode continuity, and aliases—not names alone. Do not use vector thresholds, voting, or mandatory manual review gates as substitutes for semantic judgment.

The default command stops after writing the combined candidate file. Author the local merge JSON, then rerun the same command with `--local-merge-response "D:\path\global_merge.json"`; matching episode extractions are reused and the script validates the merge and exports the strict CSV. Use `--merge-mode pro` only for explicitly requested remote Pro merge.

If the user explicitly requests remote Pro merge, submit the complete candidate file once to the chosen Pro model and trust that result by default after structural validation. Record `merge_method` as either `codex_local_skill_semantic_merge` or `bai_pro_semantic_merge`.

### 4. Validate technical integrity

Technical validation must not silently alter the selected semantic result. Require:

- every input local ID appears exactly once in the mapping;
- every mapped global ID exists;
- global asset types are only `人物`, `场景`, or `道具`;
- names and descriptions are non-empty;
- parent IDs exist, are type-compatible, and do not self-reference;
- episode labels are valid and consistent with mapped source candidates;
- all character state references resolve within the same character family.

Save `global_merge.json`, `asset_state.json`, `manifest.json`, sanitized response records, and the strict CSV.

### 5. Export and inspect Excel

Use the `Spreadsheets` skill to export `全剧_中文资产解析表.csv` to `全剧_中文资产解析表.xlsx`. Preserve exactly the five columns in [output-schema.md](references/output-schema.md). Inspect workbook values, formula errors, and the rendered preview before delivery.

### 6. Hand off to British localization

Pass the five-column workbook to the downstream localization skill. It fills English names, localized introductions, and localized character-state references, producing the eight-column target without altering the Chinese source fields.

## Failure rules

- Stop before upload when a video exceeds the configured inline limit; never silently recompress, trim, or sample it.
- Retry only network failures, rate limits, and server errors with bounded exponential backoff.
- Preserve raw invalid remote responses. In local merge mode, correct the authored merge definition and rerun validation rather than silently dropping candidates.
- Do not run the global merge until every selected episode extraction is complete.
- In optional remote mode, make only one global semantic merge request per run. If it fails or is structurally invalid, preserve diagnostics and stop unless the user authorizes switching to local merge.
- Absence or failure of a Pro model does not block the default local merge.

## Testing

Run:

```powershell
python scripts/bai_video_chinese_assets.py --self-test
```

The self-test must prove independent episode candidates, complete mapping validation, and the five-column CSV contract. Keep a mock remote merge test for the optional Pro path. Run a real 中转站 test only with upload authorization.

## Completion criteria

Complete only when the skill validates, offline tests pass, the Excel exporter still renders, output columns match the contract, and the handoff states which merge method was used and whether real 中转站 extraction or optional Pro merge was tested.

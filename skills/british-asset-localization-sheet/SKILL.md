---
name: british-asset-localization-sheet
description: Localize Chinese drama asset Excel files from the previous asset inventory step into strict eight-column British-period asset workbooks using Codex's own reasoning, not Gemini. Use when Codex needs to convert a five-column Chinese source inventory into the eight-column contract required by British shot-group workflows, preserve source descriptions and character-state evidence, assign localized English names and references for characters/scenes/props, keep family surnames consistent, output per-episode and full-series Excel files, generate Chinese/British dialogue comparison workbooks, or replace asset mentions in a whole-series shot-group workbook.
---

# British Asset Localization Sheet

## Overview

Use Codex's own reasoning to convert Chinese asset Excel files into overseas-ready British-period asset sheets. The bundled script is only a table utility: it prepares source rows as editable JSON drafts, validates completed rows, and writes one localized workbook per episode plus a full-series cumulative workbook.

Do not call Gemini for this localization step. Codex should perform naming, family-surname continuity, British-period adaptation, and prompt rewriting directly.

## Workflow

1. Confirm `.env` contains:

```dotenv
BRITISH_ASSET_INPUT_DIR=C:\path\to\project\gemini_asset_excels
BRITISH_ASSET_DRAFT_DIR=C:\path\to\project\british_localized_assets\drafts
BRITISH_ASSET_OUTPUT_DIR=C:\path\to\project\british_localized_assets
BRITISH_REFERENCE_ASSET_FILE=C:\path\to\project\英国维多利亚版资产表_EP1-EP10.csv
BRITISH_DIALOGUE_INPUT=C:\path\to\project\dialogue_tables
BRITISH_DIALOGUE_OUTPUT_DIR=C:\path\to\project\british_localized_assets\dialogue
BRITISH_SHOT_INPUT_FILE=C:\path\to\project\gemini_shot_group_excels\full_series_shot_groups.xlsx
BRITISH_SHOT_OUTPUT_FILE=C:\path\to\project\british_localized_assets\localized_full_series_shot_groups.xlsx
```

2. Prepare draft JSON files:

```powershell
python path\to\british-asset-localization-sheet\scripts\localize_british_assets.py --env-file ".env" --mode prepare
```

3. Codex reads each `*_codex_localization_draft.json` in order and creates a matching `*_completed.json` file with:

```json
{
  "episode": "EP1",
  "completed_rows": []
}
```

4. Write and validate Excel files:

```powershell
python path\to\british-asset-localization-sheet\scripts\localize_british_assets.py --env-file ".env" --mode write
```

5. Each later episode must reuse prior completed rows as continuity context so names, family surnames, and setting choices remain stable.

If `BRITISH_REFERENCE_ASSET_FILE` is set, the prepare step embeds the reference asset rows in every draft JSON. Codex should use that table as the style guide for naming, fictional setting vocabulary, prompt structure, costume detail level, and episode formatting.

6. Before producing the final localized shot version, generate dialogue localization drafts using the localized asset mapping workbook:

```powershell
python path\to\british-asset-localization-sheet\scripts\localize_british_assets.py --env-file ".env" --mode prepare-dialogue
```

7. Codex reads each `*_dialogue_localization_draft.json` in order and creates a matching `*_dialogue_completed.json` file with completed rows.

8. Write and validate per-episode dialogue comparison workbooks:

```powershell
python path\to\british-asset-localization-sheet\scripts\localize_british_assets.py --env-file ".env" --mode write-dialogue
```

9. After localized assets and dialogue are complete, replace asset mentions in the whole-series shot-group workbook:

```powershell
python path\to\british-asset-localization-sheet\scripts\localize_british_assets.py --env-file ".env" --mode map-shots
```

This writes a localized whole-series shot-group workbook and a JSON replacement report. Use `--replace-all-shot-columns` only when asset mentions appear outside obvious asset, character, role, scene, prop, visual-description, or prompt columns.

## Required Output

The output workbook must use exactly these eight Chinese columns in this order:

1. `资产类型`
2. `资产中文原名`
3. `资产本地化英文名`
4. `资产简介`
5. `原始中文解析描述`
6. `角色状态中文参考描述`
7. `角色状态本地化参考`
8. `出现集号`

Normalize source subtypes such as `人物本体`/`人物状态`, `场景本体`/`场景状态`, and `道具本体`/`道具状态` to `人物`, `场景`, and `道具`. Preserve the original Chinese description and Chinese character-state reference when supplied. Fill localized English name and localized asset brief for every row. Character rows use Westernized names with the Chinese state suffix and must fill the localized state reference; scene and prop rows use concise reusable localized names and normally leave both state-reference columns blank.

## Localization Rules

- Use one unified British historical setting, defaulting to a fictional Victorian-inspired kingdom or estate world.
- When a reference asset table is provided, match its setting and wording style before inventing new localizations.
- English names must be Westernized and suited to role energy: domineering male lead, soft heroine, villain, noble matriarch, servant, guard, etc.
- Same-family characters must share one English surname when a surname is used.
- Do not use Chinese pinyin in English names.
- Generated English localized names must not contain real-world place names; use fictional family, estate, or kingdom names.
- Every character asset must include the original Chinese state suffix after the English name, for example `Ethan-[Chinese state]`.
- If a Chinese character asset name lacks a state separator, normalize it with a hyphen suffix.
- Scene and prop descriptions must be localized to the British period setting.
- Clothing descriptions must include garment, shoes, and accessories.
- Character prompts must strengthen localized British/European visual credibility: design facial features from the character's temperament, social identity, story function, and screen presence; use British/European production styling cues, including contemporary or period-appropriate tailoring, natural grooming, restrained makeup, class/workplace signals, and region-appropriate accessories. Remove source-region ethnicity labels such as Chinese, Asian, or East Asian from localized character prompts unless the story explicitly requires them; replace them with setting, wardrobe, grooming, class, and workplace cues. This is a style and setting constraint, not an exclusionary race or ethnicity rule.
- After character localization prompts are drafted, run the localized character prompt guard before export: semantically rewrite source-video identity carryover, old nationality anchors, and face/hair shorthand that would pull the result back toward the source actor; then fail validation if residue remains.
- The prompt guard must also remove low-distinction soft-face wording such as `线条柔和`, `soft facial contours`, `soft face lines`, and `soft features`; rewrite it into clearer cheekbone, jawline, facial-structure, occupational temperament, or British/European casting cues.
- Put the reusable British-localized summary and concise image-generation guidance in `资产简介`.
- For an expanded character-state row, `资产简介` and `角色状态本地化参考` must describe only that row's state. Never copy the base character's complete state index into every state row.
- Before export, fail validation when a character-state brief names two or more sibling states, or when the source state description begins with a different known character identity.
- Keep source evidence in `原始中文解析描述`; do not overwrite it with localized prose.
- Keep source character-state evidence in `角色状态中文参考描述` and write its British visual equivalent in `角色状态本地化参考`.
- Episode appearances must be consistent, such as `EP1`, `EP2`, `EP1,EP2`, or `1,2`; never mixed forms such as `EP + Chinese numerals`.

## Validation

The script enforces:

- exactly eight output columns in the required order
- source subtype normalization to `人物`, `场景`, or `道具`
- localized asset briefs are required for all rows
- localized character-state references are required for character rows
- localized English names are required for characters, scenes, and props
- character localized names include a state suffix
- character Chinese names include a hyphen state suffix
- episode appearances are normalized to `EPn`
- one full-series workbook is written in addition to per-episode workbooks
- the shot-group mapping mode writes a report containing replaced and unreplaced asset names for manual QA
- the dialogue mode writes per-episode Chinese/British comparison workbooks plus a full-series workbook

## Dialogue Localization

Use `--mode prepare-dialogue` after `--mode write` has produced the localized full-series asset workbook. Dialogue localization is Codex-led; the script only prepares context and writes validated tables.

Inputs:

- source dialogue table file or directory, default from `BRITISH_DIALOGUE_INPUT`
- localized full-series asset workbook, default from `BRITISH_SHOT_ASSET_MAP_FILE` or `BRITISH_ASSET_FULL_SERIES_FILE`

Supported source dialogue columns are flexible. The script looks for episode, time/shot, speaker, dialogue, and context fields using common Chinese header names such as episode, role, speaker, subtitle, scene, visual description, and notes.

Outputs:

- `*_dialogue_localization_draft.json` files for Codex to fill
- per-episode localized dialogue comparison workbooks
- full-series localized dialogue comparison workbook

Dialogue output columns:

- episode
- time/shot
- Chinese character
- localized character
- scene/context
- Chinese dialogue
- British localized dialogue
- notes

Dialogue rules:

- Use the localized character names from the asset mapping workbook; do not invent a second name for the same character.
- Translate and adapt each line to the unified British period setting.
- Preserve plot information, emotional force, threat level, intimacy, sarcasm, status hierarchy, and relationship dynamics.
- Match speech style to identity: aristocrat, heir, heroine, villain, servant, guard, elder, child, etc.
- Use the current scene/context and neighboring lines when Codex fills each completed dialogue file.
- Keep the Chinese line unchanged and put the adapted British line in the localized dialogue column.
- If a speaker cannot be matched to the asset mapping, leave localized character blank and add a note for manual cleanup.

## Shot-Group Asset Replacement

Use `--mode map-shots` after `--mode write`.

Inputs:

- localized full-series asset workbook, default from `BRITISH_SHOT_ASSET_MAP_FILE` or `BRITISH_ASSET_FULL_SERIES_FILE`
- source whole-series shot-group workbook, default from `BRITISH_SHOT_INPUT_FILE`

Outputs:

- localized whole-series shot-group workbook, default from `BRITISH_SHOT_OUTPUT_FILE`
- replacement report JSON, default from `BRITISH_SHOT_REPORT_FILE`

Replacement rules:

- Character asset mentions are replaced with the localized English character asset name.
- Scene and prop mentions are replaced with their short localized English asset names. Do not append localized descriptions or prompt text into shot-group cells.
- The script replaces longest asset names first to avoid partial-name collisions.
- By default, replacement is limited to columns whose headers indicate assets, characters, roles, scenes, props, costumes, visual descriptions, or prompts.
- If the shot workbook uses nonstandard headers, rerun with `--replace-all-shot-columns`.
- Review the JSON report. Any unused asset names may indicate either the shot group never mentioned that asset or the source/localized asset names need Codex cleanup.

## Codex Editing Procedure

When filling a draft JSON:

1. Read `previous_localized_rows` first and reuse existing English names and surnames.
2. Read `rows_to_localize` and create one completed row per source row unless a duplicate should clearly merge.
3. Keep the exact eight keys required by the schema and preserve the two Chinese evidence fields.
4. For character rows, invent or reuse a Westernized English name suited to role identity and add the Chinese state suffix.
5. For character rows, write British visual adaptation in `资产简介` and the state/costume-specific equivalent in `角色状态本地化参考`.
6. For scene and prop rows, fill a concise localized English asset name and put the British-period adaptation plus image guidance in `资产简介`; normally leave both character-state fields blank.
7. Avoid real-world place names in generated English names and setting names.

## Bundled Resource

- `scripts/localize_british_assets.py`: CLI table utility for ordered source Excel reading, Codex-editable draft JSON generation, strict eight-column validation, per-episode workbook writing, and full-series workbook writing.
- `scripts/localize_british_assets.py --mode prepare-dialogue/write-dialogue`: prepare Codex-editable dialogue localization drafts and write per-episode plus full-series Chinese/British dialogue comparison workbooks.
- `scripts/localize_british_assets.py --mode map-shots`: replace source asset mentions in the whole-series shot-group workbook using the localized full-series asset mapping workbook.

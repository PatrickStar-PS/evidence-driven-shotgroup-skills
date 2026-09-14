# Output schema

## Episode candidate files

Store `episode_candidates/EPxx.json` with `episode`, extraction metadata, and `assets`. Every asset requires:

- `local_asset_id`: unique across the run, formatted from episode plus local sequence;
- `asset_type`: `人物`, `场景`, or `道具`;
- `asset_kind`: `人物本体`, `人物状态`, `场景本体`, `场景状态`, `道具本体`, or `道具状态`;
- `proposed_name` and `semantic_description`;
- `parent_local_asset_id` for state rows when the parent is present in that episode;
- `aliases`, `evidence`, `distinguishing_features`, and `episode`.

The combined file `全剧_单集资产候选.json` is a lossless concatenation of these assets. Do not deduplicate it locally.

## Global merge

Store the selected semantic merge result in `global_merge.json` (Codex local merge by default; 中转站 Pro only when explicitly requested):

```json
{
  "global_assets": [{
    "global_asset_id": "CHAR_001",
    "asset_type": "人物",
    "asset_kind": "人物本体",
    "name": "稳定中文名",
    "description": "全剧证据综合后的中文语义描述",
    "parent_global_asset_id": "",
    "aliases": [],
    "episodes": ["EP01"],
    "source_local_asset_ids": ["EP01_CHAR_001"]
  }],
  "mapping": [{"local_asset_id": "EP01_CHAR_001", "global_asset_id": "CHAR_001"}]
}
```

Every local ID must map exactly once. Mapping completeness is a structural requirement, not a semantic review mechanism.

## Chinese pre-localization workbook

Use worksheet `中文资产表` and exactly:

1. `资产类型`
2. `资产中文原名`
3. `原始中文解析描述`
4. `角色状态中文参考描述`
5. `出现集号`

Allow only `人物`, `场景`, and `道具`. Use one row per global asset. For every character row, list the base character and all related character states separated by `；`; leave the field blank for scenes and props. Sort appearances and join them with `、`.

## Final localized workbook

The downstream localization stage produces exactly:

1. `资产类型`
2. `资产中文原名`
3. `资产本地化英文名`
4. `资产简介`
5. `原始中文解析描述`
6. `角色状态中文参考描述`
7. `角色状态本地化参考`
8. `出现集号`

The parser owns columns 1, 2, 5, 6, and 8. Localization owns columns 3, 4, and 7.

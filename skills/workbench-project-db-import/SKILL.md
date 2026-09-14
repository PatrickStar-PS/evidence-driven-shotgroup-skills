---
name: workbench-project-db-import
description: Import a short-drama project's generated asset, dialogue, shot-group, output, key-pool, voice, and service configuration paths into the local asset-image workbench SQLite database after other parsing skills finish, without changing those upstream skill outputs.
---

# Workbench Project DB Import

Use this skill when the user wants to put a project's generated data sources into the asset-image workbench database, especially after running asset parsing, dialogue parsing, British localization, shot-group parsing, or video adapter generation skills.

This skill is a bridge between upstream parsing skills and the web workbench. It must not change the upstream skills' behavior or rewrite their output files unless the user separately asks for that. Its normal job is to register paths and configuration values in the workbench database so the web tool can load them by project.

## Scope

Register project-level configuration into the local workbench SQLite database:

- project name and root directory
- British localized asset workbook
- video shot-group adapter workbook
- video dialogue adapter workbook
- image output directory
- video Asset URI map
- 中转站 key pool path
- voice directory and voice library path
- selected model, concurrency, size, and service settings when supplied

Do not upload files, delete files, run video parsing, run image generation, or merge Excel files from this skill.

## Required safety rules

- Only import paths for the current project named by the user or clearly implied by the current working context.
- Do not scan or reuse another project's data unless the user explicitly names that project as the one being imported.
- Keep Excel files as the business data source; this skill only registers where those files are.
- If a source path is missing, register only when the user intentionally wants a placeholder; otherwise report the missing path.
- 如果提供了项目根目录但没有显式提供 `RELAY_OUTPUT_DIR`，导入器必须补为该项目下的 `资产生图输出`。
- 如果没有显式提供 `VIDEO_DIALOGUE_TABLE`，导入器必须只在当前项目根目录内查找台词 Excel；找不到时写入当前项目内的默认候选路径，禁止继承其他项目的台词表路径。
- 如果没有显式提供 `VIDEO_ASSET_URI_MAP`，导入器必须补为当前项目输出目录下的 `video_asset_uri_map.csv`。
- Treat API keys and key-pool files as sensitive. It is acceptable to write them to the local database when the user authorizes it, but do not print key values in the response.

## Preferred helper

Use `scripts/import_workbench_project_db.py` for deterministic imports.

Use `--set KEY=VALUE` for additional approved workbench configuration values.

The helper writes to the default database:

```text
C:\path\to\workbench\data\project_configs.db
```

Override it with `--db` only when the user is installing another workbench database.

## Handoff contract for upstream skills

When an upstream skill finishes, collect its final artifact paths and call this import skill rather than modifying the upstream skill. Map artifacts to these keys:

| Artifact | Database env key |
|---|---|
| eight-column British asset workbook | `RELAY_ASSET_TABLE` |
| asset image output directory | `RELAY_OUTPUT_DIR` |
| web video shot-group adapter workbook | `VIDEO_SHOT_TABLE` |
| web video dialogue adapter workbook | `VIDEO_DIALOGUE_TABLE` |
| video Asset URI map | `VIDEO_ASSET_URI_MAP` |
| 中转站 key pool | `BAI_KEY_POOL_FILE` and usually `PROMPT_ASSIST_BAI_KEY_POOL_FILE` |
| voice directory | `VIDEO_VOICE_DIR` |
| voice library JSON | `VOICE_ASSET_LIBRARY_JSON` |

After import, verify with the web tool endpoint when available:

```text
http://127.0.0.1:<port>/api/project-env?project=<project>
```

The final response should summarize imported keys and any missing paths, without exposing secrets.


## 配置边界补充

- 本 skill 只写入项目级数据源与项目级开关到 `project_env_vars` / `project_configs`。
- 不写入公共服务授权、API key、TOS、火山、relay 全局密钥；这些由网页工具公共配置表 `service_env_vars` 统一管理。
- `--set` 仅允许项目级键；如果传入服务级密钥键，应停止并提示改用公共服务配置导入流程。
- 这样做是为了让资产解析、台词解析、镜头组解析等上游 skill 不需要改动，导入层按项目登记数据源即可。

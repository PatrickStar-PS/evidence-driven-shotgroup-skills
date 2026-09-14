from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = Path("project_configs.db")

COMMENTS = {
    "PROJECT_NAME": "项目标识名，用于数据库按项目区分配置。",
    "PROJECT_DIR": "当前项目根目录，后续迁移/重新定位项目时的主路径。",
    "SOURCE_VIDEO_DIR": "原始剧集视频所在目录，用于视频预览、镜头源定位或后续解析辅助。",
    "ANALYSIS_OUTPUT_DIR": "镜头组解析流程的输出目录，用于追溯前置解析结果。",
    "ASSET_WORKBENCH_PORT": "网页工具本地服务端口。",
    "RELAY_ASSET_TABLE": "八列英国本地化资产表，网页人物/场景/道具资产的主数据源。",
    "RELAY_OUTPUT_DIR": "资产生图输出目录，保存生成图片、审核状态、绑定结果等项目输出。",
    "VIDEO_SHOT_TABLE": "网页视频生成读取的镜头组适配 Excel。",
    "VIDEO_DIALOGUE_TABLE": "网页视频生成读取的台词适配 Excel。",
    "VIDEO_ASSET_URI_MAP": "图片资产到火山 Asset URI 的映射表，用于 Seedance 视频参考图绑定。",
    "BAI_KEY_POOL_FILE": "中转站 key pool 文件，用于 中转站 相关调用。",
    "PROMPT_ASSIST_BAI_KEY_POOL_FILE": "提示词辅助调用使用的 中转站 key pool 文件。",
    "VIDEO_VOICE_DIR": "本地音色素材目录。",
    "VOICE_ASSET_LIBRARY_JSON": "音色素材库索引 JSON。",
    "RELAY_MODEL": "图片生成模型名称。",
    "VIDEO_MODEL": "视频生成模型名称。",
    "PROMPT_ASSIST_BAI_MODEL": "中转站 提示词辅助模型名称。",
}
PROJECT_DATA_ENV_KEYS = {
    "PROJECT_NAME",
    "PROJECT_DIR",
    "SOURCE_VIDEO_DIR",
    "ANALYSIS_OUTPUT_DIR",
    "ASSET_WORKBENCH_PORT",
    "RELAY_ASSET_TABLE",
    "RELAY_OUTPUT_DIR",
    "VIDEO_SHOT_TABLE",
    "VIDEO_DIALOGUE_TABLE",
    "VIDEO_ASSET_URI_MAP",
    "BAI_KEY_POOL_FILE",
    "PROMPT_ASSIST_BAI_KEY_POOL_FILE",
    "VIDEO_VOICE_DIR",
    "VOICE_ASSET_LIBRARY_JSON",
    "RELAY_MODEL",
    "VIDEO_MODEL",
    "PROMPT_ASSIST_BAI_MODEL",
}

PATH_KEYS = {
    "PROJECT_DIR",
    "SOURCE_VIDEO_DIR",
    "ANALYSIS_OUTPUT_DIR",
    "RELAY_ASSET_TABLE",
    "RELAY_OUTPUT_DIR",
    "VIDEO_SHOT_TABLE",
    "VIDEO_DIALOGUE_TABLE",
    "VIDEO_ASSET_URI_MAP",
    "BAI_KEY_POOL_FILE",
    "PROMPT_ASSIST_BAI_KEY_POOL_FILE",
    "VIDEO_VOICE_DIR",
    "VOICE_ASSET_LIBRARY_JSON",
}


def parse_set(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"--set must use KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit(f"--set has empty key: {item}")
        if key not in PROJECT_DATA_ENV_KEYS:
            raise SystemExit(f"--set only accepts project-level keys, got: {key}")
        result[key] = value
    return result


def ensure_schema(db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL UNIQUE,
                project_root TEXT,
                port INTEGER,
                env_file TEXT,
                shared_env_file TEXT,
                asset_table_path TEXT,
                analysis_output_dir TEXT,
                source_video_dir TEXT,
                output_dir TEXT,
                video_shot_table_path TEXT,
                video_dialogue_table_path TEXT,
                video_asset_uri_map_path TEXT,
                bai_key_pool_path TEXT,
                prompt_assist_bai_key_pool_path TEXT,
                voice_dir TEXT,
                voice_library_json TEXT,
                relay_model TEXT,
                video_model TEXT,
                prompt_assist_model TEXT,
                updated_at TEXT NOT NULL,
                last_opened_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_env_vars (
                project_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'database_import',
                effective INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_name, key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_env_vars (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                sensitive INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'shared_env',
                effective INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(project_env_vars)")}
        if "comment" not in columns:
            conn.execute("ALTER TABLE project_env_vars ADD COLUMN comment TEXT NOT NULL DEFAULT ''")


def existing_path_report(values: dict[str, str]) -> dict[str, bool]:
    return {key: Path(value).expanduser().exists() for key, value in values.items() if key in PATH_KEYS and value}


def find_workbook(project_root: Path, keywords: tuple[str, ...]) -> str:
    try:
        if not project_root.exists():
            return ""
        candidates = [
            item
            for item in project_root.rglob("*.xlsx")
            if not item.name.startswith("~$") and all(keyword in item.name for keyword in keywords)
        ]
    except OSError:
        return ""
    if not candidates:
        return ""
    whole = [item for item in candidates if item.name.startswith("全剧")]
    selected = sorted(whole or candidates, key=lambda item: (len(str(item)), str(item)))[0]
    return str(selected)


def apply_project_defaults(values: dict[str, str]) -> dict[str, str]:
    project_root_value = str(values.get("PROJECT_DIR") or values.get("SOURCE_VIDEO_DIR") or "").strip()
    if not project_root_value:
        return values
    project_root = Path(project_root_value).expanduser()
    values.setdefault("SOURCE_VIDEO_DIR", str(project_root))
    values.setdefault("ANALYSIS_OUTPUT_DIR", str(project_root / "资产输出"))
    values.setdefault("RELAY_OUTPUT_DIR", str(project_root / "资产生图输出"))
    if not str(values.get("VIDEO_DIALOGUE_TABLE") or "").strip():
        found_dialogue = find_workbook(project_root, ("台词",))
        values["VIDEO_DIALOGUE_TABLE"] = found_dialogue or str(
            Path(values["RELAY_OUTPUT_DIR"]) / "british_localized_assets" / "dialogue" / "全剧_英国本地化台词对照.xlsx"
        )
    if not str(values.get("VIDEO_ASSET_URI_MAP") or "").strip():
        values["VIDEO_ASSET_URI_MAP"] = str(Path(values["RELAY_OUTPUT_DIR"]) / "video_asset_uri_map.csv")
    return values


def upsert(db: Path, project: str, values: dict[str, str], source: str) -> dict[str, object]:
    now = dt.datetime.now().isoformat(timespec="seconds")
    values = {key: value for key, value in values.items() if key in PROJECT_DATA_ENV_KEYS and value}
    ensure_schema(db)
    with sqlite3.connect(db) as conn:
        conn.executemany(
            """
            INSERT INTO project_env_vars(project_name, key, value, comment, source, effective, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(project_name, key) DO UPDATE SET
                value=excluded.value,
                comment=excluded.comment,
                source=excluded.source,
                effective=1,
                updated_at=excluded.updated_at
            """,
            [(project, key, value, COMMENTS.get(key, ""), source, now) for key, value in sorted(values.items())],
        )
        conn.execute(
            """
            INSERT INTO project_configs(
                project_name, project_root, port, asset_table_path, analysis_output_dir,
                source_video_dir, output_dir, video_shot_table_path, video_dialogue_table_path,
                video_asset_uri_map_path, bai_key_pool_path, prompt_assist_bai_key_pool_path,
                voice_dir, voice_library_json, relay_model, video_model, prompt_assist_model,
                updated_at, last_opened_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_name) DO UPDATE SET
                project_root=COALESCE(NULLIF(excluded.project_root, ''), project_configs.project_root),
                port=COALESCE(excluded.port, project_configs.port),
                asset_table_path=COALESCE(NULLIF(excluded.asset_table_path, ''), project_configs.asset_table_path),
                analysis_output_dir=COALESCE(NULLIF(excluded.analysis_output_dir, ''), project_configs.analysis_output_dir),
                source_video_dir=COALESCE(NULLIF(excluded.source_video_dir, ''), project_configs.source_video_dir),
                output_dir=COALESCE(NULLIF(excluded.output_dir, ''), project_configs.output_dir),
                video_shot_table_path=COALESCE(NULLIF(excluded.video_shot_table_path, ''), project_configs.video_shot_table_path),
                video_dialogue_table_path=COALESCE(NULLIF(excluded.video_dialogue_table_path, ''), project_configs.video_dialogue_table_path),
                video_asset_uri_map_path=COALESCE(NULLIF(excluded.video_asset_uri_map_path, ''), project_configs.video_asset_uri_map_path),
                bai_key_pool_path=COALESCE(NULLIF(excluded.bai_key_pool_path, ''), project_configs.bai_key_pool_path),
                prompt_assist_bai_key_pool_path=COALESCE(NULLIF(excluded.prompt_assist_bai_key_pool_path, ''), project_configs.prompt_assist_bai_key_pool_path),
                voice_dir=COALESCE(NULLIF(excluded.voice_dir, ''), project_configs.voice_dir),
                voice_library_json=COALESCE(NULLIF(excluded.voice_library_json, ''), project_configs.voice_library_json),
                relay_model=COALESCE(NULLIF(excluded.relay_model, ''), project_configs.relay_model),
                video_model=COALESCE(NULLIF(excluded.video_model, ''), project_configs.video_model),
                prompt_assist_model=COALESCE(NULLIF(excluded.prompt_assist_model, ''), project_configs.prompt_assist_model),
                updated_at=excluded.updated_at,
                last_opened_at=excluded.last_opened_at
            """,
            (
                project,
                values.get("PROJECT_DIR", ""),
                int(values["ASSET_WORKBENCH_PORT"]) if values.get("ASSET_WORKBENCH_PORT", "").isdigit() else None,
                values.get("RELAY_ASSET_TABLE", ""),
                values.get("ANALYSIS_OUTPUT_DIR", ""),
                values.get("SOURCE_VIDEO_DIR", ""),
                values.get("RELAY_OUTPUT_DIR", ""),
                values.get("VIDEO_SHOT_TABLE", ""),
                values.get("VIDEO_DIALOGUE_TABLE", ""),
                values.get("VIDEO_ASSET_URI_MAP", ""),
                values.get("BAI_KEY_POOL_FILE", ""),
                values.get("PROMPT_ASSIST_BAI_KEY_POOL_FILE", ""),
                values.get("VIDEO_VOICE_DIR", ""),
                values.get("VOICE_ASSET_LIBRARY_JSON", ""),
                values.get("RELAY_MODEL", ""),
                values.get("VIDEO_MODEL", ""),
                values.get("PROMPT_ASSIST_BAI_MODEL", ""),
                now,
                now,
            ),
        )
    return {
        "db": str(db),
        "project": project,
        "updated_count": len(values),
        "updated_keys": sorted(values),
        "path_exists": existing_path_report(values),
        "updated_at": now,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import workbench project data-source paths into SQLite.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--source-video-dir")
    parser.add_argument("--analysis-output-dir")
    parser.add_argument("--port")
    parser.add_argument("--asset-table")
    parser.add_argument("--output-dir")
    parser.add_argument("--shot-table")
    parser.add_argument("--dialogue-table")
    parser.add_argument("--asset-uri-map")
    parser.add_argument("--bai-key-pool")
    parser.add_argument("--prompt-assist-bai-key-pool")
    parser.add_argument("--voice-dir")
    parser.add_argument("--voice-library")
    parser.add_argument("--source", default="database_import_skill")
    parser.add_argument("--set", action="append", default=[])
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    values = parse_set(args.set)
    values["PROJECT_NAME"] = args.project
    mapping = {
        "PROJECT_DIR": args.project_root,
        "SOURCE_VIDEO_DIR": args.source_video_dir,
        "ANALYSIS_OUTPUT_DIR": args.analysis_output_dir,
        "ASSET_WORKBENCH_PORT": args.port,
        "RELAY_ASSET_TABLE": args.asset_table,
        "RELAY_OUTPUT_DIR": args.output_dir,
        "VIDEO_SHOT_TABLE": args.shot_table,
        "VIDEO_DIALOGUE_TABLE": args.dialogue_table,
        "VIDEO_ASSET_URI_MAP": args.asset_uri_map,
        "BAI_KEY_POOL_FILE": args.bai_key_pool,
        "PROMPT_ASSIST_BAI_KEY_POOL_FILE": args.prompt_assist_bai_key_pool or args.bai_key_pool,
        "VIDEO_VOICE_DIR": args.voice_dir,
        "VOICE_ASSET_LIBRARY_JSON": args.voice_library,
    }
    values.update({key: value for key, value in mapping.items() if value})
    apply_project_defaults(values)
    missing = [key for key, ok in existing_path_report(values).items() if not ok]
    if missing and not args.allow_missing:
        raise SystemExit("Missing paths: " + ", ".join(missing))
    report = upsert(Path(args.db), args.project, values, args.source)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

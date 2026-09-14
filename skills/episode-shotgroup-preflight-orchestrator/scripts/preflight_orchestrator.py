#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


VIDEO_EXTS = {".mp4", ".mov", ".mkv"}
SCRIPT_ROOT = Path(__file__).resolve().parent
ADAPTIVE_SCRIPT_ROOT = SCRIPT_ROOT.parent.parent / "adaptive-evidence-clipped-shot-groups" / "scripts"


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def episode_id_from_path(path: Path, index: int) -> str:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    if digits:
        return f"EP{int(digits):02d}"
    return f"EP{index:02d}"


def ffprobe_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return round(float(result.stdout.strip()), 3)
    except Exception:
        return None


def plan_ranges(duration: float | None, target: float = 10.0) -> list[dict[str, Any]]:
    if not duration or duration <= 0:
        return []
    ranges = []
    start = 0.0
    idx = 1
    while start < duration - 0.001:
        end = min(duration, start + target)
        ranges.append({"range_id": f"part{idx:02d}", "analysis_start_seconds": round(start, 3), "analysis_end_seconds": round(end, 3)})
        start = end
        idx += 1
    return ranges


def run_command(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "ok": result.returncode == 0,
    }


def adaptive_local_prepare(video: Path, ep_dir: Path, duration: float | None, workers: int, ffmpeg_threads: int) -> dict[str, Any]:
    if not duration or duration <= 0:
        return {"status": "failed", "errors": ["duration is missing; cannot run adaptive local prepare"]}
    work = ep_dir / "adaptive_local_prepare"
    probe_json = work / "probe.json"
    boundaries_json = work / "boundaries.json"
    ranges_json = work / "ranges.json"
    clips_dir = work / "clips"
    clip_manifest = work / "clip_manifest.json"
    commands = [
        [
            "python",
            "-X",
            "utf8",
            str(ADAPTIVE_SCRIPT_ROOT / "probe_video.py"),
            "--input",
            str(video),
            "--output",
            str(probe_json),
        ],
        [
            "python",
            "-X",
            "utf8",
            str(ADAPTIVE_SCRIPT_ROOT / "detect_video_shot_boundaries.py"),
            "--input",
            str(video),
            "--duration",
            str(duration),
            "--output",
            str(boundaries_json),
        ],
        [
            "python",
            "-X",
            "utf8",
            str(ADAPTIVE_SCRIPT_ROOT / "plan_analysis_ranges.py"),
            "--boundaries-file",
            str(boundaries_json),
            "--duration",
            str(duration),
            "--output",
            str(ranges_json),
        ],
        [
            "python",
            "-X",
            "utf8",
            str(ADAPTIVE_SCRIPT_ROOT / "clip_analysis_ranges.py"),
            "--input",
            str(video),
            "--ranges-file",
            str(ranges_json),
            "--output-dir",
            str(clips_dir),
            "--manifest",
            str(clip_manifest),
            "--workers",
            str(workers),
            "--ffmpeg-threads",
            str(ffmpeg_threads),
            "--resume",
        ],
    ]
    logs = []
    for command in commands:
        log = run_command(command)
        logs.append(log)
        if not log["ok"]:
            return {
                "status": "failed",
                "work_dir": str(work),
                "probe_json": str(probe_json),
                "boundaries_json": str(boundaries_json),
                "ranges_json": str(ranges_json),
                "clip_manifest": str(clip_manifest),
                "commands": logs,
                "errors": [log["stderr"] or log["stdout"] or f"command failed: {command[3]}"],
            }
    adaptive_ranges = []
    if ranges_json.exists():
        payload = load_json(ranges_json)
        for item in payload.get("ranges") or []:
            adaptive_ranges.append(
                {
                    "range_id": item.get("id"),
                    "analysis_start_seconds": item.get("start_seconds"),
                    "analysis_end_seconds": item.get("end_seconds"),
                    "clip_start_seconds": item.get("clip_start_seconds"),
                    "clip_end_seconds": item.get("clip_end_seconds"),
                }
            )
    clip_count = 0
    if clip_manifest.exists():
        clip_payload = load_json(clip_manifest)
        clips = clip_payload.get("clips") or clip_payload.get("items") or clip_payload.get("ranges") or []
        clip_count = len(clips) if isinstance(clips, list) else 0
    return {
        "status": "prepared",
        "work_dir": str(work),
        "probe_json": str(probe_json),
        "boundaries_json": str(boundaries_json),
        "ranges_json": str(ranges_json),
        "clip_manifest": str(clip_manifest),
        "adaptive_ranges": adaptive_ranges,
        "clip_count": clip_count,
        "commands": logs,
        "errors": [],
    }


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def canonical_probe_duration(probe_json: Path) -> float | None:
    if not probe_json.exists():
        return None
    try:
        payload = load_json(probe_json)
    except Exception:
        return None
    videos = payload.get("videos") if isinstance(payload, dict) else None
    if isinstance(videos, list) and videos:
        value = videos[0].get("duration_seconds")
        if value is not None:
            return round(float(value), 3)
    return None


def max_range_end(ranges_json: Path) -> float | None:
    if not ranges_json.exists():
        return None
    try:
        payload = load_json(ranges_json)
    except Exception:
        return None
    ends = []
    for item in payload.get("ranges") or []:
        value = item.get("end_seconds", item.get("analysis_end_seconds"))
        if value is not None:
            ends.append(float(value))
    return max(ends) if ends else None


def validate_evidence_pack_manifest(manifest_path: Path) -> list[str]:
    try:
        manifest = load_json(manifest_path)
    except Exception as exc:
        return [f"evidence pack manifest is unreadable: {manifest_path}: {exc}"]
    pages = manifest.get("relay_pages") or []
    if not isinstance(pages, list) or not pages:
        return [f"evidence pack has no relay_pages: {manifest_path}"]
    errors: list[str] = []
    seen: set[str] = set()
    for item in pages:
        role = str(item.get("role") or "")
        if role:
            seen.add(role)
        page = Path(str(item.get("file") or ""))
        page = page if page.is_absolute() else manifest_path.parent / page
        page = page.resolve()
        if not page.exists():
            errors.append(f"evidence page does not exist relative to manifest directory: {page}")
            continue
        expected = str(item.get("sha256") or "")
        if expected and sha256_file(page) != expected:
            errors.append(f"evidence page checksum mismatch for {role or page.name}: {page}")
    required = {"range_boundaries", "action_events", "high_motion_triplets", "shot_space", "person_trajectory"}
    missing = sorted(required - seen)
    if missing:
        errors.append(f"evidence pack is missing required roles: {missing}")
    pose_enabled = bool((manifest.get("pose_gate") or {}).get("pose_enabled"))
    has_pose_page = "multi_person_geometry" in seen
    if pose_enabled != has_pose_page:
        errors.append("pose gate and multi_person_geometry attachment disagree")
    return errors


def evidence_pack_contract_errors(ep_dir: Path) -> list[str]:
    errors: list[str] = []
    for manifest in sorted(ep_dir.glob("**/evidence_pack_manifest.json")):
        errors.extend(validate_evidence_pack_manifest(manifest))
    return errors


def count_final_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    data = load_json(path)
    rows = data.get("rows") or data.get("shot_groups") or data.get("groups")
    return len(rows) if isinstance(rows, list) else None


def latest_existing(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return sorted(existing, key=lambda item: (item.stat().st_mtime, str(item)))[-1]


def find_latest_final_group_json(project: Path, episode: str) -> Path | None:
    run_root = project / "资产输出" / "05_自适应证据镜头组"
    candidates = list(run_root.glob(f"*/{episode}/shot_groups.expanded.json"))
    return latest_existing(candidates)


def qa_report_candidates(final_group_json: Path | None, project: Path, episode: str) -> list[Path]:
    candidates: list[Path] = []
    if final_group_json:
        ep_dir = final_group_json.parent
        candidates.extend(ep_dir.glob("*.qa.json"))
    candidates.extend((project / "资产输出" / "05_自适应证据镜头组").glob(f"*/{episode}/*.qa.json"))
    unique = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def read_excel_qa(project: Path, episode: str, final_group_json: Path | None) -> dict[str, Any]:
    report = latest_existing(qa_report_candidates(final_group_json, project, episode))
    if not report:
        return {"path": "", "exists": False}
    try:
        payload = load_json(report)
    except Exception as exc:
        return {"path": str(report), "exists": True, "read_error": str(exc)}
    errors = payload.get("errors") or []
    warnings = payload.get("warnings") or []
    return {
        "path": str(report),
        "exists": True,
        "rows": payload.get("rows"),
        "errors": errors if isinstance(errors, list) else [str(errors)],
        "warnings": warnings if isinstance(warnings, list) else [str(warnings)],
        "continuity_boundaries": payload.get("continuity_boundaries"),
        "continuity_mode_counts": payload.get("continuity_mode_counts"),
    }


def lightweight_qa_for_episode(project: Path, episode: str, duration: float | None, skipped: bool) -> dict[str, Any]:
    final_group_json = find_latest_final_group_json(project, episode)
    row_count = count_final_rows(final_group_json) if final_group_json else None
    excel_qa = read_excel_qa(project, episode, final_group_json)
    errors: list[str] = []
    warnings: list[str] = []
    if skipped and row_count:
        errors.append("skipped episode has semantic shot-group output")
    if row_count is not None and duration and 45 <= duration <= 75:
        if row_count > 28:
            errors.append("likely compact-record export leakage: final group count exceeds 28")
        elif row_count > 22:
            errors.append("final group count exceeds blocking threshold 22")
        elif row_count > 18:
            warnings.append("final group count is above normal range 8-18")
    if excel_qa.get("read_error"):
        errors.append(f"Excel QA report is unreadable: {excel_qa['read_error']}")
    qa_errors = excel_qa.get("errors") or []
    if qa_errors:
        errors.append(f"Excel QA has hard errors: {len(qa_errors)}")
    qa_rows = excel_qa.get("rows")
    if qa_rows is not None and row_count is not None and int(qa_rows) != int(row_count):
        errors.append(f"Excel QA row count {qa_rows} does not match JSON final group count {row_count}")
    continuity_boundaries = excel_qa.get("continuity_boundaries")
    if row_count is not None and continuity_boundaries is not None and int(continuity_boundaries) != max(0, int(row_count) - 1):
        errors.append(f"continuity boundary count {continuity_boundaries} is not N-1 for {row_count} final groups")
    qa_warnings = excel_qa.get("warnings") or []
    if qa_warnings:
        warnings.append(f"Excel QA warnings: {len(qa_warnings)}")
    status = "passed" if not errors else "failed"
    return {
        "episode": episode,
        "status": status,
        "duration_seconds": duration,
        "final_group_json": str(final_group_json) if final_group_json else "",
        "final_group_count": row_count,
        "excel_qa": excel_qa,
        "errors": errors,
        "warnings": warnings,
    }


def verify_prepare_for_dispatch(ep_dir: Path, video: Path, episode: str) -> dict[str, Any]:
    prepare_path = ep_dir / "prepare_manifest.json"
    if not prepare_path.exists():
        return {"ok": False, "errors": ["prepare_manifest.json is missing"]}
    prepare = load_json(prepare_path)
    errors: list[str] = []
    if prepare.get("episode") != episode:
        errors.append("prepare episode does not match requested episode")
    if Path(str(prepare.get("source_video") or "")).resolve() != video.resolve():
        errors.append("prepare source_video does not match current project video")
    if prepare.get("bai_called"):
        errors.append("prepare manifest unexpectedly says bai_called=true")
    adaptive = prepare.get("adaptive_local_prepare") or {}
    ranges_json = Path(str(adaptive.get("ranges_json") or ""))
    clip_manifest = Path(str(adaptive.get("clip_manifest") or ""))
    probe_json = Path(str(adaptive.get("probe_json") or ""))
    if adaptive:
        if adaptive.get("status") != "prepared":
            errors.append("adaptive local prepare is not prepared")
        if not probe_json.exists():
            errors.append("adaptive probe_json is missing")
        if not ranges_json.exists():
            errors.append("adaptive ranges_json is missing")
        if not clip_manifest.exists():
            errors.append("adaptive clip_manifest is missing")
        probe_duration = canonical_probe_duration(probe_json)
        if probe_json.exists() and probe_duration is None:
            errors.append("adaptive probe_json has no canonical videos[0].duration_seconds")
        prepare_duration = prepare.get("duration_seconds")
        if probe_duration is not None and prepare_duration is not None and abs(float(prepare_duration) - probe_duration) > 0.01:
            errors.append("prepare duration_seconds does not match adaptive probe videos[0].duration_seconds")
        range_end = max_range_end(ranges_json)
        if probe_duration is not None and range_end is not None and range_end > probe_duration + 0.01:
            errors.append(f"prepared range end {range_end:.3f}s exceeds canonical probe duration {probe_duration:.3f}s")
        if clip_manifest.exists():
            clip_payload = load_json(clip_manifest)
            clip_source = clip_payload.get("source") or {}
            if Path(str(clip_source.get("path") or "")).resolve() != video.resolve():
                errors.append("clip manifest source path does not match current project video")
            current_sha = sha256_file(video) if video.exists() else ""
            if clip_source.get("sha256") and current_sha and clip_source.get("sha256") != current_sha:
                errors.append("clip manifest source sha256 does not match current video")
    else:
        errors.append("adaptive_local_prepare is missing; run --adaptive-local-prepare before semantic dispatch")
    errors.extend(evidence_pack_contract_errors(ep_dir))
    return {
        "ok": not errors,
        "errors": errors,
        "prepare_manifest": str(prepare_path),
        "ranges_json": str(ranges_json) if adaptive else "",
        "clip_manifest": str(clip_manifest) if adaptive else "",
        "probe_json": str(probe_json) if adaptive else "",
        "clip_count": adaptive.get("clip_count") if adaptive else None,
    }


def canonical_ranges(path: Path) -> list[tuple[Any, Any, Any, Any, Any]]:
    if not path.exists():
        return []
    payload = load_json(path)
    return [
        (
            item.get("id") or item.get("range_id"),
            item.get("start_seconds"),
            item.get("end_seconds"),
            item.get("clip_start_seconds"),
            item.get("clip_end_seconds"),
        )
        for item in payload.get("ranges") or []
    ]


def find_reference_ranges(compare_project: Path, episode: str) -> Path | None:
    preflight = compare_project / "资产输出" / "06_镜头组预处理调度" / episode / "adaptive_local_prepare" / "ranges.json"
    if preflight.exists():
        return preflight
    adaptive_root = compare_project / "资产输出" / "05_自适应证据镜头组"
    candidates = sorted(adaptive_root.glob(f"*/{episode}/ranges.json"))
    return candidates[-1] if candidates else None


def compare_with_project(compare_project: Path | None, episode: str, video: Path, ranges_json: str) -> dict[str, Any] | None:
    if not compare_project:
        return None
    reference_video = compare_project / video.name
    current_sha = sha256_file(video) if video.exists() else ""
    reference_sha = sha256_file(reference_video) if reference_video.exists() else ""
    reference_ranges = find_reference_ranges(compare_project, episode)
    current_ranges = canonical_ranges(Path(ranges_json)) if ranges_json else []
    expected_ranges = canonical_ranges(reference_ranges) if reference_ranges else []
    return {
        "compare_project": str(compare_project),
        "reference_video": str(reference_video),
        "reference_video_exists": reference_video.exists(),
        "video_fingerprint_match": bool(current_sha and reference_sha and current_sha == reference_sha),
        "reference_ranges_json": str(reference_ranges) if reference_ranges else "",
        "reference_ranges_exists": bool(reference_ranges),
        "ranges_match": bool(current_ranges and expected_ranges and current_ranges == expected_ranges),
        "current_range_count": len(current_ranges),
        "reference_range_count": len(expected_ranges),
    }


def write_handoff_package(output_root: Path, plan: dict[str, Any]) -> dict[str, str]:
    json_path = output_root / "handoff_to_adaptive_parser.json"
    md_path = output_root / "handoff_to_adaptive_parser.md"
    payload = {
        "schema_version": "1.0-adaptive-parser-handoff-package",
        "dispatch_plan": str(output_root / "semantic_dispatch_plan.json"),
        "project_root": plan["project_root"],
        "ready_episodes": plan.get("dispatch_ready_episodes", []),
        "blocked_episodes": plan.get("blocked_episodes", []),
        "bai_called": False,
        "tos_uploaded": False,
        "episodes": plan.get("episodes", []),
    }
    atomic_json(json_path, payload)
    lines = [
        "# Handoff to adaptive-evidence-clipped-shot-groups",
        "",
        f"- Project root: `{plan['project_root']}`",
        f"- External authorized in this plan: `{plan.get('external_authorized')}`",
        f"- 中转站 called by orchestrator: `false`",
        f"- TOS uploaded by orchestrator: `false`",
        "",
        "## Episodes",
        "",
    ]
    for item in plan.get("episodes", []):
        lines.extend(
            [
                f"### {item['episode']}",
                "",
                f"- Dispatch ready: `{item['dispatch_ready']}`",
                f"- Blocked reasons: `{'; '.join(item.get('blocked_reasons') or []) or 'none'}`",
                f"- Video: `{item['video']}`",
                f"- Asset table: `{item['asset_table']}`",
                f"- Dialogue ledger: `{item['dialogue_ledger']}`",
                f"- Ranges JSON: `{item['ranges_json']}`",
                f"- Clip manifest: `{item['clip_manifest']}`",
                f"- Clip count: `{item['clip_count']}`",
                "",
            ]
        )
        comparison = item.get("comparison")
        if comparison:
            lines.extend(
                [
                    "Comparison:",
                    "",
                    f"- Video fingerprint match: `{comparison.get('video_fingerprint_match')}`",
                    f"- Ranges match: `{comparison.get('ranges_match')}`",
                    f"- Current/reference range count: `{comparison.get('current_range_count')}/{comparison.get('reference_range_count')}`",
                    "",
                ]
            )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def load_adaptive_command_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"adaptive command manifest is missing: {path}")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError("adaptive command manifest root must be an object")
    return payload


def adaptive_manifest_has_relay_stages(payload: dict[str, Any]) -> bool:
    for episode in payload.get("episodes") or []:
        for stage in episode.get("stages") or []:
            if str(stage.get("kind") or "") == "relay":
                return True
    return False


def validate_adaptive_command_manifest(path: Path, ready_episodes: list[str]) -> tuple[list[str], dict[str, Any] | None]:
    errors: list[str] = []
    try:
        payload = load_adaptive_command_manifest(path)
    except Exception as exc:
        return [str(exc)], None
    if payload.get("schema_version") != "1.0-adaptive-batch-command-manifest":
        errors.append("adaptive command manifest schema_version must be 1.0-adaptive-batch-command-manifest")
    episodes = payload.get("episodes") or []
    if not isinstance(episodes, list) or not episodes:
        errors.append("adaptive command manifest episodes are empty")
        return errors, payload
    manifest_eps = [str(item.get("episode") or "") for item in episodes]
    if len(set(manifest_eps)) != len(manifest_eps):
        errors.append("adaptive command manifest has duplicated episodes")
    ready_set = set(ready_episodes)
    for ep in manifest_eps:
        if ep not in ready_set:
            errors.append(f"adaptive command manifest episode {ep} is not dispatch-ready")
    for episode in episodes:
        ep = str(episode.get("episode") or "")
        stages = episode.get("stages") or []
        if not isinstance(stages, list) or not stages:
            errors.append(f"adaptive command manifest episode {ep} has no stages")
            continue
        for stage in stages:
            name = str(stage.get("name") or "")
            kind = str(stage.get("kind") or "")
            commands = stage.get("commands") or []
            if kind not in {"local", "relay"}:
                errors.append(f"adaptive command manifest episode {ep} stage {name} has invalid kind {kind!r}")
            if not isinstance(commands, list):
                errors.append(f"adaptive command manifest episode {ep} stage {name} commands must be a list")
                continue
            seen_ids: set[str] = set()
            for command in commands:
                command_id = str(command.get("id") or "")
                argv = command.get("argv")
                if not command_id:
                    errors.append(f"adaptive command manifest episode {ep} stage {name} has command without id")
                elif command_id in seen_ids:
                    errors.append(f"adaptive command manifest episode {ep} stage {name} duplicates command id {command_id}")
                seen_ids.add(command_id)
                if not isinstance(argv, list) or not argv:
                    errors.append(f"adaptive command manifest episode {ep} stage {name} command {command_id or '<missing>'} has empty argv")
    return errors, payload


def execute_adaptive_runner(
    output_root: Path,
    command_manifest: Path,
    episode_workers: int,
    range_workers: int,
    local_workers: int,
    resume: bool,
    run_id: str | None = None,
) -> dict[str, Any]:
    suffix = f"_{run_id}" if run_id else ""
    status = output_root / f"adaptive_runner_status{suffix}.json"
    logs_dir = output_root / f"adaptive_runner_logs{suffix}"
    work_dir = output_root / f"adaptive_runner_workspaces{suffix}"
    command = [
        "python",
        "-X",
        "utf8",
        str(ADAPTIVE_SCRIPT_ROOT / "run_multi_episode_pipeline.py"),
        "--manifest",
        str(command_manifest),
        "--status",
        str(status),
        "--logs-dir",
        str(logs_dir),
        "--work-dir",
        str(work_dir),
        "--episode-workers",
        str(episode_workers),
        "--range-workers",
        str(range_workers),
        "--local-workers",
        str(local_workers),
        "--resume" if resume else "--no-resume",
    ]
    result = run_command(command)
    return {
        "command": command,
        "returncode": result["returncode"],
        "ok": result["ok"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "status": str(status),
        "logs_dir": str(logs_dir),
        "work_dir": str(work_dir),
    }


def build_adaptive_manifest_from_prepare(
    project: Path,
    output_root: Path,
    asset_table: Path,
    ready_episodes: list[str],
    tos_env: Path,
    key_pool: Path | None,
    final_root: Path,
    local_workers: int,
    range_workers: int,
    run_id: str,
) -> dict[str, Any]:
    manifest = output_root / f"adaptive_command_manifest_auto_{run_id}.json"
    command = [
        "python",
        "-X",
        "utf8",
        str(SCRIPT_ROOT / "build_adaptive_command_manifest.py"),
        "--project-root",
        str(project),
        "--preflight-root",
        str(output_root),
        "--final-root",
        str(final_root),
        "--asset-workbook",
        str(asset_table),
        "--tos-env",
        str(tos_env),
        "--output",
        str(manifest),
        "--local-workers",
        str(local_workers),
        "--range-workers",
        str(range_workers),
    ]
    for episode in ready_episodes:
        command.extend(["--episode", episode])
    if key_pool:
        command.extend(["--key-pool", str(key_pool)])
    result = run_command(command)
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or result["stdout"] or "auto adaptive command manifest generation failed")
    return {"path": str(manifest), "command": command, "result": result}


def finalize_adaptive_outputs(
    project: Path,
    output_root: Path,
    asset_table: Path,
    command_manifest: Path,
    ready_episodes: list[str],
    final_root: Path,
) -> dict[str, Any]:
    command = [
        "python",
        "-X",
        "utf8",
        str(SCRIPT_ROOT / "finalize_adaptive_outputs.py"),
        "--project-root",
        str(project),
        "--manifest",
        str(command_manifest),
        "--preflight-root",
        str(output_root),
        "--final-root",
        str(final_root),
        "--asset-workbook",
        str(asset_table),
        "--allow-contract-fix",
    ]
    for episode in ready_episodes:
        command.extend(["--episode", episode])
    result = run_command(command)
    return {
        "command": command,
        "returncode": result["returncode"],
        "ok": result["ok"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "report": str(final_root / "orchestrator_finalize_report.json"),
    }


def write_semantic_dispatch_plan(
    output_root: Path,
    project: Path,
    asset_table: Path,
    episode_items: list[dict[str, Any]],
    external_authorized: bool,
    execute_semantic: bool,
    compare_project: Path | None,
    adaptive_command_manifest: Path | None,
) -> dict[str, Any]:
    planned = []
    for item in episode_items:
        if not item.get("ready_for_semantic"):
            continue
        ep = str(item["episode"])
        video = Path(str(item["video"]))
        ep_dir = output_root / ep
        dialogue = project / "资产输出" / "04_完整台词台账" / ep / "dialogue_ledger.json"
        verify = verify_prepare_for_dispatch(ep_dir, video, ep)
        blocked = []
        if not external_authorized:
            blocked.append("external semantic dispatch not authorized")
        if not verify["ok"]:
            blocked.extend(verify["errors"])
        comparison = compare_with_project(compare_project, ep, video, verify["ranges_json"])
        if comparison and not comparison.get("video_fingerprint_match"):
            blocked.append("comparison project video fingerprint does not match")
        if comparison and comparison.get("reference_ranges_exists") and not comparison.get("ranges_match"):
            blocked.append("prepared ranges do not match comparison project")
        planned.append(
            {
                "episode": ep,
                "video": str(video),
                "asset_table": str(asset_table),
                "dialogue_ledger": str(dialogue),
                "prepare_manifest": verify["prepare_manifest"],
                "ranges_json": verify["ranges_json"],
                "clip_manifest": verify["clip_manifest"],
                "clip_count": verify["clip_count"],
                "dispatch_ready": not blocked,
                "blocked_reasons": blocked,
                "comparison": comparison,
                "handoff_target_skill": "adaptive-evidence-clipped-shot-groups",
                "handoff_instruction": (
                    "Use the current-project asset workbook, episode dialogue ledger, and prepared adaptive ranges/clips. "
                    "Do not reuse another project's assets, dialogue, or semantic results. Run the existing adaptive parser; "
                    "after completion, run lightweight QA before whole-drama merge."
                ),
            }
        )
    plan = {
        "schema_version": "1.0-episode-shotgroup-semantic-dispatch-plan",
        "project_root": str(project),
        "output_root": str(output_root),
        "external_authorized": external_authorized,
        "execute_semantic_requested": execute_semantic,
        "adaptive_command_manifest": str(adaptive_command_manifest) if adaptive_command_manifest else "",
        "bai_called": False,
        "tos_uploaded": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "episodes": planned,
        "dispatch_ready_episodes": [item["episode"] for item in planned if item["dispatch_ready"]],
        "blocked_episodes": [item["episode"] for item in planned if not item["dispatch_ready"]],
    }
    if execute_semantic:
        manifest_errors: list[str] = []
        if not adaptive_command_manifest:
            manifest_errors.append("--adaptive-command-manifest is required with --execute-semantic")
        else:
            manifest_errors, manifest_payload = validate_adaptive_command_manifest(
                adaptive_command_manifest,
                plan["dispatch_ready_episodes"],
            )
            plan["adaptive_manifest_has_relay_stages"] = bool(
                manifest_payload and adaptive_manifest_has_relay_stages(manifest_payload)
            )
        if manifest_errors:
            plan["execution_blocked_reasons"] = manifest_errors
            plan["dispatch_ready_episodes"] = []
            plan["blocked_episodes"] = sorted({*plan["blocked_episodes"], *[item["episode"] for item in planned]})
            for item in planned:
                item["dispatch_ready"] = False
                item.setdefault("blocked_reasons", []).extend(manifest_errors)
    atomic_json(output_root / "semantic_dispatch_plan.json", plan)
    plan["handoff_package"] = write_handoff_package(output_root, plan)
    atomic_json(output_root / "semantic_dispatch_plan.json", plan)
    return plan


def run(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project_root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else project / "资产输出" / "06_镜头组预处理调度"
    asset_table = Path(args.asset_table).resolve() if args.asset_table else project / "资产输出" / "02_英国本地化资产" / "全剧_英国本地化资产表.xlsx"
    final_root = Path(args.final_root).resolve() if args.final_root else project / "资产输出" / "05_自适应证据镜头组"
    skip = {item.upper().replace(" ", "") for item in args.skip_episode}
    videos = [Path(p).resolve() for p in args.video] if args.video else sorted(p.resolve() for p in project.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    now = datetime.now().isoformat(timespec="seconds")
    episodes = []

    for index, video in enumerate(videos, 1):
        ep = episode_id_from_path(video, index)
        ep_dir = output_root / ep
        skipped = ep.upper() in skip
        existing_prepare = None
        existing_prepare_path = ep_dir / "prepare_manifest.json"
        if args.mode == "semantic-from-prepare" and existing_prepare_path.exists() and not args.adaptive_local_prepare:
            existing_prepare = load_json(existing_prepare_path)
        duration = (
            existing_prepare.get("duration_seconds")
            if existing_prepare
            else ffprobe_duration(video) if not args.simulate_metadata else args.simulate_duration
        )
        fingerprint = sha256_file(video) if video.exists() and not args.fast_simulate else f"SIMULATED-{video.name}"
        adaptive_prepare = existing_prepare.get("adaptive_local_prepare") if existing_prepare else None
        if skipped:
            ranges = []
        elif existing_prepare:
            ranges = existing_prepare.get("ranges") or []
        elif args.adaptive_local_prepare and not (args.simulate_metadata or args.fast_simulate):
            adaptive_prepare = adaptive_local_prepare(video, ep_dir, duration, args.clip_workers, args.ffmpeg_threads)
            ranges = adaptive_prepare.get("adaptive_ranges") or []
        else:
            ranges = plan_ranges(duration)
        prepare = dict(existing_prepare) if existing_prepare else {
            "episode": ep,
            "source_video": str(video),
            "source_exists": video.exists(),
            "source_fingerprint": fingerprint,
            "duration_seconds": duration,
            "mode": args.mode,
            "prepared_steps": [] if skipped else (
                ["fingerprint", "probe", "boundary_detection", "adaptive_range_plan", "clip_materialization"]
                if adaptive_prepare and adaptive_prepare.get("status") == "prepared"
                else ["fingerprint", "probe", "range_plan"]
            ),
            "ranges": ranges,
            "adaptive_local_prepare": adaptive_prepare,
            "bai_called": False,
            "tos_uploaded": False,
            "ready_for_bai": False,
            "updated_at": now,
        }
        prepare["semantic_check_at"] = now if args.mode == "semantic-from-prepare" else prepare.get("semantic_check_at")
        dialogue = project / "资产输出" / "04_完整台词台账" / ep / "dialogue_ledger.json"
        waiting_for = []
        if not asset_table.exists():
            waiting_for.append("asset_table")
        if not dialogue.exists():
            waiting_for.append("dialogue_ledger")
        ready = bool(not skipped and not waiting_for and ranges)
        qa = lightweight_qa_for_episode(project, ep, duration, skipped) if args.lightweight_qa else None
        if qa and qa.get("status") == "failed":
            ready = False
        dependency = {
            "episode": ep,
            "asset_table": {"path": str(asset_table), "exists": asset_table.exists()},
            "dialogue_ledger": {"path": str(dialogue), "exists": dialogue.exists()},
            "waiting_for": waiting_for,
            "ready_for_semantic": ready,
        }
        if skipped:
            status = "skipped"
        elif qa and qa.get("status") == "failed":
            status = "qa_failed"
        elif adaptive_prepare and adaptive_prepare.get("status") == "failed":
            status = "failed"
        elif not video.exists():
            status = "failed"
        elif "asset_table" in waiting_for:
            status = "waiting_assets"
        elif "dialogue_ledger" in waiting_for:
            status = "waiting_dialogue"
        elif ready:
            status = "ready_for_semantic"
        else:
            status = "prepared"
        state = {
            "episode": ep,
            "status": status,
            "project_root": str(project),
            "prepare_manifest": str(ep_dir / "prepare_manifest.json"),
            "dependency_check": str(ep_dir / "dependency_check.json"),
            "lightweight_qa": str(ep_dir / "lightweight_qa.json") if qa else "",
            "updated_at": now,
        }
        atomic_json(ep_dir / "prepare_manifest.json", prepare)
        atomic_json(ep_dir / "dependency_check.json", dependency)
        if qa:
            atomic_json(ep_dir / "lightweight_qa.json", qa)
        atomic_json(ep_dir / "episode_state.json", state)
        episodes.append({"episode": ep, "status": status, "ready_for_semantic": ready, "skipped": skipped, "waiting_for": waiting_for, "ranges": len(ranges), "video": str(video)})

    batch = {
        "project_root": str(project),
        "output_root": str(output_root),
        "mode": args.mode,
        "simulate": bool(args.simulate_metadata or args.fast_simulate),
        "bai_called": False,
        "created_at": now,
        "episodes": [{k: v for k, v in e.items() if k != "video"} for e in episodes],
        "ready_episodes": [e["episode"] for e in episodes if e["ready_for_semantic"]],
        "skipped_episodes": [e["episode"] for e in episodes if e["skipped"]],
    }
    if args.mode == "semantic-from-prepare":
        auto_manifest_report = None
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.execute_semantic and not args.adaptive_command_manifest and args.auto_build_adaptive_manifest:
            if not args.tos_env:
                raise RuntimeError("--tos-env is required when auto-building the adaptive command manifest for production execution")
            key_pool = Path(args.key_pool).resolve() if args.key_pool else None
            auto_manifest_report = build_adaptive_manifest_from_prepare(
                project,
                output_root,
                asset_table,
                [e["episode"] for e in episodes if e["ready_for_semantic"]],
                Path(args.tos_env).resolve(),
                key_pool,
                final_root,
                args.local_workers,
                args.range_workers,
                run_id,
            )
            args.adaptive_command_manifest = auto_manifest_report["path"]
        semantic_plan = write_semantic_dispatch_plan(
            output_root,
            project,
            asset_table,
            episodes,
            args.authorize_external,
            args.execute_semantic,
            Path(args.compare_project).resolve() if args.compare_project else None,
            Path(args.adaptive_command_manifest).resolve() if args.adaptive_command_manifest else None,
        )
        batch["semantic_dispatch_plan"] = semantic_plan
        if auto_manifest_report:
            batch["auto_adaptive_command_manifest"] = auto_manifest_report
        batch["ready_episodes"] = semantic_plan.get("dispatch_ready_episodes", [])
        batch["blocked_episodes"] = semantic_plan.get("blocked_episodes", [])
        if args.execute_semantic and batch["ready_episodes"] and args.adaptive_command_manifest:
            runner = execute_adaptive_runner(
                output_root,
                Path(args.adaptive_command_manifest).resolve(),
                args.episode_workers,
                args.range_workers,
                args.local_workers,
                args.resume,
                run_id if auto_manifest_report else None,
            )
            batch["adaptive_runner"] = runner
            batch["adaptive_runner_invoked"] = True
            batch["bai_called"] = bool(semantic_plan.get("adaptive_manifest_has_relay_stages"))
            batch["tos_uploaded"] = batch["bai_called"]
            if args.auto_finalize:
                finalizer = finalize_adaptive_outputs(
                    project,
                    output_root,
                    asset_table,
                    Path(args.adaptive_command_manifest).resolve(),
                    batch["ready_episodes"],
                    final_root,
                )
                batch["adaptive_finalize"] = finalizer
                if finalizer.get("ok"):
                    batch["final_outputs"] = {
                        "json": str(final_root / "全剧_英国本地化镜头组.json"),
                        "workbook": str(final_root / "全剧_英国本地化镜头组_12列.xlsx"),
                        "report": str(final_root / "orchestrator_finalize_report.json"),
                    }
            if not runner["ok"]:
                if not batch.get("adaptive_finalize", {}).get("ok"):
                    batch["blocked_episodes"] = sorted({*batch.get("blocked_episodes", []), *batch.get("ready_episodes", [])})
                    batch["ready_episodes"] = []
    atomic_json(output_root / "batch_state.json", batch)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and check per-episode shot-group parsing readiness, optionally invoking the existing adaptive parser runner after explicit authorization.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--asset-table")
    parser.add_argument("--video", action="append", default=[])
    parser.add_argument("--skip-episode", action="append", default=[])
    parser.add_argument("--mode", choices=["prepare-only", "prepare-transport", "semantic-from-prepare", "lightweight-qa", "simulate"], default="prepare-only")
    parser.add_argument("--simulate-metadata", action="store_true", help="Use --simulate-duration instead of ffprobe.")
    parser.add_argument("--fast-simulate", action="store_true", help="Avoid hashing video bytes; use simulated fingerprints.")
    parser.add_argument("--simulate-duration", type=float, default=59.3)
    parser.add_argument("--lightweight-qa", action="store_true")
    parser.add_argument("--adaptive-local-prepare", action="store_true", help="Run existing adaptive parser local scripts for probe/boundaries/ranges/clips, but never TOS or 中转站.")
    parser.add_argument("--clip-workers", type=int, default=2)
    parser.add_argument("--ffmpeg-threads", type=int, default=3)
    parser.add_argument("--authorize-external", action="store_true", help="Mark semantic dispatch as externally authorized.")
    parser.add_argument("--execute-semantic", action="store_true", help="Invoke the existing adaptive parser runner after all dispatch guards pass. Requires --authorize-external and --adaptive-command-manifest.")
    parser.add_argument("--direct-run", action="store_true", help="Alias for an explicit user request to run immediately when guards pass; enables --authorize-external and --execute-semantic.")
    parser.add_argument("--adaptive-command-manifest", help="Existing adaptive-evidence-clipped-shot-groups command manifest with schema_version=1.0-adaptive-batch-command-manifest.")
    parser.add_argument("--auto-build-adaptive-manifest", action=argparse.BooleanOptionalAction, default=True, help="When executing semantic production without --adaptive-command-manifest, build one from current-project prepared ranges/clips.")
    parser.add_argument("--auto-finalize", action=argparse.BooleanOptionalAction, default=True, help="After primary compact outputs exist, validate/fix compact contract fields, aggregate by narrative_group, expand, validate, and export final JSON/XLSX without rerunning 中转站.")
    parser.add_argument("--tos-env", help="TOS environment file used only when auto-building a production adaptive command manifest.")
    parser.add_argument("--key-pool", help="中转站 key pool file used only when auto-building a production adaptive command manifest. Defaults to <project>/bai_key_pool.txt in the manifest builder.")
    parser.add_argument("--final-root", help="Final shot-group output root. Defaults to <project>/资产输出/05_自适应证据镜头组.")
    parser.add_argument("--episode-workers", type=int, default=3)
    parser.add_argument("--range-workers", type=int, default=8)
    parser.add_argument("--local-workers", type=int, default=2)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--compare-project", help="Optional reference project root used only to compare video fingerprints and prepared ranges.")
    args = parser.parse_args()
    if args.direct_run:
        args.authorize_external = True
        args.execute_semantic = True
    if args.mode in {"prepare-only", "simulate", "semantic-from-prepare"}:
        pass
    elif args.mode == "prepare-transport":
        raise SystemExit("prepare-transport is a declared mode but this first implementation intentionally does not upload TOS.")
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

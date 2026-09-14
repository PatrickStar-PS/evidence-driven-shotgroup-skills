#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ADAPTIVE = Path(__file__).resolve().parents[2] / "adaptive-evidence-clipped-shot-groups" / "scripts"
DEFAULT_NODE = Path(shutil.which("node") or "node")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(argv: list[str], *, allow_fail: bool = False) -> dict[str, Any]:
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    report = {
        "argv": argv,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "ok": result.returncode == 0,
    }
    if result.returncode != 0 and not allow_fail:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"command failed: {argv}")
    return report


def py(script: Path, *args: object) -> list[str]:
    return ["python", "-X", "utf8", str(script), *map(str, args)]


def command_ok(report: dict[str, Any]) -> bool:
    return bool(report.get("ok"))


def duration_from_prepare(preflight_root: Path, episode: str) -> float:
    prepare = preflight_root / episode / "prepare_manifest.json"
    if not prepare.exists():
        raise RuntimeError(f"{episode}: prepare_manifest.json is missing: {prepare}")
    payload = load_json(prepare)
    adaptive = payload.get("adaptive_local_prepare") or {}
    probe = Path(str(adaptive.get("probe_json") or ""))
    if probe.exists():
        probe_payload = load_json(probe)
        videos = probe_payload.get("videos") or []
        if videos and videos[0].get("duration_seconds") is not None:
            return float(videos[0]["duration_seconds"])
    if payload.get("duration_seconds") is not None:
        return float(payload["duration_seconds"])
    raise RuntimeError(f"{episode}: cannot determine duration from prepare manifest")


def episode_ranges(preflight_root: Path, episode: str) -> list[dict[str, Any]]:
    ranges_path = preflight_root / episode / "adaptive_local_prepare" / "ranges.json"
    if not ranges_path.exists():
        raise RuntimeError(f"{episode}: ranges.json is missing: {ranges_path}")
    ranges = load_json(ranges_path).get("ranges") or []
    if not ranges:
        raise RuntimeError(f"{episode}: ranges.json contains no ranges")
    return ranges


def output_roots_from_manifest(manifest: Path, final_root: Path, episodes: list[str]) -> dict[str, Path]:
    if manifest.exists():
        payload = load_json(manifest)
        roots = payload.get("orchestrator_output_roots") or {}
        if isinstance(roots, dict) and roots:
            return {str(ep): Path(str(path)).resolve() for ep, path in roots.items() if str(ep) in episodes}
    return {ep: (final_root / "orchestrated_auto" / ep).resolve() for ep in episodes}


def validate_or_fix_compact(
    compact: Path,
    duration: float,
    boundaries: Path,
    range_start: float,
    range_end: float,
    adaptive_scripts: Path,
    helper_scripts: Path,
    allow_contract_fix: bool,
) -> dict[str, Any]:
    validate = py(
        adaptive_scripts / "validate_compact_timeline.py",
        "--input",
        compact,
        "--duration",
        f"{duration:.3f}",
        "--boundaries-file",
        boundaries,
        "--range-start",
        range_start,
        "--range-end",
        range_end,
    )
    first = run_command(validate, allow_fail=True)
    if command_ok(first):
        return {"compact": str(compact), "fixed": False, "validate": first}
    if not allow_contract_fix:
        raise RuntimeError(first["stderr"] or first["stdout"] or f"compact validation failed: {compact}")
    fixed = compact.with_name("compact_timeline.contract_fixed.json")
    backup = compact.with_name("compact_timeline.before_contract_fix.json")
    fix_report = run_command(py(helper_scripts / "fix_compact_contract_fields.py", "--input", compact, "--output", fixed, "--backup", backup))
    second = run_command(
        [
            *validate[:validate.index("--input") + 1],
            str(fixed),
            *validate[validate.index("--input") + 2 :],
        ],
        allow_fail=True,
    )
    if not command_ok(second):
        raise RuntimeError(second["stderr"] or second["stdout"] or f"contract-fixed compact validation failed: {fixed}")
    shutil.copy2(fixed, compact)
    return {"compact": str(compact), "fixed": True, "backup": str(backup), "fix": fix_report, "validate_before": first, "validate_after": second}


def finalize_episode(
    episode: str,
    episode_root: Path,
    preflight_root: Path,
    asset_workbook: Path,
    adaptive_scripts: Path,
    helper_scripts: Path,
    node: Path,
    allow_contract_fix: bool,
) -> dict[str, Any]:
    duration = duration_from_prepare(preflight_root, episode)
    ranges = episode_ranges(preflight_root, episode)
    boundaries = preflight_root / episode / "adaptive_local_prepare" / "boundaries.json"
    compact_inputs: list[Path] = []
    compact_reports: list[dict[str, Any]] = []
    for item in ranges:
        rid = str(item.get("id") or item.get("range_id") or "")
        if not rid:
            raise RuntimeError(f"{episode}: range without id")
        compact = episode_root / rid / "compact_timeline.json"
        if not compact.exists():
            raise RuntimeError(f"{episode} {rid}: compact_timeline.json is missing; primary 中转站 output is not complete")
        range_start = float(item.get("start_seconds", item.get("analysis_start_seconds")))
        range_end = float(item.get("end_seconds", item.get("analysis_end_seconds")))
        compact_reports.append(validate_or_fix_compact(compact, duration, boundaries, range_start, range_end, adaptive_scripts, helper_scripts, allow_contract_fix))
        compact_inputs.append(compact)

    merged = episode_root / "compact_timeline.merged.json"
    merge_report = run_command(py(adaptive_scripts / "merge_compact_ranges.py", "--inputs", *compact_inputs, "--duration", f"{duration:.3f}", "--episode", episode.replace("EP", ""), "--output", merged))

    expand_config = episode_root / "expand_config.json"
    config_report = run_command(py(helper_scripts / "build_expand_config_from_compact.py", "--compact", merged, "--assets", asset_workbook, "--output", expand_config))

    expanded = episode_root / "shot_groups.expanded.json"
    expand_report = run_command(py(adaptive_scripts / "expand_compact_timeline.py", "--input", merged, "--config", expand_config, "--output", expanded))
    expanded_validate = run_command(py(adaptive_scripts / "validate_expanded_shot_groups.py", "--input", expanded, "--duration", f"{duration:.3f}"))

    workbook = episode_root / f"{episode}_英国本地化镜头组_12列.xlsx"
    workbook_report = run_command([str(node), str(adaptive_scripts / "build_shot_group_workbook.mjs"), "--input", str(expanded), "--assets", str(asset_workbook), "--output", str(workbook)])
    rows = len(load_json(expanded).get("rows") or [])
    return {
        "episode": episode,
        "output_root": str(episode_root),
        "duration_seconds": duration,
        "compact_ranges": len(compact_inputs),
        "contract_fixes": sum(1 for report in compact_reports if report.get("fixed")),
        "merged_compact": str(merged),
        "expand_config": str(expand_config),
        "expanded_json": str(expanded),
        "workbook": str(workbook),
        "rows": rows,
        "reports": {
            "compact": compact_reports,
            "merge": merge_report,
            "config": config_report,
            "expand": expand_report,
            "expanded_validate": expanded_validate,
            "workbook": workbook_report,
        },
    }


def build_whole_drama(
    episode_results: list[dict[str, Any]],
    final_root: Path,
    asset_workbook: Path,
    adaptive_scripts: Path,
    node: Path,
) -> dict[str, Any]:
    final_root.mkdir(parents=True, exist_ok=True)
    whole_json = final_root / "全剧_英国本地化镜头组.json"
    if len(episode_results) == 1:
        source = Path(episode_results[0]["expanded_json"])
        shutil.copy2(source, whole_json)
        merge_report = {"ok": True, "mode": "single_episode_copy", "source": str(source)}
    else:
        inputs = [Path(item["expanded_json"]) for item in episode_results]
        merge_report = run_command(py(adaptive_scripts / "merge_episode_shot_groups.py", "--inputs", *inputs, "--output", whole_json))
    whole_workbook = final_root / "全剧_英国本地化镜头组_12列.xlsx"
    workbook_report = run_command([str(node), str(adaptive_scripts / "build_shot_group_workbook.mjs"), "--input", str(whole_json), "--assets", str(asset_workbook), "--output", str(whole_workbook)])
    rows = len(load_json(whole_json).get("rows") or [])
    return {
        "json": str(whole_json),
        "workbook": str(whole_workbook),
        "rows": rows,
        "merge": merge_report,
        "workbook_report": workbook_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize adaptive parser compact outputs from the orchestrator without rerunning 中转站.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--episode", action="append", default=[])
    parser.add_argument("--preflight-root", type=Path)
    parser.add_argument("--final-root", type=Path)
    parser.add_argument("--asset-workbook", type=Path)
    parser.add_argument("--adaptive-scripts", type=Path, default=DEFAULT_ADAPTIVE)
    parser.add_argument("--helper-scripts", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--node", type=Path, default=DEFAULT_NODE)
    parser.add_argument("--allow-contract-fix", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    project = args.project_root.resolve()
    preflight_root = (args.preflight_root or project / "资产输出" / "06_镜头组预处理调度").resolve()
    final_root = (args.final_root or project / "资产输出" / "05_自适应证据镜头组").resolve()
    asset_workbook = (args.asset_workbook or project / "资产输出" / "02_英国本地化资产" / "全剧_英国本地化资产表.xlsx").resolve()
    episodes = [ep.upper() for ep in args.episode]
    if not episodes and args.manifest and args.manifest.exists():
        payload = load_json(args.manifest)
        episodes = [str(item.get("episode") or "").upper() for item in payload.get("episodes") or [] if item.get("episode")]
    if not episodes:
        episodes = sorted([p.name.upper() for p in preflight_root.iterdir() if p.is_dir() and p.name.upper().startswith("EP")])
    roots = output_roots_from_manifest(args.manifest.resolve() if args.manifest else Path(), final_root, episodes)
    results = []
    for episode in episodes:
        root = roots.get(episode)
        if root is None:
            raise RuntimeError(f"{episode}: no orchestrated output root found")
        results.append(finalize_episode(episode, root, preflight_root, asset_workbook, args.adaptive_scripts.resolve(), args.helper_scripts.resolve(), args.node.resolve(), args.allow_contract_fix))
    whole = build_whole_drama(results, final_root, asset_workbook, args.adaptive_scripts.resolve(), args.node.resolve())
    report = {
        "status": "complete",
        "project_root": str(project),
        "episodes": results,
        "whole_drama": whole,
    }
    save_json(final_root / "orchestrator_finalize_report.json", report)
    print(json.dumps({"status": "complete", "episodes": len(results), "whole_rows": whole["rows"], "whole_workbook": whole["workbook"], "report": str(final_root / "orchestrator_finalize_report.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

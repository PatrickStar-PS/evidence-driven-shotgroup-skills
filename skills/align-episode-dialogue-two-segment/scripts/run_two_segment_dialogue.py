#!/usr/bin/env python3
"""Run the complete two-segment dialogue workflow."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def run(command: list[str], cwd: Path, allow_code: set[int] | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode not in (allow_code or {0}):
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--assets-workbook", type=Path, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--key-pool-file", type=Path, required=True)
    parser.add_argument("--tos-env-file", type=Path, required=True)
    parser.add_argument("--transport-script", type=Path, help="Optional TOS transport override; defaults to the bundled script")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--expires", type=int, default=21600)
    parser.add_argument("--overlap", type=float, default=3.0)
    args = parser.parse_args()
    if args.overlap <= 0:
        raise RuntimeError("overlap must be positive")
    if args.expires < 60 or args.expires > 604800:
        raise RuntimeError("expires must be between 60 and 604800 seconds")
    started = time.time()
    root = Path.cwd().resolve()
    scripts = Path(__file__).resolve().parent
    transport_script = args.transport_script.resolve() if args.transport_script else scripts / "tos_video_transport.py"
    if not transport_script.is_file():
        raise RuntimeError(f"TOS transport script not found: {transport_script}")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    episode = str(args.episode).zfill(2)
    characters = output / "character_input.json"
    clips = output / "clips"
    clip_manifest = output / "two_segment_manifest.json"
    run([sys.executable, str(scripts / "normalize_character_assets.py"), "--assets-workbook", str(args.assets_workbook.resolve()), "--episode", episode, "--output", str(characters)], root)
    run([sys.executable, str(scripts / "plan_two_segments.py"), "--video", str(args.video.resolve()), "--output-dir", str(clips), "--manifest", str(clip_manifest), "--overlap", str(args.overlap)], root)
    manifest = json.loads(clip_manifest.read_text(encoding="utf-8-sig"))
    parts = manifest["ranges"]
    progress: dict[str, Any] = {"schema_version": "1.0-dialogue-two-segment-run", "episode": episode, "status": "running", "parts": {}, "started_epoch": started}
    progress_path = output / "run_manifest.json"
    atomic_json(progress_path, progress)

    def worker(index: int, item: dict[str, Any]) -> dict[str, Any]:
        part_id = item["id"]
        part_dir = output / part_id
        part_dir.mkdir(parents=True, exist_ok=True)
        url_file, tos_manifest = part_dir / "temporary_url.json", part_dir / "tos_manifest.json"
        ledger, raw = part_dir / "dialogue_ledger_local.json", part_dir / "raw_response.json"
        transport_log = run([sys.executable, str(transport_script), "--input", str(Path(item["clip_path"]).resolve()),
            "--env-file", str(args.tos_env_file.resolve()), "--manifest", str(tos_manifest), "--url-output", str(url_file),
            "--prefix", f"ep{episode}-dialogue-two-segment-{part_id}", "--expires", str(args.expires)], root)
        extract_log = run([sys.executable, str(scripts / "bai_extract_dialogue_clip.py"), "--url-file", str(url_file),
            "--key-pool-file", str(args.key_pool_file.resolve()), "--character-input", str(characters), "--episode", episode,
            "--part-id", part_id, "--duration", str(item["actual_clip_duration_seconds"]), "--source-name", Path(item["clip_path"]).name,
            "--output", str(ledger), "--raw-output", str(raw), "--model", args.model, "--key-offset", str(index)], root)
        return {"status": "complete", "ledger": str(ledger), "raw": str(raw), "transport_log": transport_log, "extract_log": extract_log}

    failures: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(worker, index, item): item["id"] for index, item in enumerate(parts)}
        for future in concurrent.futures.as_completed(futures):
            part_id = futures[future]
            try:
                progress["parts"][part_id] = future.result()
            except Exception as exc:
                failure = {"status": "failed", "error": str(exc)}
                progress["parts"][part_id] = failure
                failures.append({"part_id": part_id, "error": str(exc)})
            atomic_json(progress_path, progress)
    if failures:
        progress.update({"status": "partial", "failures": failures, "elapsed_seconds": round(time.time() - started, 3)})
        atomic_json(progress_path, progress)
        raise RuntimeError(f"{len(failures)} part(s) failed; inspect {progress_path}")
    merged, quarantine = output / "dialogue_ledger.json", output / "quarantined_events.json"
    csv_output, report = output / "dialogue_ledger.csv", output / "validation_report.json"
    try:
        merge_command = [sys.executable, str(scripts / "merge_two_segment_ledgers.py"), "--manifest", str(clip_manifest),
            "--part01", progress["parts"]["part01"]["ledger"], "--part02", progress["parts"]["part02"]["ledger"],
            "--character-input", str(characters), "--episode", episode, "--model", args.model, "--output", str(merged), "--quarantine-output", str(quarantine)]
        run(merge_command, root)
        duration = manifest["source"]["duration_seconds"]
        run([sys.executable, str(scripts / "validate_dialogue_ledger.py"), "--input", str(merged), "--character-input", str(characters),
             "--duration", str(duration), "--csv-output", str(csv_output), "--report", str(report)], root)
        merged_payload = json.loads(merged.read_text(encoding="utf-8-sig"))
        validation_payload = json.loads(report.read_text(encoding="utf-8-sig"))
        with csv_output.open("r", encoding="utf-8-sig", newline="") as stream:
            csv_event_count = sum(1 for _ in csv.DictReader(stream))
        if validation_payload.get("status") != "passed" or csv_event_count != len(merged_payload.get("events") or []):
            raise RuntimeError("final output count or validation status mismatch")
    except Exception as exc:
        progress.update({"status": "failed", "error": str(exc), "elapsed_seconds": round(time.time() - started, 3)})
        atomic_json(progress_path, progress)
        raise
    progress.update({"status": "complete", "ledger": str(merged), "csv": str(csv_output), "validation_report": str(report), "elapsed_seconds": round(time.time() - started, 3)})
    atomic_json(progress_path, progress)
    print(json.dumps({"status": "complete", "ledger": str(merged), "csv": str(csv_output), "elapsed_seconds": progress["elapsed_seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

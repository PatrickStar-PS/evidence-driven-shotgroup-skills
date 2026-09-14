#!/usr/bin/env python3
"""Probe episode videos locally and emit a resumable source manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


def natural_key(path: Path) -> list[object]:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", path.name)]


def fingerprint(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as stream:
        digest.update(stream.read(4 * 1024 * 1024))
        if size > 4 * 1024 * 1024:
            stream.seek(max(0, size - 4 * 1024 * 1024))
            digest.update(stream.read(4 * 1024 * 1024))
    return digest.hexdigest()


def episode_label(path: Path, fallback: int) -> str:
    match = re.search(r"(?:ep|episode|第)?\s*0*(\d{1,4})(?:集)?", path.stem, re.I)
    number = int(match.group(1)) if match else fallback
    return f"{number:02d}"


def collect_videos(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() in VIDEO_EXTENSIONS else []
    if source.is_dir():
        return sorted(
            (item for item in source.iterdir() if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS),
            key=natural_key,
        )
    return []


def probe(ffprobe: str, path: Path) -> dict:
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"ffprobe exited with {result.returncode}")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Video file or directory")
    parser.add_argument("--output", required=True, help="Output JSON manifest")
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    videos = collect_videos(source)
    if not videos:
        raise SystemExit(f"No MP4, MOV, or MKV videos found at: {source}")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("ffprobe is required for local probing but was not found on PATH.")

    manifest = {"schema_version": "1.0", "source": str(source), "videos": [], "errors": []}
    for index, path in enumerate(videos, 1):
        item = {
            "episode": episode_label(path, index),
            "name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "fingerprint": fingerprint(path),
            "status": "pending",
            "completed_segment_ids": [],
        }
        try:
            metadata = probe(ffprobe, path)
            duration = float(metadata.get("format", {}).get("duration", 0) or 0)
            item.update({"duration_seconds": duration, "streams": metadata.get("streams", []), "status": "probed"})
        except Exception as exc:  # Preserve batch progress instead of aborting all files.
            item.update({"status": "failed", "error": str(exc)})
            manifest["errors"].append({"path": str(path), "error": str(exc)})
        manifest["videos"].append(item)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "videos": len(videos), "errors": len(manifest["errors"])}, ensure_ascii=False))
    return 0 if not manifest["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())

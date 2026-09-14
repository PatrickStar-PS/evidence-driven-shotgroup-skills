#!/usr/bin/env python3
"""Plan and optionally render two overlapping dialogue-safe video clips."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout


def probe_duration(video: Path, ffprobe: str) -> float:
    value = run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)]).strip()
    duration = float(value)
    if duration <= 0:
        raise RuntimeError("video duration must be positive")
    return duration


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_silences(text: str) -> list[tuple[float, float]]:
    starts: list[float] = []
    result: list[tuple[float, float]] = []
    for line in text.splitlines():
        start = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start:
            starts.append(float(start.group(1)))
        end = re.search(r"silence_end:\s*([0-9.]+)", line)
        if end and starts:
            result.append((starts.pop(0), float(end.group(1))))
    return result


def choose_split(duration: float, silences: list[tuple[float, float]], window: float) -> tuple[float, str, tuple[float, float] | None]:
    midpoint = duration / 2.0
    eligible = [(start, end) for start, end in silences if start < end and abs(((start + end) / 2.0) - midpoint) <= window]
    if not eligible:
        return midpoint, "midpoint_fallback", None
    selected = min(eligible, key=lambda item: abs(((item[0] + item[1]) / 2.0) - midpoint))
    return (selected[0] + selected[1]) / 2.0, "silence_midpoint", selected


def build_manifest(video: Path, duration: float, split: float, overlap: float, reason: str, silence: tuple[float, float] | None, output_dir: Path, source_hash: str) -> dict[str, Any]:
    left_end = min(duration, split + overlap)
    right_start = max(0.0, split - overlap)
    ranges = [
        {"id": "part01", "clip_path": str((output_dir / "part01.mp4").resolve()), "absolute_offset_seconds": 0.0,
         "logical_start_seconds": 0.0, "logical_end_seconds": round(split, 3), "clip_start_seconds": 0.0,
         "clip_end_seconds": round(left_end, 3), "actual_clip_duration_seconds": round(left_end, 3)},
        {"id": "part02", "clip_path": str((output_dir / "part02.mp4").resolve()), "absolute_offset_seconds": round(right_start, 3),
         "logical_start_seconds": round(split, 3), "logical_end_seconds": round(duration, 3), "clip_start_seconds": round(right_start, 3),
         "clip_end_seconds": round(duration, 3), "actual_clip_duration_seconds": round(duration - right_start, 3)},
    ]
    return {"schema_version": "1.0-dialogue-two-segment-plan", "source": {"path": str(video.resolve()), "name": video.name,
            "sha256": source_hash, "duration_seconds": round(duration, 3)}, "split": {"seconds": round(split, 3), "reason": reason,
            "silence_interval": list(silence) if silence else None, "context_margin_each_side_seconds": overlap,
            "shared_overlap_seconds": round(left_end - right_start, 3)}, "ranges": ranges, "warnings": [] if silence else ["No qualifying midpoint silence; used midpoint fallback."]}


def render_clip(video: Path, item: dict[str, Any], ffmpeg: str) -> None:
    target = Path(item["clip_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, "-y", "-ss", str(item["clip_start_seconds"]), "-i", str(video), "-t", str(item["actual_clip_duration_seconds"]),
         "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(target)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--overlap", type=float, default=3.0)
    parser.add_argument("--search-window", type=float, default=10.0)
    parser.add_argument("--silence-duration", type=float, default=0.45)
    parser.add_argument("--silence-noise", default="-32dB")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--duration", type=float, help="Testing override; avoids ffprobe")
    parser.add_argument("--silences-json", type=Path, help="Testing override containing [[start,end],...]")
    args = parser.parse_args()
    if args.overlap <= 0:
        raise RuntimeError("overlap must be positive")
    if args.search_window < 0:
        raise RuntimeError("search-window must not be negative")
    if args.silence_duration <= 0:
        raise RuntimeError("silence-duration must be positive")
    video = args.video.resolve()
    duration = args.duration if args.duration is not None else probe_duration(video, args.ffprobe)
    if duration <= args.overlap * 2:
        raise RuntimeError("video duration must be greater than twice the overlap")
    if args.silences_json:
        silences = [tuple(map(float, pair)) for pair in json.loads(args.silences_json.read_text(encoding="utf-8-sig"))]
    else:
        completed = subprocess.run([args.ffmpeg, "-hide_banner", "-i", str(video), "-af", f"silencedetect=noise={args.silence_noise}:d={args.silence_duration}", "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        silences = parse_silences(completed.stderr)
    split, reason, silence = choose_split(duration, silences, args.search_window)
    source_hash = sha256_file(video) if video.exists() else "testing-no-source-file"
    manifest = build_manifest(video, duration, split, args.overlap, reason, silence, args.output_dir.resolve(), source_hash)
    if not args.plan_only:
        if not video.is_file():
            raise RuntimeError(f"video not found: {video}")
        for item in manifest["ranges"]:
            render_clip(video, item, args.ffmpeg)
            item["status"] = "ready"
    else:
        for item in manifest["ranges"]:
            item["status"] = "planned"
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "planned" if args.plan_only else "ready", "split": round(split, 3), "reason": reason, "overlap": manifest["split"]["shared_overlap_seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def scene_scores(video: Path) -> list[tuple[float, float]]:
    command = [
        "ffmpeg", "-hide_banner", "-i", str(video),
        "-vf", "select='gte(scene,0)',metadata=print:key=lavfi.scene_score:file=-",
        "-an", "-f", "null", "NUL",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    output = completed.stdout + "\n" + completed.stderr
    current_time: float | None = None
    result: list[tuple[float, float]] = []
    for line in output.splitlines():
        time_match = re.search(r"pts_time:([0-9.]+)", line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        score_match = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if score_match and current_time is not None:
            result.append((current_time, float(score_match.group(1))))
            current_time = None
    if not result:
        raise RuntimeError("ffmpeg returned no scene scores")
    return result


def clustered_peaks(samples: list[tuple[float, float]], threshold: float, cluster_gap: float, min_gap: float) -> list[dict]:
    above = [(time, score) for time, score in samples if score >= threshold]
    clusters: list[list[tuple[float, float]]] = []
    for item in above:
        if not clusters or item[0] - clusters[-1][-1][0] > cluster_gap:
            clusters.append([item])
        else:
            clusters[-1].append(item)
    peaks = [max(cluster, key=lambda item: item[1]) for cluster in clusters]
    selected: list[tuple[float, float]] = []
    for peak in peaks:
        if not selected or peak[0] - selected[-1][0] >= min_gap:
            selected.append(peak)
        elif peak[1] > selected[-1][1]:
            selected[-1] = peak
    return [{"seconds": round(time, 3), "score": round(score, 6)} for time, score in selected if time > 0.05]


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect candidate visual boundaries without slicing or exporting frames.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--cluster-gap", type=float, default=0.18)
    parser.add_argument("--min-gap", type=float, default=0.35)
    args = parser.parse_args()
    peaks = clustered_peaks(scene_scores(args.input), args.threshold, args.cluster_gap, args.min_gap)
    result = {
        "schema_version": "1.0",
        "method": "scene-score peak clustering; no video slicing or frame export",
        "video": str(args.input),
        "duration_seconds": args.duration,
        "boundaries": [0.0, *[item["seconds"] for item in peaks], args.duration],
        "peaks": peaks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(peaks) + 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

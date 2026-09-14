#!/usr/bin/env python3
"""Export the representative frames already selected by build_pose_evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    manifest = read_json(args.manifest.resolve())
    candidates = manifest.get("orientation_candidate_frames") or manifest.get("pose_frames") or []
    selected = []
    seen = set()
    for item in candidates:
        value = round(float(item["timestamp"]), 3)
        key = (str(item.get("shot_id") or ""), value)
        if key not in seen:
            selected.append({
                "shot_id": key[0],
                "timestamp_seconds": value,
                "candidate_role": str(item.get("candidate_role") or "legacy_pose_rep"),
                "motion_score": float(item.get("motion_score") or 0.0),
            })
            seen.add(key)
    if not selected:
        raise RuntimeError("manifest has no orientation candidate frames")

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(args.input.resolve()))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {args.input}")
    files = []
    try:
        for index, item in enumerate(selected, start=1):
            timestamp = item["timestamp_seconds"]
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError(f"cannot decode frame at {timestamp:.3f}s")
            path = output / f"frame_{index:02d}_{int(round(timestamp * 1000)):06d}ms.jpg"
            encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
            if not encoded_ok:
                raise RuntimeError(f"cannot encode frame at {timestamp:.3f}s")
            encoded.tofile(str(path))
            files.append({**item, "file": path.name})
    finally:
        capture.release()

    with (output / "representative_frames.json").open("w", encoding="utf-8") as stream:
        json.dump({"schema_version": "0.2-multiperson-candidates", "frames": files}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"frames": len(files), "output_dir": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

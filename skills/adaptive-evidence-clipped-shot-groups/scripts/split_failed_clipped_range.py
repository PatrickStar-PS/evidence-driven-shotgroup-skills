#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def clipped_range(range_id: str, start: float, end: float, duration: float, context: float) -> dict:
    clip_start = round(max(0.0, start - context), 3)
    clip_end = round(min(duration, end + context), 3)
    return {
        "id": range_id,
        "start_seconds": round(start, 3),
        "end_seconds": round(end, 3),
        "logical_start_seconds": round(start, 3),
        "logical_end_seconds": round(end, 3),
        "clip_start_seconds": clip_start,
        "clip_end_seconds": clip_end,
        "clip_duration_seconds": round(clip_end - clip_start, 3),
        "absolute_offset_seconds": clip_start,
        "core_start_clip_seconds": round(start - clip_start, 3),
        "core_end_clip_seconds": round(end - clip_start, 3),
        "context_before_seconds": round(start - clip_start, 3),
        "context_after_seconds": round(clip_end - end, 3),
        "seam_owner": "start" if start > 0 else "none",
        "recovery_range": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Split one failed logical range without touching completed ranges.")
    parser.add_argument("--ranges-file", type=Path, required=True)
    parser.add_argument("--range-id", required=True)
    parser.add_argument("--split-at", type=float, required=True)
    parser.add_argument("--context-seconds", type=float, default=1.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.ranges_file.read_text(encoding="utf-8-sig"))
    matches = [item for item in plan.get("ranges") or [] if str(item.get("id")) == args.range_id]
    if len(matches) != 1:
        raise RuntimeError(f"expected one failed range named {args.range_id!r}")
    failed = matches[0]
    start = float(failed["logical_start_seconds"])
    end = float(failed["logical_end_seconds"])
    if not start + 3.0 < args.split_at < end - 3.0:
        raise RuntimeError("recovery split must leave at least 3 seconds on each side")
    duration = float(plan["duration_seconds"])
    ranges = [
        clipped_range(f"{args.range_id}a", start, args.split_at, duration, args.context_seconds),
        clipped_range(f"{args.range_id}b", args.split_at, end, duration, args.context_seconds),
    ]
    result = {
        "schema_version": "1.0",
        "duration_seconds": duration,
        "mode": "recovery_segmented",
        "transport_mode": "overlap_clipped_video",
        "context_seconds": args.context_seconds,
        "replaces_range_id": args.range_id,
        "ranges": ranges,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

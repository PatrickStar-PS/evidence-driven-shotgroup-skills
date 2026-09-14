#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def overlaps(item: dict, start: float, end: float) -> bool:
    return float(item.get("start", 0.0)) < end and float(item.get("end", 0.0)) > start


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice an expansion config for an isolated absolute-time canary.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be greater than --start")
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    sliced = dict(data)
    sliced["groups"] = [
        {
            **item,
            "start": round(max(args.start, float(item["start"])), 3),
            "end": round(min(args.end, float(item["end"])), 3),
        }
        for item in data.get("groups") or []
        if overlaps(item, args.start, args.end)
    ]
    for field in ("people_rules", "scene_rules", "prop_rules"):
        sliced[field] = [item for item in data.get(field) or [] if overlaps(item, args.start, args.end)]
    sliced["canary_range"] = {"start_seconds": args.start, "end_seconds": args.end}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sliced, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"groups": len(sliced["groups"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

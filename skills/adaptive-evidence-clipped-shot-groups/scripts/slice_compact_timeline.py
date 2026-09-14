#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep an exact absolute-time slice from a compact timeline without changing semantic records.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.end <= args.start:
        raise RuntimeError("Slice end must be greater than slice start")
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    records = data.get("records") or []
    selected = [record for record in records if float(record["start_seconds"]) >= args.start - 0.001 and float(record["end_seconds"]) <= args.end + 0.001]
    if not selected:
        raise RuntimeError("No compact records fall inside the requested slice")
    if abs(float(selected[0]["start_seconds"]) - args.start) > 0.01 or abs(float(selected[-1]["end_seconds"]) - args.end) > 0.01:
        raise RuntimeError("Requested slice must align to existing compact record boundaries")
    data["records"] = selected
    data["analysis_start_seconds"] = args.start
    data["analysis_end_seconds"] = args.end
    data["boundary_audit"] = [
        item for item in (data.get("boundary_audit") or [])
        if args.start + 0.001 < float(item.get("candidate_seconds", -1)) < args.end - 0.001
    ]
    data.setdefault("warnings", []).append(f"Deterministic absolute-time slice retained {args.start:.3f}-{args.end:.3f}s without semantic rewriting.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(selected), "start": args.start, "end": args.end}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

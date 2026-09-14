#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Reuse a prior semantic seam decision for the same source and seam time.")
    parser.add_argument("--prior-audited", type=Path, required=True)
    parser.add_argument("--previous-timeline", type=Path, required=True)
    parser.add_argument("--current-timeline", type=Path, required=True)
    parser.add_argument("--seam-seconds", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    prior = json.loads(args.prior_audited.read_text(encoding="utf-8-sig"))
    previous = json.loads(args.previous_timeline.read_text(encoding="utf-8-sig"))
    current = json.loads(args.current_timeline.read_text(encoding="utf-8-sig"))
    seam = round(args.seam_seconds, 3)
    matches = [
        item for item in prior.get("boundary_audit") or []
        if abs(float(item.get("candidate_seconds", -999.0)) - seam) <= 0.02
    ]
    if len(matches) != 1:
        raise RuntimeError(f"prior seam audit missing or duplicated at {seam:.3f}s")
    previous_records = sorted(previous.get("records") or [], key=lambda item: float(item["end_seconds"]))
    current_records = sorted(current.get("records") or [], key=lambda item: float(item["start_seconds"]))
    if not previous_records or not current_records:
        raise RuntimeError("seam reuse requires records on both sides")
    audit = dict(matches[0])
    audit["candidate_seconds"] = seam
    audit["observed_seconds"] = seam
    audit["before_visible_subject"] = str(previous_records[-1].get("primary_visible_subject") or "").strip()
    audit["after_visible_subject"] = str(current_records[0].get("primary_visible_subject") or "").strip()
    if audit.get("decision") == "merge_false":
        if not audit.get("same_shot_evidence"):
            raise RuntimeError("prior merge_false lacks same-shot evidence")
        if audit["before_visible_subject"] != audit["after_visible_subject"]:
            raise RuntimeError("current adjacent subjects conflict with the reused merge_false decision")
    current["boundary_audit"] = [
        item for item in current.get("boundary_audit") or []
        if abs(float(item.get("candidate_seconds", -999.0)) - seam) > 0.02
    ] + [audit]
    current.setdefault("transport", {})["start_seam_audit"] = audit
    current["transport"]["start_seam_audit_source"] = str(args.prior_audited)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"seam_seconds": seam, "decision": audit.get("decision"), "reused": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

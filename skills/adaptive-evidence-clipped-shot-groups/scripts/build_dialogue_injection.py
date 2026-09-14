#!/usr/bin/env python3
"""Create a bounded, immutable dialogue injection for downstream shot parsing."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-events", type=int, default=1)
    args = parser.parse_args()
    if args.start < 0 or args.end <= args.start or args.context_events < 0:
        raise RuntimeError("Invalid injection range or context count")

    ledger_path = args.ledger.resolve()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8-sig"))
    events = sorted(
        ledger.get("events") or [],
        key=lambda item: (
            float(item["start_seconds"]),
            float(item["end_seconds"]),
            item["dialogue_id"],
        ),
    )
    hit_indexes = [
        index
        for index, event in enumerate(events)
        if float(event["start_seconds"]) < args.end
        and float(event["end_seconds"]) > args.start
    ]
    if hit_indexes:
        first = max(0, min(hit_indexes) - args.context_events)
        last = min(len(events), max(hit_indexes) + args.context_events + 1)
        selected = events[first:last]
    else:
        selected = []
    has_delivery_contract = ledger.get("schema_version") in {
        "2.1-video-dialogue-ledger-delivery",
        "2.2-video-dialogue-ledger-dual-track",
    }
    has_dual_track = ledger.get("schema_version") == "2.2-video-dialogue-ledger-dual-track"
    payload = {
        "schema_version": (
            "2.1-dialogue-injection-delivery"
            if has_delivery_contract
            else "2.0-dialogue-injection"
        ),
        "episode": ledger.get("episode"),
        "source_ledger": {
            "name": ledger_path.name,
            "sha256": file_sha256(ledger_path),
            "size_bytes": ledger_path.stat().st_size,
            "schema_version": ledger.get("schema_version"),
            "episode": ledger.get("episode"),
        },
        "range": {
            "start_seconds": args.start,
            "end_seconds": args.end,
            "interval": "half-open",
        },
        "immutability_contract": (
            "Copy dialogue_id, speaker, text, times, delivery, and audio/subtitle relation exactly; shot parsing may add only visibility or shot placement."
            if has_dual_track
            else "Copy dialogue_id, speaker, text, times, and delivery exactly; shot parsing may add only visibility or shot placement."
            if has_delivery_contract
            else "Copy dialogue_id, speaker, text, and times exactly; shot parsing may add only visibility or shot placement."
        ),
        "events": selected,
        "warnings": [] if selected else ["no_dialogue_event_overlaps_range"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"events": len(selected), "output": str(args.output.resolve())},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

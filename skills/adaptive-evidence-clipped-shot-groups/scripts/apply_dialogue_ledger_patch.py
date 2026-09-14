#!/usr/bin/env python3
"""Synchronize compact timelines to an authoritative validated dialogue ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()

    timeline = json.loads(args.input.read_text(encoding="utf-8-sig"))
    ledger = json.loads(args.ledger.read_text(encoding="utf-8-sig"))
    ledger_by_id = {str(item.get("dialogue_id")): item for item in ledger.get("events") or []}
    changes = []

    for event in timeline.get("dialogue_events") or []:
        dialogue_id = str(event.get("dialogue_id") or "")
        source = ledger_by_id.get(dialogue_id)
        if not source:
            continue
        speaker = str(source.get("speaker_chinese_name") or "unclear")
        before = str(event.get("speaker") or "")
        event["speaker"] = speaker
        event["delivery"] = json.loads(json.dumps(source.get("delivery") or {}, ensure_ascii=False))
        if before != speaker:
            changes.append({"dialogue_id": dialogue_id, "scope": "dialogue_event", "before": before, "after": speaker})

    for record in timeline.get("records") or []:
        record_speakers = []
        for utterance in record.get("dialogue_utterances") or []:
            dialogue_id = str(utterance.get("dialogue_id") or "")
            source = ledger_by_id.get(dialogue_id)
            if not source:
                continue
            speaker = str(source.get("speaker_chinese_name") or "unclear")
            before = str(utterance.get("speaker") or "")
            utterance["speaker"] = speaker
            utterance["delivery"] = json.loads(json.dumps(source.get("delivery") or {}, ensure_ascii=False))
            if speaker not in record_speakers:
                record_speakers.append(speaker)
            if before != speaker:
                changes.append({
                    "dialogue_id": dialogue_id,
                    "scope": f"record:{record.get('id')}",
                    "before": before,
                    "after": speaker,
                })
        if record_speakers:
            record["speaker"] = "、".join(record_speakers)

    timeline.setdefault("warnings", []).append(
        "Validated whole-episode dialogue ledger synchronized locally; visual semantics were not changed."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    args.audit.write_text(json.dumps({
        "schema_version": "1.0-dialogue-ledger-sync-audit",
        "input": str(args.input.resolve()),
        "ledger": str(args.ledger.resolve()),
        "changes": changes,
        "text_changes": 0,
        "time_changes": 0,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"speaker_changes": len(changes), "text_changes": 0, "time_changes": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

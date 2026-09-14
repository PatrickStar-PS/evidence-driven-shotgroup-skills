#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def normalized(text: object) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:\"“”‘’（）()]+", "", str(text or "")).lower()


def speaker(event: dict) -> str:
    return str(event.get("speaker_id") or event.get("speaker_chinese_name") or event.get("speaker_label") or "")


def overlap(a: dict, b: dict) -> float:
    return max(0.0, min(float(a["end_seconds"]), float(b["end_seconds"])) -
               max(float(a["start_seconds"]), float(b["start_seconds"])))


def merge_evidence(left: dict, right: dict) -> None:
    left["evidence"] = list(dict.fromkeys([*(left.get("evidence") or []), *(right.get("evidence") or [])]))
    left["warnings"] = list(dict.fromkeys([
        *(left.get("warnings") or []),
        *(right.get("warnings") or []),
        "derived_overlap_dedup",
    ]))


def derive(payload: dict, fuzzy_threshold: float, snap_seconds: float) -> tuple[dict, dict]:
    source_events = [copy.deepcopy(item) for item in payload.get("events") or []]
    active = [True] * len(source_events)
    decisions: list[dict] = []
    changed = True
    while changed:
        changed = False
        for i, left in enumerate(source_events):
            if not active[i]:
                continue
            for j in range(i + 1, len(source_events)):
                if not active[j]:
                    continue
                right = source_events[j]
                shared = overlap(left, right)
                if shared <= 0:
                    continue
                lt, rt = normalized(left.get("chinese_text")), normalized(right.get("chinese_text"))
                similarity = SequenceMatcher(None, lt, rt).ratio() if lt and rt else 0.0
                containment = bool(lt and rt and (lt in rt or rt in lt))
                same_speaker = speaker(left) == speaker(right)
                duplicate = containment or (same_speaker and shared >= 0.5 and similarity >= fuzzy_threshold)
                if not duplicate:
                    continue
                keep_index, drop_index = (i, j) if (len(lt), float(left["end_seconds"]) - float(left["start_seconds"])) >= (
                    len(rt), float(right["end_seconds"]) - float(right["start_seconds"])
                ) else (j, i)
                kept, dropped = source_events[keep_index], source_events[drop_index]
                kept["start_seconds"] = round(min(float(kept["start_seconds"]), float(dropped["start_seconds"])), 3)
                kept["end_seconds"] = round(max(float(kept["end_seconds"]), float(dropped["end_seconds"])), 3)
                merge_evidence(kept, dropped)
                kept.setdefault("derived_dedup", {})["absorbed_dialogue_ids"] = list(dict.fromkeys([
                    *((kept.get("derived_dedup") or {}).get("absorbed_dialogue_ids") or []),
                    str(dropped.get("dialogue_id") or ""),
                ]))
                active[drop_index] = False
                decisions.append({
                    "action": "merge_duplicate",
                    "kept_dialogue_id": kept.get("dialogue_id"),
                    "dropped_dialogue_id": dropped.get("dialogue_id"),
                    "same_speaker": same_speaker,
                    "speaker_conflict": not same_speaker,
                    "containment": containment,
                    "text_similarity": round(similarity, 4),
                    "overlap_seconds": round(shared, 3),
                    "merged_start_seconds": kept["start_seconds"],
                    "merged_end_seconds": kept["end_seconds"],
                })
                changed = True
                break
            if changed:
                break

    events = sorted((event for index, event in enumerate(source_events) if active[index]),
                    key=lambda item: (float(item["start_seconds"]), float(item["end_seconds"]), str(item.get("dialogue_id") or "")))
    unresolved = []
    for previous, current in zip(events, events[1:]):
        shared = overlap(previous, current)
        if shared <= 0:
            continue
        if shared <= snap_seconds:
            before = float(previous["end_seconds"])
            previous["end_seconds"] = round(float(current["start_seconds"]), 3)
            decisions.append({
                "action": "snap_adjacent_boundary",
                "left_dialogue_id": previous.get("dialogue_id"),
                "right_dialogue_id": current.get("dialogue_id"),
                "overlap_seconds": round(shared, 3),
                "left_end_before": before,
                "left_end_after": previous["end_seconds"],
            })
        else:
            unresolved.append({
                "left_dialogue_id": previous.get("dialogue_id"),
                "right_dialogue_id": current.get("dialogue_id"),
                "overlap_seconds": round(shared, 3),
            })
    if unresolved:
        raise RuntimeError("unresolved non-duplicate dialogue overlaps: " + json.dumps(unresolved, ensure_ascii=False))

    result = copy.deepcopy(payload)
    result["events"] = events
    result["derived_dialogue_dedup"] = {
        "schema_version": "1.0-derived-dialogue-overlap-dedup",
        "source_event_count": len(source_events),
        "output_event_count": len(events),
        "decision_count": len(decisions),
    }
    audit = {
        "schema_version": "1.0-derived-dialogue-overlap-dedup-audit",
        "source_event_count": len(source_events),
        "output_event_count": len(events),
        "removed_event_count": len(source_events) - len(events),
        "decisions": decisions,
        "unresolved_overlaps": unresolved,
        "status": "passed",
    }
    return result, audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive a non-overlapping dialogue ledger without modifying its source.")
    parser.add_argument("--input-ledger", required=True, type=Path)
    parser.add_argument("--output-ledger", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--fuzzy-threshold", type=float, default=0.52)
    parser.add_argument("--snap-seconds", type=float, default=0.25)
    args = parser.parse_args()
    payload = json.loads(args.input_ledger.read_text(encoding="utf-8-sig"))
    result, audit = derive(payload, args.fuzzy_threshold, args.snap_seconds)
    result["derived_dialogue_dedup"]["source_ledger"] = str(args.input_ledger.resolve())
    args.output_ledger.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.output_ledger.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": audit["status"],
        "source_events": audit["source_event_count"],
        "output_events": audit["output_event_count"],
        "removed": audit["removed_event_count"],
        "decisions": len(audit["decisions"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

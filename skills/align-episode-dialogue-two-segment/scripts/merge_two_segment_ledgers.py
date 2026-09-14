#!/usr/bin/env python3
"""Merge two clip-local dialogue ledgers without dropping seam utterances."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any


CONFIDENCE = {"low": 0, "medium": 1, "high": 2}


def normalize_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def normalize_confidence(event: dict[str, Any]) -> None:
    """Keep the canonical event and delivery confidence fields in sync."""
    delivery = event.get("delivery")
    if not isinstance(delivery, dict):
        return
    event_confidence = str(event.get("confidence") or "")
    delivery_confidence = str(delivery.get("confidence") or "")
    if event_confidence not in CONFIDENCE and delivery_confidence in CONFIDENCE:
        event["confidence"] = delivery_confidence
    elif delivery_confidence not in CONFIDENCE and event_confidence in CONFIDENCE:
        delivery["confidence"] = event_confidence


def interval_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    start = max(float(a["start_seconds"]), float(b["start_seconds"]))
    end = min(float(a["end_seconds"]), float(b["end_seconds"]))
    return max(0.0, end - start)


def is_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ta, tb = normalize_text(a.get("chinese_text")), normalize_text(b.get("chinese_text"))
    if not ta or not tb or difflib.SequenceMatcher(None, ta, tb).ratio() < 0.82:
        return False
    duration_min = max(0.05, min(float(a["end_seconds"]) - float(a["start_seconds"]), float(b["end_seconds"]) - float(b["start_seconds"])))
    timing_matches = interval_overlap(a, b) / duration_min >= 0.20 or abs(float(a["start_seconds"]) - float(b["start_seconds"])) <= 1.20
    speakers_match = a.get("speaker_id") == b.get("speaker_id") or "unclear" in {a.get("speaker_id"), b.get("speaker_id")}
    return timing_matches and speakers_match


def edge_distance(event: dict[str, Any]) -> float:
    center = (float(event["start_seconds"]) + float(event["end_seconds"])) / 2.0
    return min(center - float(event["_clip_abs_start"]), float(event["_clip_abs_end"]) - center)


def quality(event: dict[str, Any]) -> tuple[float, int, int]:
    return edge_distance(event), CONFIDENCE.get(str(event.get("confidence")), -1), len(normalize_text(event.get("chinese_text")))


def load_candidates(manifest: dict[str, Any], ledger_paths: dict[str, Path], tolerance: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    duration = float(manifest["source"]["duration_seconds"])
    for part in manifest["ranges"]:
        part_id = str(part["id"])
        ledger = json.loads(ledger_paths[part_id].read_text(encoding="utf-8-sig"))
        clip_duration = float(part["actual_clip_duration_seconds"])
        offset = float(part["absolute_offset_seconds"])
        raw_events = [item for item in (ledger.get("events") or []) if isinstance(item, dict)]
        parsed_ranges: list[tuple[float, float]] = []
        for item in raw_events:
            try:
                parsed_ranges.append((float(item["start_seconds"]), float(item["end_seconds"])))
            except (KeyError, TypeError, ValueError):
                continue
        absolute_ceiling = min(duration, offset + clip_duration)
        absolute_basis = bool(
            offset > 0
            and parsed_ranges
            and all(start >= offset - tolerance and end <= absolute_ceiling + tolerance and end > start for start, end in parsed_ranges)
            and any(end > clip_duration + tolerance for _, end in parsed_ranges)
        )
        for raw_event in raw_events:
            event = dict(raw_event)
            normalize_confidence(event)
            try:
                local_start, local_end = float(event["start_seconds"]), float(event["end_seconds"])
            except (KeyError, TypeError, ValueError):
                quarantined.append({"source_part": part_id, "reason": "invalid_local_time", "event": event})
                continue
            if absolute_basis:
                absolute_start = max(offset, local_start)
                absolute_end = min(absolute_ceiling, local_end)
                if absolute_end <= absolute_start:
                    quarantined.append({"source_part": part_id, "reason": "absolute_time_invalid", "event": event})
                    continue
                event.setdefault("warnings", []).append("normalized_absolute_timestamp_basis")
                event["start_seconds"], event["end_seconds"] = round(absolute_start, 3), round(absolute_end, 3)
                event["_source_part"] = part_id
                event["_clip_abs_start"] = offset
                event["_clip_abs_end"] = offset + clip_duration
                event["_logical_core"] = [float(part["logical_start_seconds"]), float(part["logical_end_seconds"])]
                candidates.append(event)
                continue
            if local_start < -tolerance or local_end > clip_duration + tolerance or local_end <= local_start:
                if offset > 0 and local_start >= offset - tolerance and local_end <= absolute_ceiling + tolerance and local_end > local_start:
                    event.setdefault("warnings", []).append("normalized_mixed_absolute_timestamp_basis")
                    event["start_seconds"], event["end_seconds"] = round(max(offset, local_start), 3), round(min(absolute_ceiling, local_end), 3)
                    event["_source_part"] = part_id
                    event["_clip_abs_start"] = offset
                    event["_clip_abs_end"] = offset + clip_duration
                    event["_logical_core"] = [float(part["logical_start_seconds"]), float(part["logical_end_seconds"])]
                    candidates.append(event)
                    continue
                quarantined.append({"source_part": part_id, "reason": "local_time_out_of_range", "event": event})
                continue
            local_start, local_end = max(0.0, local_start), min(clip_duration, local_end)
            absolute_start, absolute_end = offset + local_start, min(duration, offset + local_end)
            if absolute_end <= absolute_start:
                quarantined.append({"source_part": part_id, "reason": "absolute_time_invalid", "event": event})
                continue
            event["start_seconds"], event["end_seconds"] = round(absolute_start, 3), round(absolute_end, 3)
            event["_source_part"] = part_id
            event["_clip_abs_start"] = offset
            event["_clip_abs_end"] = offset + clip_duration
            event["_logical_core"] = [float(part["logical_start_seconds"]), float(part["logical_end_seconds"])]
            candidates.append(event)
    return candidates, quarantined


def merge_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    merged: list[dict[str, Any]] = []
    duplicate_count = 0
    for candidate in sorted(candidates, key=lambda event: (float(event["start_seconds"]), float(event["end_seconds"]))):
        match_index = next((index for index, existing in enumerate(merged) if existing.get("_source_part") != candidate.get("_source_part") and is_duplicate(existing, candidate)), None)
        if match_index is None:
            merged.append(candidate)
            continue
        duplicate_count += 1
        existing = merged[match_index]
        winner, loser = (candidate, existing) if quality(candidate) > quality(existing) else (existing, candidate)
        winner.setdefault("warnings", [])
        if "deduplicated_overlap_copy" not in winner["warnings"]:
            winner["warnings"].append("deduplicated_overlap_copy")
        winner["_duplicate_sources"] = sorted({existing["_source_part"], candidate["_source_part"]})
        merged[match_index] = winner
    return merged, duplicate_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--part01", type=Path, required=True)
    parser.add_argument("--part02", type=Path, required=True)
    parser.add_argument("--character-input", type=Path, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quarantine-output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.30)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    character_input = json.loads(args.character_input.read_text(encoding="utf-8-sig"))
    candidates, quarantined = load_candidates(manifest, {"part01": args.part01, "part02": args.part02}, args.tolerance)
    events, duplicate_count = merge_candidates(candidates)
    events.sort(key=lambda event: (float(event["start_seconds"]), float(event["end_seconds"]), normalize_text(event.get("chinese_text"))))
    episode = str(args.episode).zfill(2)
    seam_unique = 0
    split = float(manifest["split"]["seconds"])
    for index, event in enumerate(events, 1):
        core_start, core_end = event.pop("_logical_core")
        if not (core_start <= float(event["start_seconds"]) < core_end) and abs(float(event["start_seconds"]) - split) <= float(manifest["split"]["shared_overlap_seconds"]):
            seam_unique += 1
            event.setdefault("warnings", []).append("kept_unique_seam_event")
        event["dialogue_id"] = f"EP{episode}-D{index:04d}"
        event.pop("_source_part", None)
        event.pop("_clip_abs_start", None)
        event.pop("_clip_abs_end", None)
        event.pop("_duplicate_sources", None)
    source = manifest["source"]
    result = {"schema_version": "2.1-video-dialogue-ledger-delivery", "episode": episode,
              "source": {"name": source["name"], "fingerprint": "sha256:" + source["sha256"], "duration_seconds": float(source["duration_seconds"])},
              "analysis": {"backend": "bai-tos-url-two-segment", "model": args.model, "input_contract": "video+character-assets",
              "interval_type": "utterance", "gaps_allowed": True, "overlaps_allowed": True,
              "delivery_contract": "speech-rate+intonation+timbre+emotion+rhythm-pause", "segment_count": 2,
              "overlap_duplicates_removed": duplicate_count, "unique_seam_events_kept": seam_unique,
              "quarantined_events": len(quarantined), "total_dialogue_events": len(events),
              "unclear_speaker_events": sum(1 for event in events if event.get("speaker_id") == "unclear")},
              "characters": character_input.get("characters") or [], "events": events,
              "warnings": (["Timestamp quarantine is non-empty; resolve before accepting this ledger."] if quarantined else []), "errors": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.quarantine_output.parent.mkdir(parents=True, exist_ok=True)
    args.quarantine_output.write_text(json.dumps({"quarantined_events": quarantined}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "review_required" if quarantined else "complete", "events": len(events), "duplicates_removed": duplicate_count, "quarantined": len(quarantined)}, ensure_ascii=False))
    return 2 if quarantined else 0


if __name__ == "__main__":
    raise SystemExit(main())

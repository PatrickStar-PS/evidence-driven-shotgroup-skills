from __future__ import annotations

import hashlib
import json
import re
from typing import Any


LOCK_SCORE_THRESHOLD = 0.50


def _round_time(value: object) -> float:
    return round(float(value), 3)


def build_boundary_contract(
    boundary_data: dict[str, Any] | None,
    range_start: float,
    range_end: float,
    lock_score_threshold: float = LOCK_SCORE_THRESHOLD,
) -> dict[str, Any]:
    boundary_data = boundary_data or {}
    score_by_time = {
        _round_time(item.get("seconds")): float(item.get("score", 0.0))
        for item in boundary_data.get("peaks") or []
        if isinstance(item, dict) and item.get("seconds") is not None
    }
    candidates: list[dict[str, Any]] = []
    for raw in boundary_data.get("boundaries") or []:
        seconds = _round_time(raw)
        if not range_start + 0.05 < seconds < range_end - 0.05:
            continue
        score = score_by_time.get(seconds)
        candidates.append(
            {
                "seconds": seconds,
                "score": None if score is None else round(score, 6),
                "tier": "locked" if score is not None and score >= lock_score_threshold else "advisory",
            }
        )
    range_edge_candidates = [
        {
            "seconds": _round_time(value),
            "score": round(score_by_time[_round_time(value)], 6),
            "tier": "locked" if score_by_time[_round_time(value)] >= lock_score_threshold else "advisory",
        }
        for value in (range_start, range_end)
        if _round_time(value) in score_by_time
    ]

    locked_edges = [
        _round_time(range_start),
        *[item["seconds"] for item in candidates if item["tier"] == "locked"],
        _round_time(range_end),
    ]
    locked_edges = sorted(set(locked_edges))
    evidence_edges = sorted(set([_round_time(range_start), *[item["seconds"] for item in candidates], _round_time(range_end)]))
    evidence_intervals = [
        {
            "evidence_interval_id": f"C{index:03d}",
            "start_seconds": left,
            "end_seconds": right,
            "start_anchor_seconds": round(min(right - 0.001, left + min(0.12, max(0.03, (right - left) * 0.2))), 3),
            "middle_anchor_seconds": round((left + right) / 2.0, 3),
            "end_anchor_seconds": round(max(left, right - min(0.12, max(0.03, (right - left) * 0.2))), 3),
        }
        for index, (left, right) in enumerate(zip(evidence_edges, evidence_edges[1:]), 1)
        if right > left
    ]
    intervals = [
        {
            "interval_id": f"I{index:03d}",
            "start_seconds": left,
            "end_seconds": right,
            "start_anchor_seconds": round(min(right - 0.001, left + min(0.12, max(0.03, (right - left) * 0.2))), 3),
            "middle_anchor_seconds": round((left + right) / 2.0, 3),
            "end_anchor_seconds": round(max(left, right - min(0.12, max(0.03, (right - left) * 0.2))), 3),
        }
        for index, (left, right) in enumerate(zip(locked_edges, locked_edges[1:]), 1)
        if right > left
    ]
    return {
        "schema_version": "1.0",
        "lock_score_threshold": lock_score_threshold,
        "range_start_seconds": _round_time(range_start),
        "range_end_seconds": _round_time(range_end),
        "candidates": candidates,
        "range_edge_candidates": range_edge_candidates,
        "evidence_intervals": evidence_intervals,
        "locked_intervals": intervals,
    }


def interval_for_time(contract: dict[str, Any], seconds: float) -> dict[str, Any] | None:
    intervals = contract.get("locked_intervals") or []
    for index, interval in enumerate(intervals):
        start = float(interval["start_seconds"])
        end = float(interval["end_seconds"])
        if start - 0.001 <= seconds < end - 0.001 or (index == len(intervals) - 1 and seconds <= end + 0.001):
            return interval
    return None


def interval_label(contract: dict[str, Any], seconds: float) -> str:
    interval = None
    for index, candidate in enumerate(contract.get("evidence_intervals") or []):
        start = float(candidate["start_seconds"])
        end = float(candidate["end_seconds"])
        if start - 0.001 <= seconds < end - 0.001 or (
            index == len(contract.get("evidence_intervals") or []) - 1 and seconds <= end + 0.001
        ):
            interval = candidate
            break
    if not interval:
        return ""
    return (
        f"{interval.get('evidence_interval_id', interval.get('interval_id'))} "
        f"{float(interval['start_seconds']):.3f}-{float(interval['end_seconds']):.3f}"
    )


def normalized_dialogue_text(value: object) -> str:
    return re.sub(r"[\s，。！？、；…,.!?：:‘’“”\"']", "", str(value or ""))


def normalized_identity(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value or "")).lower()


def ensure_dialogue_contract(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    events_by_id: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    next_number = 1

    for record in sorted(data.get("records") or [], key=lambda item: float(item.get("start_seconds", 0.0))):
        event_ids: list[str] = []
        utterances = record.get("dialogue_utterances") or []
        for utterance in utterances:
            if not isinstance(utterance, dict):
                continue
            text = str(utterance.get("text") or "").strip()
            speaker = str(utterance.get("speaker") or "").strip()
            if not text or not speaker:
                continue
            start = float(utterance.get("start_seconds", record.get("start_seconds", 0.0)))
            end = float(utterance.get("end_seconds", record.get("end_seconds", start)))
            requested_id = str(utterance.get("dialogue_id") or "").strip()
            same_continuation = bool(
                previous
                and normalized_dialogue_text(previous["text"]) == normalized_dialogue_text(text)
                and normalized_identity(previous["speaker"]) == normalized_identity(speaker)
                and start <= float(previous["end_seconds"]) + 0.15
            )
            requested_event = events_by_id.get(requested_id) if requested_id else None
            requested_matches = bool(
                requested_event
                and normalized_dialogue_text(requested_event.get("text")) == normalized_dialogue_text(text)
                and normalized_identity(requested_event.get("speaker")) == normalized_identity(speaker)
            )
            if same_continuation:
                event = previous
            elif requested_matches:
                event = requested_event
            else:
                if requested_event:
                    warnings.append(f"dialogue_id {requested_id} is reused with different text or speaker; assigned a new event id")
                event_id = requested_id if requested_id and not requested_event else f"D{next_number:03d}"
                while event_id in events_by_id:
                    next_number += 1
                    event_id = f"D{next_number:03d}"
                event = {
                    "dialogue_id": event_id,
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                    "speaker": speaker,
                    "text": text,
                    "basis": utterance.get("basis") or "both",
                }
                events.append(event)
                events_by_id[event_id] = event
                next_number += 1
            if event is previous and normalized_identity(event["speaker"]) != normalized_identity(speaker):
                warnings.append(f"dialogue_id {event['dialogue_id']} changes speaker across adjacent records")
            if (
                previous
                and normalized_dialogue_text(previous["text"]) == normalized_dialogue_text(text)
                and normalized_identity(previous["speaker"]) != normalized_identity(speaker)
                and start <= float(previous["end_seconds"]) + 0.15
                and not str(utterance.get("speaker_change_evidence") or "").strip()
            ):
                warnings.append(
                    f"dialogue speaker conflict near {start:.3f}s for repeated text: {text}"
                )
            event["start_seconds"] = round(min(float(event["start_seconds"]), start), 3)
            event["end_seconds"] = round(max(float(event["end_seconds"]), end), 3)
            utterance["dialogue_id"] = event["dialogue_id"]
            if event["dialogue_id"] not in event_ids:
                event_ids.append(event["dialogue_id"])
            previous = event
        record["dialogue_event_ids"] = event_ids

    data["dialogue_events"] = events
    for warning in warnings:
        if warning not in data.setdefault("warnings", []):
            data["warnings"].append(warning)
    return warnings


def dialogue_fingerprint(data: dict[str, Any]) -> str:
    projection = {
        "dialogue_events": data.get("dialogue_events") or [],
        "records": [
            {
                "id": record.get("id"),
                "speaker": record.get("speaker"),
                "dialogue_event_ids": record.get("dialogue_event_ids") or [],
                "dialogue_utterances": record.get("dialogue_utterances") or [],
                "chinese_dialogue": record.get("chinese_dialogue"),
                "on_screen_text": record.get("on_screen_text"),
                "sound": record.get("sound"),
                "mouth_dynamics": record.get("mouth_dynamics"),
            }
            for record in data.get("records") or []
        ],
    }
    payload = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

#!/usr/bin/env python3
"""Validate a video-derived dialogue ledger without semantic rewriting."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_EVIDENCE = {"audible_speech", "burned_subtitle", "lip_sync", "turn_taking", "character_context", "narrative_context"}
ALLOWED_SPEECH_RATE = {"very_slow", "slow", "medium", "fast", "very_fast", "unclear"}
ALLOWED_PAUSE_DURATION = {"micro", "short", "medium", "long"}
ALLOWED_PAUSE_FUNCTION = {"breath", "hesitation", "emphasis", "turn", "reveal", "unclear"}
ALLOWED_TEXT_SOURCE = {"audio", "partial_audio", "subtitle_fallback"}
ALLOWED_AUDIO_SUBTITLE_RELATION = {"match", "punctuation_only", "paraphrase", "review_substitution", "subtitle_omitted", "audio_unclear", "unclear"}
ALLOWED_SUBTITLE_CLASSIFICATION = {"spoken_dialogue", "non_dialogue_screen_text", "unclear"}
ALLOWED_CANDIDATE_DECISION = {"spoken_dialogue", "non_dialogue_screen_text", "ocr_error", "duplicate"}
DELIVERY_FIELDS = ("speech_rate", "intonation", "timbre", "emotion", "rhythm_pause", "pause_profile", "confidence")


def issue(code: str, detail: str, event_id: str | None = None) -> dict[str, str]:
    result = {"code": code, "detail": detail}
    if event_id:
        result["dialogue_id"] = event_id
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--character-input", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--subtitle-candidates", type=Path)
    parser.add_argument("--tolerance", type=float, default=0.15)
    args = parser.parse_args()
    ledger: dict[str, Any] = json.loads(args.input.read_text(encoding="utf-8-sig"))
    inputs = json.loads(args.character_input.read_text(encoding="utf-8-sig"))
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    schema_version = ledger.get("schema_version")
    if schema_version not in {"2.0-video-dialogue-ledger", "2.1-video-dialogue-ledger-delivery", "2.2-video-dialogue-ledger-dual-track"}:
        errors.append(issue("invalid_schema_version", str(ledger.get("schema_version"))))
    require_delivery = schema_version in {"2.1-video-dialogue-ledger-delivery", "2.2-video-dialogue-ledger-dual-track"}
    require_dual_track = schema_version == "2.2-video-dialogue-ledger-dual-track"
    if schema_version == "2.0-video-dialogue-ledger":
        warnings.append(issue("legacy_schema_without_delivery", "Legacy ledger is accepted, but it has no locked voice-delivery contract"))
    source = ledger.get("source") or {}
    if not source.get("fingerprint") or not source.get("name"):
        errors.append(issue("missing_source_identity", "source.name and source.fingerprint are required"))
    analysis = ledger.get("analysis") or {}
    if analysis.get("input_contract") not in {"video+character-assets", "video+character-assets+anonymous-voice-clusters"}:
        errors.append(issue("invalid_input_contract", str(analysis.get("input_contract"))))
    events = ledger.get("events")
    if not isinstance(events, list):
        errors.append(issue("events_not_list", "events must be a JSON list"))
        events = []
    characters = {item.get("character_id"): item for item in inputs.get("characters") or []}
    seen_ids: set[str] = set()
    previous_key: tuple[float, float, str] | None = None
    unclear_count = 0
    for event in events:
        event_id = str(event.get("dialogue_id") or "")
        if not re.fullmatch(r"EP\d+-D\d{4}", event_id):
            errors.append(issue("invalid_dialogue_id", "Expected EPxx-D0001 format", event_id or None))
        if event_id in seen_ids:
            errors.append(issue("duplicate_dialogue_id", "dialogue_id must be unique", event_id))
        seen_ids.add(event_id)
        try:
            start = float(event["start_seconds"])
            end = float(event["end_seconds"])
        except (KeyError, TypeError, ValueError):
            errors.append(issue("invalid_time", "start_seconds and end_seconds must be numeric", event_id))
            continue
        if start < 0 or end <= start or end > args.duration + args.tolerance:
            errors.append(issue("time_out_of_range", f"range {start}-{end} is outside 0-{args.duration}", event_id))
        order_key = (start, end, event_id)
        if previous_key and order_key < previous_key:
            errors.append(issue("events_not_ordered", "events must be ordered by start, end, id", event_id))
        previous_key = order_key
        speaker = event.get("speaker_id")
        if speaker == "unclear":
            unclear_count += 1
            if not event.get("warnings"):
                errors.append(issue("unclear_without_warning", "unclear speaker requires a warning", event_id))
            if event.get("speaker_chinese_name") != "unclear" or event.get("speaker_english_name") != "unclear":
                errors.append(issue("unclear_name_mismatch", "unclear speaker requires unclear names", event_id))
            if not str(event.get("speaker_label") or "").strip():
                errors.append(issue("missing_speaker_label", "unclear speaker requires a visible or audible speaker_label", event_id))
        elif speaker not in characters:
            errors.append(issue("unknown_speaker", f"speaker_id {speaker!r} is not in character assets", event_id))
        else:
            card = characters[speaker]
            if event.get("speaker_chinese_name") != card.get("chinese_name") or event.get("speaker_english_name") != card.get("english_name"):
                errors.append(issue("speaker_name_mismatch", "speaker names must exactly match the asset card", event_id))
        if not str(event.get("chinese_text") or "").strip():
            errors.append(issue("empty_dialogue_text", "chinese_text is required", event_id))
        if require_dual_track:
            audible_text = str(event.get("audible_text") or "").strip()
            chinese_text = str(event.get("chinese_text") or "").strip()
            if not audible_text:
                errors.append(issue("empty_audible_text", "audible_text is required", event_id))
            if chinese_text != audible_text:
                errors.append(issue("canonical_text_mismatch", "chinese_text must exactly equal audible_text", event_id))
            if "subtitle_text" not in event or not isinstance(event.get("subtitle_text"), str):
                errors.append(issue("invalid_subtitle_text", "subtitle_text must be a string, using an empty string when absent", event_id))
            if event.get("text_source") not in ALLOWED_TEXT_SOURCE:
                errors.append(issue("invalid_text_source", str(event.get("text_source")), event_id))
            relation = event.get("audio_subtitle_relation")
            if relation not in ALLOWED_AUDIO_SUBTITLE_RELATION:
                errors.append(issue("invalid_audio_subtitle_relation", str(relation), event_id))
            subtitle_text = str(event.get("subtitle_text") or "").strip()
            if relation == "subtitle_omitted" and subtitle_text:
                errors.append(issue("subtitle_omitted_with_text", "subtitle_omitted requires an empty subtitle_text", event_id))
            if relation in {"match", "punctuation_only", "paraphrase", "review_substitution"} and not subtitle_text:
                errors.append(issue("relation_requires_subtitle", f"{relation} requires subtitle_text", event_id))
            if event.get("text_source") == "subtitle_fallback" and not event.get("warnings"):
                errors.append(issue("subtitle_fallback_without_warning", "subtitle_fallback requires a warning", event_id))
        if event.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append(issue("invalid_confidence", str(event.get("confidence")), event_id))
        delivery = event.get("delivery")
        if require_delivery and not isinstance(delivery, dict):
            errors.append(issue("missing_delivery", "delivery object is required", event_id))
        if isinstance(delivery, dict):
            missing_delivery_fields = [field for field in DELIVERY_FIELDS if field not in delivery]
            if missing_delivery_fields:
                errors.append(issue("missing_delivery_fields", ",".join(missing_delivery_fields), event_id))
            if delivery.get("speech_rate") not in ALLOWED_SPEECH_RATE:
                errors.append(issue("invalid_speech_rate", str(delivery.get("speech_rate")), event_id))
            for field in ("intonation", "timbre", "emotion", "rhythm_pause"):
                if not str(delivery.get(field) or "").strip():
                    errors.append(issue(f"empty_{field}", f"delivery.{field} is required", event_id))
            if delivery.get("confidence") not in ALLOWED_CONFIDENCE:
                errors.append(issue("invalid_delivery_confidence", str(delivery.get("confidence")), event_id))
            pause_profile = delivery.get("pause_profile")
            if not isinstance(pause_profile, list):
                errors.append(issue("invalid_pause_profile", "delivery.pause_profile must be a list", event_id))
            else:
                previous_ratio = -1.0
                for pause_index, pause in enumerate(pause_profile, 1):
                    if not isinstance(pause, dict):
                        errors.append(issue("invalid_pause", f"pause {pause_index} must be an object", event_id))
                        continue
                    try:
                        ratio = float(pause.get("position_ratio"))
                    except (TypeError, ValueError):
                        errors.append(issue("invalid_pause_position", f"pause {pause_index} position_ratio must be numeric", event_id))
                        continue
                    if ratio < 0 or ratio > 1 or ratio < previous_ratio:
                        errors.append(issue("invalid_pause_position", f"pause {pause_index} position_ratio must be ordered within 0..1", event_id))
                    previous_ratio = ratio
                    if pause.get("duration") not in ALLOWED_PAUSE_DURATION:
                        errors.append(issue("invalid_pause_duration", f"pause {pause_index}: {pause.get('duration')!r}", event_id))
                    if pause.get("function") not in ALLOWED_PAUSE_FUNCTION:
                        errors.append(issue("invalid_pause_function", f"pause {pause_index}: {pause.get('function')!r}", event_id))
        evidence = event.get("evidence") or []
        if not evidence:
            errors.append(issue("missing_evidence", "at least one evidence value is required", event_id))
        unknown_evidence = set(evidence) - ALLOWED_EVIDENCE
        if unknown_evidence:
            errors.append(issue("invalid_evidence", ",".join(sorted(unknown_evidence)), event_id))
    subtitle_cards = ledger.get("subtitle_audit") if require_dual_track else []
    if require_dual_track and not isinstance(subtitle_cards, list):
        errors.append(issue("subtitle_audit_not_list", "subtitle_audit must be a JSON list"))
        subtitle_cards = []
    subtitle_ids: set[str] = set()
    linked_dialogue_ids: set[str] = set()
    unmatched_spoken_cards = 0
    for card in subtitle_cards or []:
        subtitle_id = str(card.get("subtitle_id") or "")
        if not re.fullmatch(r"EP\d+-S\d{4}", subtitle_id):
            errors.append(issue("invalid_subtitle_id", "Expected EPxx-S0001 format", subtitle_id or None))
        if subtitle_id in subtitle_ids:
            errors.append(issue("duplicate_subtitle_id", "subtitle_id must be unique", subtitle_id))
        subtitle_ids.add(subtitle_id)
        try:
            start = float(card["start_seconds"])
            end = float(card["end_seconds"])
        except (KeyError, TypeError, ValueError):
            errors.append(issue("invalid_subtitle_time", "subtitle start/end must be numeric", subtitle_id))
            continue
        if start < 0 or end <= start or end > args.duration + args.tolerance:
            errors.append(issue("subtitle_time_out_of_range", f"range {start}-{end} is outside 0-{args.duration}", subtitle_id))
        if not str(card.get("subtitle_text") or "").strip():
            errors.append(issue("empty_subtitle_audit_text", "subtitle_text is required", subtitle_id))
        classification = card.get("classification")
        if classification not in ALLOWED_SUBTITLE_CLASSIFICATION:
            errors.append(issue("invalid_subtitle_classification", str(classification), subtitle_id))
        links = card.get("linked_dialogue_ids")
        if not isinstance(links, list):
            errors.append(issue("invalid_subtitle_links", "linked_dialogue_ids must be a list", subtitle_id))
            links = []
        if classification == "spoken_dialogue" and not links:
            unmatched_spoken_cards += 1
            errors.append(issue("unmatched_spoken_subtitle", "spoken dialogue subtitle must link to at least one dialogue event", subtitle_id))
        for linked_id in links:
            if linked_id not in seen_ids:
                errors.append(issue("subtitle_link_unknown_dialogue", str(linked_id), subtitle_id))
            linked_dialogue_ids.add(str(linked_id))
        if card.get("confidence") not in ALLOWED_CONFIDENCE:
            errors.append(issue("invalid_subtitle_confidence", str(card.get("confidence")), subtitle_id))
    if require_dual_track:
        for event in events:
            if "burned_subtitle" in (event.get("evidence") or []) and event.get("dialogue_id") not in linked_dialogue_ids:
                errors.append(issue("dialogue_missing_subtitle_backlink", "burned_subtitle evidence requires a subtitle_audit backlink", event.get("dialogue_id")))
    candidate_resolutions = ledger.get("candidate_resolutions") or []
    if args.subtitle_candidates:
        candidate_payload = json.loads(args.subtitle_candidates.read_text(encoding="utf-8-sig"))
        expected_candidate_ids = {str(item.get("candidate_id") or "") for item in candidate_payload.get("candidates") or []}
        if not isinstance(candidate_resolutions, list):
            errors.append(issue("candidate_resolutions_not_list", "candidate_resolutions must be a list"))
            candidate_resolutions = []
        resolved_ids: set[str] = set()
        for resolution in candidate_resolutions:
            candidate_id = str(resolution.get("candidate_id") or "")
            if candidate_id not in expected_candidate_ids:
                errors.append(issue("unknown_candidate_resolution", candidate_id or "empty candidate_id"))
            if candidate_id in resolved_ids:
                errors.append(issue("duplicate_candidate_resolution", candidate_id))
            resolved_ids.add(candidate_id)
            decision = resolution.get("decision")
            if decision not in ALLOWED_CANDIDATE_DECISION:
                errors.append(issue("invalid_candidate_decision", f"{candidate_id}: {decision!r}"))
            if not str(resolution.get("reason") or "").strip():
                errors.append(issue("candidate_resolution_without_reason", candidate_id))
            subtitle_links = resolution.get("linked_subtitle_ids")
            dialogue_links = resolution.get("linked_dialogue_ids")
            if not isinstance(subtitle_links, list) or not isinstance(dialogue_links, list):
                errors.append(issue("invalid_candidate_links", candidate_id))
                continue
            if decision in {"spoken_dialogue", "duplicate"} and (not subtitle_links or not dialogue_links):
                errors.append(issue("unlinked_candidate_resolution", candidate_id))
            for subtitle_id in subtitle_links:
                if subtitle_id not in subtitle_ids:
                    errors.append(issue("candidate_link_unknown_subtitle", f"{candidate_id}: {subtitle_id}"))
            for dialogue_id in dialogue_links:
                if dialogue_id not in seen_ids:
                    errors.append(issue("candidate_link_unknown_dialogue", f"{candidate_id}: {dialogue_id}"))
        missing_candidates = sorted(expected_candidate_ids - resolved_ids)
        for candidate_id in missing_candidates:
            errors.append(issue("unresolved_subtitle_candidate", candidate_id))
        if analysis.get("subtitle_candidate_resolutions") != len(candidate_resolutions):
            errors.append(issue("derived_count_mismatch", f"analysis.subtitle_candidate_resolutions={analysis.get('subtitle_candidate_resolutions')!r}, expected {len(candidate_resolutions)}"))
    expected_counts = {"total_dialogue_events": len(events), "unclear_speaker_events": unclear_count}
    if require_dual_track:
        expected_counts.update({
            "subtitle_audit_cards": len(subtitle_cards or []),
            "unmatched_spoken_subtitle_cards": unmatched_spoken_cards,
            "audio_subtitle_mismatch_events": sum(
                1 for event in events
                if event.get("audio_subtitle_relation") in {"paraphrase", "review_substitution", "audio_unclear", "unclear"}
            ),
        })
    for field, expected in expected_counts.items():
        if analysis.get(field) != expected:
            errors.append(issue("derived_count_mismatch", f"analysis.{field}={analysis.get(field)!r}, expected {expected}"))
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "dialogue_id", "start_seconds", "end_seconds", "speaker_id", "speaker_chinese_name", "speaker_english_name", "speaker_label",
        "chinese_text", "speech_rate", "intonation", "timbre", "emotion", "rhythm_pause", "pause_profile", "delivery_confidence",
        "evidence", "confidence", "warnings",
    ]
    if require_dual_track:
        fields[7:7] = ["audible_raw_text", "audible_text", "subtitle_text", "text_source", "audio_subtitle_relation"]
    with args.csv_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for event in events:
            delivery = event.get("delivery") if isinstance(event.get("delivery"), dict) else {}
            row = {field: " | ".join(map(str, event.get(field) or [])) if isinstance(event.get(field), list) else event.get(field, "") for field in fields}
            for field in ("speech_rate", "intonation", "timbre", "emotion", "rhythm_pause"):
                row[field] = delivery.get(field, "")
            row["pause_profile"] = json.dumps(delivery.get("pause_profile") or [], ensure_ascii=False, separators=(",", ":"))
            row["delivery_confidence"] = delivery.get("confidence", "")
            writer.writerow(row)
    report = {"schema_version": "2.1-dialogue-ledger-validation", "status": "passed" if not errors else "failed", "event_count": len(events), "unclear_speaker_events": unclear_count, "errors": errors, "warnings": warnings}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "events": len(events), "errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

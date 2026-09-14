#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from timeline_contract import build_boundary_contract, ensure_dialogue_contract, interval_for_time


LOCKED_DIALOGUE_CONTRACT_VERSIONS = {
    "2.3-dialogue-injection-locked",
    "2.4-dialogue-injection-delivery-locked",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge validated absolute-time compact range timelines.")
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    documents = [json.loads(path.read_text(encoding="utf-8-sig")) for path in args.inputs]
    versions = {str(document.get("prompt_contract_version") or "unspecified") for document in documents}
    output_contract_version = str(documents[-1].get("prompt_contract_version") or "mixed-compatible")
    dialogue_contract_versions = [
        str((document.get("dialogue_injection_contract") or {}).get("version") or "")
        for document in documents
    ]
    locked_dialogue_documents = [
        document
        for document, version in zip(documents, dialogue_contract_versions)
        if version in LOCKED_DIALOGUE_CONTRACT_VERSIONS
    ]
    locked_dialogue_mode = bool(locked_dialogue_documents) and all(
        not version or version in LOCKED_DIALOGUE_CONTRACT_VERSIONS
        for version in dialogue_contract_versions
    )
    locked_dialogue_events: dict[str, dict] = {}
    locked_dialogue_errors: list[str] = []
    if locked_dialogue_mode:
        semantic_fields = ("start_seconds", "end_seconds", "speaker", "text", "delivery")
        for document in locked_dialogue_documents:
            for event in document.get("dialogue_events") or []:
                if not isinstance(event, dict):
                    continue
                dialogue_id = str(event.get("dialogue_id") or "").strip()
                if not dialogue_id:
                    locked_dialogue_errors.append("locked dialogue event is missing dialogue_id")
                    continue
                previous = locked_dialogue_events.get(dialogue_id)
                if previous is not None and any(previous.get(field) != event.get(field) for field in semantic_fields):
                    locked_dialogue_errors.append(f"conflicting locked dialogue event: {dialogue_id}")
                    continue
                locked_dialogue_events.setdefault(dialogue_id, dict(event))

    records = []
    previous_max_group = 0
    previous_document = None
    combined_intervals: list[dict] = []
    combined_candidates: list[dict] = []
    lock_thresholds: list[float] = []
    for document_index, document in enumerate(documents, 1):
        document_records = document.get("records", [])
        contract = document.get("boundary_contract") if isinstance(document.get("boundary_contract"), dict) else {}
        id_map: dict[str, str] = {}
        for interval in contract.get("locked_intervals") or []:
            old_id = str(interval.get("interval_id") or "")
            new_id = f"R{document_index:02d}-{old_id or f'I{len(combined_intervals) + 1:03d}'}"
            id_map[old_id] = new_id
            combined_intervals.append({**interval, "interval_id": new_id})
        for record in document_records:
            old_id = str(record.get("interval_id") or "")
            if old_id in id_map:
                record["interval_id"] = id_map[old_id]
            if not locked_dialogue_mode:
                dialogue_id_map: dict[str, str] = {}
                for utterance in record.get("dialogue_utterances") or []:
                    if not isinstance(utterance, dict):
                        continue
                    old_dialogue_id = str(utterance.get("dialogue_id") or "").strip()
                    if old_dialogue_id:
                        new_dialogue_id = dialogue_id_map.setdefault(
                            old_dialogue_id, f"R{document_index:02d}-{old_dialogue_id}"
                        )
                        utterance["dialogue_id"] = new_dialogue_id
                record["dialogue_event_ids"] = [
                    dialogue_id_map.get(str(value), f"R{document_index:02d}-{value}")
                    for value in record.get("dialogue_event_ids") or []
                ]
        combined_candidates.extend(contract.get("candidates") or [])
        combined_candidates.extend(contract.get("range_edge_candidates") or [])
        if contract.get("lock_score_threshold") is not None:
            lock_thresholds.append(float(contract["lock_score_threshold"]))
        groups = sorted({int(record.get("narrative_group") or 1) for record in document_records})
        first_group = groups[0] if groups else 1
        merge_first = False
        if previous_document and document_records:
            previous_record = previous_document.get("records", [])[-1]
            current_record = document_records[0]
            same_scene = str(previous_record.get("scene_observation") or "").split("，", 1)[0] == str(current_record.get("scene_observation") or "").split("，", 1)[0]
            dialogue_continues = bool(previous_record.get("dialogue_utterances")) and bool(current_record.get("dialogue_utterances"))
            merge_first = same_scene and dialogue_continues
        offset = previous_max_group - first_group if merge_first else previous_max_group + 1 - first_group
        if not records:
            offset = 1 - first_group
        for record in document_records:
            record["narrative_group"] = int(record.get("narrative_group") or first_group) + offset
            records.append(record)
        previous_max_group = max((int(record.get("narrative_group") or 1) for record in document_records), default=previous_max_group)
        previous_document = document
    records.sort(key=lambda record: float(record["start_seconds"]))
    for index, record in enumerate(records, 1):
        record["id"] = f"E{index:03d}"

    candidate_by_time: dict[float, dict] = {}
    for candidate in combined_candidates:
        seconds = round(float(candidate.get("seconds")), 3)
        current = candidate_by_time.get(seconds)
        if current is None or float(candidate.get("score") or 0.0) > float(current.get("score") or 0.0):
            candidate_by_time[seconds] = candidate
    combined_candidates = [candidate_by_time[key] for key in sorted(candidate_by_time)]
    synthetic_boundary_data = {
        "boundaries": [0.0, *[float(item.get("seconds")) for item in combined_candidates], args.duration],
        "peaks": [
            {"seconds": float(item.get("seconds")), "score": float(item.get("score"))}
            for item in combined_candidates
            if item.get("score") is not None
        ],
    }
    merged_boundary_contract = build_boundary_contract(
        synthetic_boundary_data,
        0.0,
        args.duration,
        min(lock_thresholds) if lock_thresholds else 0.5,
    )
    merged_false_times = {
        round(float(item["candidate_seconds"]), 3)
        for document in documents
        for item in [
            *(document.get("boundary_audit") or []),
            *([document.get("transport", {}).get("start_seam_audit")] if isinstance(document.get("transport", {}).get("start_seam_audit"), dict) else []),
        ]
        if item.get("decision") == "merge_false"
    }
    for record in records:
        record_start = float(record["start_seconds"])
        record_end = float(record["end_seconds"])
        midpoint = (record_start + record_end) / 2.0
        overlapping_intervals = [
            interval
            for interval in merged_boundary_contract.get("locked_intervals") or []
            if float(interval["end_seconds"]) > record_start + 0.001
            and float(interval["start_seconds"]) < record_end - 0.001
        ]
        internal_edges = [
            round(float(interval["end_seconds"]), 3)
            for interval in overlapping_intervals[:-1]
            if record_start + 0.001 < float(interval["end_seconds"]) < record_end - 0.001
        ]
        if len(overlapping_intervals) > 1 and internal_edges and all(edge in merged_false_times for edge in internal_edges):
            record["interval_id"] = "_".join(str(interval["interval_id"]) for interval in overlapping_intervals)
        else:
            interval = interval_for_time(merged_boundary_contract, midpoint)
            if interval:
                record["interval_id"] = interval["interval_id"]
        record["evidence_interval_ids"] = [
            str(candidate["evidence_interval_id"])
            for candidate in merged_boundary_contract.get("evidence_intervals") or []
            if float(candidate["end_seconds"]) > record_start + 0.001
            and float(candidate["start_seconds"]) < record_end - 0.001
        ]

    audit_by_candidate: dict[float, dict] = {}
    for document in documents:
        for item in document.get("boundary_audit") or []:
            audit_by_candidate[round(float(item["candidate_seconds"]), 3)] = item
        transport_audit = (document.get("transport") or {}).get("start_seam_audit")
        if isinstance(transport_audit, dict):
            audit_by_candidate[round(float(transport_audit["candidate_seconds"]), 3)] = transport_audit
    ranges = sorted((float(document.get("analysis_start_seconds", 0.0)), float(document.get("analysis_end_seconds", args.duration))) for document in documents)
    seam_errors: list[str] = []
    transport_continuity_audits: list[dict] = []
    allowed_transport_modes = {"inherit_state", "new_scene", "verify_from_video"}
    for _, split_point in ranges[:-1]:
        previous_record = max((record for record in records if float(record["end_seconds"]) <= split_point + 0.1), key=lambda record: float(record["end_seconds"]), default=None)
        next_record = min((record for record in records if float(record["start_seconds"]) >= split_point - 0.1), key=lambda record: float(record["start_seconds"]), default=None)
        before_subject = str((previous_record or {}).get("primary_visible_subject") or "range boundary before subject")
        after_subject = str((next_record or {}).get("primary_visible_subject") or "range boundary after subject")
        if round(split_point, 3) not in audit_by_candidate:
            seam_errors.append(
                f"missing overlap-informed range seam audit at {split_point:.3f}s; "
                "a transport boundary must never be forced to keep_cut"
            )
            continue
        transport_audit = audit_by_candidate[round(split_point, 3)]
        continuity_decision = transport_audit.get("continuity_decision")
        continuity_mode = str((continuity_decision or {}).get("continuity_mode") or "")
        if not isinstance(continuity_decision, dict) or continuity_mode not in allowed_transport_modes:
            seam_errors.append(
                f"range seam at {split_point:.3f}s lacks a valid second-wave continuity decision; "
                "expected inherit_state, new_scene, or verify_from_video"
            )
            continue
        transport_continuity_audits.append(transport_audit)
    result = {
        "schema_version": "1.0",
        "prompt_contract_version": output_contract_version,
        "source_prompt_contract_versions": sorted(versions),
        "episode": str(args.episode).zfill(2),
        "duration_seconds": args.duration,
        "boundary_audit": [audit_by_candidate[key] for key in sorted(audit_by_candidate)],
        "transport_continuity_audits": transport_continuity_audits,
        "transport_continuity_contract": {
            "boundary_level": "planned_range_seams",
            "expected_boundary_count": max(0, len(ranges) - 1),
            "allowed_modes": ["inherit_state", "new_scene", "verify_from_video"],
            "ownership": "right_hand_range_start_seam",
        },
        "boundary_contract": merged_boundary_contract,
        "records": records,
        "warnings": ([f"Merged structurally compatible partial reruns from prompt contracts: {', '.join(sorted(versions))}."] if len(versions) > 1 else []) + [warning for document in documents for warning in (document.get("warnings") or [])],
        "errors": seam_errors + locked_dialogue_errors + [error for document in documents for error in (document.get("errors") or [])],
    }
    if locked_dialogue_mode:
        result["dialogue_events"] = sorted(
            locked_dialogue_events.values(),
            key=lambda event: (float(event.get("start_seconds") or 0.0), str(event.get("dialogue_id") or "")),
        )
        result["dialogue_injection_contract"] = dict(locked_dialogue_documents[0]["dialogue_injection_contract"])
        result["dialogue_injection_contract"]["event_count"] = len(result["dialogue_events"])
    else:
        ensure_dialogue_contract(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "audits": len(result["boundary_audit"]), "ranges": len(documents)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

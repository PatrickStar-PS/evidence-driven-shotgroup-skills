#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from continuity_handoff import CONTRACT_VERSION, validate_group_continuity_handoffs


CAMERA_VIEWS = {"1 俯瞰/俯视", "2 正视", "3 侧视", "4 反打", "待确认"}
TIME_OF_DAY_VALUES = {"day", "night", "dawn", "dusk", "unclear", "mixed"}
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def compact_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def family(asset: str) -> str:
    return asset.split(" - ", 1)[0].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate locally expanded British shot-group JSON.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--tolerance", type=float, default=0.1)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    delivery_required = bool((data.get("dialogue_translation_contract") or {}).get("delivery_instruction_field"))
    rows = data.get("rows")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty array")
        rows = []
    continuity_contract = data.get("continuity_handoff_contract")
    if not isinstance(continuity_contract, dict):
        errors.append("continuity_handoff_contract must be an object")
    else:
        if str(continuity_contract.get("version") or "") != CONTRACT_VERSION:
            errors.append(f"unsupported continuity handoff contract: {continuity_contract.get('version')!r}")
        expected_boundaries = max(0, len(rows) - 1)
        if int(continuity_contract.get("expected_boundary_count", -1)) != expected_boundaries:
            errors.append(
                f"continuity_handoff_contract expected_boundary_count must be {expected_boundaries}"
            )
    errors.extend(validate_group_continuity_handoffs(rows, data.get("continuity_handoffs"), args.tolerance))

    previous_end = 0.0
    seen_ids: set[str] = set()
    seen_dialogue_segments: set[str] = set()
    dialogue_segments_by_id: dict[str, list[dict]] = {}
    for index, row in enumerate(rows, 1):
        label = str(row.get("group_id") or f"row {index}")
        expected = f"EP{int(row.get('episode', 0)):02d}-G{index:03d}"
        if label != expected:
            errors.append(f"{label}: expected sequential id {expected}")
        if label in seen_ids:
            errors.append(f"{label}: duplicated id")
        seen_ids.add(label)
        try:
            start = float(row.get("start_seconds"))
            end = float(row.get("end_seconds"))
        except (TypeError, ValueError):
            errors.append(f"{label}: invalid numeric time")
            continue
        if start > previous_end + args.tolerance:
            errors.append(f"{label}: timeline gap {start - previous_end:.3f}s")
        if start < previous_end - args.tolerance:
            errors.append(f"{label}: timeline overlap {previous_end - start:.3f}s")
        if end <= start or end > args.duration + args.tolerance:
            errors.append(f"{label}: invalid range {start}-{end}")
        previous_end = end

        scene = str(row.get("scene") or "").strip()
        time_of_day = str(row.get("time_of_day") or "").strip()
        if time_of_day not in TIME_OF_DAY_VALUES:
            errors.append(f"{label}: invalid time_of_day {time_of_day!r}")
        elif time_of_day == "mixed":
            errors.append(f"{label}: mixed time_of_day requires a shot-group boundary")
        elif time_of_day == "unclear":
            warnings.append(f"{label}: time_of_day remains unclear")
        if not str(row.get("time_of_day_evidence") or "").strip():
            errors.append(f"{label}: time_of_day_evidence is required")
        people = [str(value).strip() for value in (row.get("main_characters") or []) if str(value).strip()]
        linked = [str(value).strip() for value in (row.get("linked_assets") or []) if str(value).strip()]
        if not scene:
            errors.append(f"{label}: scene is empty")
        if not people:
            errors.append(f"{label}: main_characters is empty")
        scene_assets = [value.strip() for value in scene.replace("、", "；").split("；") if value.strip()]
        missing_scene_assets = [value for value in scene_assets if value not in linked]
        if missing_scene_assets:
            errors.append(f"{label}: scene assets are absent from linked_assets: {missing_scene_assets}")
        for person in people:
            if person.startswith("背景路人"):
                continue
            if person not in linked:
                errors.append(f"{label}: person absent from linked_assets: {person}")
            if " - " not in person and "-" not in person:
                errors.append(f"{label}: character must use an exact person wardrobe/state asset: {person}")

        visual_parts = [
            str(row.get("narrative_summary") or ""),
            str(row.get("composition") or ""),
            str(row.get("initial_frame") or ""),
            str(row.get("final_frame") or ""),
            str(row.get("mouth_dynamics") or ""),
            str(row.get("expressions_gaze") or ""),
        ]
        for shot in row.get("subshots") or []:
            visual_parts.extend(str(shot.get(key) or "") for key in ("description", "spatial_positions", "contact_actions"))
        visual_blob = " ".join(visual_parts)
        for person in people:
            if person not in visual_blob:
                errors.append(f"{label}: exact character-state asset is absent from visual prose: {person}")

        by_family: dict[str, set[str]] = {}
        for person in people:
            by_family.setdefault(family(person), set()).add(person)
        for name, variants in by_family.items():
            # "Supporting Character" is a generic localized placeholder shared by
            # multiple distinct source characters in the canonical asset workbook.
            # It cannot be used as a stable person-family key for wardrobe conflicts.
            if name == "Supporting Character":
                continue
            if len(variants) > 1:
                errors.append(f"{label}: conflicting state assets for {name}: {sorted(variants)}")

        chinese = str(row.get("chinese_dialogue") or "").strip()
        british = str(row.get("british_localized_dialogue") or "").strip()
        if chinese and not british:
            errors.append(f"{label}: Chinese dialogue has no British-localized dialogue")
        if british:
            for part_index, part in enumerate(british.split(" | "), 1):
                translated_text = part.split(":", 1)[1].strip() if ":" in part else part.strip()
                if CJK_RE.search(translated_text):
                    errors.append(f"{label}: British-localized dialogue part {part_index} still contains Chinese text")
        delivery_items = row.get("dialogue_delivery")
        if delivery_required and chinese and not isinstance(delivery_items, list):
            errors.append(f"{label}: dialogue_delivery must be an array when dialogue is present")
            delivery_items = []
        if isinstance(delivery_items, list):
            for delivery_index, item in enumerate(delivery_items, 1):
                if not isinstance(item, dict):
                    errors.append(f"{label}: dialogue_delivery {delivery_index} must be an object")
                    continue
                dialogue_id = str(item.get("dialogue_id") or "").strip()
                segment_id = str(item.get("dialogue_segment_id") or "").strip()
                if not dialogue_id:
                    errors.append(f"{label}: dialogue_delivery {delivery_index} has no dialogue_id")
                if not segment_id:
                    errors.append(f"{label}: dialogue_delivery {delivery_index} has no dialogue_segment_id")
                elif segment_id in seen_dialogue_segments:
                    errors.append(f"{label}: duplicated dialogue segment {segment_id}")
                else:
                    seen_dialogue_segments.add(segment_id)
                try:
                    segment_index = int(item.get("segment_index"))
                    segment_count = int(item.get("segment_count"))
                    segment_start = float(item.get("start_seconds"))
                    segment_end = float(item.get("end_seconds"))
                    if segment_index < 1 or segment_count < segment_index:
                        errors.append(f"{label}: dialogue_delivery {delivery_index} has invalid segment index/count")
                    if segment_start < start - args.tolerance or segment_end > end + args.tolerance or segment_end <= segment_start:
                        errors.append(f"{label}: dialogue segment {segment_id} is outside its owner group")
                except (TypeError, ValueError):
                    errors.append(f"{label}: dialogue_delivery {delivery_index} has invalid segment metadata")
                if dialogue_id:
                    dialogue_segments_by_id.setdefault(dialogue_id, []).append(item)
                if not str(item.get("performance_direction") or "").strip():
                    errors.append(f"{label}: dialogue_delivery {delivery_index} has no performance_direction")
                if CJK_RE.search(str(item.get("localized_text") or "")):
                    errors.append(f"{label}: dialogue_delivery {delivery_index} localized_text contains Chinese")
                status = item.get("timing_status")
                if status not in {"fits_source_rate", "fits_hard_limit_but_not_source_rate", "needs_condense"}:
                    errors.append(f"{label}: dialogue_delivery {delivery_index} has invalid timing_status")
                elif status == "needs_condense":
                    errors.append(f"{label}: dialogue_delivery {delivery_index} translation must be condensed before export")
                elif status == "fits_hard_limit_but_not_source_rate":
                    warnings.append(f"{label}: dialogue_delivery {delivery_index} fits duration but is faster than the source delivery")
            expected_chinese = "；".join(str(item.get("source_text") or "") for item in delivery_items if isinstance(item, dict) and item.get("source_text"))
            if compact_text(chinese) != compact_text(expected_chinese):
                errors.append(f"{label}: chinese_dialogue disagrees with its uniquely owned dialogue segments")
            for item in delivery_items:
                if isinstance(item, dict) and str(item.get("localized_text") or "").strip() not in british:
                    errors.append(f"{label}: localized dialogue segment is absent from british_localized_dialogue")
        if row.get("camera_view") not in CAMERA_VIEWS:
            errors.append(f"{label}: invalid camera_view")
        if row.get("camera_view") == "待确认":
            warnings.append(f"{label}: camera_view remains pending")

        subshots = row.get("subshots") or []
        if not subshots:
            errors.append(f"{label}: subshots is empty")
        for shot_index, shot in enumerate(subshots, 1):
            shot_time_of_day = str(shot.get("time_of_day") or "").strip()
            if shot_time_of_day not in TIME_OF_DAY_VALUES - {"mixed"}:
                errors.append(f"{label}/subshot {shot_index}: invalid time_of_day {shot_time_of_day!r}")
            if not str(shot.get("time_of_day_evidence") or "").strip():
                errors.append(f"{label}/subshot {shot_index}: time_of_day_evidence is required")
            if time_of_day not in {"", "unclear", "mixed"} and shot_time_of_day not in {time_of_day, "unclear"}:
                errors.append(f"{label}/subshot {shot_index}: time_of_day conflicts with parent group")
            try:
                shot_start = float(shot.get("start_seconds"))
                shot_end = float(shot.get("end_seconds"))
            except (TypeError, ValueError):
                errors.append(f"{label}/subshot {shot_index}: invalid numeric time")
                continue
            if shot_start < start - args.tolerance or shot_end > end + args.tolerance or shot_end <= shot_start:
                errors.append(f"{label}/subshot {shot_index}: outside parent range")

    assembly_items = data.get("dialogue_assembly")
    segmentation_required = bool(data.get("dialogue_segmentation_contract"))
    if segmentation_required and not isinstance(assembly_items, list):
        errors.append("dialogue_assembly must be an array")
        assembly_items = []
    if isinstance(assembly_items, list):
        expected_ids: set[str] = set()
        for assembly in assembly_items:
            if not isinstance(assembly, dict):
                errors.append("dialogue_assembly item must be an object")
                continue
            dialogue_id = str(assembly.get("dialogue_id") or "").strip()
            expected_ids.add(dialogue_id)
            segments = sorted(dialogue_segments_by_id.get(dialogue_id) or [], key=lambda item: int(item.get("segment_index") or 0))
            expected_count = int(assembly.get("segment_count") or 0)
            if len(segments) != expected_count:
                errors.append(f"{dialogue_id}: expected {expected_count} uniquely owned segments, found {len(segments)}")
                continue
            actual_segment_ids = [str(item.get("dialogue_segment_id") or "") for item in segments]
            if actual_segment_ids != list(assembly.get("segment_ids") or []):
                errors.append(f"{dialogue_id}: segment IDs or order disagree with dialogue_assembly")
            if [int(item.get("segment_index") or 0) for item in segments] != list(range(1, expected_count + 1)):
                errors.append(f"{dialogue_id}: segment indexes are not continuous")
            if compact_text("".join(str(item.get("source_text") or "") for item in segments)) != compact_text(assembly.get("source_text")):
                errors.append(f"{dialogue_id}: source text was lost or duplicated across groups")
            if compact_text("".join(str(item.get("localized_text") or "") for item in segments)) != compact_text(assembly.get("localized_text")):
                errors.append(f"{dialogue_id}: localized text was lost or duplicated across groups")
        unexpected_ids = set(dialogue_segments_by_id) - expected_ids
        if unexpected_ids:
            errors.append(f"dialogue segments missing from dialogue_assembly: {sorted(unexpected_ids)}")

    if rows and abs(previous_end - args.duration) > args.tolerance:
        errors.append(f"final end {previous_end:.3f} differs from duration {args.duration:.3f}")

    report = {"valid": not errors, "rows": len(rows), "errors": errors, "warnings": warnings}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

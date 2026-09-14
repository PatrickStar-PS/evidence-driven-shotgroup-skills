#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PERSISTENT_STATE_TERMS = (
    "蒙眼", "蒙住", "遮眼", "眼罩", "眼部", "眼睛", "纱巾", "丝巾", "蕾丝带", "缎带",
    "绑", "束缚", "捆", "手腕", "被子", "毯", "床单", "床品", "枕头", "覆盖", "盖着",
    "外套", "披着", "穿着", "脱下", "伤口", "血", "湿发", "手持", "拿着", "握着",
)
STATE_RELEASE_TERMS = (
    "取下", "摘下", "解开", "松开", "放下", "丢下", "离手", "不再", "消失", "移除",
    "露出双眼", "没有被", "未被", "换成",
)


def text(value: object) -> str:
    return str(value or "").strip()


def clip(value: object, limit: int) -> str:
    content = " ".join(text(value).split())
    return content if len(content) <= limit else content[: max(0, limit - 1)].rstrip() + "…"


def clip_around_term(content: str, terms: list[str], limit: int = 180) -> str:
    compact = " ".join(text(content).split())
    positions = [compact.find(term) for term in terms if term and compact.find(term) >= 0]
    if not positions:
        return clip(compact, limit)
    pos = min(positions)
    start = max(0, pos - max(20, limit // 3))
    end = min(len(compact), start + limit)
    start = max(0, end - limit)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end].strip() + suffix


def stateful_notes(records: list[dict[str, Any]], limit: int = 8) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        fields = [
            record.get("visual_details"),
            record.get("transient_visual_details"),
            record.get("visible_action"),
            record.get("contact_actions"),
            record.get("initial_frame"),
            record.get("final_frame"),
        ]
        for person in record.get("visible_characters") or []:
            if isinstance(person, dict):
                fields.extend([
                    person.get("appearance"),
                    person.get("support_contact"),
                    person.get("character_action"),
                    person.get("frame_crop"),
                    person.get("occlusion_relation"),
                ])
        for prop in record.get("prop_continuity") or []:
            if isinstance(prop, dict):
                fields.extend([
                    prop.get("identity"),
                    prop.get("appearance_invariants"),
                    prop.get("holder"),
                    prop.get("support_contact"),
                    prop.get("start_state"),
                    prop.get("middle_state"),
                    prop.get("end_state"),
                    prop.get("continuity_to_next"),
                ])
        content = " ".join(text(value) for value in fields if text(value))
        matched = [term for term in PERSISTENT_STATE_TERMS if term in content]
        if not matched or any(term in content for term in STATE_RELEASE_TERMS):
            continue
        key = "、".join(dict.fromkeys(matched[:4]))
        if key in seen:
            continue
        seen.add(key)
        notes.append(f"命中={','.join(dict.fromkeys(matched[:6]))}；证据={clip_around_term(content, matched, 180)}")
        if len(notes) >= limit:
            break
    return notes


def compact_character_state(person: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": person.get("identity", ""),
        "screen_position": person.get("screen_position", ""),
        "anchor_presence_end": (person.get("anchor_presence") or {}).get("end"),
        "body_posture": person.get("body_posture", ""),
        "torso_orientation": person.get("torso_orientation", ""),
        "head_orientation": person.get("head_orientation", ""),
        "gaze_target": person.get("gaze_target", ""),
        "support_contact": person.get("support_contact", ""),
        "character_action": person.get("character_action", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract the previous logical core's final model-authored state for the next range.")
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-range-id", required=True)
    parser.add_argument("--target-range-id", required=True)
    args = parser.parse_args()

    data: dict[str, Any] = json.loads(args.timeline.read_text(encoding="utf-8-sig"))
    records = sorted(data.get("records") or [], key=lambda item: (float(item.get("end_seconds", 0)), float(item.get("start_seconds", 0))))
    if not records:
        raise RuntimeError("timeline contains no records")
    tail = records[-1]
    result = {
        "schema_version": "1.0-seam-continuity-injection",
        "contract_version": "1.1-text-state",
        "source_range_id": args.source_range_id,
        "target_range_id": args.target_range_id,
        "source_end_seconds": tail.get("end_seconds"),
        "continuity_mode": "verify_from_video",
        "seam_type": "pending_target_video_verification",
        "scene_state": {
            "scene_asset": tail.get("scene_asset") or tail.get("resolved_scene") or "",
            "scene_observation": tail.get("scene_observation", ""),
            "fixed_scene_evidence": tail.get("fixed_scene_evidence", ""),
            "time_of_day": tail.get("time_of_day", "unclear"),
            "time_of_day_evidence": tail.get("time_of_day_evidence", ""),
            "bound_asset_hints": tail.get("asset_hints") or [],
        },
        "action_handoff": {
            "subject": tail.get("primary_visible_subject", ""),
            "action": tail.get("visible_action", ""),
            "final_state": tail.get("final_frame", ""),
            "contact_actions": tail.get("contact_actions", ""),
            "completion_status": "requires_target_video_verification",
        },
        "primary_visible_subject": tail.get("primary_visible_subject", ""),
        "screen_order_end": (tail.get("screen_order_left_to_right") or {}).get("end") or [],
        "visible_characters_end": [
            compact_character_state(person)
            for person in tail.get("visible_characters") or []
            if (person.get("anchor_presence") or {}).get("end") is not False
        ],
        "prop_tail_states": [
            {"instance_id": prop.get("instance_id", ""), "visible_instance_count": prop.get("visible_instance_count"), "identity": prop.get("identity", ""), "appearance_invariants": prop.get("appearance_invariants", ""), "holder": prop.get("holder", ""), "support_contact": prop.get("support_contact", ""), "end_state": prop.get("end_state", ""), "continuity_to_next": prop.get("continuity_to_next", ""), "exclusive_holder_after": prop.get("exclusive_holder_after", "")}
            for prop in tail.get("prop_continuity") or []
        ],
        "persistent_state_tail_notes": stateful_notes(records),
        "final_frame": tail.get("final_frame", ""),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"status": "complete", "props": len(result["prop_tail_states"]), "persistent_state_notes": len(result["persistent_state_tail_notes"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "1.0-group-boundary-handoff"
ALLOWED_MODES = {"inherit_state", "new_scene", "verify"}
AUDIT_MODE_MAP = {
    "inherit_state": "inherit_state",
    "new_scene": "new_scene",
    "verify": "verify",
    "verify_from_video": "verify",
}
PERSISTENT_STATE_TERMS = (
    "蒙眼", "蒙住", "遮眼", "眼罩", "眼部", "眼睛", "纱巾", "丝巾", "蕾丝带", "缎带",
    "绑", "束缚", "捆", "手腕", "被子", "毯", "床单", "床品", "枕头", "覆盖", "盖着",
    "外套", "披着", "穿着", "脱下", "伤口", "血", "湿发", "手持", "拿着", "握着",
)
STATE_RELEASE_TERMS = (
    "取下", "摘下", "解开", "松开", "放下", "丢下", "离手", "不再", "消失", "移除",
    "露出双眼", "没有被", "未被", "换成",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _clip(value: object, limit: int) -> str:
    text = " ".join(_text(value).split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _clip_around_term(text: str, terms: list[str], limit: int = 180) -> str:
    compact = " ".join(_text(text).split())
    positions = [compact.find(term) for term in terms if term and compact.find(term) >= 0]
    if not positions:
        return _clip(compact, limit)
    pos = min(positions)
    start = max(0, pos - max(20, limit // 3))
    end = min(len(compact), start + limit)
    start = max(0, end - limit)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end].strip() + suffix


def _record_scene(record: dict[str, Any], row: dict[str, Any], edge: str) -> str:
    resolved = _text(record.get("_resolved_scene_asset") or record.get("resolved_scene_asset"))
    if resolved:
        return resolved
    group_scenes = [value.strip() for value in _text(row.get("scene")).replace("、", "；").split("；") if value.strip()]
    if len(group_scenes) == 1:
        return group_scenes[0]
    if len(group_scenes) > 1:
        return group_scenes[0] if edge == "head" else group_scenes[-1]
    return ""


def _stateful_tail_notes(records: list[dict[str, Any]], limit: int = 8) -> list[str]:
    notes: list[str] = []
    active_terms: set[str] = set()
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
        text = " ".join(_text(value) for value in fields if _text(value))
        if not text:
            continue
        released = any(term in text for term in STATE_RELEASE_TERMS)
        matched = [term for term in PERSISTENT_STATE_TERMS if term in text]
        if matched and not released:
            key = "、".join(dict.fromkeys(matched[:4]))
            if key not in active_terms:
                active_terms.add(key)
                notes.append(f"命中={','.join(dict.fromkeys(matched[:6]))}；证据={_clip_around_term(text, matched, 180)}")
                if len(notes) >= limit:
                    break
    return notes


def _record_tail_state(row: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    record = records[-1] if records else {}
    subshots = row.get("subshots") if isinstance(row.get("subshots"), list) else []
    subshot = subshots[-1] if subshots else {}
    order = record.get("screen_order_left_to_right") if isinstance(record.get("screen_order_left_to_right"), dict) else {}
    characters = []
    for person in record.get("visible_characters") or []:
        if not isinstance(person, dict):
            continue
        characters.append({
            "identity": _text(person.get("identity")),
            "screen_position": _text(person.get("screen_position")),
            "body_posture": _text(person.get("body_posture")),
            "torso_orientation": _text(person.get("torso_orientation")),
            "head_orientation": _text(person.get("head_orientation")),
            "gaze_target": _text(person.get("gaze_target")),
            "support_contact": _text(person.get("support_contact")),
            "character_action": _text(person.get("character_action")),
        })
    props = []
    for item in record.get("prop_continuity") or []:
        if not isinstance(item, dict):
            continue
        props.append({
            "instance_id": _text(item.get("instance_id")),
            "identity": _text(item.get("identity")),
            "holder": _text(item.get("holder")),
            "end_state": _text(item.get("end_state")),
        })
    return {
        "scene": _record_scene(record, row, "tail"),
        "resolved_group_scene": _text(row.get("scene")),
        "time_of_day": _text(record.get("time_of_day")) or _text(row.get("time_of_day")),
        "final_frame": _text(row.get("final_frame")),
        "primary_visible_subject": _text(record.get("primary_visible_subject")),
        "screen_order_end": [str(value) for value in (order.get("end") or [])],
        "spatial_positions": _text(subshot.get("spatial_positions")),
        "contact_actions": _text(subshot.get("contact_actions")),
        "visible_characters_end": characters,
        "prop_tail_states": props,
        "persistent_state_tail_notes": _stateful_tail_notes(records),
    }


def _record_head_state(row: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    record = records[0] if records else {}
    subshots = row.get("subshots") if isinstance(row.get("subshots"), list) else []
    subshot = subshots[0] if subshots else {}
    order = record.get("screen_order_left_to_right") if isinstance(record.get("screen_order_left_to_right"), dict) else {}
    return {
        "scene": _record_scene(record, row, "head"),
        "resolved_group_scene": _text(row.get("scene")),
        "time_of_day": _text(record.get("time_of_day")) or _text(row.get("time_of_day")),
        "initial_frame": _text(row.get("initial_frame")),
        "primary_visible_subject": _text(record.get("primary_visible_subject")),
        "screen_order_start": [str(value) for value in (order.get("start") or [])],
        "spatial_positions": _text(subshot.get("spatial_positions")),
        "contact_actions": _text(subshot.get("contact_actions")),
    }


def _nearest_audit(compact: dict[str, Any], seconds: float, tolerance: float) -> dict[str, Any] | None:
    candidates = []
    for item in compact.get("boundary_audit") or []:
        if not isinstance(item, dict):
            continue
        try:
            delta = abs(float(item.get("candidate_seconds")) - seconds)
        except (TypeError, ValueError):
            continue
        if delta <= tolerance:
            candidates.append((0 if isinstance(item.get("continuity_decision"), dict) else 1, delta, item))
    return min(candidates, default=(99, 99.0, None), key=lambda value: (value[0], value[1]))[2]


def _derive_mode(
    previous: dict[str, Any],
    current: dict[str, Any],
    audit: dict[str, Any] | None,
) -> tuple[str, str, str]:
    decision = audit.get("continuity_decision") if isinstance(audit, dict) and isinstance(audit.get("continuity_decision"), dict) else {}
    seam_type = _text(decision.get("seam_type"))
    audit_mode = AUDIT_MODE_MAP.get(_text(decision.get("continuity_mode")))
    if seam_type in {"scene_transition", "time_jump"}:
        return "new_scene", seam_type, "audited_overlap_pixels"
    if audit_mode == "verify":
        continuity_flags = [
            _text(decision.get("scene_match")).lower(),
            _text(decision.get("action_continues")).lower(),
            _text(decision.get("character_state_continues")).lower(),
        ]
        if seam_type in {"same_scene_cut", "continuous_action"} and continuity_flags == ["true", "true", "true"]:
            return "inherit_state", seam_type, "audited_overlap_pixels_consistency_resolution"
    if audit_mode:
        return audit_mode, seam_type or "unclear", "audited_overlap_pixels"

    previous_scene = _text(previous.get("scene"))
    current_scene = _text(current.get("scene"))
    previous_time = _text(previous.get("time_of_day"))
    current_time = _text(current.get("time_of_day"))
    scene_known = previous_scene and current_scene and "待确认" not in previous_scene + current_scene
    explicit_time_change = previous_time not in {"", "unclear"} and current_time not in {"", "unclear"} and previous_time != current_time
    if scene_known and previous_scene != current_scene:
        return "new_scene", "scene_transition", "deterministic_group_state_audit"
    if explicit_time_change:
        return "new_scene", "time_jump", "deterministic_group_state_audit"
    if scene_known and previous_scene == current_scene:
        return "inherit_state", "same_scene_cut", "deterministic_group_state_audit"
    return "verify", "unclear", "deterministic_group_state_audit"


def _instruction(mode: str, previous: dict[str, Any], current: dict[str, Any]) -> str:
    persistent_note = ""
    if previous.get("persistent_state_tail_notes"):
        persistent_note = f"未解除状态物={_clip('；'.join(previous['persistent_state_tail_notes']), 220)}。"
    if mode == "inherit_state":
        return (
            f"继承上一组末态：场景={_clip(previous['scene'], 60)}，昼夜={previous['time_of_day']}，"
            f"末帧={_clip(previous['final_frame'], 120)}，站位/遮挡={_clip(previous['spatial_positions'], 160)}，"
            f"接触={_clip(previous['contact_actions'], 100)}。{persistent_note}本组首态={_clip(current['initial_frame'], 120)}；"
            "除剧情明确发生的动作、切镜或重新构图外，人物状态、接触关系、关键道具、光线方向与曝光保持连续。"
        )
    if mode == "new_scene":
        return (
            f"上一组结束于{_clip(previous['scene'], 60)}：{_clip(previous['final_frame'], 120)}。"
            f"{persistent_note}本组以新场景{_clip(current['scene'], 60)}开始：{_clip(current['initial_frame'], 120)}。"
            "不继承上一组空间站位、接触关系和场景光线；"
            "只保留剧情明确持续的人物身份、服装/伤病/湿身状态与随身关键道具。"
        )
    return (
        f"边界证据不足：上一组末帧={_clip(previous['final_frame'], 120)}；"
        f"{persistent_note}本组首帧={_clip(current['initial_frame'], 120)}。"
        "生成前必须依据目标组首帧视频证据核验场景、站位、接触、道具和光线，不得自行臆造继承或换场。"
    )


def attach_group_continuity_handoffs(
    rows: list[dict[str, Any]],
    group_records: list[list[dict[str, Any]]],
    compact: dict[str, Any],
    tolerance: float = 0.16,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(group_records) != len(rows):
        raise ValueError("group_records length must match rows length")
    for row in rows:
        row.pop("continuity_handoff", None)

    handoffs = []
    for index in range(1, len(rows)):
        previous_row = rows[index - 1]
        current_row = rows[index]
        boundary = float(current_row["start_seconds"])
        previous_state = _record_tail_state(previous_row, group_records[index - 1])
        current_state = _record_head_state(current_row, group_records[index])
        audit = _nearest_audit(compact, boundary, tolerance)
        mode, seam_type, authority = _derive_mode(previous_state, current_state, audit)
        persistent_assets = sorted(set(previous_row.get("linked_assets") or []) & set(current_row.get("linked_assets") or []))
        handoff = {
            "handoff_id": f"{previous_row['group_id']}->{current_row['group_id']}",
            "source_group_id": str(previous_row["group_id"]),
            "target_group_id": str(current_row["group_id"]),
            "boundary_seconds": round(boundary, 3),
            "mode": mode,
            "seam_type": seam_type,
            "authority": authority,
            "previous_final_state": previous_state,
            "target_initial_state": current_state,
            "persistent_assets": persistent_assets,
            "inherited_state": previous_state if mode == "inherit_state" else {},
            "reset_fields": ["screen_order", "spatial_positions", "contact_actions", "scene_lighting"] if mode == "new_scene" else [],
            "instruction": _instruction(mode, previous_state, current_state),
            "audit_decision": audit if isinstance(audit, dict) else None,
        }
        current_row["continuity_handoff"] = handoff
        handoffs.append(handoff)

    contract = {
        "version": CONTRACT_VERSION,
        "boundary_level": "final_shot_groups",
        "allowed_modes": ["inherit_state", "new_scene", "verify"],
        "expected_boundary_count": max(0, len(rows) - 1),
        "ownership": "right_hand_target_group_only",
        "audit_priority": "overlap_pixel_audit_then_deterministic_group_state_audit",
    }
    return contract, handoffs


def validate_group_continuity_handoffs(
    rows: list[dict[str, Any]],
    handoffs: object,
    tolerance: float = 0.1,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(handoffs, list):
        return ["continuity_handoffs must be an array"]
    expected = max(0, len(rows) - 1)
    if len(handoffs) != expected:
        errors.append(f"expected {expected} continuity handoffs, found {len(handoffs)}")
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for item in handoffs:
        if not isinstance(item, dict):
            errors.append("continuity handoff must be an object")
            continue
        source = _text(item.get("source_group_id"))
        target = _text(item.get("target_group_id"))
        handoff_id = _text(item.get("handoff_id"))
        if handoff_id in seen_ids:
            errors.append(f"duplicate continuity handoff id: {handoff_id}")
        seen_ids.add(handoff_id)
        pair = (source, target)
        if pair in by_pair:
            errors.append(f"duplicate continuity handoff pair: {source}->{target}")
        by_pair[pair] = item
        mode = _text(item.get("mode"))
        if mode not in ALLOWED_MODES:
            errors.append(f"{source}->{target}: invalid continuity mode {mode!r}")
        if not _text(item.get("instruction")):
            errors.append(f"{source}->{target}: missing continuity instruction")
        if not isinstance(item.get("previous_final_state"), dict) or not isinstance(item.get("target_initial_state"), dict):
            errors.append(f"{source}->{target}: missing boundary states")
        if mode == "inherit_state" and not isinstance(item.get("inherited_state"), dict):
            errors.append(f"{source}->{target}: inherit_state requires inherited_state")
        if mode == "new_scene" and not item.get("reset_fields"):
            errors.append(f"{source}->{target}: new_scene requires reset_fields")

    if rows:
        first_handoff = rows[0].get("continuity_handoff")
        if first_handoff is not None and first_handoff != "":
            errors.append(f"{rows[0].get('group_id')}: first group must not own a continuity handoff")
    for index in range(1, len(rows)):
        previous = rows[index - 1]
        current = rows[index]
        source = _text(previous.get("group_id"))
        target = _text(current.get("group_id"))
        item = by_pair.get((source, target))
        if item is None:
            errors.append(f"missing continuity handoff: {source}->{target}")
            continue
        if current.get("continuity_handoff") != item:
            errors.append(f"{target}: target row handoff disagrees with root continuity_handoffs")
        try:
            boundary = float(item.get("boundary_seconds"))
            previous_end = float(previous.get("end_seconds"))
            current_start = float(current.get("start_seconds"))
            if abs(boundary - previous_end) > tolerance or abs(boundary - current_start) > tolerance:
                errors.append(f"{source}->{target}: boundary_seconds does not match adjacent group boundary")
        except (TypeError, ValueError):
            errors.append(f"{source}->{target}: invalid boundary_seconds")
    return errors

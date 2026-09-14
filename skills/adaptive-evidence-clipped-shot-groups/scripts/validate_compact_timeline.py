#!/usr/bin/env python3
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import re
from pathlib import Path

from timeline_contract import build_boundary_contract, normalized_dialogue_text, normalized_identity


REQUIRED = {
    "id",
    "start_seconds",
    "end_seconds",
    "boundary",
    "scene_observation",
    "primary_visible_subject",
    "visible_characters",
    "visible_action",
    "shot_size",
    "camera_angle",
    "camera_motion",
    "camera_view",
    "spatial_positions",
    "contact_actions",
    "initial_frame",
    "final_frame",
    "expression_gaze",
    "mouth_dynamics",
    "speaker",
    "dialogue_utterances",
    "chinese_dialogue",
    "on_screen_text",
    "sound",
    "asset_hints",
    "confidence",
    "warnings",
}

PROMPT_CONTRACT_VERSION = "3.9-mouth-motion-speech-sync"
ALLOWED_TIME_OF_DAY = {"day", "night", "dawn", "dusk", "unclear"}
DELIVERY_FIELDS = {"speech_rate", "intonation", "timbre", "emotion", "rhythm_pause", "pause_profile", "confidence"}
ALLOWED_SPEECH_RATE = {"very_slow", "slow", "medium", "fast", "very_fast", "unclear"}
LEGACY_PROMPT_CONTRACT_VERSIONS = {
    "3.8-reaction-shot-dialogue-lock",
    "3.7-screen-order-transition",
    "3.6-seam-state-and-screen-order-motion",
    "3.3-background-people-static-light-filter",
    "3.2-asset-owned-generation-facts",
    "3.1-person-trajectory-evidence",
    "3.0-asset-bound-no-repeat",
    "2.9-camera-axis-separation",
    "2.8-transient-chain-oblique-view",
    "2.7-transient-motion-horizontal-view",
    "2.6-daylight-dialogue-segmentation",
    "2.5-dialogue-injection-overlap-clipped-adaptive-evidence",
    "2.3-dialogue-injection-locked",
    "2.2-locked-interval-dialogue-events",
    "2.1-screen-axis-evidence",
    "2.0-screen-relative-orientation",
    "1.1-visible-speaker",
    "1.2-background-character-audit",
    "1.3-chinese-character-reference-cards",
    "1.4-bilingual-character-reference-cards",
    "1.5-focus-state",
    "1.6-person-visual-state",
    "1.7-focus-evidence",
    "1.8-spatial-focus-separation",
    "1.9-pairwise-blocking",
}
ALLOWED_SPEECH_SYNC_STATUS = {
    "matched_on_screen_dialogue",
    "off_screen_audio_reaction",
    "non_speech_mouth_motion",
    "no_visible_mouth_motion",
    "unclear",
}

NON_HUMAN_VISIBLE_IDENTITY_TERMS = (
    "外景全景", "内景全景", "场景全景", "酒店外景", "建筑外景", "大堂全景", "走廊全景",
    "办公室全景", "宴会厅全景", "喷泉水池", "车辆全景", "汽车全景",
)
STATIC_LIGHT_TERMS = (
    "灯具", "吊灯", "灯带", "霓虹", "氛围灯", "顶光", "背景灯",
    "蓝色", "红色", "紫色", "彩色", "蓝光", "红光", "霓虹色",
)
DYNAMIC_LIGHT_MARKERS = (
    "开启", "打开", "亮起", "熄灭", "关闭", "闪烁", "闪动", "警灯", "扫过", "掠过",
    "照到脸", "照在脸", "屏幕光", "车灯", "由暗变亮", "由亮变暗",
)


TRANSIENT_ACTION_MARKERS = (
    "进入", "经过", "穿过", "交错", "遮挡", "离开", "移出", "掠过",
    "pass", "enter", "exit", "cross", "occlud",
)


def contains_positive_speech_claim(value: object) -> bool:
    text = str(value or "").lower()
    for negated in (
        "不说话", "未说话", "没有说话", "无说话", "非说话", "并未说话", "并不说话",
        "不开口", "未开口", "没有开口", "无开口", "并未开口", "并不开口",
        "无锁定发言依据", "not speaking", "not_speaking",
    ):
        text = text.replace(negated, "")
    return any(marker in text for marker in ("说话", "讲话", "开口", "配合台词", "念出台词", "说出", "speaking", "speaks"))


def collect_lightweight_warnings(records: list[dict]) -> list[str]:
    """Report likely omissions without changing content or failing validation."""
    warnings: list[str] = []
    for record_index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            continue
        label = f"record {record_index}"
        camera_view = str(record.get("camera_view") or "").strip()
        camera_evidence = str(record.get("camera_view_evidence") or "").strip()
        if not camera_evidence:
            warnings.append(f"{label}: camera_view_evidence is missing")
        evidence_lower = camera_evidence.lower()
        if camera_view == "2 正视" and any(
            marker in evidence_lower
            for marker in (
                "侧面机位", "侧向机位", "摄影机位于主体侧面", "摄影机光轴与人物运动轴近似垂直",
                "side camera", "lateral camera axis",
            )
        ):
            warnings.append(f"{label}: camera_view says frontal but its evidence describes a side viewpoint")
        if camera_view == "3 侧视" and any(
            marker in evidence_lower
            for marker in (
                "正面机位", "摄影机正对主体", "摄影机光轴与人物运动轴基本重合",
                "沿画面纵深迎着摄影机", "frontal view", "front view",
            )
        ):
            warnings.append(f"{label}: camera_view says side but its evidence describes a frontal viewpoint")

        visible_characters = record.get("visible_characters")
        if not isinstance(visible_characters, list):
            continue
        utterances = [item for item in (record.get("dialogue_utterances") or []) if isinstance(item, dict)]
        off_screen_utterances = [item for item in utterances if item.get("speaker_visibility") == "off_screen"]
        on_screen_utterances = [item for item in utterances if item.get("speaker_visibility") == "on_screen"]
        if off_screen_utterances and not on_screen_utterances:
            for character_index, character in enumerate(visible_characters, 1):
                if not isinstance(character, dict):
                    continue
                action = str(character.get("character_action") or "").lower()
                if character.get("mouth_state") == "speaking" or contains_positive_speech_claim(action):
                    warnings.append(
                        f"{label}/character {character_index}: off-screen locked dialogue conflicts with a visible speaking mouth/action; reaction-shot semantics must be reviewed"
                    )
                if character.get("speech_sync_status") == "matched_on_screen_dialogue":
                    warnings.append(
                        f"{label}/character {character_index}: matched_on_screen_dialogue conflicts with off-screen-only locked dialogue"
                    )
            record_speech_text = " ".join(
                str(record.get(field) or "").lower()
                for field in ("beat_summary", "primary_visible_subject", "visible_action", "mouth_dynamics")
            )
            if contains_positive_speech_claim(record_speech_text):
                warnings.append(
                    f"{label}: off-screen locked dialogue conflicts with record-level speaking prose; reaction-shot semantics must be reviewed"
                )
        for character_index, character in enumerate(visible_characters, 1):
            if not isinstance(character, dict):
                continue
            character_label = f"{label}/character {character_index}"
            mouth_state = character.get("mouth_state")
            speech_sync_status = character.get("speech_sync_status")
            if mouth_state == "speaking" and speech_sync_status != "matched_on_screen_dialogue":
                warnings.append(
                    f"{character_label}: mouth_state=speaking requires speech_sync_status=matched_on_screen_dialogue"
                )
            if speech_sync_status == "matched_on_screen_dialogue":
                matching_visible = any(
                    item.get("speaker_visibility") == "on_screen"
                    and identity_matches(character.get("identity"), item.get("speaker"))
                    for item in utterances
                )
                if not matching_visible:
                    warnings.append(
                        f"{character_label}: matched_on_screen_dialogue has no matching on-screen locked utterance"
                    )
            presence = character.get("anchor_presence")
            if not isinstance(presence, dict) or not all(
                isinstance(presence.get(key), bool) for key in ("start", "middle", "end")
            ):
                warnings.append(f"{character_label}: anchor_presence is missing or invalid")
                continue
            if presence == {"start": False, "middle": True, "end": False}:
                action = str(character.get("character_action") or "").lower()
                if not any(marker in action for marker in TRANSIENT_ACTION_MARKERS):
                    warnings.append(
                        f"{character_label}: middle-only person lacks an enter/pass/occlude/exit action chain"
                    )
        prop_continuity = record.get("prop_continuity")
        if prop_continuity is None:
            warnings.append(f"{label}: prop_continuity is missing; soft warning only")
        elif not isinstance(prop_continuity, list):
            warnings.append(f"{label}: prop_continuity is not an array; soft warning only")
        else:
            required_prop_fields = (
                "instance_id", "visible_instance_count", "identity", "appearance_invariants", "holder",
                "support_contact", "start_state", "middle_action", "end_state", "source",
                "continuity_from_previous", "continuity_to_next", "exclusive_holder_after",
            )
            for prop_index, prop in enumerate(prop_continuity, 1):
                if not isinstance(prop, dict):
                    warnings.append(f"{label}/prop {prop_index}: prop entry is not an object; soft warning only")
                    continue
                missing_prop_fields = [field for field in required_prop_fields if not str(prop.get(field) or "").strip()]
                if missing_prop_fields:
                    warnings.append(
                        f"{label}/prop {prop_index}: missing {', '.join(missing_prop_fields)}; soft warning only"
                    )
        screen_order = record.get("screen_order_left_to_right")
        if not isinstance(screen_order, dict) or not all(
            isinstance(screen_order.get(anchor), list) for anchor in ("start", "middle", "end")
        ):
            warnings.append(f"{label}: screen_order_left_to_right is missing or invalid; soft warning only")
            continue
        for character in record.get("visible_characters") or []:
            if not isinstance(character, dict):
                continue
            identity = normalized_identity(character.get("identity"))
            presence = character.get("anchor_presence") or {}
            for anchor in ("start", "middle", "end"):
                listed = identity_matches_order(identity, normalized_order(screen_order.get(anchor)))
                declared = presence.get(anchor)
                if isinstance(declared, bool) and listed != declared:
                    warnings.append(
                        f"{label}: {character.get('identity')} anchor_presence.{anchor} disagrees with "
                        f"screen_order_left_to_right.{anchor}; soft warning only"
                    )
        transition = record.get("position_transition")
        allowed_transition_types = {
            "stable", "crosses_behind", "crosses_in_front", "reblocked_after_cut", "unclear"
        }
        if not isinstance(transition, dict) or transition.get("type") not in allowed_transition_types:
            warnings.append(f"{label}: position_transition is missing or invalid; soft warning only")
        elif screen_order_has_reversal(screen_order) and transition.get("type") == "stable":
            warnings.append(f"{label}: anchor screen order reverses but position_transition is stable; soft warning only")
        elif transition.get("type") == "stable" and record_action_claims_side_change(record):
            warnings.append(
                f"{label}: visible action describes a left/right side change but position_transition is stable; "
                "soft warning only"
            )
        elif transition.get("type") in {"crosses_behind", "crosses_in_front", "reblocked_after_cut"}:
            if not str(transition.get("description") or "").strip():
                warnings.append(f"{label}: position_transition description is missing; soft warning only")
            if not isinstance(transition.get("evidence_timestamps"), list):
                warnings.append(f"{label}: position_transition evidence_timestamps is missing; soft warning only")
    for record_index in range(1, len(records)):
        previous = records[record_index - 1]
        current = records[record_index]
        if not isinstance(previous, dict) or not isinstance(current, dict):
            continue
        previous_order = previous.get("screen_order_left_to_right")
        current_order = current.get("screen_order_left_to_right")
        if not isinstance(previous_order, dict) or not isinstance(current_order, dict):
            continue
        if pair_order_reversed(previous_order.get("end"), current_order.get("start")):
            transition_type = str((current.get("position_transition") or {}).get("type") or "")
            if current.get("boundary") in {"cut", "reframe"} and transition_type != "reblocked_after_cut":
                warnings.append(
                    f"record {record_index + 1}: screen order changes across a cut/reframe without "
                    "position_transition=reblocked_after_cut; soft warning only"
                )
    return warnings


def normalized_order(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [normalized_identity(value) for value in values if normalized_identity(value) and str(value).lower() != "unclear"]


def identity_matches_order(identity: str, order: list[str]) -> bool:
    if not identity:
        return False
    return any(
        identity == candidate
        or (len(identity) >= 2 and len(candidate) >= 2 and (identity in candidate or candidate in identity))
        for candidate in order
    )


def pair_order_reversed(left: object, right: object) -> bool:
    left_order = normalized_order(left)
    right_order = normalized_order(right)
    common = [identity for identity in left_order if identity in right_order]
    if len(common) < 2:
        return False
    left_index = {identity: index for index, identity in enumerate(left_order)}
    right_index = {identity: index for index, identity in enumerate(right_order)}
    return any(
        (left_index[a] - left_index[b]) * (right_index[a] - right_index[b]) < 0
        for index, a in enumerate(common)
        for b in common[index + 1:]
    )


def screen_order_has_reversal(screen_order: dict) -> bool:
    return pair_order_reversed(screen_order.get("start"), screen_order.get("middle")) or pair_order_reversed(
        screen_order.get("middle"), screen_order.get("end")
    ) or pair_order_reversed(screen_order.get("start"), screen_order.get("end"))


def record_action_claims_side_change(record: dict) -> bool:
    action_texts = [str(record.get("visible_action") or "")]
    for character in record.get("visible_characters") or []:
        if isinstance(character, dict):
            action_texts.append(str(character.get("character_action") or ""))
    for text in action_texts:
        compact = re.sub(r"\s+", "", text)
        left_index = min((compact.find(token) for token in ("画面左", "左后方", "左侧") if token in compact), default=-1)
        right_index = min((compact.find(token) for token in ("画面右", "右后方", "右侧") if token in compact), default=-1)
        if left_index >= 0 and right_index >= 0 and ("→" in compact or "经过" in compact or "换到" in compact):
            return True
    return False


def normalized_identity(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value or "")).lower()


def identity_matches(left: object, right: object) -> bool:
    left_value = normalized_identity(left)
    right_value = normalized_identity(right)
    return bool(left_value and right_value and (left_value in right_value or right_value in left_value))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a compact full-episode evidence timeline.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--boundaries-file", type=Path)
    parser.add_argument("--range-start", type=float, default=0.0)
    parser.add_argument("--range-end", type=float)
    parser.add_argument("--tolerance", type=float, default=0.1)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    contract_version = data.get("prompt_contract_version")
    if contract_version not in {PROMPT_CONTRACT_VERSION, *LEGACY_PROMPT_CONTRACT_VERSIONS}:
        errors: list[str] = [f"prompt_contract_version must be {PROMPT_CONTRACT_VERSION}"]
    else:
        errors = []
    soft_spatial_warnings: list[str] = []
    require_person_visual_state = contract_version in {PROMPT_CONTRACT_VERSION, "3.1-person-trajectory-evidence", "2.1-screen-axis-evidence", "1.9-pairwise-blocking", "1.8-spatial-focus-separation"}
    require_pairwise_blocking = contract_version in {PROMPT_CONTRACT_VERSION, "3.1-person-trajectory-evidence", "2.1-screen-axis-evidence", "1.9-pairwise-blocking"}
    require_screen_relative_orientation = contract_version in {PROMPT_CONTRACT_VERSION, "3.1-person-trajectory-evidence", "2.1-screen-axis-evidence"}
    require_locked_intervals = contract_version in {PROMPT_CONTRACT_VERSION, "3.1-person-trajectory-evidence"}
    records = data.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records must be a non-empty array")
        records = []

    range_end = args.duration if args.range_end is None else args.range_end
    boundary_contract = data.get("boundary_contract") if isinstance(data.get("boundary_contract"), dict) else None
    locked_candidates: set[float] = set()
    merged_false_candidates: set[float] = set()
    if args.boundaries_file:
        boundary_data = json.loads(args.boundaries_file.read_text(encoding="utf-8-sig"))
        expected_contract = build_boundary_contract(boundary_data, args.range_start, range_end)
        if require_locked_intervals:
            if boundary_contract != expected_contract:
                errors.append("boundary_contract does not match the local boundary file and range")
            boundary_contract = expected_contract
            locked_candidates = {
                round(float(item["seconds"]), 3)
                for item in expected_contract.get("candidates") or []
                if item.get("tier") == "locked"
            }
        candidates = [float(value) for value in (boundary_data.get("boundaries") or []) if args.range_start + 0.05 < float(value) < range_end - 0.05]
        audit = data.get("boundary_audit")
        if not isinstance(audit, list):
            errors.append("boundary_audit must be an array when boundary candidates are supplied")
            audit = []
        audited_candidates: list[float] = []
        kept_observations: list[float] = []
        kept_subjects: list[tuple[float, str, str]] = []
        for audit_index, item in enumerate(audit, 1):
            if not isinstance(item, dict):
                errors.append(f"boundary_audit {audit_index}: must be an object")
                continue
            try:
                candidate = float(item.get("candidate_seconds"))
                observed = float(item.get("observed_seconds"))
            except (TypeError, ValueError):
                errors.append(f"boundary_audit {audit_index}: invalid numeric time")
                continue
            decision = item.get("decision")
            if decision not in {"keep_cut", "keep_reframe", "merge_false"}:
                errors.append(f"boundary_audit {audit_index}: invalid decision")
            if require_locked_intervals and round(candidate, 3) in locked_candidates:
                if decision in {"keep_cut", "keep_reframe"} and abs(observed - candidate) > args.tolerance:
                    errors.append(f"boundary_audit {audit_index}: locked candidate time cannot move")
            if decision == "merge_false":
                merged_false_candidates.add(round(candidate, 3))
            if not str(item.get("reason") or "").strip():
                errors.append(f"boundary_audit {audit_index}: reason is required")
            before_subject = str(item.get("before_visible_subject") or "").strip()
            after_subject = str(item.get("after_visible_subject") or "").strip()
            same_shot_evidence = item.get("same_shot_evidence")
            if not before_subject or not after_subject:
                errors.append(f"boundary_audit {audit_index}: before_visible_subject and after_visible_subject are required")
            if not isinstance(same_shot_evidence, bool):
                errors.append(f"boundary_audit {audit_index}: same_shot_evidence must be boolean")
            if decision == "merge_false":
                if same_shot_evidence is not True:
                    errors.append(f"boundary_audit {audit_index}: merge_false requires same_shot_evidence=true")
                if before_subject and after_subject and not identity_matches(before_subject, after_subject):
                    errors.append(f"boundary_audit {audit_index}: merge_false cannot join different visible subjects")
            audited_candidates.append(candidate)
            if decision in {"keep_cut", "keep_reframe"}:
                kept_observations.append(observed)
                kept_subjects.append((observed, before_subject, after_subject))
        for candidate in candidates:
            matches = [value for value in audited_candidates if abs(value - candidate) <= 0.02]
            if len(matches) != 1:
                errors.append(f"candidate {candidate:.3f}: expected exactly one boundary audit, got {len(matches)}")
        record_boundaries = [float(record.get("start_seconds", -999)) for record in records[1:]]
        for observed in kept_observations:
            if not any(abs(boundary - observed) <= 0.15 for boundary in record_boundaries):
                errors.append(f"kept boundary {observed:.3f}: no record boundary within 0.15s")
        for observed, before_subject, after_subject in kept_subjects:
            boundary_index = next((index for index, boundary in enumerate(record_boundaries, 1) if abs(boundary - observed) <= 0.15), None)
            if boundary_index is None:
                continue
            previous_subject = str(records[boundary_index - 1].get("primary_visible_subject") or "").strip()
            next_subject = str(records[boundary_index].get("primary_visible_subject") or "").strip()
            if before_subject and previous_subject and not identity_matches(before_subject, previous_subject):
                errors.append(f"kept boundary {observed:.3f}: before_visible_subject disagrees with previous record")
            if after_subject and next_subject and not identity_matches(after_subject, next_subject):
                errors.append(f"kept boundary {observed:.3f}: after_visible_subject disagrees with next record")

    previous_end = args.range_start
    previous_dialogue = ""
    previous_utterance: dict | None = None
    seen: set[str] = set()
    locked_intervals = {
        str(item.get("interval_id")): item
        for item in (boundary_contract or {}).get("locked_intervals") or []
        if isinstance(item, dict)
    }
    evidence_intervals = {
        str(item.get("evidence_interval_id")): item
        for item in (boundary_contract or {}).get("evidence_intervals") or []
        if isinstance(item, dict)
    }
    dialogue_events = data.get("dialogue_events")
    dialogue_event_by_id: dict[str, dict] = {}
    require_delivery = (data.get("dialogue_injection_contract") or {}).get("version") == "2.4-dialogue-injection-delivery-locked"
    if require_locked_intervals:
        if not isinstance(dialogue_events, list):
            errors.append("dialogue_events must be an array")
            dialogue_events = []
        for event_index, event in enumerate(dialogue_events, 1):
            if not isinstance(event, dict):
                errors.append(f"dialogue event {event_index}: must be an object")
                continue
            dialogue_id = str(event.get("dialogue_id") or "").strip()
            if not dialogue_id or dialogue_id in dialogue_event_by_id:
                errors.append(f"dialogue event {event_index}: dialogue_id is empty or duplicated")
                continue
            if not str(event.get("speaker") or "").strip() or not str(event.get("text") or "").strip():
                errors.append(f"dialogue event {dialogue_id}: speaker and text are required")
            delivery = event.get("delivery")
            if require_delivery and not isinstance(delivery, dict):
                errors.append(f"dialogue event {dialogue_id}: locked delivery is required")
            elif isinstance(delivery, dict):
                missing_delivery = sorted(DELIVERY_FIELDS - set(delivery))
                if missing_delivery:
                    errors.append(f"dialogue event {dialogue_id}: delivery missing {', '.join(missing_delivery)}")
                if delivery.get("speech_rate") not in ALLOWED_SPEECH_RATE:
                    errors.append(f"dialogue event {dialogue_id}: invalid delivery speech_rate")
            try:
                event_start = float(event.get("start_seconds"))
                event_end = float(event.get("end_seconds"))
                if event_end <= event_start:
                    errors.append(f"dialogue event {dialogue_id}: invalid range")
            except (TypeError, ValueError):
                errors.append(f"dialogue event {dialogue_id}: invalid numeric time")
            dialogue_event_by_id[dialogue_id] = event
    for index, record in enumerate(records, 1):
        label = f"record {index}"
        missing = sorted(REQUIRED - set(record))
        if missing:
            errors.append(f"{label}: missing {', '.join(missing)}")
        if contract_version == PROMPT_CONTRACT_VERSION:
            time_of_day = str(record.get("time_of_day") or "").strip()
            if time_of_day not in ALLOWED_TIME_OF_DAY:
                errors.append(f"{label}: invalid time_of_day {time_of_day!r}")
            if not str(record.get("time_of_day_evidence") or "").strip():
                errors.append(f"{label}: time_of_day_evidence is required")
            if "fixed_scene_evidence" not in record:
                errors.append(f"{label}: fixed_scene_evidence is required")
            generation_facts = record.get("generation_facts")
            required_generation_fields = {
                "subject_lighting",
                "contrast_exposure",
                "depth_of_field",
                "focus_transition",
                "composition_change",
                "dynamic_environment",
            }
            if not isinstance(generation_facts, dict):
                errors.append(f"{label}: generation_facts must be an object")
            else:
                missing_generation = sorted(required_generation_fields - set(generation_facts))
                if missing_generation:
                    errors.append(f"{label}: generation_facts missing {', '.join(missing_generation)}")
                if generation_facts.get("depth_of_field") not in {"shallow", "deep", "rack_focus", "unclear"}:
                    errors.append(f"{label}: invalid generation_facts.depth_of_field")
                for generation_field in required_generation_fields - {"depth_of_field"}:
                    if not str(generation_facts.get(generation_field) or "").strip():
                        errors.append(f"{label}: generation_facts.{generation_field} is required")
                forbidden_generation_terms = (
                    "西装", "礼服", "马甲", "T恤", "衬衫", "夹克", "外套", "裙", "制服", "配饰", "胸针", "项链",
                    "墙面", "地面", "家具", "大理石", "装修", "陈设", "沙发", "桌椅",
                )
                generation_blob = " ".join(str(generation_facts.get(field) or "") for field in required_generation_fields)
                if any(term in generation_blob for term in forbidden_generation_terms):
                    errors.append(f"{label}: generation_facts contains asset-owned appearance or fixed-scene detail")
                subject_light = str(generation_facts.get("subject_lighting") or "")
                if any(term in subject_light for term in STATIC_LIGHT_TERMS) and not any(
                    marker in subject_light for marker in DYNAMIC_LIGHT_MARKERS
                ):
                    errors.append(f"{label}: generation_facts.subject_lighting contains static environmental light")
                dynamic_environment = str(generation_facts.get("dynamic_environment") or "")
                if any(term in dynamic_environment for term in STATIC_LIGHT_TERMS) and not any(
                    marker in dynamic_environment for marker in DYNAMIC_LIGHT_MARKERS
                ):
                    errors.append(f"{label}: generation_facts.dynamic_environment contains non-narrative static light")
            if str(record.get("lighting_composition") or "").strip():
                errors.append(f"{label}: legacy lighting_composition must be empty under the current contract")
        record_id = str(record.get("id", ""))
        if not record_id or record_id in seen:
            errors.append(f"{label}: id is empty or duplicated")
        seen.add(record_id)
        try:
            start = float(record.get("start_seconds"))
            end = float(record.get("end_seconds"))
        except (TypeError, ValueError):
            errors.append(f"{label}: invalid numeric time")
            continue
        if start < -args.tolerance or end <= start:
            errors.append(f"{label}: invalid range {start}-{end}")
        if require_locked_intervals:
            interval_id = str(record.get("interval_id") or "").strip()
            interval = locked_intervals.get(interval_id)
            if not interval and "_" in interval_id:
                component_ids = [item for item in interval_id.split("_") if item]
                component_intervals = [locked_intervals.get(item) for item in component_ids]
                if component_ids and all(component_intervals):
                    component_starts = [float(item["start_seconds"]) for item in component_intervals]
                    component_ends = [float(item["end_seconds"]) for item in component_intervals]
                    contiguous = all(
                        abs(component_ends[index] - component_starts[index + 1]) <= args.tolerance
                        for index in range(len(component_intervals) - 1)
                    )
                    internal_edges = component_ends[:-1]
                    if contiguous and all(edge in merged_false_candidates for edge in internal_edges):
                        interval = {
                            "start_seconds": component_starts[0],
                            "end_seconds": component_ends[-1],
                        }
            if not interval:
                errors.append(f"{label}: interval_id is missing or absent from boundary_contract")
            else:
                interval_start = float(interval["start_seconds"])
                interval_end = float(interval["end_seconds"])
                crossed_locked_edges = [
                    candidate
                    for candidate in locked_candidates
                    if start + args.tolerance < candidate < end - args.tolerance
                ]
                unresolved_crossings = [
                    candidate for candidate in crossed_locked_edges if candidate not in merged_false_candidates
                ]
                if unresolved_crossings:
                    errors.append(
                        f"{label}: record crosses kept locked boundaries {unresolved_crossings}"
                    )
                for anchor_field in ("start_anchor_subject", "middle_anchor_subject", "end_anchor_subject"):
                    if not str(record.get(anchor_field) or "").strip():
                        errors.append(f"{label}: {anchor_field} is required")
                anchor_times = record.get("anchor_evidence_timestamps")
                if not isinstance(anchor_times, list) or len(anchor_times) != 3:
                    errors.append(f"{label}: anchor_evidence_timestamps must contain exactly three times")
                else:
                    try:
                        numeric_anchors = [float(value) for value in anchor_times]
                        if any(value < interval_start - args.tolerance or value > interval_end + args.tolerance for value in numeric_anchors):
                            errors.append(f"{label}: anchor evidence falls outside the locked parent interval")
                    except (TypeError, ValueError):
                        errors.append(f"{label}: invalid anchor evidence time")
            evidence_interval_ids = record.get("evidence_interval_ids")
            if not isinstance(evidence_interval_ids, list) or not evidence_interval_ids:
                errors.append(f"{label}: evidence_interval_ids must be a non-empty array")
            else:
                for evidence_interval_id in evidence_interval_ids:
                    if str(evidence_interval_id) not in evidence_intervals:
                        errors.append(f"{label}: unknown evidence_interval_id {evidence_interval_id}")
        if start < previous_end - args.tolerance:
            errors.append(f"{label}: overlap before {start}")
        if start > previous_end + args.tolerance:
            errors.append(f"{label}: gap of {start - previous_end:.3f}s")
        if end > args.duration + args.tolerance:
            errors.append(f"{label}: end exceeds duration")
        if record.get("confidence") not in {"high", "medium", "low"}:
            errors.append(f"{label}: invalid confidence")
        if record.get("camera_view") not in {"1 俯瞰/俯视", "2 正视", "3 侧视", "4 反打", "待确认"}:
            errors.append(f"{label}: invalid camera_view")
        primary_visible_subject = str(record.get("primary_visible_subject") or "").strip()
        if not primary_visible_subject:
            errors.append(f"{label}: primary_visible_subject is required")
        visible_characters = record.get("visible_characters")
        if not isinstance(visible_characters, list):
            errors.append(f"{label}: visible_characters must be an array")
            visible_characters = []
        visible_identities: list[str] = []
        for character_index, character in enumerate(visible_characters, 1):
            character_label = f"{label}/visible character {character_index}"
            if not isinstance(character, dict):
                errors.append(f"{character_label}: must be an object")
                continue
            identity = str(character.get("identity") or "").strip()
            appearance = str(character.get("appearance") or "").strip()
            screen_position = str(character.get("screen_position") or "").strip()
            mouth_state = character.get("mouth_state")
            if not identity or not appearance or not screen_position:
                errors.append(f"{character_label}: identity, appearance and screen_position are required")
            if any(term in identity for term in NON_HUMAN_VISIBLE_IDENTITY_TERMS):
                errors.append(f"{character_label}: visible_characters identity describes a scene or object, not a person")
            if mouth_state not in {"speaking", "not_speaking", "unclear"}:
                errors.append(f"{character_label}: invalid mouth_state")
            if require_person_visual_state:
                required_character_fields = (
                    "body_posture",
                    "body_orientation",
                    "support_contact",
                    "visibility_scope",
                    "depth_layer",
                    "relative_camera_distance",
                    "frame_occupancy",
                    "frame_crop",
                    "occlusion_relation",
                    "depth_evidence",
                    "focus_state",
                    "focus_evidence",
                    "gaze_direction",
                    "facial_expression",
                    "character_action",
                )
                if require_screen_relative_orientation:
                    required_character_fields += ("torso_orientation", "head_orientation", "gaze_target")
                if contract_version == PROMPT_CONTRACT_VERSION:
                    required_character_fields += (
                        "mouth_visual_action",
                        "speech_sync_status",
                        "mouth_action_evidence",
                    )
                for field in required_character_fields:
                    if not str(character.get(field) or "").strip():
                        errors.append(f"{character_label}: {field} is required")
                if (
                    contract_version == PROMPT_CONTRACT_VERSION
                    and character.get("speech_sync_status") not in ALLOWED_SPEECH_SYNC_STATUS
                ):
                    errors.append(f"{character_label}: invalid speech_sync_status")
                if character.get("body_posture") not in {"standing", "sitting", "walking", "kneeling", "crouching", "lying", "leaning", "unclear"}:
                    errors.append(f"{character_label}: invalid body_posture")
                if character.get("visibility_scope") not in {"全身", "半身", "胸像", "局部", "背景虚焦"}:
                    errors.append(f"{character_label}: invalid visibility_scope")
                if character.get("depth_layer") not in {"前景", "中景", "背景", "unclear"}:
                    errors.append(f"{character_label}: invalid depth_layer")
                if character.get("focus_state") not in {"sharp", "slightly_soft", "heavily_defocused", "unclear"}:
                    errors.append(f"{character_label}: invalid focus_state")
                if character.get("relative_camera_distance") not in {"closer_than_focus", "same_plane", "farther_than_focus", "unclear"}:
                    errors.append(f"{character_label}: invalid relative_camera_distance")
                if character.get("frame_occupancy") not in {"dominant", "large", "medium", "small", "tiny"}:
                    errors.append(f"{character_label}: invalid frame_occupancy")
                if require_screen_relative_orientation:
                    orientation_blob = " ".join(str(character.get(field) or "") for field in ("torso_orientation", "head_orientation", "gaze_direction"))
                    if re.search(r"(?<!画面)(?<!frame_)左|(?<!画面)(?<!frame_)右", orientation_blob):
                        errors.append(f"{character_label}: left/right orientation must use explicit screen coordinates")
                if character.get("relative_camera_distance") == "closer_than_focus" and character.get("depth_layer") == "背景":
                    errors.append(f"{character_label}: closer_than_focus cannot be background")
                if character.get("relative_camera_distance") == "farther_than_focus" and character.get("depth_layer") == "前景":
                    errors.append(f"{character_label}: farther_than_focus cannot be foreground")
                focus_evidence = str(character.get("focus_evidence") or "")
                forbidden_spatial_terms = ("位于", "前景", "中景", "后景", "后方", "侧后", "距离", "更近", "更远")
                if any(term in focus_evidence for term in forbidden_spatial_terms):
                    errors.append(f"{character_label}: focus_evidence contains spatial-placement language")
            if identity:
                visible_identities.append(identity)
        if require_person_visual_state:
            edge_audit = record.get("edge_character_audit")
            if not isinstance(edge_audit, dict):
                errors.append(f"{label}: edge_character_audit must be an object")
            else:
                edge_status = edge_audit.get("status")
                edge_observations = edge_audit.get("observations")
                if edge_status not in {"present", "none", "uncertain"}:
                    errors.append(f"{label}: invalid edge_character_audit status")
                if not isinstance(edge_observations, list):
                    errors.append(f"{label}: edge_character_audit observations must be an array")
                else:
                    if edge_status == "present" and not edge_observations:
                        errors.append(f"{label}: present edge_character_audit needs observations")
                    for edge_index, observation in enumerate(edge_observations, 1):
                        edge_label = f"{label}/edge observation {edge_index}"
                        if not isinstance(observation, dict):
                            errors.append(f"{edge_label}: must be an object")
                            continue
                        if observation.get("edge") not in {"left", "right", "top", "bottom"}:
                            errors.append(f"{edge_label}: invalid edge")
                        edge_identity = str(observation.get("identity") or "").strip()
                        if not edge_identity or not str(observation.get("visible_fragment") or "").strip() or not str(observation.get("screen_position") or "").strip():
                            errors.append(f"{edge_label}: identity, visible_fragment and screen_position are required")
                        elif not any(identity_matches(edge_identity, identity) for identity in visible_identities):
                            errors.append(f"{edge_label}: edge identity is absent from visible_characters")
        if require_pairwise_blocking:
            relations = record.get("relative_blocking")
            if not isinstance(relations, list):
                errors.append(f"{label}: relative_blocking must be an array")
                relations = []
            expected_pairs = len(visible_identities) * (len(visible_identities) - 1) // 2
            seen_pairs: set[tuple[str, str]] = set()
            for relation_index, relation in enumerate(relations, 1):
                relation_label = f"{label}/relative blocking {relation_index}"
                if not isinstance(relation, dict):
                    errors.append(f"{relation_label}: must be an object")
                    continue
                subject = str(relation.get("subject") or "").strip()
                relative_to = str(relation.get("relative_to") or "").strip()
                evidence = str(relation.get("evidence") or "").strip()
                if not subject or not relative_to or not evidence:
                    errors.append(f"{relation_label}: subject, relative_to and evidence are required")
                    continue
                if identity_matches(subject, relative_to):
                    errors.append(f"{relation_label}: subject and relative_to must be different people")
                if not any(identity_matches(subject, identity) for identity in visible_identities):
                    errors.append(f"{relation_label}: subject is absent from visible_characters")
                if not any(identity_matches(relative_to, identity) for identity in visible_identities):
                    errors.append(f"{relation_label}: relative_to is absent from visible_characters")
                pair = tuple(sorted((normalized_identity(subject), normalized_identity(relative_to))))
                if pair in seen_pairs:
                    errors.append(f"{relation_label}: duplicate or reverse-duplicate person pair")
                seen_pairs.add(pair)
                horizontal = relation.get("horizontal_relation")
                depth = relation.get("depth_relation")
                occlusion = relation.get("occlusion")
                if horizontal not in {"left_of", "right_of", "overlapping", "unclear"}:
                    errors.append(f"{relation_label}: invalid horizontal_relation")
                if depth not in {"in_front_of", "behind", "same_plane", "unclear"}:
                    errors.append(f"{relation_label}: invalid depth_relation")
                if occlusion not in {"blocks", "blocked_by", "none", "unclear"}:
                    errors.append(f"{relation_label}: invalid occlusion")
                if require_screen_relative_orientation and relation.get("facing_relationship") not in {"face_to_face", "same_direction", "back_to_back", "crossing", "unclear"}:
                    errors.append(f"{relation_label}: invalid facing_relationship")
                if occlusion == "blocks" and depth == "behind":
                    soft_spatial_warnings.append(f"{relation_label}: a blocking subject is marked behind relative_to; preserve observation for review")
                if occlusion == "blocked_by" and depth == "in_front_of":
                    soft_spatial_warnings.append(f"{relation_label}: a blocked subject is marked in front of relative_to; preserve observation for review")
            if len(relations) != expected_pairs:
                errors.append(f"{label}: relative_blocking needs {expected_pairs} unique pairs, got {len(relations)}")
        if require_person_visual_state:
            sharp_layers = {
                str(character.get("depth_layer") or "")
                for character in visible_characters
                if isinstance(character, dict)
                and character.get("focus_state") == "sharp"
                and character.get("depth_layer") in {"前景", "中景", "背景"}
            }
            composition = str(record.get("lighting_composition") or "").lower()
            structured_depth = str((record.get("generation_facts") or {}).get("depth_of_field") or "").strip()
            if (
                len(sharp_layers) > 1
                and structured_depth != "deep"
                and not any(marker in composition for marker in ("深焦", "大景深", "deep focus"))
            ):
                errors.append(f"{label}: sharp characters span multiple depth layers without explicit deep-focus evidence")
        utterances = record.get("dialogue_utterances")
        if not isinstance(utterances, list):
            errors.append(f"{label}: dialogue_utterances must be an array")
            utterances = []
        record_event_ids = record.get("dialogue_event_ids")
        if require_locked_intervals and not isinstance(record_event_ids, list):
            errors.append(f"{label}: dialogue_event_ids must be an array")
            record_event_ids = []
        record_event_ids = [str(value) for value in (record_event_ids or [])]
        utterance_texts: list[str] = []
        utterance_previous = start
        for utterance_index, utterance in enumerate(utterances, 1):
            utterance_label = f"{label}/utterance {utterance_index}"
            text = str(utterance.get("text") or "").strip() if isinstance(utterance, dict) else ""
            speaker = str(utterance.get("speaker") or "").strip() if isinstance(utterance, dict) else ""
            basis = utterance.get("basis") if isinstance(utterance, dict) else None
            speaker_visibility = utterance.get("speaker_visibility") if isinstance(utterance, dict) else None
            dialogue_id = str(utterance.get("dialogue_id") or "").strip() if isinstance(utterance, dict) else ""
            try:
                utterance_start = float(utterance.get("start_seconds"))
                utterance_end = float(utterance.get("end_seconds"))
            except (AttributeError, TypeError, ValueError):
                errors.append(f"{utterance_label}: invalid numeric time")
                continue
            if not text or not speaker:
                errors.append(f"{utterance_label}: text and speaker are required")
            if basis not in {"audio", "burned_subtitle", "both", "dialogue_injection"}:
                errors.append(f"{utterance_label}: invalid basis")
            if speaker_visibility not in {"on_screen", "off_screen", "unclear"}:
                errors.append(f"{utterance_label}: invalid speaker_visibility")
            if require_locked_intervals:
                event = dialogue_event_by_id.get(dialogue_id)
                if not dialogue_id or event is None:
                    errors.append(f"{utterance_label}: dialogue_id is missing or absent from dialogue_events")
                else:
                    if dialogue_id not in record_event_ids:
                        errors.append(f"{utterance_label}: dialogue_id is absent from record dialogue_event_ids")
                    if normalized_dialogue_text(event.get("text")) != normalized_dialogue_text(text):
                        errors.append(f"{utterance_label}: text disagrees with dialogue event {dialogue_id}")
                    if normalized_identity(event.get("speaker")) != normalized_identity(speaker):
                        errors.append(f"{utterance_label}: speaker disagrees with dialogue event {dialogue_id}")
                if (
                    previous_utterance
                    and normalized_dialogue_text(previous_utterance.get("text")) == normalized_dialogue_text(text)
                    and normalized_identity(previous_utterance.get("speaker")) != normalized_identity(speaker)
                    and utterance_start <= float(previous_utterance.get("end_seconds", 0.0)) + 0.15
                    and not str(utterance.get("speaker_change_evidence") or "").strip()
                ):
                    errors.append(f"{utterance_label}: repeated adjacent text changes speaker without evidence")
            if speaker_visibility == "on_screen" and not any(identity_matches(speaker, identity) for identity in visible_identities):
                # A locked dialogue ledger intentionally keeps an unlisted minor
                # character as ``unclear``.  The visual pass may still describe
                # that person (for example, "助理-西装眼镜") without inventing a
                # stable asset identity.  Treat a uniquely visible speaking
                # mouth as structurally consistent, while preserving the
                # ledger's unresolved speaker instead of assigning a new name.
                unresolved_speaker = normalized_identity(speaker) in {"unclear", "未知", "不明"}
                visible_speakers = [
                    character
                    for character in visible_characters
                    if isinstance(character, dict) and character.get("mouth_state") == "speaking"
                ]
                if not (unresolved_speaker and len(visible_speakers) == 1):
                    errors.append(f"{utterance_label}: on-screen speaker is absent from visible_characters")
            if utterance_start < start - args.tolerance or utterance_end > end + args.tolerance or utterance_end <= utterance_start:
                errors.append(f"{utterance_label}: outside parent range")
            if utterance_start < utterance_previous - args.tolerance:
                errors.append(f"{utterance_label}: utterances are not chronological")
            utterance_previous = utterance_end
            utterance_texts.append(text)
            previous_utterance = utterance
        chinese_dialogue = str(record.get("chinese_dialogue") or "").strip()
        normalized_dialogue = re.sub(r"[\s，。！？、；…,.!?]", "", chinese_dialogue)
        for utterance_text in utterance_texts:
            normalized_utterance = re.sub(r"[\s，。！？、；…,.!?]", "", utterance_text)
            if normalized_utterance and normalized_utterance not in normalized_dialogue:
                errors.append(f"{label}: utterance missing from chinese_dialogue: {utterance_text}")
        subtitle_matches = re.findall(r"(?:台词字幕|剧情字幕|字幕)[:：]\s*([^\r\n；|]+)", str(record.get("on_screen_text") or ""))
        for subtitle_raw in subtitle_matches:
            subtitle = re.sub(r"[\s，。！？、；…,.!?]", "", subtitle_raw)
            joined_utterances = re.sub(r"[\s，。！？、；…,.!?]", "", "".join(utterance_texts))
            subtitle_coverage = SequenceMatcher(None, subtitle, joined_utterances).ratio() if joined_utterances else 0.0
            continued_from_previous = subtitle in previous_dialogue and (
                "延续" in str(record.get("sound") or "")
                or (joined_utterances and joined_utterances in subtitle)
            )
            if subtitle and subtitle not in joined_utterances and subtitle_coverage < 0.82 and not continued_from_previous:
                errors.append(f"{label}: dialogue subtitle missing from dialogue_utterances: {subtitle_raw.strip()}")
        previous_dialogue = normalized_dialogue
        previous_end = end

    if records and abs(previous_end - range_end) > args.tolerance:
        errors.append(f"final end {previous_end:.3f} differs from range end {range_end:.3f}")

    lightweight_warnings = [*collect_lightweight_warnings(records), *soft_spatial_warnings]
    report = {
        "valid": not errors,
        "records": len(records),
        "errors": errors,
        "warnings": lightweight_warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

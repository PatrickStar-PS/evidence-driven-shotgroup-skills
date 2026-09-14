#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from timeline_contract import ensure_dialogue_contract, interval_for_time


VALID_VISIBILITY_SCOPES = {"\u5168\u8eab", "\u534a\u8eab", "\u80f8\u50cf", "\u5c40\u90e8", "\u80cc\u666f\u865a\u7126"}
VALID_DEPTH_LAYERS = {"前景", "中景", "背景", "unclear"}
ASSET_OWNED_GENERATION_TERMS = (
    "西装", "礼服", "马甲", "T恤", "衬衫", "夹克", "外套", "裙", "制服", "配饰", "胸针", "项链",
    "墙面", "地面", "家具", "灯具", "吊灯", "灯带", "霓虹", "氛围灯", "顶光", "背景灯",
    "大理石", "装修", "陈设", "沙发", "桌椅",
)
STATIC_LIGHT_COLOUR_TERMS = ("蓝色", "红色", "紫色", "彩色", "蓝光", "红光", "霓虹色")
DYNAMIC_LIGHT_MARKERS = (
    "开启", "打开", "亮起", "熄灭", "关闭", "闪烁", "闪动", "警灯", "扫过", "掠过",
    "照到脸", "照在脸", "屏幕光", "车灯", "由暗变亮", "由亮变暗",
    "turn on", "turn off", "flicker", "flash", "sweep", "screen light", "headlight",
)


def normalize_visibility_scope(value: object) -> str:
    text = str(value or "").strip()
    if text in VALID_VISIBILITY_SCOPES:
        return text
    if "\u80cc\u666f" in text and any(term in text for term in ("\u865a\u7126", "\u6a21\u7cca", "\u865a\u5316")):
        return "\u80cc\u666f\u865a\u7126"
    if "\u5168\u8eab" in text:
        return "\u5168\u8eab"
    if "\u534a\u8eab" in text:
        return "\u534a\u8eab"
    if any(term in text for term in ("三四分身", "四分之三身", "3/4身", "三分之二身")):
        return "\u534a\u8eab"
    if "\u80f8\u50cf" in text or "\u80f8\u90e8" in text:
        return "\u80f8\u50cf"
    if any(term in text for term in ("\u5c40\u90e8", "\u80a9\u90e8", "\u5934\u90e8", "\u80cc\u5f71", "\u4fa7\u9762")):
        return "\u5c40\u90e8"
    return text


def normalize_depth_layer(value: object) -> str:
    """Normalize only the enum shape; do not choose between multiple claimed layers."""
    text = str(value or "").strip()
    if text in VALID_DEPTH_LAYERS:
        return text
    claimed = [layer for layer in ("前景", "中景", "背景") if layer in text]
    if len(claimed) == 1:
        return claimed[0]
    return "unclear"


def normalize_screen_axis(value: object) -> str:
    text = str(value or "").strip()
    if not text or text == "unclear":
        return text
    text = re.sub(r"(?<!\u753b\u9762)\u5de6", "\u753b\u9762\u5de6", text)
    text = re.sub(r"(?<!\u753b\u9762)\u53f3", "\u753b\u9762\u53f3", text)
    return text


def sanitize_generation_fact(value: object, field: str) -> str:
    """Drop asset-owned details and static environmental-light clauses."""
    text = str(value or "").strip()
    if not text:
        return text
    clauses = [item.strip() for item in re.split(r"[，；。]", text) if item.strip()]
    retained: list[str] = []
    for clause in clauses:
        dynamic_light = any(marker.lower() in clause.lower() for marker in DYNAMIC_LIGHT_MARKERS)
        has_asset_detail = any(term in clause for term in ASSET_OWNED_GENERATION_TERMS)
        has_static_colour = any(term in clause for term in STATIC_LIGHT_COLOUR_TERMS)
        if has_asset_detail and not (field == "dynamic_environment" and dynamic_light):
            continue
        if field in {"subject_lighting", "light_direction_color", "contrast_exposure"} and has_static_colour and not dynamic_light:
            continue
        if field == "dynamic_environment" and (has_asset_detail or has_static_colour) and not dynamic_light:
            continue
        retained.append(clause)
    if retained:
        return "，".join(retained)
    return "无" if field == "dynamic_environment" else "unclear"


def primary(record: dict) -> str:
    return str(record.get("primary_visible_subject") or "").strip()


def normalized_identity(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value or "")).lower()


def identity_matches(left: object, right: object) -> bool:
    left_value = normalized_identity(left)
    right_value = normalized_identity(right)
    return bool(left_value and right_value and (left_value in right_value or right_value in left_value))


def subtitle_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"^(?:剧情字幕|台词字幕|字幕)[:：]\s*", "", text)
    return re.sub(r"[\s，。！？、；“”‘’,.!?]", "", text)


def strip_quoted_dialogue_from_action(value: object) -> str:
    """Keep the visible action while removing dialogue text owned by the locked ledger."""
    text = str(value or "").strip()
    text = re.sub(r"[：:]?[“\"][^”\"]*[”\"]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:")
    text = re.sub(r"喊出[。.]?$", "开口喊话", text)
    return text


def contains_positive_speech_claim(value: object) -> bool:
    text = str(value or "").lower()
    for negated in (
        "不说话", "未说话", "没有说话", "并未说话", "并不说话", "未开口", "没有开口",
        "无锁定发言依据", "not speaking", "not_speaking",
    ):
        text = text.replace(negated, "")
    return any(marker in text for marker in ("说话", "讲话", "开口说", "开口讲", "配合台词", "念出台词", "说出", "speaking", "speaks"))


def strip_reaction_speech_claims(value: object) -> str:
    """Remove only speech ownership claims while retaining visible reaction motion."""
    text = strip_quoted_dialogue_from_action(value)
    text = re.sub(r"开口(?:说话|讲话|发言)", "", text)
    text = re.sub(r"(?:严肃|持续|继续|正在)?说话", "", text)
    text = re.sub(r"(?:讲|强调)规矩", "作强调手势", text)
    text = re.sub(r"说出[^，；。→]*", "", text)
    text = re.sub(r"配合台词|念出台词", "", text)
    text = re.sub(r"[，；]{2,}", "，", text)
    text = re.sub(r"(?:→\s*){2,}", "→", text)
    return text.strip(" ，；。→")


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize compact relay labels without reinterpreting video semantics.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    records = data.get("records") or []
    fixes: list[str] = []
    locked_dialogue_events = None
    if (data.get("dialogue_injection_contract") or {}).get("version") in {"2.3-dialogue-injection-locked", "2.4-dialogue-injection-delivery-locked"}:
        locked_dialogue_events = json.loads(json.dumps(data.get("dialogue_events") or [], ensure_ascii=False))

    previous_dialogue = ""
    previous_utterance_texts: list[str] = []
    for index, record in enumerate(records, 1):
        generation_facts = record.get("generation_facts")
        if isinstance(generation_facts, dict):
            if "subject_lighting" not in generation_facts and "light_direction_color" in generation_facts:
                generation_facts["subject_lighting"] = generation_facts.pop("light_direction_color")
                fixes.append(f"record {index}: migrated generation_facts.light_direction_color to subject_lighting")
            for generation_field in (
                "subject_lighting",
                "contrast_exposure",
                "focus_transition",
                "composition_change",
                "dynamic_environment",
            ):
                current_generation = str(generation_facts.get(generation_field) or "").strip()
                normalized_generation = sanitize_generation_fact(current_generation, generation_field)
                if normalized_generation != current_generation:
                    generation_facts[generation_field] = normalized_generation
                    fixes.append(f"record {index}: removed asset-owned clause from generation_facts.{generation_field}")
        camera_view = str(record.get("camera_view") or "").strip()
        camera_view_aliases = {
            "俯瞰": "1 俯瞰/俯视",
            "俯视": "1 俯瞰/俯视",
            "俯瞰/俯视": "1 俯瞰/俯视",
            "正视": "2 正视",
            "侧视": "3 侧视",
            "反打": "4 反打",
        }
        if camera_view in camera_view_aliases:
            record["camera_view"] = camera_view_aliases[camera_view]
            fixes.append(f"record {index}: normalized camera_view label")
        visibility_scope_aliases = {
            "局部背影": "局部",
            "局部虚焦": "局部",
            "特写": "胸像",
        }
        for character_index, character in enumerate(record.get("visible_characters") or [], 1):
            scope = str(character.get("visibility_scope") or "").strip() if isinstance(character, dict) else ""
            if scope in visibility_scope_aliases:
                character["visibility_scope"] = visibility_scope_aliases[scope]
                fixes.append(f"record {index}/visible character {character_index}: normalized visibility_scope label")
            elif isinstance(character, dict):
                normalized_scope = normalize_visibility_scope(scope)
                if normalized_scope != scope:
                    character["visibility_scope"] = normalized_scope
                    fixes.append(f"record {index}/visible character {character_index}: normalized descriptive visibility_scope")
                depth_layer = str(character.get("depth_layer") or "").strip()
                normalized_depth = normalize_depth_layer(depth_layer)
                if normalized_depth != depth_layer:
                    character["depth_layer"] = normalized_depth
                    fixes.append(f"record {index}/visible character {character_index}: normalized ambiguous depth_layer to {normalized_depth}")
                for field in ("torso_orientation", "head_orientation", "body_orientation", "gaze_direction"):
                    current = str(character.get(field) or "").strip()
                    normalized = normalize_screen_axis(current)
                    if normalized != current:
                        character[field] = normalized
                        fixes.append(f"record {index}/visible character {character_index}: normalized {field} to screen coordinates")
                focus_evidence = str(character.get("focus_evidence") or "").strip()
                forbidden_focus_terms = ("位于", "前景", "中景", "后景", "后方", "侧后", "距离", "更近", "更远")
                if any(term in focus_evidence for term in forbidden_focus_terms):
                    clauses = [part.strip() for part in re.split(r"[，；。]", focus_evidence) if part.strip()]
                    optical_clauses = [part for part in clauses if not any(term in part for term in forbidden_focus_terms)]
                    if optical_clauses:
                        normalized_focus = "，".join(optical_clauses)
                    else:
                        normalized_focus = {
                            "sharp": "可见轮廓与纹理清晰",
                            "slightly_soft": "可见轮廓略微放软",
                            "heavily_defocused": "可见轮廓明显虚化",
                        }.get(str(character.get("focus_state") or ""), "清晰度证据不足")
                    character["focus_evidence"] = normalized_focus
                    fixes.append(f"record {index}/visible character {character_index}: removed spatial placement from focus_evidence")
                if locked_dialogue_events is not None:
                    current_action = str(character.get("character_action") or "").strip()
                    normalized_action = strip_quoted_dialogue_from_action(current_action)
                    if normalized_action != current_action:
                        character["character_action"] = normalized_action
                        fixes.append(f"record {index}/visible character {character_index}: removed locked dialogue text from visual action")
        if not isinstance(record.get("visible_characters"), list) or not record.get("visible_characters"):
            subject = primary(record)
            speaking = any(item.get("speaker_visibility") == "on_screen" for item in (record.get("dialogue_utterances") or []))
            record["visible_characters"] = [{
                "identity": subject,
                "appearance": str(record.get("visual_details") or subject or "visible appearance"),
                "screen_position": str(record.get("spatial_positions") or "visible frame position"),
                "mouth_state": "speaking" if speaking else "unclear",
                "mouth_visual_action": "unclear",
                "speech_sync_status": "matched_on_screen_dialogue" if speaking else "unclear",
                "mouth_action_evidence": "unclear",
                "body_posture": "unclear",
                "torso_orientation": "unclear",
                "head_orientation": "unclear",
                "body_orientation": "unclear",
                "gaze_direction": "unclear",
                "gaze_target": "unclear",
                "support_contact": "unclear",
                "visibility_scope": "\u5c40\u90e8",
                "depth_layer": "unclear",
                "relative_camera_distance": "unclear",
                "frame_occupancy": "tiny",
                "frame_crop": str(record.get("initial_frame") or "visible fragment"),
                "occlusion_relation": "unclear",
                "depth_evidence": "unclear",
                "focus_state": "unclear",
                "focus_evidence": "unclear",
                "facial_expression": "unclear",
                "anchor_presence": {"start": True, "middle": True, "end": True},
                "character_action": str(record.get("visible_action") or "visible but action unclear"),
            }]
            fixes.append(f"record {index}: populated visible_characters from the record's own primary subject and visual fields")
        visible_characters = record.get("visible_characters") or []
        sharp_layers = {
            str(person.get("depth_layer") or "")
            for person in visible_characters
            if isinstance(person, dict) and person.get("focus_state") == "sharp" and str(person.get("depth_layer") or "") in {"前景", "中景", "背景"}
        }
        lighting = str(record.get("lighting_composition") or "")
        if len(sharp_layers) > 1 and not any(term in lighting.lower() for term in ("深焦", "大景深", "deep focus", "large depth of field")):
            sharp_people = [person for person in visible_characters if isinstance(person, dict) and person.get("focus_state") == "sharp"]
            if sharp_people and all(str(person.get("focus_evidence") or "").strip() for person in sharp_people):
                generation_facts = record.get("generation_facts")
                if isinstance(generation_facts, dict):
                    generation_facts["depth_of_field"] = "deep"
                    fixes.append(f"record {index}: reconciled explicit multi-layer sharp evidence with generation_facts.depth_of_field")
                else:
                    record["lighting_composition"] = (lighting + "；逐人清晰证据显示跨景深主体均清晰，采用大景深/深焦表现").strip("；")
                    fixes.append(f"record {index}: reconciled explicit multi-layer sharp evidence with deep-focus composition")
        edge_audit = record.get("edge_character_audit")
        if isinstance(edge_audit, dict):
            for observation_index, observation in enumerate(edge_audit.get("observations") or [], 1):
                if not isinstance(observation, dict):
                    continue
                edge_identity = str(observation.get("identity") or "").strip()
                if not edge_identity or any(identity_matches(edge_identity, person.get("identity")) for person in visible_characters if isinstance(person, dict)):
                    continue
                fragment = str(observation.get("visible_fragment") or "").strip()
                position = str(observation.get("screen_position") or "").strip()
                evidence_text = " ".join((edge_identity, fragment, position))
                background = "背景" in evidence_text
                visibly_soft = any(term in evidence_text for term in ("虚焦", "模糊", "虚化"))
                visible_characters.append({
                    "identity": edge_identity,
                    "appearance": fragment or "边缘人物局部",
                    "screen_position": position or "画框边缘",
                    "mouth_state": "unclear",
                    "mouth_visual_action": "unclear",
                    "speech_sync_status": "unclear",
                    "mouth_action_evidence": "unclear",
                    "body_posture": "unclear",
                    "torso_orientation": "unclear",
                    "head_orientation": "unclear",
                    "body_orientation": "unclear",
                    "support_contact": "unclear",
                    "visibility_scope": "背景虚焦" if background and visibly_soft else "局部",
                    "depth_layer": "背景" if background else "unclear",
                    "relative_camera_distance": "farther_than_focus" if background else "unclear",
                    "frame_occupancy": "tiny",
                    "frame_crop": fragment or "仅见画框边缘局部",
                    "occlusion_relation": "unclear",
                    "depth_evidence": "边缘审计仅确认人物局部存在；除明确背景标签外，物理前后证据不足",
                    "focus_state": "heavily_defocused" if visibly_soft else "unclear",
                    "focus_evidence": "边缘局部呈明显柔化" if visibly_soft else "边缘观察未提供足够清晰度证据",
                    "gaze_direction": "unclear",
                    "gaze_target": "unclear",
                    "facial_expression": "unclear",
                    "character_action": "可见局部，无足够动作证据",
                })
                fixes.append(f"record {index}/edge observation {observation_index}: synchronized existing edge evidence into visible_characters")
        relations = record.get("relative_blocking")
        if isinstance(relations, list):
            for relation_index, relation in enumerate(relations, 1):
                if isinstance(relation, dict):
                    for field in ("horizontal_relation", "depth_relation", "occlusion", "facing_relationship"):
                        value = relation.get(field)
                        if isinstance(value, str) and value != value.strip():
                            relation[field] = value.strip()
                            fixes.append(f"record {index}/relative blocking {relation_index}: trimmed {field} whitespace")
                if isinstance(relation, dict) and relation.get("occlusion") not in {"blocks", "blocked_by", "none", "unclear"}:
                    relation["occlusion"] = "unclear"
                    fixes.append(f"record {index}/relative blocking {relation_index}: normalized unsupported occlusion label to unclear")
                if isinstance(relation, dict) and relation.get("depth_relation") not in {"in_front_of", "behind", "same_plane", "unclear"}:
                    relation["depth_relation"] = "unclear"
                    fixes.append(f"record {index}/relative blocking {relation_index}: normalized unsupported depth_relation label to unclear")
                if isinstance(relation, dict) and relation.get("facing_relationship") not in {"face_to_face", "same_direction", "back_to_back", "crossing", "unclear"}:
                    relation["facing_relationship"] = "unclear"
                    fixes.append(f"record {index}/relative blocking {relation_index}: normalized unsupported facing_relationship label to unclear")
            identities = [str(person.get("identity") or "").strip() for person in visible_characters if isinstance(person, dict) and str(person.get("identity") or "").strip()]
            existing_pairs = {
                tuple(sorted((normalized_identity(item.get("subject")), normalized_identity(item.get("relative_to")))))
                for item in relations if isinstance(item, dict)
            }
            for left_index, left in enumerate(identities):
                for right in identities[left_index + 1:]:
                    pair = tuple(sorted((normalized_identity(left), normalized_identity(right))))
                    if pair in existing_pairs:
                        continue
                    relations.append({
                        "subject": left,
                        "relative_to": right,
                        "horizontal_relation": "unclear",
                        "depth_relation": "unclear",
                        "occlusion": "unclear",
                        "facing_relationship": "unclear",
                        "evidence": "边缘审计仅确认人物局部存在，两人相对站位证据不足",
                    })
                    existing_pairs.add(pair)
                    fixes.append(f"record {index}: added an uncertainty-preserving pairwise relation for synchronized edge evidence")
        current_dialogue = str(record.get("chinese_dialogue") or "").strip()
        screen_text = str(record.get("on_screen_text") or "")
        current_utterances = record.get("dialogue_utterances") or []
        if isinstance(current_utterances, list):
            ordered_utterances = sorted(
                (item for item in current_utterances if isinstance(item, dict)),
                key=lambda item: (
                    float(item.get("start_seconds", 0.0)),
                    float(item.get("end_seconds", item.get("start_seconds", 0.0))),
                    str(item.get("dialogue_id") or ""),
                ),
            )
            if ordered_utterances != current_utterances:
                record["dialogue_utterances"] = ordered_utterances
                current_utterances = ordered_utterances
                fixes.append(f"record {index}: ordered locked dialogue utterances chronologically")
        current_subtitle = subtitle_text(screen_text)
        previous_utterance_continues = any(subtitle_text(text) and subtitle_text(text) in current_subtitle for text in previous_utterance_texts)
        if not current_dialogue and previous_dialogue and not current_utterances and (previous_dialogue in screen_text or previous_utterance_continues):
            sound = str(record.get("sound") or "").strip()
            if "延续" not in sound:
                record["sound"] = (sound + "；上一镜台词字幕延续").strip("；")
                fixes.append(f"record {index}: marked an unchanged prior subtitle as continued audio")
        if current_dialogue:
            previous_dialogue = current_dialogue
        if current_utterances:
            previous_utterance_texts = [str(item.get("text") or "").strip() for item in current_utterances if isinstance(item, dict) and str(item.get("text") or "").strip()]
        record_start = float(record.get("start_seconds", 0.0))
        record_end = float(record.get("end_seconds", record_start))
        contract = data.get("boundary_contract") if isinstance(data.get("boundary_contract"), dict) else {}
        locked_intervals = contract.get("locked_intervals") or []
        evidence_intervals = contract.get("evidence_intervals") or []
        expected_evidence_ids = [
            str(interval.get("evidence_interval_id") or "")
            for interval in evidence_intervals
            if str(interval.get("evidence_interval_id") or "")
            and float(interval["end_seconds"]) > record_start + 0.001
            and float(interval["start_seconds"]) < record_end - 0.001
        ]
        if expected_evidence_ids and record.get("evidence_interval_ids") != expected_evidence_ids:
            record["evidence_interval_ids"] = expected_evidence_ids
            fixes.append(f"record {index}: copied evidence_interval_ids from locked boundary contract")
        merge_false_times = {
            round(float(item.get("candidate_seconds")), 3)
            for item in data.get("boundary_audit") or []
            if item.get("decision") == "merge_false" and item.get("candidate_seconds") is not None
        }
        overlapping = [
            interval for interval in locked_intervals
            if float(interval["end_seconds"]) > record_start + 0.001
            and float(interval["start_seconds"]) < record_end - 0.001
        ]
        # The relay occasionally omits the explicit three-anchor summary even
        # though it returned the record-level initial/primary/final subjects.
        # Fill only by copying those existing model fields and the locked
        # boundary-contract timestamps; do not infer a new person or action.
        anchor_subject_sources = (
            ("start_anchor_subject", "initial_frame"),
            ("middle_anchor_subject", "primary_visible_subject"),
            ("end_anchor_subject", "final_frame"),
        )
        for anchor_field, source_field in anchor_subject_sources:
            if not str(record.get(anchor_field) or "").strip():
                copied_subject = str(record.get(source_field) or primary(record)).strip()
                if copied_subject:
                    record[anchor_field] = copied_subject
                    fixes.append(f"record {index}: copied {anchor_field} from existing {source_field}")
        anchor_times = record.get("anchor_evidence_timestamps")
        if (not isinstance(anchor_times, list) or len(anchor_times) != 3) and overlapping:
            midpoint = (record_start + record_end) / 2.0
            middle_interval = min(
                overlapping,
                key=lambda interval: abs(float(interval.get("middle_anchor_seconds", midpoint)) - midpoint),
            )
            record["anchor_evidence_timestamps"] = [
                round(float(overlapping[0].get("start_anchor_seconds", record_start)), 3),
                round(float(middle_interval.get("middle_anchor_seconds", midpoint)), 3),
                round(float(overlapping[-1].get("end_anchor_seconds", record_end)), 3),
            ]
            fixes.append(f"record {index}: copied anchor_evidence_timestamps from locked boundary contract")
        internal_edges = [
            round(float(interval["end_seconds"]), 3)
            for interval in overlapping[:-1]
            if record_start + 0.001 < float(interval["end_seconds"]) < record_end - 0.001
        ]
        if len(overlapping) > 1 and internal_edges and all(edge in merge_false_times for edge in internal_edges):
            normalized_interval_id = "_".join(str(interval["interval_id"]) for interval in overlapping)
        else:
            interval = interval_for_time(contract, (record_start + record_end) / 2.0)
            normalized_interval_id = str((interval or {}).get("interval_id") or "")
        if normalized_interval_id and record.get("interval_id") != normalized_interval_id:
            record["interval_id"] = normalized_interval_id
            fixes.append(f"record {index}: normalized interval_id from the locked boundary contract")
        for utterance_index, utterance in enumerate(record.get("dialogue_utterances") or [], 1):
            speaker = str(utterance.get("speaker") or "").strip()
            visible_identities = [
                str(person.get("identity") or "").strip()
                for person in visible_characters
                if isinstance(person, dict)
            ]
            if (
                utterance.get("speaker_visibility") == "on_screen"
                and speaker
                and not any(identity_matches(speaker, identity) for identity in visible_identities)
            ):
                utterance["speaker_visibility"] = "off_screen"
                fixes.append(
                    f"record {index}/utterance {utterance_index}: reconciled on-screen visibility with the record's visible-character list"
                )
            try:
                utterance_start = float(utterance.get("start_seconds"))
                utterance_end = float(utterance.get("end_seconds"))
            except (TypeError, ValueError):
                continue
            clipped_start = max(record_start, utterance_start)
            clipped_end = min(record_end, utterance_end)
            if clipped_end > clipped_start and (clipped_start != utterance_start or clipped_end != utterance_end):
                utterance["start_seconds"] = round(clipped_start, 3)
                utterance["end_seconds"] = round(clipped_end, 3)
                fixes.append(f"record {index}/utterance {utterance_index}: clipped timing to its parent visual interval")

        normalized_utterances = [item for item in (record.get("dialogue_utterances") or []) if isinstance(item, dict)]
        off_screen_only = bool(normalized_utterances) and all(
            item.get("speaker_visibility") == "off_screen" for item in normalized_utterances
        )
        if off_screen_only:
            visible_characters = [item for item in (record.get("visible_characters") or []) if isinstance(item, dict)]
            conflict = any(
                person.get("mouth_state") == "speaking"
                or person.get("speech_sync_status") == "matched_on_screen_dialogue"
                or contains_positive_speech_claim(person.get("character_action"))
                for person in visible_characters
            ) or any(
                contains_positive_speech_claim(record.get(field))
                for field in ("beat_summary", "primary_visible_subject", "visible_action", "mouth_dynamics")
            )
            if conflict:
                speaker_names = []
                for utterance in normalized_utterances:
                    speaker = str(utterance.get("speaker") or "").strip()
                    if speaker and speaker not in speaker_names:
                        speaker_names.append(speaker)
                off_screen_speaker = "、".join(speaker_names) or "画外人物"
                action_summaries: list[str] = []
                mouth_summaries: list[str] = []
                for character_index, person in enumerate(visible_characters, 1):
                    identity = str(person.get("identity") or f"可见人物{character_index}")
                    mouth_visual = str(person.get("mouth_visual_action") or "unclear").strip()
                    if person.get("mouth_state") == "speaking" or person.get("speech_sync_status") == "matched_on_screen_dialogue":
                        person["mouth_state"] = "not_speaking"
                        person["speech_sync_status"] = "off_screen_audio_reaction"
                    cleaned_action = strip_reaction_speech_claims(person.get("character_action"))
                    if cleaned_action != str(person.get("character_action") or "").strip():
                        person["character_action"] = cleaned_action or mouth_visual
                        fixes.append(
                            f"record {index}/visible character {character_index}: removed speech ownership contradicted by off-screen-only locked dialogue"
                        )
                    action_summaries.append(f"{identity}{person.get('character_action') or mouth_visual}")
                    mouth_summaries.append(f"{identity}：{mouth_visual}")
                primary_identity = str((visible_characters[0] if visible_characters else {}).get("identity") or primary(record) or "画面人物")
                record["beat_summary"] = f"{primary_identity}对{off_screen_speaker}的画外台词作出可见反应"
                record["primary_visible_subject"] = f"{primary_identity}反应镜头"
                record["visible_action"] = "；".join(action_summaries)
                record["mouth_dynamics"] = "；".join(mouth_summaries + [f"{off_screen_speaker}画外发言"])
                fixes.append(f"record {index}: reconciled reaction-shot prose with off-screen-only locked dialogue")

        position_parts: list[str] = []
        for person in visible_characters:
            if not isinstance(person, dict):
                continue
            identity = str(person.get("identity") or "可见人物")
            facts = [
                str(person.get("screen_position") or ""),
                f"景深层级{person.get('depth_layer')}" if person.get("depth_layer") else "",
                f"相对镜头{person.get('relative_camera_distance')}" if person.get("relative_camera_distance") else "",
                str(person.get("frame_crop") or ""),
                str(person.get("torso_orientation") or ""),
                str(person.get("head_orientation") or ""),
            ]
            position_parts.append(f"{identity}：" + "，".join(value for value in facts if value and value != "unclear"))
        relation_parts: list[str] = []
        for relation in record.get("relative_blocking") or []:
            if not isinstance(relation, dict):
                continue
            relation_parts.append(
                f"{relation.get('subject')}相对{relation.get('relative_to')}："
                f"横向={relation.get('horizontal_relation')}，前后={relation.get('depth_relation')}，"
                f"遮挡={relation.get('occlusion')}，朝向={relation.get('facing_relationship')}"
            )
        if position_parts:
            record["spatial_positions"] = "；".join([*position_parts, *relation_parts])
        action_parts = [
            f"{person.get('identity')}：{person.get('character_action')}"
            for person in visible_characters
            if isinstance(person, dict) and str(person.get("character_action") or "").strip()
        ]
        if action_parts:
            record["visible_action"] = "；".join(action_parts)
        scene = str(record.get("scene_observation") or "")
        identities = [str(person.get("identity") or "") for person in visible_characters if isinstance(person, dict)]
        identity_bases = [re.split(r"[-（(]", identity, maxsplit=1)[0] for identity in identities]
        if "，" in scene and any(identity and identity in scene for identity in [*identities, *identity_bases]):
            record["scene_observation"] = scene.split("，", 1)[0]

    for audit_index, item in enumerate(data.get("boundary_audit") or [], 1):
        try:
            observed = float(item.get("observed_seconds"))
        except (TypeError, ValueError):
            continue
        decision = item.get("decision")
        if decision in {"keep_cut", "keep_reframe"} and item.get("same_shot_evidence") is True:
            containing = next((record for record in records if float(record.get("start_seconds", 0)) < observed < float(record.get("end_seconds", 0))), None)
            reason = str(item.get("reason") or "")
            if containing and any(term in reason for term in ("同构图", "连续运镜", "连续画面", "同一连续镜头", "无切")):
                item["decision"] = "merge_false"
                item["before_visible_subject"] = primary(containing)
                item["after_visible_subject"] = primary(containing)
                fixes.append(f"boundary audit {audit_index}: reconciled explicit same-shot evidence with merge_false")
                decision = "merge_false"
        if decision == "merge_false":
            containing = next((record for record in records if float(record.get("start_seconds", 0)) < observed < float(record.get("end_seconds", 0))), None)
            if containing and primary(containing):
                item["before_visible_subject"] = primary(containing)
                item["after_visible_subject"] = primary(containing)
                item["same_shot_evidence"] = True
                fixes.append(f"boundary audit {audit_index}: normalized verbose same-shot labels to the containing record subject")
        elif decision in {"keep_cut", "keep_reframe"}:
            before = max((record for record in records if float(record.get("end_seconds", -1)) <= observed + 0.15), key=lambda record: float(record.get("end_seconds", -1)), default=None)
            after = min((record for record in records if float(record.get("start_seconds", 1e9)) >= observed - 0.15), key=lambda record: float(record.get("start_seconds", 1e9)), default=None)
            if before and primary(before):
                item["before_visible_subject"] = primary(before)
            if after and primary(after):
                item["after_visible_subject"] = primary(after)

    dialogue_warnings = ensure_dialogue_contract(data)
    if locked_dialogue_events is not None:
        data["dialogue_events"] = locked_dialogue_events
    data.setdefault("warnings", []).append(
        f"Deterministic compact-label normalization applied {len(fixes)} structural fixes and found {len(dialogue_warnings)} dialogue continuity conflicts; no video frames were reviewed or semantic identities reinterpreted."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"fixes": len(fixes), "records": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

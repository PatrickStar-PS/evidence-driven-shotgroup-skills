#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from continuity_handoff import attach_group_continuity_handoffs


SHOT_SIZE = {"wide": "全景", "full": "全身", "medium": "中景", "close-up": "近景", "extreme-close-up": "特写", "unknown": "中景"}
ANGLE = {"eye-level": "平视", "high-angle": "俯拍", "low-angle": "仰拍", "overhead": "俯视", "unknown": "平视"}
CJK_RE = re.compile(r"[\u3400-\u9fff]")
ENGLISH_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
DEFAULT_RATE_TARGET_WPS = {
    "very_slow": 1.6,
    "slow": 2.1,
    "medium": 2.8,
    "fast": 3.6,
    "very_fast": 4.3,
    "unclear": 3.0,
}
PAUSE_RESERVE_SECONDS = {"micro": 0.08, "short": 0.18, "medium": 0.35, "long": 0.6}
STATIC_LIGHT_TERMS = (
    "灯具", "吊灯", "灯带", "霓虹", "氛围灯", "顶光", "背景灯",
    "蓝色", "红色", "紫色", "彩色", "蓝光", "红光", "霓虹色",
    "冷色调", "暖色调", "冷光", "暖光",
)
DYNAMIC_LIGHT_MARKERS = (
    "开启", "打开", "亮起", "熄灭", "关闭", "闪烁", "闪动", "警灯", "扫过", "掠过",
    "照到脸", "照在脸", "屏幕光", "车灯", "由暗变亮", "由亮变暗",
)
PROP_ACTION_MARKERS = (
    "手持", "持有", "拿着", "拿起", "拿出", "捧着", "抱着", "夹着", "夹持", "握住", "托持",
    "递出", "递给", "交给", "接过", "接住", "打开", "翻开", "合上", "放下", "举起", "使用", "抽出", "取出",
)
PROP_TRANSFER_MARKERS = ("递", "交", "接", "转交", "交给", "拿给", "放到", "取走")


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build_localized_delivery(event: dict, translated: str, timing_config: dict) -> dict:
    delivery = event.get("delivery") if isinstance(event.get("delivery"), dict) else {}
    start = float(event.get("start_seconds") or 0.0)
    end = float(event.get("end_seconds") or start)
    duration = max(0.0, end - start)
    pause_profile = delivery.get("pause_profile") if isinstance(delivery.get("pause_profile"), list) else []
    pause_reserve = sum(PAUSE_RESERVE_SECONDS.get(str(item.get("duration") or ""), 0.0) for item in pause_profile if isinstance(item, dict))
    pause_reserve = min(pause_reserve, max(0.0, duration - 0.35))
    available_speech = max(0.35, duration - pause_reserve)
    word_count = len(ENGLISH_WORD_RE.findall(translated))
    required_wps = word_count / available_speech if word_count else 0.0
    speech_rate = str(delivery.get("speech_rate") or "unclear")
    rate_targets = dict(DEFAULT_RATE_TARGET_WPS)
    for key, value in (timing_config.get("rate_target_wps") or {}).items():
        if key in rate_targets:
            rate_targets[key] = float(value)
    target_wps = rate_targets.get(speech_rate, rate_targets["unclear"])
    hard_limit_wps = float(timing_config.get("hard_limit_wps", 4.5))
    tolerance_wps = float(timing_config.get("tolerance_wps", 0.15))
    if required_wps <= target_wps + tolerance_wps:
        timing_status = "fits_source_rate"
    elif required_wps <= hard_limit_wps + tolerance_wps:
        timing_status = "fits_hard_limit_but_not_source_rate"
    else:
        timing_status = "needs_condense"
    pause_text = "无明确句内停顿"
    if pause_profile:
        pause_text = "、".join(
            f"约{float(item.get('position_ratio', 0)) * 100:.0f}%处{item.get('duration', 'short')}停顿（{item.get('function', 'unclear')}）"
            for item in pause_profile
            if isinstance(item, dict)
        )
    direction = (
        f"在{duration:.2f}秒原始窗口内完成；语速={speech_rate}；"
        f"语调={delivery.get('intonation', 'unclear')}；音色={delivery.get('timbre', 'unclear')}；"
        f"情绪={delivery.get('emotion', 'unclear')}；节奏/停顿={delivery.get('rhythm_pause', 'unclear')}；{pause_text}。"
    )
    return {
        "source_delivery": json.loads(json.dumps(delivery, ensure_ascii=False)),
        "source_window_seconds": round(duration, 3),
        "pause_reserve_seconds": round(pause_reserve, 3),
        "available_speech_seconds": round(available_speech, 3),
        "english_word_count": word_count,
        "required_words_per_second": round(required_wps, 3),
        "source_rate_target_wps": round(target_wps, 3),
        "hard_limit_wps": round(hard_limit_wps, 3),
        "timing_status": timing_status,
        "performance_direction": direction,
    }


def split_text_by_weights(text: str, weights: list[float]) -> list[str]:
    """Split text once across ordered time weights, preferring punctuation boundaries."""
    value = str(text or "").strip()
    if len(weights) <= 1:
        return [value]
    tokens = list(value) if CJK_RE.search(value) else re.findall(r"\S+(?:\s+|$)", value)
    if len(tokens) < len(weights):
        raise RuntimeError(f"Dialogue text has fewer split units than cross-group segments: {value!r}")
    total_weight = sum(max(0.0, weight) for weight in weights)
    if total_weight <= 0:
        raise RuntimeError("Dialogue segment weights must be positive")
    cuts: list[int] = []
    consumed_weight = 0.0
    previous_cut = 0
    strong_punctuation = set("。！？!?；;")
    soft_punctuation = set("，,、：:")
    for index, weight in enumerate(weights[:-1], 1):
        consumed_weight += max(0.0, weight)
        target = round(len(tokens) * consumed_weight / total_weight)
        lower = previous_cut + 1
        upper = len(tokens) - (len(weights) - index)
        target = min(upper, max(lower, target))
        radius = max(2, round(len(tokens) * 0.12))
        candidates: list[tuple[float, int]] = []
        for position in range(max(lower, target - radius), min(upper, target + radius) + 1):
            last = tokens[position - 1].rstrip()
            final_character = last[-1:] if last else ""
            priority = 0 if final_character in strong_punctuation else 1 if final_character in soft_punctuation else 3
            candidates.append((abs(position - target) + priority * 0.75, position))
        cut = min(candidates)[1] if candidates else target
        cuts.append(cut)
        previous_cut = cut
    boundaries = [0, *cuts, len(tokens)]
    return ["".join(tokens[left:right]).strip() for left, right in zip(boundaries, boundaries[1:])]


def delivery_for_segment(event: dict, segment_start: float, segment_end: float) -> dict:
    delivery = json.loads(json.dumps(event.get("delivery") or {}, ensure_ascii=False))
    full_start = float(event.get("start_seconds") or segment_start)
    full_end = float(event.get("end_seconds") or segment_end)
    full_duration = max(0.001, full_end - full_start)
    segment_duration = max(0.001, segment_end - segment_start)
    pauses: list[dict] = []
    for pause in delivery.get("pause_profile") or []:
        if not isinstance(pause, dict):
            continue
        try:
            absolute_pause = full_start + float(pause.get("position_ratio")) * full_duration
        except (TypeError, ValueError):
            continue
        if segment_start - 0.001 <= absolute_pause <= segment_end + 0.001:
            localized_pause = dict(pause)
            localized_pause["position_ratio"] = round(min(1.0, max(0.0, (absolute_pause - segment_start) / segment_duration)), 4)
            pauses.append(localized_pause)
    delivery["pause_profile"] = pauses
    return delivery


def build_dialogue_segments(
    groups: list[dict],
    dialogue_events: list[dict],
    translations: dict,
    translations_by_dialogue_id: dict,
    seam_tolerance: float,
) -> tuple[dict[int, list[dict]], list[dict], list[str]]:
    by_group: dict[int, list[dict]] = {index: [] for index in range(1, len(groups) + 1)}
    assembly: list[dict] = []
    warnings: list[str] = []
    for event in sorted(dialogue_events, key=lambda item: (float(item.get("start_seconds", 0)), str(item.get("dialogue_id") or ""))):
        dialogue_id = str(event.get("dialogue_id") or "").strip()
        source_text = str(event.get("text") or "").strip()
        if not dialogue_id or not source_text:
            continue
        localized_text = str(translations_by_dialogue_id.get(dialogue_id) or translations.get(source_text) or "").strip()
        if not localized_text:
            raise RuntimeError(f"Missing British-localized dialogue for {dialogue_id!r}")
        if localized_text == source_text or CJK_RE.search(localized_text):
            raise RuntimeError(f"British-localized dialogue remains Chinese for {dialogue_id}: {localized_text}")
        event_start = float(event["start_seconds"])
        event_end = float(event["end_seconds"])
        overlaps: list[dict] = []
        for group_index, group in enumerate(groups, 1):
            group_start, group_end = float(group["start"]), float(group["end"])
            start, end = max(event_start, group_start), min(event_end, group_end)
            if end > start + 0.0005:
                overlaps.append({"group_index": group_index, "start_seconds": start, "end_seconds": end, "duration": end - start})
        if not overlaps:
            continue
        material = [item for item in overlaps if item["duration"] > seam_tolerance]
        if not material:
            material = [max(overlaps, key=lambda item: item["duration"])]
        ignored = [item for item in overlaps if item not in material]
        if ignored:
            ignored_seconds = sum(item["duration"] for item in ignored)
            warnings.append(f"{dialogue_id}: snapped {ignored_seconds:.3f}s seam-only overlap to the material group")
        weights = [item["duration"] for item in material]
        source_fragments = split_text_by_weights(source_text, weights)
        localized_fragments = split_text_by_weights(localized_text, weights)
        segment_ids: list[str] = []
        for segment_index, (overlap, source_fragment, localized_fragment) in enumerate(zip(material, source_fragments, localized_fragments), 1):
            segment_id = f"{dialogue_id}-S{segment_index:02d}"
            segment_ids.append(segment_id)
            segment_event = dict(event)
            segment_event["start_seconds"] = round(float(overlap["start_seconds"]), 3)
            segment_event["end_seconds"] = round(float(overlap["end_seconds"]), 3)
            segment_event["delivery"] = delivery_for_segment(event, segment_event["start_seconds"], segment_event["end_seconds"])
            continuation = "whole" if len(material) == 1 else "starts_here" if segment_index == 1 else "ends_here" if segment_index == len(material) else "continues"
            by_group[overlap["group_index"]].append({
                "dialogue_id": dialogue_id,
                "dialogue_segment_id": segment_id,
                "segment_index": segment_index,
                "segment_count": len(material),
                "continuation": continuation,
                "start_seconds": segment_event["start_seconds"],
                "end_seconds": segment_event["end_seconds"],
                "speaker": event.get("speaker"),
                "text": source_fragment,
                "localized_text": localized_fragment,
                "source_event": segment_event,
                "boundary_snap_seconds": round(sum(item["duration"] for item in ignored), 3) if len(material) == 1 else 0.0,
            })
        assembly.append({
            "dialogue_id": dialogue_id,
            "source_text": source_text,
            "localized_text": localized_text,
            "segment_ids": segment_ids,
            "segment_count": len(segment_ids),
        })
    return by_group, assembly, warnings


def record_blob(record: dict) -> str:
    parts = [record.get("primary_visible_subject", ""), record.get("scene_observation", ""), record.get("visual_details", ""), record.get("transient_visual_details", ""), record.get("visible_action", "")]
    for person in record.get("visible_characters") or []:
        parts.extend([
            person.get("identity", ""),
            person.get("appearance", ""),
            person.get("gaze_direction", ""),
            person.get("gaze_target", ""),
            person.get("torso_orientation", ""),
            person.get("head_orientation", ""),
            person.get("facial_expression", ""),
            person.get("character_action", ""),
            person.get("focus_evidence", ""),
            person.get("depth_evidence", ""),
            person.get("frame_crop", ""),
            person.get("occlusion_relation", ""),
        ])
    for relation in record.get("relative_blocking") or []:
        parts.extend([
            relation.get("subject", ""),
            relation.get("relative_to", ""),
            relation.get("horizontal_relation", ""),
            relation.get("depth_relation", ""),
            relation.get("occlusion", ""),
            relation.get("facing_relationship", ""),
            relation.get("evidence", ""),
        ])
    return " ".join(str(value) for value in parts)


def match_rule(text: str, seconds: float, rules: list[dict], field: str) -> str:
    candidates: list[tuple[int, str]] = []
    for rule in rules:
        if seconds < float(rule.get("start", 0)) - 0.01 or seconds > float(rule.get("end", 10**9)) + 0.01:
            continue
        for alias in rule.get(field) or []:
            if alias and alias in text:
                candidates.append((len(alias), str(rule["asset"])))
    return max(candidates, default=(0, ""))[1]


def _normalized_dialogue_text(value: object) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’—\-]", "", str(value or "")).casefold()


def resolve_dialogue_speaker_asset(
    segment: dict,
    records: list[dict],
    people_rules: list[dict],
) -> str:
    """Resolve an unclear ledger speaker only from unique on-screen record evidence."""
    seconds = float(segment.get("start_seconds", 0))
    speaker_text = str(segment.get("speaker") or "").strip()
    direct = match_rule(speaker_text, seconds, people_rules, "aliases")
    if direct:
        return direct
    if speaker_text and speaker_text.casefold() not in {"unclear", "unknown", "待确认", "未知"}:
        return speaker_text

    dialogue_id = str(segment.get("dialogue_id") or "").strip()
    source_text = _normalized_dialogue_text(segment.get("text") or segment.get("source_text"))
    candidates: set[str] = set()
    for record in records:
        if float(record.get("end_seconds", 0)) < float(segment.get("start_seconds", 0)) - 0.01:
            continue
        if float(record.get("start_seconds", 0)) > float(segment.get("end_seconds", 0)) + 0.01:
            continue
        placement = next((
            item for item in record.get("dialogue_placements") or []
            if isinstance(item, dict)
            and str(item.get("dialogue_id") or "") == dialogue_id
            and str(item.get("speaker_visibility") or "") == "on_screen"
        ), None)
        if placement is None:
            continue
        matched_people: list[tuple[str, str]] = []
        for person in record.get("visible_characters") or []:
            if not isinstance(person, dict):
                continue
            identity = str(person.get("identity") or "").strip()
            asset = match_rule(identity, seconds, people_rules, "aliases")
            if asset:
                matched_people.append((asset, _normalized_dialogue_text(person.get("character_action"))))
        if not matched_people:
            continue
        text_supported = {asset for asset, action in matched_people if source_text and source_text in action}
        if len(text_supported) == 1:
            candidates.update(text_supported)
        elif len(matched_people) == 1:
            candidates.add(matched_people[0][0])
    return next(iter(candidates)) if len(candidates) == 1 else (speaker_text or "unclear")


def scene_evidence_text(record: dict) -> str:
    """Return only location-bearing evidence used for deterministic scene binding."""
    values = [
        record.get("scene_observation", ""),
        record.get("fixed_scene_evidence", ""),
        record.get("transition", ""),
    ]
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def scene_rule_score(text: str, rule: dict) -> tuple[int, list[str]]:
    normalized = str(text or "").casefold()
    matches: list[str] = []
    for keyword in list(rule.get("keywords") or []) + list(rule.get("aliases") or []):
        value = str(keyword or "").strip()
        if value and value.casefold() in normalized and value not in matches:
            matches.append(value)
    for keyword in rule.get("negative_keywords") or []:
        value = str(keyword or "").strip()
        if value and value.casefold() in normalized:
            return 0, []
    # Longer, specific phrases should beat generic one-word aliases.
    score = sum(max(1, min(4, len(value) // 2)) for value in matches)
    return score, matches


def resolve_record_scene_asset(record: dict, configured_scene: str, scene_rules: list[dict]) -> str:
    """Resolve one boundary record to one canonical scene without using a composite group label."""
    scored: list[tuple[int, str]] = []
    evidence = scene_evidence_text(record)
    for rule in scene_rules:
        if not isinstance(rule, dict) or not str(rule.get("asset") or "").strip():
            continue
        score, _ = scene_rule_score(evidence, rule)
        if score:
            scored.append((score, str(rule["asset"]).strip()))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    configured_assets = [value.strip() for value in str(configured_scene or "").replace("、", "；").split("；") if value.strip()]
    return configured_assets[0] if len(configured_assets) == 1 else ""


def resolve_group_scene(
    configured_scene: str,
    selected: list[dict],
    scene_rules: list[dict],
    settings: dict | None = None,
) -> tuple[str, dict, list[str]]:
    """Resolve a canonical scene without letting a static group label hide contrary video evidence.

    Rules are optional for backward compatibility.  A correction requires a unique
    per-record winner, support from multiple records, and a dominant duration share.
    """
    settings = settings or {}
    configured_scene = str(configured_scene or "").strip()
    usable_rules = [
        rule for rule in scene_rules
        if isinstance(rule, dict) and str(rule.get("asset") or "").strip()
    ]
    if not usable_rules:
        return configured_scene, {
            "status": "not_evaluated",
            "configured_scene": configured_scene,
            "resolved_scene": configured_scene,
            "reason": "scene_rules_missing",
        }, []

    minimum_record_score = int(settings.get("minimum_record_score", 2))
    minimum_support_records = int(settings.get("minimum_support_records", 2))
    minimum_duration_share = float(settings.get("minimum_duration_share", 0.67))
    mode = str(settings.get("mode") or "correct_high_confidence")
    votes: dict[str, dict] = {}
    record_audit: list[dict] = []
    total_duration = sum(max(0.001, float(record["end_seconds"]) - float(record["start_seconds"])) for record in selected)

    for record in selected:
        evidence = scene_evidence_text(record)
        scored: list[tuple[int, str, list[str]]] = []
        for rule in usable_rules:
            score, matches = scene_rule_score(evidence, rule)
            if score:
                scored.append((score, str(rule["asset"]).strip(), matches))
        scored.sort(key=lambda item: (-item[0], item[1]))
        winner = ""
        winner_score = 0
        winner_matches: list[str] = []
        if scored and scored[0][0] >= minimum_record_score:
            tied = len(scored) > 1 and scored[1][0] == scored[0][0]
            if not tied:
                winner_score, winner, winner_matches = scored[0]
        duration = max(0.001, float(record["end_seconds"]) - float(record["start_seconds"]))
        if winner:
            vote = votes.setdefault(winner, {"records": 0, "duration": 0.0, "matches": []})
            vote["records"] += 1
            vote["duration"] += duration
            vote["matches"].extend(item for item in winner_matches if item not in vote["matches"])
        record_audit.append({
            "start_seconds": float(record["start_seconds"]),
            "end_seconds": float(record["end_seconds"]),
            "winner": winner,
            "score": winner_score,
            "matches": winner_matches,
        })

    ranked = sorted(
        votes.items(),
        key=lambda item: (-item[1]["duration"], -item[1]["records"], item[0]),
    )
    candidate = ranked[0][0] if ranked else ""
    candidate_vote = ranked[0][1] if ranked else {"records": 0, "duration": 0.0, "matches": []}
    duration_share = float(candidate_vote["duration"]) / total_duration if total_duration else 0.0
    unique_duration_winner = not (
        len(ranked) > 1 and abs(float(ranked[1][1]["duration"]) - float(candidate_vote["duration"])) < 0.001
    )
    strong = bool(
        candidate
        and unique_duration_winner
        and int(candidate_vote["records"]) >= minimum_support_records
        and duration_share >= minimum_duration_share
    )

    resolved = configured_scene
    status = "confirmed" if candidate == configured_scene and strong else "insufficient_evidence"
    warnings: list[str] = []
    if strong and candidate != configured_scene:
        message = (
            f"scene evidence conflicts with configured scene: {configured_scene!r} -> {candidate!r}; "
            f"support={candidate_vote['records']} records/{duration_share:.1%} duration; "
            f"matches={','.join(candidate_vote['matches'])}"
        )
        if mode == "error":
            raise RuntimeError(message)
        if mode == "correct_high_confidence":
            resolved = candidate
            status = "corrected_high_confidence"
            warnings.append(message)
        else:
            status = "conflict_preserved"
            warnings.append(message)

    audit = {
        "status": status,
        "configured_scene": configured_scene,
        "resolved_scene": resolved,
        "candidate_scene": candidate,
        "support_records": int(candidate_vote["records"]),
        "duration_share": round(duration_share, 4),
        "matched_keywords": list(candidate_vote["matches"]),
        "record_votes": record_audit,
    }
    return resolved, audit, warnings


def person_assets(record: dict, rules: list[dict]) -> list[str]:
    result: list[str] = []
    midpoint = (float(record["start_seconds"]) + float(record["end_seconds"])) / 2
    for person in record.get("visible_characters") or []:
        text = " ".join(str(person.get(key, "")) for key in ("identity", "appearance"))
        asset = match_rule(text, midpoint, rules, "aliases")
        if asset and asset not in result:
            result.append(asset)
    if not result:
        asset = match_rule(record_blob(record), midpoint, rules, "aliases")
        if asset:
            result.append(asset)
    return result


def replace_people(text: str, seconds: float, rules: list[dict]) -> str:
    value = str(text or "")
    applicable = [r for r in rules if float(r.get("start", 0)) - 0.01 <= seconds <= float(r.get("end", 10**9)) + 0.01]
    protected_assets: dict[str, str] = {}
    for index, asset in enumerate(dict.fromkeys(str(rule.get("asset") or "") for rule in applicable)):
        if not asset or asset not in value:
            continue
        token = f"__BOUND_PERSON_ASSET_{index}__"
        value = value.replace(asset, token)
        protected_assets[token] = asset
    for rule in applicable:
        for alias in sorted(rule.get("aliases") or [], key=len, reverse=True):
            value = value.replace(alias, str(rule["asset"]))
    for token, asset in protected_assets.items():
        value = value.replace(token, asset)
    return value


def compact_time_evidence(time_of_day: str, evidence: str) -> str:
    if not str(evidence or "").strip():
        return ""
    return {
        "day": "直接可见自然日光、明亮室外环境或连续白天剧情依据",
        "night": "直接可见夜空、夜景或连续夜间剧情依据",
        "dawn": "直接可见黎明天色或明确清晨剧情依据",
        "dusk": "直接可见黄昏天色或明确傍晚剧情依据",
        "unclear": "缺少可直接判断昼夜的外部光景",
    }.get(str(time_of_day), "昼夜依据已记录但不复述固定场景细节")


def strip_redundant_bound_appearance(text: str, assets: list[str]) -> str:
    value = str(text or "")
    bound_assets = [item for item in assets if item and "候选新增" not in item and item in value]
    for asset in sorted(bound_assets, key=len, reverse=True):
        value = re.sub(
            rf"({re.escape(asset)})\s*[，,：:；;]?\s*(?:身穿|穿着|佩戴|戴着|头戴)[^，。；|]*",
            r"\1",
            value,
        )
    wardrobe_terms = ("西装", "礼服", "马甲", "T恤", "衬衫", "夹克", "外套", "裙", "制服", "睡衣", "风衣", "大衣")
    for term in wardrobe_terms:
        if any(term in asset for asset in bound_assets):
            value = re.sub(rf"(?:身穿|穿着)[^，。；|]{{0,16}}{re.escape(term)}", "", value)
    return re.sub(r"[，；]\s*[，；]", "；", value).strip("，； ")


def base_asset_name(asset: str) -> str:
    return str(asset or "").split(" - ", 1)[0].strip() or str(asset or "").strip()


def compact_asset_references(text: str, assets: list[str], keep_first: bool) -> str:
    """Keep a bound wardrobe/state asset once, then use its base character name."""
    value = str(text or "")
    for asset in sorted(
        (item for item in assets if item and "候选新增" not in item),
        key=len,
        reverse=True,
    ):
        replacement = base_asset_name(asset)
        matches = list(re.finditer(re.escape(asset), value))
        if not matches:
            continue
        rebuilt: list[str] = []
        cursor = 0
        for match_index, match in enumerate(matches):
            rebuilt.append(value[cursor:match.start()])
            rebuilt.append(asset if keep_first and match_index == 0 else replacement)
            cursor = match.end()
        rebuilt.append(value[cursor:])
        value = "".join(rebuilt)
    return value


def filter_static_light_text(value: object, allow_dynamic: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    retained: list[str] = []
    for clause in (item.strip() for item in re.split(r"[，；。]", text) if item.strip()):
        has_static_light = any(term in clause for term in STATIC_LIGHT_TERMS)
        has_dynamic_light = any(marker in clause for marker in DYNAMIC_LIGHT_MARKERS)
        if has_static_light and not (allow_dynamic and has_dynamic_light):
            continue
        retained.append(clause)
    return "，".join(retained)


def strip_static_light_descriptors(value: object) -> str:
    """Remove static light-source/color wording while retaining camera or transition facts."""
    text = str(value or "").strip()
    if not text:
        return ""
    dynamic_light = re.compile(
        r"(?:灯|光|屏幕|车灯).{0,8}(?:开启|打开|亮起|熄灭|关闭|闪烁|闪动|扫过|掠过|照到脸|照在脸|由暗变亮|由亮变暗)"
        r"|(?:开启|打开|亮起|熄灭|关闭|闪烁|闪动|扫过|掠过|由暗变亮|由亮变暗).{0,8}(?:灯|光|屏幕|车灯)"
    )
    cleaned: list[str] = []
    for clause in (item.strip() for item in text.split("；") if item.strip()):
        if not dynamic_light.search(clause):
            clause = re.sub(r"(?:蓝色|红色|紫色|彩色|冷色调|暖色调|蓝光|红光|冷光|暖光|霓虹色)", "", clause)
            clause = re.sub(r"(?:固定)?(?:灯带|吊灯|氛围灯|霓虹灯|顶光|背景灯)(?:持续发光)?", "", clause)
        clause = re.sub(r"\s+", " ", clause).strip(" ，；")
        if clause:
            cleaned.append(clause)
    return "；".join(cleaned)


def render_generation_facts(record: dict) -> str:
    facts = record.get("generation_facts")
    if not isinstance(facts, dict):
        return filter_static_light_text(record.get("lighting_composition"))
    subject_lighting = facts.get("subject_lighting", facts.get("light_direction_color", ""))
    values = (
        ("主体受光", filter_static_light_text(subject_lighting, allow_dynamic=True)),
        ("明暗", filter_static_light_text(facts.get("contrast_exposure"))),
        ("景深", str(facts.get("depth_of_field") or "").strip()),
        ("焦点变化", str(facts.get("focus_transition") or "").strip()),
        ("构图变化", str(facts.get("composition_change") or "").strip()),
        ("动态环境", filter_static_light_text(facts.get("dynamic_environment"), allow_dynamic=True)),
    )
    return "，".join(f"{label}={value}" for label, value in values if value)


def render_prop_continuity(record: dict) -> str:
    parts: list[str] = []
    for prop in record.get("prop_continuity") or []:
        if not isinstance(prop, dict) or not str(prop.get("identity") or "").strip():
            continue
        facts = [str(prop.get("identity") or "").strip()]
        labels = (
            ("实例", "instance_id"),
            ("可见数量", "visible_instance_count"),
            ("外观不变量", "appearance_invariants"),
            ("持有者", "holder"),
            ("接触", "support_contact"),
            ("首帧", "start_state"),
            ("动作", "middle_action"),
            ("尾帧", "end_state"),
            ("来源", "source"),
            ("前镜继承", "continuity_from_previous"),
            ("后镜保持", "continuity_to_next"),
            ("交接后唯一持有者", "exclusive_holder_after"),
        )
        facts.extend(
            f"{label}={str(prop.get(field) or '').strip()}"
            for label, field in labels
            if str(prop.get(field) or "").strip()
        )
        parts.append("，".join(facts))
    return "；".join(parts)


def collect_prop_continuity_warnings(records: list[dict]) -> dict[int, list[str]]:
    """Warn about likely prop-source breaks; never block, rewrite, or rerun."""
    result: dict[int, list[str]] = {id(record): [] for record in records}
    previous_props: dict[str, dict] = {}
    for record in records:
        warnings = result[id(record)]
        props = [item for item in (record.get("prop_continuity") or []) if isinstance(item, dict)]
        record_action = " ".join(
            str(record.get(field) or "")
            for field in ("transient_visual_details", "visible_action", "contact_actions", "initial_frame", "final_frame")
        )
        if not props:
            character_actions = " ".join(
                str(character.get("character_action") or "")
                for character in (record.get("visible_characters") or [])
                if isinstance(character, dict)
            )
            action_evidence = " ".join((record_action, character_actions))
            if any(marker in action_evidence for marker in PROP_ACTION_MARKERS):
                warnings.append("soft_prop_continuity: 临时道具参与动作但缺少prop_continuity；仅提醒，不阻止输出")
            previous_props = {}
            continue
        current_props: dict[str, dict] = {}
        for prop in props:
            identity = str(prop.get("identity") or "").strip()
            if not identity:
                warnings.append("soft_prop_continuity: 道具连续性记录缺少identity；仅提醒，不阻止输出")
                continue
            instance_id = str(prop.get("instance_id") or "").strip()
            key = re.sub(r"\s+", "", instance_id or identity).lower()
            if key in current_props:
                warnings.append(f"soft_prop_continuity: {identity}的同一instance_id在单镜重复出现；仅提醒，不阻止输出")
            current_props[key] = prop
            source = str(prop.get("source") or "").strip()
            start_state = str(prop.get("start_state") or "").strip()
            middle_action = str(prop.get("middle_action") or "").strip()
            previous = previous_props.get(key)
            action_blob = " ".join((record_action, start_state, middle_action, str(prop.get("end_state") or "")))
            if previous is None and any(marker in action_blob for marker in PROP_ACTION_MARKERS) and source in {"", "unclear", "未知", "待确认"}:
                warnings.append(f"soft_prop_continuity: {identity}首次参与动作但来源不清；仅提醒，不阻止输出")
            if previous is not None:
                inherited = str(prop.get("continuity_from_previous") or "").strip()
                if inherited in {"", "none", "unclear", "未知", "待确认"}:
                    warnings.append(f"soft_prop_continuity: {identity}与上一镜的继承关系不清；仅提醒，不阻止输出")
                previous_holder = str(previous.get("holder") or "").strip()
                current_holder = str(prop.get("holder") or "").strip()
                if previous_holder and current_holder and previous_holder != current_holder and not any(
                    marker in action_blob for marker in PROP_TRANSFER_MARKERS
                ):
                    warnings.append(f"soft_prop_continuity: {identity}持有者由{previous_holder}变为{current_holder}但未写交接动作；仅提醒，不阻止输出")
        previous_props = current_props
    return result


def relative_blocking_text(record: dict, max_relations: int = 4, max_evidence_chars: int = 48) -> str:
    horizontal_labels = {
        "left_of": "位于左侧",
        "right_of": "位于右侧",
        "overlapping": "画面横向重叠",
        "unclear": "横向关系不确定",
    }
    depth_labels = {
        "in_front_of": "更靠近镜头",
        "behind": "距离镜头更远",
        "same_plane": "处于同一纵深",
        "unclear": "前后关系不确定",
    }
    occlusion_labels = {
        "blocks": "遮挡对方",
        "blocked_by": "被对方遮挡",
        "none": "无直接遮挡",
        "unclear": "遮挡关系不确定",
    }
    facing_labels = {
        "face_to_face": "两人面对面",
        "same_direction": "两人大致同向",
        "back_to_back": "两人背向",
        "crossing": "两人朝向交叉",
        "unclear": "朝向关系不确定",
    }
    ranked: list[tuple[int, int, dict]] = []
    for index, relation in enumerate(record.get("relative_blocking") or []):
        if not isinstance(relation, dict):
            continue
        subject = str(relation.get("subject") or "").strip()
        relative_to = str(relation.get("relative_to") or "").strip()
        if not subject or not relative_to:
            continue
        score = 0
        if str(relation.get("occlusion") or "") in {"blocks", "blocked_by"}:
            score += 8
        if str(relation.get("depth_relation") or "") in {"in_front_of", "behind"}:
            score += 5
        if str(relation.get("facing_relationship") or "") in {"face_to_face", "back_to_back", "crossing"}:
            score += 3
        if str(relation.get("horizontal_relation") or "") in {"left_of", "right_of", "overlapping"}:
            score += 2
        if str(relation.get("evidence") or "").strip():
            score += 1
        if score:
            ranked.append((-score, index, relation))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = sorted(ranked[:max_relations], key=lambda item: item[1])

    parts: list[str] = []
    for _, _, relation in selected:
        subject = str(relation.get("subject") or "").strip()
        relative_to = str(relation.get("relative_to") or "").strip()
        horizontal = horizontal_labels.get(str(relation.get("horizontal_relation") or ""), "横向关系不确定")
        depth = depth_labels.get(str(relation.get("depth_relation") or ""), "前后关系不确定")
        occlusion = occlusion_labels.get(str(relation.get("occlusion") or ""), "遮挡关系不确定")
        facing = facing_labels.get(str(relation.get("facing_relationship") or ""), "朝向关系不确定")
        evidence = str(relation.get("evidence") or "").strip()
        if len(evidence) > max_evidence_chars:
            evidence = evidence[: max_evidence_chars - 1].rstrip() + "…"
        suffix = f"，依据：{evidence}" if evidence else ""
        parts.append(f"{subject}相对{relative_to}：{horizontal}、{depth}、{occlusion}、{facing}{suffix}")
    return "；".join(parts)


def screen_order_transition_text(record: dict) -> str:
    order = record.get("screen_order_left_to_right")
    if not isinstance(order, dict):
        return ""

    def render_anchor(label: str, key: str) -> str:
        values = order.get(key)
        if not isinstance(values, list) or not values:
            return f"{label}=unclear"
        return f"{label}=" + " < ".join(str(value) for value in values)

    parts = [
        render_anchor("首", "start"),
        render_anchor("中", "middle"),
        render_anchor("尾", "end"),
    ]
    transition = record.get("position_transition")
    if isinstance(transition, dict):
        transition_type = str(transition.get("type") or "unclear")
        description = str(transition.get("description") or "").strip()
        timestamps = transition.get("evidence_timestamps")
        timestamp_text = ""
        if isinstance(timestamps, list) and timestamps:
            timestamp_text = "，证据时间=" + "/".join(str(value) for value in timestamps)
        parts.append(f"变化={transition_type}" + (f"，{description}" if description else "") + timestamp_text)
    return "站位时间轴（观众画面坐标，左<右）：" + "；".join(parts)


def compact_person_positions(record: dict) -> str:
    """Render concise per-person geometry while retaining full raw spatial JSON upstream."""
    parts: list[str] = []
    for person in record.get("visible_characters") or []:
        if not isinstance(person, dict):
            continue
        identity = str(person.get("identity") or "").strip()
        if not identity:
            continue
        facts = [str(person.get("screen_position") or "").strip()]
        for label, key in (
            ("景深", "depth_layer"),
            ("姿态", "body_posture"),
            ("躯干", "torso_orientation"),
            ("头部", "head_orientation"),
        ):
            value = str(person.get(key) or "").strip()
            if value and value not in {"unclear", "未知", "待确认"}:
                facts.append(f"{label}={value}")
        parts.append(f"{identity}：" + "，".join(value for value in facts if value))
    return "；".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand a validated compact timeline using deterministic asset and grouping rules.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compact = json.loads(args.input.read_text(encoding="utf-8-sig"))
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    records = compact.get("records") or []
    prop_continuity_warnings = collect_prop_continuity_warnings(records)
    people_rules = config.get("people_rules") or []
    known_person_assets = list(dict.fromkeys(
        str(rule.get("asset") or "").strip()
        for rule in people_rules
        if str(rule.get("asset") or "").strip() and "候选新增" not in str(rule.get("asset") or "")
    ))

    def clean_visual_text(text: object, at_seconds: float, matched_assets: list[str]) -> str:
        localized = replace_people(str(text or ""), at_seconds, people_rules)
        referenced_assets = list(matched_assets)
        referenced_assets.extend(asset for asset in known_person_assets if asset in localized and asset not in referenced_assets)
        return strip_redundant_bound_appearance(localized, referenced_assets)

    def generation_text(text: object, at_seconds: float, matched_assets: list[str], keep_first: bool = False) -> str:
        cleaned = clean_visual_text(text, at_seconds, matched_assets)
        nonvisible_references = [
            asset for asset in known_person_assets
            if asset in cleaned and asset not in matched_assets
        ]
        cleaned = compact_asset_references(cleaned, nonvisible_references, False)
        return compact_asset_references(cleaned, matched_assets, keep_first)

    prop_rules = config.get("prop_rules") or []
    translations = config.get("translations") or {}
    translations_by_dialogue_id = config.get("translations_by_dialogue_id") or {}
    timing_config = config.get("dialogue_timing") or {}
    dialogue_events_by_id = {
        str(item.get("dialogue_id")): item
        for item in compact.get("dialogue_events") or []
        if isinstance(item, dict) and item.get("dialogue_id")
    }
    groups = list(config.get("groups") or [])
    scene_rules = list(config.get("scene_rules") or [])
    scene_resolution_settings = config.get("scene_resolution") if isinstance(config.get("scene_resolution"), dict) else {}
    seam_tolerance = float((config.get("dialogue_segmentation") or {}).get("seam_tolerance_seconds", 0.15))
    dialogue_segments_by_group, dialogue_assembly, dialogue_segmentation_warnings = build_dialogue_segments(
        groups,
        list(dialogue_events_by_id.values()),
        translations,
        translations_by_dialogue_id,
        seam_tolerance,
    )
    rows: list[dict] = []
    group_records: list[list[dict]] = []

    for group_index, group in enumerate(groups, 1):
        start, end = float(group["start"]), float(group["end"])
        selected = [r for r in records if float(r["start_seconds"]) >= start - 0.01 and float(r["end_seconds"]) <= end + 0.01]
        if not selected:
            raise RuntimeError(f"No compact records for configured group {start:.3f}-{end:.3f}")
        configured_scene = str(group.get("scene") or config["default_scene"])
        group_scene, scene_resolution, scene_warnings = resolve_group_scene(
            configured_scene,
            selected,
            scene_rules,
            scene_resolution_settings,
        )
        for record in selected:
            record["_resolved_scene_asset"] = resolve_record_scene_asset(record, group_scene, scene_rules)
        scene_bound = bool(group_scene and "（候选新增" not in group_scene and "(候选新增" not in group_scene)
        configured_time_of_day = str(group.get("time_of_day") or "").strip()
        configured_time_evidence = str(group.get("time_of_day_evidence") or "").strip()
        explicit_times = list(dict.fromkeys(str(record.get("time_of_day") or "unclear") for record in selected if str(record.get("time_of_day") or "unclear") != "unclear"))
        group_time_of_day = configured_time_of_day or (explicit_times[0] if len(explicit_times) == 1 else "mixed" if len(explicit_times) > 1 else "unclear")
        characters: list[str] = []
        linked: list[str] = [group_scene]
        subshots: list[dict] = []
        utterances: list[dict] = []
        for record in selected:
            midpoint = (float(record["start_seconds"]) + float(record["end_seconds"])) / 2
            record_time_of_day = str(record.get("time_of_day") or "unclear")
            record_time_evidence = str(record.get("time_of_day_evidence") or "")
            if record_time_of_day == "unclear" and configured_time_of_day:
                record_time_of_day = configured_time_of_day
                record_time_evidence = configured_time_evidence or "由同一连续场景中相邻、具直接光线证据的镜头继承"
            record_time_evidence = compact_time_evidence(record_time_of_day, record_time_evidence)
            assets = person_assets(record, people_rules)
            for asset in assets:
                if asset not in characters:
                    characters.append(asset)
                if asset not in linked:
                    linked.append(asset)
            source_people_parts: list[str] = []
            for person in record.get("visible_characters") or []:
                person_match_text = " ".join(str(person.get(key, "")) for key in ("identity", "appearance"))
                bound_person_asset = match_rule(person_match_text, midpoint, people_rules, "aliases")
                appearance = str(person.get("appearance") or "").strip()
                facts = [
                    str(person.get("identity") or ""),
                ]
                if not bound_person_asset and appearance and appearance != "asset_bound":
                    facts.insert(1, appearance)
                optional_facts = [
                    ("身体姿态", person.get("body_posture")),
                    ("清晰状态", person.get("focus_state")),
                    ("面部表情", person.get("facial_expression")),
                    ("人物动作", person.get("character_action")),
                ]
                facts.extend(f"{label}：{value}" for label, value in optional_facts if str(value or "").strip())
                source_people_parts.append("，".join(value for value in facts if value))
            source_people = "; ".join(source_people_parts)
            description_parts = [
                "" if scene_bound else record.get("scene_observation", ""),
                f"出镜资产：{'、'.join(assets)}" if assets else "",
                f"昼夜/光景：{record_time_of_day}；依据：{record_time_evidence}",
                f"主画面主体：{record.get('primary_visible_subject', '')}",
            ]
            if record.get("focus_subject"):
                description_parts.append(f"焦点策略：{record.get('focus_policy', 'unclear')}")
            if source_people:
                description_parts.append(f"可见人物：{source_people}")
            blocking_text = relative_blocking_text(record)
            screen_order_text = screen_order_transition_text(record)
            transient_details = str(record.get("transient_visual_details") or "").strip()
            if not transient_details and not scene_bound:
                transient_details = str(record.get("visual_details") or "").strip()
            description_parts.append(transient_details)
            prop_continuity_text = render_prop_continuity(record)
            if prop_continuity_text:
                description_parts.append(f"道具连续性：{prop_continuity_text}")
            if not source_people:
                description_parts.append(record.get("visible_action", ""))
            if record.get("sound"):
                description_parts.append(f"声音：{record['sound']}")
            description = generation_text("。".join(part.strip("。") for part in description_parts if part), midpoint, assets, keep_first=True)
            subshots.append({
                "start_seconds": float(record["start_seconds"]),
                "end_seconds": float(record["end_seconds"]),
                "shot_size": SHOT_SIZE.get(record.get("shot_size"), "中景"),
                "camera_angle": ANGLE.get(record.get("camera_angle"), "平视"),
                "time_of_day": record_time_of_day,
                "time_of_day_evidence": record_time_evidence,
                "description": description,
                "spatial_positions": generation_text("；".join(value for value in (screen_order_text, compact_person_positions(record), blocking_text) if value), midpoint, assets),
                "contact_actions": generation_text(str(record.get("contact_actions") or "无"), midpoint, assets),
                "environment_motion": generation_text(strip_static_light_descriptors(f"{record.get('camera_motion', 'static')}；转场：{record.get('transition', '')}"), midpoint, assets),
                "evidence": [f"video@{float(record['start_seconds']):.3f}-{float(record['end_seconds']):.3f}"],
                "confidence": record.get("confidence", "medium"),
            })
            blob = record_blob(record)
            for prop in prop_rules:
                if midpoint < float(prop.get("start", 0)) - 0.01 or midpoint > float(prop.get("end", 10**9)) + 0.01:
                    continue
                if any(keyword in blob for keyword in prop.get("keywords") or []) and prop["asset"] not in linked:
                    linked.append(prop["asset"])
        if not characters:
            for record in selected:
                for person in record.get("visible_characters") or []:
                    identity = str(person.get("identity") or "").strip()
                    if identity.startswith("背景路人") and identity not in characters:
                        characters.append(identity)
        utterances = []
        for segment in dialogue_segments_by_group.get(group_index) or []:
            item = dict(segment)
            item["speaker_asset"] = resolve_dialogue_speaker_asset(item, selected, people_rules)
            utterances.append(item)

        timeline = lambda key: "；".join(f"{float(r['start_seconds']):.3f}-{float(r['end_seconds']):.3f} {replace_people(str(r.get(key) or ''), (float(r['start_seconds'])+float(r['end_seconds']))/2, people_rules)}" for r in selected)
        generation_timeline = "；".join(
            f"{float(r['start_seconds']):.3f}-{float(r['end_seconds']):.3f} {render_generation_facts(r)}"
            for r in selected
            if render_generation_facts(r)
        )
        person_expression_parts = []
        for record in selected:
            midpoint = (float(record["start_seconds"]) + float(record["end_seconds"])) / 2
            states = []
            for person in record.get("visible_characters") or []:
                identity = str(person.get("identity") or "可见人物")
                expression = str(person.get("facial_expression") or "").strip()
                gaze = str(person.get("gaze_direction") or "").strip()
                if expression or gaze:
                    states.append(f"{identity}：表情={expression or 'unclear'}，视线={gaze or 'unclear'}")
            summary = "；".join(states) or str(record.get("expression_gaze") or "")
            person_expression_parts.append(
                f"{float(record['start_seconds']):.3f}-{float(record['end_seconds']):.3f} {replace_people(summary, midpoint, people_rules)}"
            )
        chinese = "；".join(str(item.get("text") or "") for item in utterances if item.get("text"))
        english_parts = []
        sound_parts = []
        dialogue_delivery = []
        row_dialogue_warnings: list[str] = []
        for item in utterances:
            text = str(item.get("text") or "")
            dialogue_id = str(item.get("dialogue_id") or "").strip()
            translated = str(item.get("localized_text") or translations_by_dialogue_id.get(dialogue_id) or translations.get(text) or "").strip()
            if text and not translated:
                raise RuntimeError(f"Missing British-localized dialogue for {dialogue_id or text!r}")
            if translated == text or CJK_RE.search(translated):
                raise RuntimeError(f"British-localized dialogue remains Chinese for {dialogue_id or text!r}: {translated}")
            speaker = item.get("speaker_asset") or "现场说话人"
            source_event = item.get("source_event") if isinstance(item.get("source_event"), dict) else dialogue_events_by_id.get(dialogue_id) or item
            localized_delivery = build_localized_delivery(source_event, translated, timing_config)
            english_parts.append(f"{speaker}: {translated}")
            sound_parts.append(
                f"[{float(source_event.get('start_seconds', item.get('start_seconds', 0))):.3f}-"
                f"{float(source_event.get('end_seconds', item.get('end_seconds', 0))):.3f}] {speaker}: {translated}；"
                f"表演指导（不朗读）：{localized_delivery['performance_direction']}"
            )
            dialogue_delivery.append({
                "dialogue_id": dialogue_id,
                "dialogue_segment_id": item.get("dialogue_segment_id") or f"{dialogue_id}-S01",
                "segment_index": int(item.get("segment_index") or 1),
                "segment_count": int(item.get("segment_count") or 1),
                "continuation": item.get("continuation") or "whole",
                "start_seconds": float(item.get("start_seconds", source_event.get("start_seconds", 0))),
                "end_seconds": float(item.get("end_seconds", source_event.get("end_seconds", 0))),
                "speaker": speaker,
                "source_text": text,
                "localized_text": translated,
                "boundary_snap_seconds": float(item.get("boundary_snap_seconds") or 0.0),
                **localized_delivery,
            })
            if localized_delivery["timing_status"] == "needs_condense":
                row_dialogue_warnings.append(
                    f"{dialogue_id or text}: localized dialogue exceeds {localized_delivery['hard_limit_wps']:.2f} words/s and must be condensed"
                )
        row = {
            "episode": str(config.get("episode") or compact.get("episode")).zfill(2),
            "group_id": f"EP{int(config.get('episode') or compact.get('episode')):02d}-G{group_index:03d}",
            "start_seconds": start,
            "end_seconds": end,
            "scene": group_scene,
            "scene_resolution": scene_resolution,
            "time_of_day": group_time_of_day,
            "time_of_day_evidence": compact_time_evidence(group_time_of_day, configured_time_evidence or timeline("time_of_day_evidence")),
            "main_characters": characters,
            "subshots": subshots,
            "narrative_summary": generation_text(str(group.get("summary") or selected[0].get("beat_summary") or ""), start, characters),
            "camera_trajectory": generation_text(strip_static_light_descriptors(timeline("transition")), start, characters),
            "composition": generation_text(f"昼夜/光景：{group_time_of_day}；依据：{compact_time_evidence(group_time_of_day, timeline('time_of_day_evidence'))}；{generation_timeline}", start, characters),
            "initial_frame": generation_text(str(selected[0].get("initial_frame") or ""), start, characters),
            "final_frame": generation_text(str(selected[-1].get("final_frame") or ""), end - 0.001, characters),
            "mouth_dynamics": generation_text(timeline("mouth_dynamics"), start, characters),
            "expressions_gaze": generation_text("；".join(person_expression_parts), start, characters),
            "sound_dialogue": " | ".join(sound_parts),
            "chinese_dialogue": chinese,
            "british_localized_dialogue": " | ".join(english_parts),
            "dialogue_delivery": dialogue_delivery,
            "linked_assets": linked,
            "camera_view": selected[0].get("camera_view") or "2 正视",
            "within_group_view_change": " → ".join(str(r.get("camera_view") or "2 正视") for r in selected),
            "warnings": [warning for r in selected for warning in (r.get("warnings") or [])]
            + [warning for r in selected for warning in prop_continuity_warnings.get(id(r), [])]
            + scene_warnings
            + row_dialogue_warnings,
        }
        rows.append(row)
        group_records.append(selected)

    continuity_handoff_contract, continuity_handoffs = attach_group_continuity_handoffs(
        rows,
        group_records,
        compact,
    )

    output = {
        "schema_version": "1.0",
        "source": {"compact_timeline": str(args.input)},
        "dialogue_translation_contract": {
            "lookup": "dialogue_id_then_legacy_exact_text",
            "missing_translation_policy": "error",
            "cjk_in_translated_text_policy": "error",
            "localized_text_is_speakable_only": True,
            "delivery_instruction_field": "rows[].dialogue_delivery[].performance_direction",
            "overlong_translation_policy": "condense_before_export",
            "default_hard_limit_wps": float(timing_config.get("hard_limit_wps", 4.5)),
        },
        "dialogue_segmentation_contract": {
            "authority": "local_deterministic_assembly",
            "one_segment_owner": True,
            "seam_tolerance_seconds": seam_tolerance,
            "split_strategy": "time_weighted_with_punctuation_preference",
            "duplicate_full_event_across_groups": "error",
        },
        "asset_binding_contract": {
            "person_fixed_appearance_source": "exact person-wardrobe/state asset",
            "scene_fixed_detail_source": "exact scene asset",
            "scene_resolution": "configured scene is corrected only by dominant per-record fixed visual evidence from explicit scene_rules",
            "expanded_visual_prose_policy": "omit bound person clothing and bound scene static details; retain actions, blocking, focus state, lighting, camera, and transient plot objects",
            "on_screen_text_policy": "retain source text in compact evidence only; exclude it from generation prose unless an explicit British-localized text rule is supplied",
            "spatial_render_policy": "retain complete structured relative_blocking in compact records; render only the highest-value relations with capped evidence in generation prose",
        },
        "continuity_handoff_contract": continuity_handoff_contract,
        "continuity_handoffs": continuity_handoffs,
        "dialogue_assembly": dialogue_assembly,
        "rows": rows,
        "warnings": (compact.get("warnings") or [])
        + dialogue_segmentation_warnings
        + [warning for record in records for warning in prop_continuity_warnings.get(id(record), [])],
        "errors": [],
    }
    dump(args.output, output)
    print(json.dumps({"status": "complete", "groups": len(rows), "subshots": sum(len(row["subshots"]) for row in rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

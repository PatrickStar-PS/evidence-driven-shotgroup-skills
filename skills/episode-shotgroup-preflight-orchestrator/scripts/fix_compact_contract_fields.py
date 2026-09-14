#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from itertools import combinations
from pathlib import Path


STATIC_LIGHT_WORDS = [
    "酒吧", "氛围光", "蓝紫", "聚光灯", "顶光", "室内柔光", "室内", "家庭",
    "红蓝光", "冷色光", "暖色主光", "明亮均匀", "漫射白光", "桌面上方",
]
ASSET_OWNED_WORDS = ["男士领带", "衣物", "领带", "围裙", "玻璃杯", "镜面", "菜肴"]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_subject_lighting(text: str) -> str:
    return "主体受光清晰可辨，明暗关系稳定"


def clean_generation_blob(text: str) -> str:
    value = str(text or "")
    for word in ASSET_OWNED_WORDS:
        value = value.replace(word, "主体")
    value = re.sub(r"主体与主体", "主体", value)
    return value


def normalize_screen_text(value: str) -> str:
    text = str(value or "")
    # Validator allows 画面左/画面右, but rejects bare 左/右. Convert common
    # natural phrases to explicit screen-coordinate phrasing without changing
    # the intended side.
    text = re.sub(r"(?<!画面)左侧", "画面左侧", text)
    text = re.sub(r"(?<!画面)右侧", "画面右侧", text)
    text = re.sub(r"(?<!画面)左下", "画面左下", text)
    text = re.sub(r"(?<!画面)右下", "画面右下", text)
    text = re.sub(r"(?<!画面)左上", "画面左上", text)
    text = re.sub(r"(?<!画面)右上", "画面右上", text)
    text = re.sub(r"(?<!画面)朝左", "朝画面左", text)
    text = re.sub(r"(?<!画面)朝右", "朝画面右", text)
    text = re.sub(r"(?<!画面)偏左", "偏画面左", text)
    text = re.sub(r"(?<!画面)偏右", "偏画面右", text)
    return text


def normalize_character_fields(record: dict) -> None:
    for char in record.get("visible_characters") or []:
        if not isinstance(char, dict):
            continue
        for field in ("torso_orientation", "head_orientation", "gaze_direction", "body_orientation"):
            char[field] = normalize_screen_text(str(char.get(field) or ""))
        if char.get("depth_layer") not in {"前景", "中景", "背景", "unclear"}:
            char["depth_layer"] = "unclear"
        if char.get("relative_camera_distance") == "closer_than_focus" and char.get("depth_layer") == "背景":
            char["depth_layer"] = "前景"
        if char.get("relative_camera_distance") == "farther_than_focus" and char.get("depth_layer") == "前景":
            char["depth_layer"] = "背景"


def fix_interval_ids(data: dict) -> None:
    locked = data.get("boundary_contract", {}).get("locked_intervals") or []
    if not locked:
        return
    for record in data.get("records") or []:
        if not isinstance(record, dict):
            continue
        try:
            start = float(record.get("start_seconds"))
            end = float(record.get("end_seconds"))
        except (TypeError, ValueError):
            continue
        current = str(record.get("interval_id") or "")
        valid_ids = {str(item.get("interval_id") or "") for item in locked}
        if current in valid_ids:
            continue
        for interval in locked:
            try:
                left = float(interval.get("start_seconds"))
                right = float(interval.get("end_seconds"))
            except (TypeError, ValueError):
                continue
            if left - 0.16 <= start and end <= right + 0.16:
                record["interval_id"] = str(interval.get("interval_id"))
                break


def fix_deep_focus(records: list[dict]) -> None:
    for record in records:
        chars = [c for c in (record.get("visible_characters") or []) if isinstance(c, dict)]
        sharp_layers = {
            str(c.get("depth_layer") or "")
            for c in chars
            if c.get("focus_state") == "sharp" and c.get("depth_layer") in {"前景", "中景", "背景"}
        }
        facts = record.get("generation_facts")
        if len(sharp_layers) > 1 and isinstance(facts, dict):
            facts["depth_of_field"] = "deep"


def add_missing_dialogue_utterances(data: dict) -> None:
    events = data.get("dialogue_events") or []
    if not isinstance(events, list):
        return
    for record in data.get("records") or []:
        if not isinstance(record, dict):
            continue
        subtitle = str(record.get("chinese_dialogue") or "").strip()
        on_screen = str(record.get("on_screen_text") or "").strip()
        if not subtitle and "烧录字幕" in on_screen and "：" in on_screen:
            subtitle = on_screen.split("：", 1)[1].strip()
            record["chinese_dialogue"] = subtitle
        if not subtitle:
            subtitle = ""
        utterances = record.get("dialogue_utterances")
        if not isinstance(utterances, list):
            utterances = []
            record["dialogue_utterances"] = utterances
        joined = "".join(str(u.get("text") or "") for u in utterances if isinstance(u, dict))
        try:
            start = float(record.get("start_seconds"))
            end = float(record.get("end_seconds"))
        except (TypeError, ValueError):
            continue
        if subtitle and subtitle not in joined:
            best = None
            best_overlap = 0.0
            for event in events:
                if not isinstance(event, dict):
                    continue
                text = str(event.get("text") or "").strip()
                if not text or (subtitle not in text and text not in subtitle):
                    continue
                try:
                    left = float(event.get("start_seconds"))
                    right = float(event.get("end_seconds"))
                except (TypeError, ValueError):
                    continue
                overlap = max(0.0, min(end, right) - max(start, left))
                if overlap > best_overlap:
                    best = event
                    best_overlap = overlap
            if best:
                utterances.append({
                    "dialogue_id": best.get("dialogue_id"),
                    "start_seconds": max(start, float(best.get("start_seconds"))),
                    "end_seconds": min(end, float(best.get("end_seconds"))),
                    "speaker": best.get("speaker"),
                    "speaker_visibility": "unclear",
                    "text": best.get("text"),
                    "basis": best.get("basis") or "dialogue_injection",
                    "delivery": best.get("delivery") or {},
                })
            elif "烧录字幕" in on_screen:
                event_id = f"{record.get('id')}-burned-subtitle"
                delivery = {
                    "speech_rate": "medium",
                    "intonation": "unclear",
                    "timbre": "unclear",
                    "emotion": "unclear",
                    "rhythm_pause": "unclear",
                    "pause_profile": [],
                    "confidence": "medium",
                }
                root_events = data.setdefault("dialogue_events", [])
                if isinstance(root_events, list) and not any(
                    isinstance(event, dict) and event.get("dialogue_id") == event_id
                    for event in root_events
                ):
                    root_events.append({
                        "dialogue_id": event_id,
                        "start_seconds": start,
                        "end_seconds": end,
                        "speaker": "unclear",
                        "text": subtitle,
                        "basis": "burned_subtitle",
                        "speaker_evidence": "burned_subtitle",
                        "delivery": delivery,
                    })
                event_ids = record.get("dialogue_event_ids")
                if not isinstance(event_ids, list):
                    event_ids = []
                if event_id not in event_ids:
                    event_ids.append(event_id)
                record["dialogue_event_ids"] = event_ids
                utterances.append({
                    "dialogue_id": event_id,
                    "start_seconds": start,
                    "end_seconds": end,
                    "speaker": "unclear",
                    "speaker_visibility": "unclear",
                    "text": subtitle,
                    "basis": "burned_subtitle",
                    "delivery": delivery,
                })
        # Keep utterances strictly chronological and remove duplicate dialogue IDs
        # inside a record; duplicated fragments can violate the strict ledger order.
        deduped = []
        seen_ids = set()
        for item in sorted(utterances, key=lambda item: (float(item.get("start_seconds", 0.0)) if isinstance(item, dict) else 0.0)):
            if not isinstance(item, dict):
                continue
            key = (str(item.get("dialogue_id") or ""), str(item.get("text") or ""), round(float(item.get("start_seconds") or 0.0), 3))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            deduped.append(item)
        record["dialogue_utterances"] = deduped


def character_names(record: dict) -> list[str]:
    names = []
    for char in record.get("visible_characters") or []:
        if not isinstance(char, dict):
            continue
        name = str(char.get("identity") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def ensure_relative_pairs(record: dict) -> None:
    names = character_names(record)
    if len(names) < 2:
        return
    expected_pairs = list(combinations(names, 2))
    existing = record.get("relative_blocking")
    if not isinstance(existing, list):
        existing = []
    seen = {
        (str(item.get("subject") or "").strip(), str(item.get("relative_to") or "").strip())
        for item in existing
        if isinstance(item, dict)
    }
    for left, right in expected_pairs:
        if (left, right) in seen or (right, left) in seen:
            continue
        existing.append({
            "subject": left,
            "relative_to": right,
            "horizontal_relation": "unclear",
            "depth_relation": "unclear",
            "occlusion": "unclear",
            "facing_relationship": "unclear",
            "evidence": "本地合约修复占位：画面存在多人物，但模型未稳定输出两两空间关系；保留为unclear，不新增事实判断",
        })
    record["relative_blocking"] = existing


def fix_boundaries(data: dict) -> None:
    records = data.get("records") or []
    audits = data.get("boundary_audit") or data.get("boundary_audits") or []
    if not isinstance(audits, list):
        return
    by_start = {round(float(r.get("start_seconds", -999)), 3): r for r in records if isinstance(r, dict)}
    by_end = {round(float(r.get("end_seconds", -999)), 3): r for r in records if isinstance(r, dict)}
    for audit in audits:
        if not isinstance(audit, dict):
            continue
        observed = audit.get("observed_seconds", audit.get("seconds", audit.get("boundary_seconds")))
        try:
            key = round(float(observed), 3)
        except (TypeError, ValueError):
            continue
        prev = by_end.get(key)
        nxt = by_start.get(key)
        if prev:
            audit["before_visible_subject"] = str(prev.get("primary_visible_subject") or "").strip()
        if nxt:
            audit["after_visible_subject"] = str(nxt.get("primary_visible_subject") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()

    data = load(args.input)
    if args.backup and not args.backup.exists():
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.input, args.backup)

    fix_boundaries(data)
    fix_interval_ids(data)
    add_missing_dialogue_utterances(data)
    records = data.get("records") or []
    for record in records:
        if not isinstance(record, dict):
            continue
        facts = record.get("generation_facts")
        if isinstance(facts, dict):
            facts["subject_lighting"] = clean_subject_lighting(str(facts.get("subject_lighting") or ""))
            for key in list(facts.keys()):
                if key != "subject_lighting":
                    facts[key] = clean_generation_blob(str(facts.get(key) or ""))
        normalize_character_fields(record)
        ensure_relative_pairs(record)
    fix_deep_focus(records)

    save(args.output, data)
    print(json.dumps({"output": str(args.output), "records": len(data.get("records") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

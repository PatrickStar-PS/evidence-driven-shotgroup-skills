#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from timeline_contract import dialogue_fingerprint


def normalized(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value or "")).lower()


def direction_from_text(value: object) -> str:
    text = str(value or "")
    if "画面左" in text or "screen_left" in text:
        return "screen_left"
    if "画面右" in text or "screen_right" in text:
        return "screen_right"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply high-confidence local profile direction hints to compact primary subjects.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    dialogue_before = dialogue_fingerprint(data)
    evidence = json.loads(args.evidence_manifest.read_text(encoding="utf-8-sig"))
    samples = evidence.get("spatial_profile_hints") or []
    fixes: list[str] = []

    for record_index, record in enumerate(data.get("records") or [], 1):
        start = float(record.get("start_seconds", 0))
        end = float(record.get("end_seconds", start))
        candidates: list[tuple[int, str, float]] = []
        for sample in samples:
            timestamp = float(sample.get("timestamp", -1))
            if not (start - 0.01 <= timestamp < end + 0.01):
                continue
            for hint in sample.get("hints") or []:
                box = hint.get("box") or [0, 0, 0, 0]
                candidates.append((int(box[2]) * int(box[3]), str(hint.get("direction") or ""), timestamp))
        if not candidates:
            continue
        candidates.sort(reverse=True)
        _area, direction, timestamp = candidates[0]
        if direction not in {"screen_left", "screen_right"}:
            continue
        primary = normalized(record.get("primary_visible_subject"))
        people = record.get("visible_characters") or []
        person = next((item for item in people if primary and (primary in normalized(item.get("identity")) or normalized(item.get("identity")) in primary)), None)
        if not isinstance(person, dict):
            continue
        chinese_direction = "画面左" if direction == "screen_left" else "画面右"
        opposite = "画面右" if direction == "screen_left" else "画面左"
        torso = str(person.get("torso_orientation") or "unclear")
        if opposite in torso:
            torso = "unclear（侧脸检测与原躯干方向冲突）"
            person["torso_orientation"] = torso
        person["head_orientation"] = f"头部朝{chinese_direction}（本地侧脸检测）"
        person["orientation_evidence"] = f"{timestamp:.3f}秒自动空间代表帧的OpenCV侧脸检测指向{chinese_direction}"
        person["body_orientation"] = f"躯干：{torso}；头部：朝{chinese_direction}"
        if opposite in str(person.get("gaze_direction") or ""):
            person["gaze_direction"] = "unclear"
            person["gaze_target"] = "unclear"
        primary_direction = direction
        for relation in record.get("relative_blocking") or []:
            if normalized(relation.get("subject")) == normalized(person.get("identity")):
                other_name = relation.get("relative_to")
            elif normalized(relation.get("relative_to")) == normalized(person.get("identity")):
                other_name = relation.get("subject")
            else:
                continue
            other = next((item for item in people if normalized(item.get("identity")) == normalized(other_name)), None)
            other_direction = direction_from_text(other.get("head_orientation")) if isinstance(other, dict) else ""
            if other_direction and other_direction == primary_direction:
                relation["facing_relationship"] = "same_direction"
                relation["evidence"] = f"本地主体侧脸检测与另一人物头部字段均指向{chinese_direction}；两人同向而非面对面"
        fixes.append(f"record {record_index}: applied {direction} profile hint at {timestamp:.3f}s to primary subject")

    data.setdefault("warnings", []).append(f"Applied {len(fixes)} local high-confidence profile-direction hints; frontal or ambiguous faces were not changed.")
    data["profile_orientation_fixes"] = fixes
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dialogue_after = dialogue_fingerprint(data)
    if dialogue_after != dialogue_before:
        raise RuntimeError("Profile-orientation patch changed the frozen dialogue contract")
    data["dialogue_fingerprint"] = dialogue_after
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(data.get("records") or []), "fixes": len(fixes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

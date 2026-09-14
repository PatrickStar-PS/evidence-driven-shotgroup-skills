#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from timeline_contract import dialogue_fingerprint


PERSON_FIELDS = {
    "screen_position", "torso_orientation", "head_orientation", "body_orientation",
    "gaze_direction", "gaze_target", "depth_layer", "relative_camera_distance",
    "frame_occupancy", "frame_crop", "occlusion_relation", "depth_evidence",
    "orientation_evidence",
}
RELATION_FIELDS = {
    "horizontal_relation", "depth_relation", "occlusion", "facing_relationship", "evidence",
}
DEPTH_ONLY_PERSON_FIELDS = {
    "screen_position", "depth_layer", "relative_camera_distance", "frame_occupancy",
    "frame_crop", "occlusion_relation", "depth_evidence",
}
DEPTH_ONLY_RELATION_FIELDS = {"horizontal_relation", "depth_relation", "occlusion", "evidence"}


def normalized(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value or "")).lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a focused spatial patch without changing times, identities, dialogue, or actions.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--depth-only", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    dialogue_before = dialogue_fingerprint(data)
    patch = json.loads(args.patch.read_text(encoding="utf-8-sig"))
    fixes: list[str] = []

    for correction in patch.get("corrections") or []:
        start = float(correction.get("start_seconds", -1))
        end = float(correction.get("end_seconds", -1))
        record = next((item for item in data.get("records") or [] if abs(float(item.get("start_seconds", -9)) - start) <= 0.15 and abs(float(item.get("end_seconds", -9)) - end) <= 0.15), None)
        if not isinstance(record, dict):
            continue
        for corrected_person in correction.get("visible_characters") or []:
            identity = normalized(corrected_person.get("identity"))
            person = next((item for item in record.get("visible_characters") or [] if normalized(item.get("identity")) == identity), None)
            if not isinstance(person, dict):
                continue
            for field in (DEPTH_ONLY_PERSON_FIELDS if args.depth_only else PERSON_FIELDS):
                value = corrected_person.get(field)
                if value is not None and str(value).strip():
                    person[field] = value
            fixes.append(f"{start:.3f}-{end:.3f}: updated spatial fields for {corrected_person.get('identity')}")
        corrected_relations = correction.get("relative_blocking") or []
        for corrected_relation in corrected_relations:
            pair = {normalized(corrected_relation.get("subject")), normalized(corrected_relation.get("relative_to"))}
            relation = next((item for item in record.get("relative_blocking") or [] if {normalized(item.get("subject")), normalized(item.get("relative_to"))} == pair), None)
            if not isinstance(relation, dict):
                continue
            for field in (DEPTH_ONLY_RELATION_FIELDS if args.depth_only else RELATION_FIELDS):
                value = corrected_relation.get(field)
                if value is not None and str(value).strip():
                    relation[field] = value
            fixes.append(f"{start:.3f}-{end:.3f}: updated pairwise spatial relation")

    data.setdefault("warnings", []).append(f"Applied {len(fixes)} focused image-only spatial field updates; no times, identities, dialogue, or actions changed.")
    data["spatial_patch_fixes"] = fixes
    dialogue_after = dialogue_fingerprint(data)
    if dialogue_after != dialogue_before:
        raise RuntimeError("Spatial patch changed the frozen dialogue contract")
    data["dialogue_fingerprint"] = dialogue_after
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(data.get("records") or []), "fixes": len(fixes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

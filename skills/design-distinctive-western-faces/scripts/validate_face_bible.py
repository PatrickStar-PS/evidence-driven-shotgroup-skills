#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "1.0-distinctive-western-cast-faces"
AXES = (
    "outline", "forehead", "cheekbones", "jaw", "chin", "brows",
    "eyes", "nose", "mouth", "skin_detail", "hairline", "hair_colour", "asymmetry",
)
STRUCTURAL = {"outline", "forehead", "cheekbones", "jaw", "eyes", "nose"}
VAGUE = re.compile(r"\b(western face|european beauty|handsome ceo|beautiful face|high-class features)\b", re.I)
CJK = re.compile(r"[\u3400-\u9fff]")


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError("JSON root must be an object")
    return value


def text(value: Any) -> str:
    return " ".join(str(value or "").split())


def signature(character: dict[str, Any]) -> tuple[str, ...]:
    axes = character.get("feature_axes") or {}
    return tuple(text(axes.get(axis)).casefold() for axis in AXES)


def write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a distinctive cast face bible and export prompt/collision CSV files.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--normalized-json", type=Path)
    parser.add_argument("--prompt-csv", type=Path)
    parser.add_argument("--collision-csv", type=Path)
    args = parser.parse_args()

    payload = load(args.input.resolve())
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != SCHEMA:
        errors.append(f"schema_version must be {SCHEMA}")
    characters = payload.get("characters")
    if not isinstance(characters, list) or not characters:
        errors.append("characters must be a non-empty array")
        characters = []

    names: set[str] = set()
    source_names: set[str] = set()
    signatures: dict[tuple[str, ...], str] = {}
    prompt_rows: list[list[Any]] = []
    collision_rows: list[list[Any]] = []

    for index, character in enumerate(characters, 1):
        label = text(character.get("localized_name")) or f"character {index}"
        source = text(character.get("source_name"))
        if not source or not label:
            errors.append(f"character {index}: source_name and localized_name are required")
        if label.casefold() in names:
            errors.append(f"duplicate localized_name: {label}")
        if source.casefold() in source_names:
            errors.append(f"duplicate source_name: {source}")
        names.add(label.casefold())
        source_names.add(source.casefold())

        axes = character.get("feature_axes")
        if not isinstance(axes, dict):
            errors.append(f"{label}: feature_axes must be an object")
            axes = {}
        missing = [axis for axis in AXES if not text(axes.get(axis))]
        if missing:
            errors.append(f"{label}: missing feature axes: {', '.join(missing)}")

        sig = signature(character)
        if sig in signatures:
            errors.append(f"{label}: exact face signature duplicates {signatures[sig]}")
        signatures[sig] = label

        injection = text(character.get("prompt_injection"))
        negative = text(character.get("negative_prompt"))
        if len(injection) < 300:
            errors.append(f"{label}: prompt_injection is too short for a stable identity lock")
        if VAGUE.search(injection):
            errors.append(f"{label}: prompt_injection uses vague casting language")
        injection_lower = injection.casefold()
        required_prompt_concepts = {
            "outline": ("face", "outline"),
            "eyes": ("eye", "eyelid"),
            "nose": ("nose", "nasal"),
            "jaw": ("jaw",),
            "skin_detail": ("skin", "pore"),
            "hairline": ("hairline", "hair"),
        }
        absent_concepts = [
            name for name, terms in required_prompt_concepts.items()
            if not any(term in injection_lower for term in terms)
        ]
        if absent_concepts:
            errors.append(f"{label}: prompt_injection omits identity concepts: {', '.join(absent_concepts)}")
        if "hair" not in injection_lower or "pure black" not in injection_lower:
            errors.append(f"{label}: prompt_injection must lock non-black hair and explicitly forbid pure black hair")
        if not any(term in injection_lower for term in ("very fair", "pale ivory", "porcelain-fair", "cool-ivory")):
            errors.append(f"{label}: prompt_injection must specify very fair, pale ivory, porcelain-fair, or cool-ivory skin")
        if not any(term in injection_lower for term in ("avoid tan", "golden beige", "bronzed skin")):
            errors.append(f"{label}: prompt_injection must explicitly avoid tanned, golden beige, or bronzed skin")
        if CJK.search(injection):
            warnings.append(f"{label}: prompt_injection contains CJK text; English-only image prompts are preferred")

        contrasts = character.get("contrast_against") or []
        if not isinstance(contrasts, list):
            errors.append(f"{label}: contrast_against must be an array")
            contrasts = []
        for contrast in contrasts:
            other = text((contrast or {}).get("localized_name"))
            differences = (contrast or {}).get("differences") or []
            if not other or len(differences) < 8:
                errors.append(f"{label}: every contrast entry requires another name and at least eight differences")
                continue
            structural_count = sum(any(axis in text(value).casefold() for axis in STRUCTURAL) for value in differences)
            if structural_count < 5:
                errors.append(f"{label} vs {other}: fewer than five differences explicitly name structural axes")
            collision_rows.append([label, other, len(differences), structural_count, " | ".join(map(text, differences))])

        prompt_rows.append([
            source, label, text(character.get("role")), text(character.get("age_band")),
            text(character.get("family_group")),
            text(character.get("prompt_injection_cn")),
            injection,
            text(character.get("negative_prompt_cn")),
            negative,
        ])

    known = names
    for character in characters:
        label = text(character.get("localized_name"))
        for contrast in character.get("contrast_against") or []:
            other = text((contrast or {}).get("localized_name"))
            if other and other.casefold() not in known:
                errors.append(f"{label}: contrast target does not exist: {other}")

    report = {
        "status": "failed" if errors else "passed",
        "character_count": len(characters),
        "errors": errors,
        "warnings": warnings,
    }
    payload["validation"] = report

    if args.normalized_json:
        target = args.normalized_json.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.prompt_csv:
        write_csv(args.prompt_csv.resolve(), [
            "source_name", "localized_name", "role", "age_band", "family_group",
            "face_prompt_injection_cn", "face_prompt_injection",
            "face_negative_prompt_cn", "face_negative_prompt",
        ], prompt_rows)
    if args.collision_csv:
        write_csv(args.collision_csv.resolve(), [
            "character_a", "character_b", "difference_count", "explicit_structural_count", "differences",
        ], collision_rows)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

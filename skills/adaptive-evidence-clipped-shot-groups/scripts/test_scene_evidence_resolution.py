#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "expand_compact_timeline.py"
SPEC = importlib.util.spec_from_file_location("expand_compact_timeline", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


RULES = [
    {
        "asset": "Private Infirmary Ward",
        "keywords": ["医院病房", "病房内景", "医用病床"],
        "negative_keywords": ["豪宅卧室", "卧室床边", "雕花木质大床"],
    },
    {
        "asset": "Blackwood Manor Principal Bedroom",
        "keywords": ["冷家别墅卧室", "豪宅卧室", "卧室床边", "卧室环境", "雕花木质大床", "软包床头"],
        "negative_keywords": ["医院病房", "病房内景", "医用病床"],
    },
]


def record(start: float, end: float, observation: str, fixed: str = "") -> dict:
    return {
        "start_seconds": start,
        "end_seconds": end,
        "scene_observation": observation,
        "fixed_scene_evidence": fixed,
        "transition": "硬切",
    }


def main() -> int:
    bedroom_records = [
        record(102.667, 103.533, "卧室床边环境", "雕花木质大床、软包床头、地毯"),
        record(103.533, 104.667, "卧室地面环境", "床裙背景"),
        record(104.667, 106.367, "卧室环境背景", "室内浅色背景墙与线条"),
        record(106.367, 110.016, "豪宅卧室环境", "雕花木质大床、软包床头"),
    ]
    resolved, audit, warnings = MODULE.resolve_group_scene(
        "Private Infirmary Ward", bedroom_records, RULES
    )
    assert resolved == "Blackwood Manor Principal Bedroom"
    assert audit["status"] == "corrected_high_confidence"
    assert audit["support_records"] >= 2
    assert audit["duration_share"] >= 0.67
    assert warnings and "Private Infirmary Ward" in warnings[0]

    ambiguous = [
        record(0, 2, "医院病房", "医用病床"),
        record(2, 4, "豪宅卧室", "雕花木质大床"),
    ]
    resolved, audit, warnings = MODULE.resolve_group_scene(
        "Private Infirmary Ward", ambiguous, RULES
    )
    assert resolved == "Private Infirmary Ward"
    assert audit["status"] == "insufficient_evidence"
    assert not warnings

    resolved, audit, warnings = MODULE.resolve_group_scene(
        "Private Infirmary Ward", bedroom_records, []
    )
    assert resolved == "Private Infirmary Ward"
    assert audit["status"] == "not_evaluated"
    assert not warnings

    try:
        MODULE.resolve_group_scene(
            "Private Infirmary Ward", bedroom_records, RULES, {"mode": "error"}
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("error mode must reject a strong scene conflict")

    print("scene evidence resolution: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy

from continuity_handoff import attach_group_continuity_handoffs, validate_group_continuity_handoffs


def _row(group_id: str, start: float, end: float, scene: str) -> dict:
    return {
        "group_id": group_id,
        "start_seconds": start,
        "end_seconds": end,
        "scene": scene,
        "time_of_day": "day",
        "initial_frame": f"{group_id}首态",
        "final_frame": f"{group_id}尾态",
        "linked_assets": [scene, "人物A"],
        "subshots": [{"spatial_positions": "人物A在中央", "contact_actions": "无接触"}],
    }


def test_attach_and_validate_all_boundaries() -> None:
    rows = [
        _row("EP01-G001", 0.0, 5.0, "场景A"),
        _row("EP01-G002", 5.0, 10.0, "场景A"),
        _row("EP01-G003", 10.0, 15.0, "场景B"),
    ]
    records = [[{}], [{}], [{}]]
    compact = {"boundary_audit": [{
        "candidate_seconds": 5.0,
        "continuity_decision": {"seam_type": "continuous_action", "continuity_mode": "inherit_state"},
    }]}
    contract, handoffs = attach_group_continuity_handoffs(rows, records, compact)
    assert contract["expected_boundary_count"] == 2
    assert [item["mode"] for item in handoffs] == ["inherit_state", "new_scene"]
    assert "continuity_handoff" not in rows[0]
    assert rows[1]["continuity_handoff"] is handoffs[0]
    assert rows[2]["continuity_handoff"] is handoffs[1]
    assert validate_group_continuity_handoffs(rows, handoffs) == []


def test_unresolved_boundary_stays_verify_and_missing_is_blocking() -> None:
    rows = [
        _row("EP01-G001", 0.0, 5.0, "待确认"),
        _row("EP01-G002", 5.0, 10.0, "待确认"),
    ]
    contract, handoffs = attach_group_continuity_handoffs(rows, [[{}], [{}]], {})
    assert contract["expected_boundary_count"] == 1
    assert handoffs[0]["mode"] == "verify"
    broken_rows = deepcopy(rows)
    broken_rows[1].pop("continuity_handoff")
    errors = validate_group_continuity_handoffs(broken_rows, [])
    assert any("expected 1 continuity handoffs" in error for error in errors)
    assert any("missing continuity handoff" in error for error in errors)


def test_composite_group_scene_uses_boundary_record_scene() -> None:
    rows = [
        _row("EP01-G001", 0.0, 5.0, "场景A"),
        _row("EP01-G002", 5.0, 10.0, "场景A；场景B"),
    ]
    records = [
        [{"_resolved_scene_asset": "场景A"}],
        [{"_resolved_scene_asset": "场景A"}],
    ]
    _, handoffs = attach_group_continuity_handoffs(rows, records, {})
    assert handoffs[0]["mode"] == "inherit_state"
    assert handoffs[0]["seam_type"] == "same_scene_cut"


def test_fully_continuous_verify_audit_normalizes_only_derived_handoff() -> None:
    rows = [
        _row("EP01-G001", 0.0, 5.0, "场景A"),
        _row("EP01-G002", 5.0, 10.0, "场景A"),
    ]
    audit = {
        "candidate_seconds": 5.0,
        "continuity_decision": {
            "seam_type": "continuous_action",
            "continuity_mode": "verify_from_video",
            "scene_match": "true",
            "action_continues": "true",
            "character_state_continues": "true",
        },
    }
    _, handoffs = attach_group_continuity_handoffs(rows, [[{}], [{}]], {"boundary_audit": [audit]})
    assert handoffs[0]["mode"] == "inherit_state"
    assert handoffs[0]["authority"] == "audited_overlap_pixels_consistency_resolution"
    assert handoffs[0]["audit_decision"]["continuity_decision"]["continuity_mode"] == "verify_from_video"


if __name__ == "__main__":
    test_attach_and_validate_all_boundaries()
    test_unresolved_boundary_stays_verify_and_missing_is_blocking()
    test_composite_group_scene_uses_boundary_record_scene()
    test_fully_continuous_verify_audit_normalizes_only_derived_handoff()
    print("group continuity handoff tests passed")

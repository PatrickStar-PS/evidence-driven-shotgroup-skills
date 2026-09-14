#!/usr/bin/env python3
from __future__ import annotations

import bai_compact_timeline as bai
from expand_compact_timeline import screen_order_transition_text
from validate_compact_timeline import collect_lightweight_warnings


def record(order: dict, transition: dict, boundary: str = "continuous") -> dict:
    return {
        "camera_view": "2 正视",
        "camera_view_evidence": "摄影机沿人物运动轴正对主体",
        "visible_characters": [],
        "prop_continuity": [],
        "screen_order_left_to_right": order,
        "position_transition": transition,
        "boundary": boundary,
    }


def main() -> int:
    crossing = record(
        {
            "start": ["Emma", "Henry"],
            "middle": ["Emma", "Henry"],
            "end": ["Henry", "Emma"],
        },
        {
            "type": "crosses_behind",
            "description": "Emma从Henry左后方经过其身后移动至右后方",
            "evidence_timestamps": [1.0, 2.64],
        },
    )
    warnings = collect_lightweight_warnings([crossing])
    assert not any("position_transition" in warning for warning in warnings), warnings
    rendered = screen_order_transition_text(crossing)
    assert "首=Emma < Henry" in rendered
    assert "尾=Henry < Emma" in rendered
    assert "crosses_behind" in rendered

    bad_crossing = record(crossing["screen_order_left_to_right"], {"type": "stable"})
    warnings = collect_lightweight_warnings([bad_crossing])
    assert any("anchor screen order reverses" in warning for warning in warnings), warnings

    after_cut = record(
        {"start": ["Emma", "Henry"], "middle": ["Emma", "Henry"], "end": ["Emma", "Henry"]},
        {"type": "stable", "description": "", "evidence_timestamps": []},
        boundary="cut",
    )
    warnings = collect_lightweight_warnings([crossing, after_cut])
    assert any("reblocked_after_cut" in warning for warning in warnings), warnings

    prompt = bai.prompt(
        episode="30",
        duration=8.7,
        range_start=0.0,
        range_end=8.7,
        has_context_sheet=True,
        has_pose_evidence=False,
        boundary_contract=None,
        asset_cards=[],
        evidence_roles=["range_boundaries", "action_events", "high_motion_triplets", "shot_space", "person_trajectory"],
        dialogue_injection=None,
        continuity_injection=None,
    )
    assert '"position_transition"' in prompt
    assert "reblocked_after_cut" in prompt
    print("screen-order transition tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

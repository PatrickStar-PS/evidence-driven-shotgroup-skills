#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent


def test_builder() -> None:
    timeline = {
        "records": [{
            "start_seconds": 50.0,
            "end_seconds": 60.6,
            "scene_observation": "庄园室外泳池",
            "fixed_scene_evidence": "泳池、石质池沿",
            "time_of_day": "day",
            "time_of_day_evidence": "自然日光",
            "asset_hints": ["庄园泳池", "顾云-深色西装", "宋清如-酒红色吊带裙"],
            "primary_visible_subject": "顾云抱着宋清如走向池边",
            "visible_action": "顾云抱着宋清如继续走向池边",
            "contact_actions": "顾云双臂托住宋清如",
            "final_frame": "顾云仍抱着宋清如",
            "screen_order_left_to_right": {"end": ["宋清如", "顾云"]},
            "visible_characters": [{
                "identity": "顾云",
                "screen_position": "画面右侧",
                "anchor_presence": {"end": True},
                "body_posture": "standing",
                "torso_orientation": "朝画面左侧",
                "head_orientation": "低头",
                "gaze_target": "宋清如",
                "support_contact": "双臂托住宋清如",
                "character_action": "抱着宋清如向前走",
            }],
            "prop_continuity": [],
        }]
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "timeline.json"
        output = tmp_path / "continuity.json"
        source.write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
        subprocess.run([
            sys.executable, str(HERE / "build_seam_continuity_injection.py"),
            "--timeline", str(source), "--output", str(output),
            "--source-range-id", "part07", "--target-range-id", "part08",
        ], check=True, capture_output=True, text=True, encoding="utf-8")
        data = json.loads(output.read_text(encoding="utf-8"))
    assert data["contract_version"] == "1.1-text-state"
    assert data["continuity_mode"] == "verify_from_video"
    assert data["seam_type"] == "pending_target_video_verification"
    assert data["scene_state"]["scene_observation"] == "庄园室外泳池"
    assert data["action_handoff"]["completion_status"] == "requires_target_video_verification"
    assert data["visible_characters_end"][0]["body_posture"] == "standing"
    assert data["visible_characters_end"][0]["support_contact"] == "双臂托住宋清如"
    assert "tail_frame" not in data


def test_seam_audit_contract() -> None:
    source = (HERE / "bai_audit_range_seam.py").read_text(encoding="utf-8")
    for value in (
        "continuous_action", "same_scene_cut", "scene_transition", "time_jump",
        "inherit_state", "new_scene", "continuity_decision",
    ):
        assert value in source


def test_final_group_writeback_contract() -> None:
    expand_source = (HERE / "expand_compact_timeline.py").read_text(encoding="utf-8")
    schema_source = (HERE.parent / "references" / "output-schema.md").read_text(encoding="utf-8")
    assert "attach_group_continuity_handoffs" in expand_source
    assert '"continuity_handoff_contract"' in expand_source
    assert '"continuity_handoffs"' in expand_source
    assert "1.0-group-boundary-handoff" in schema_source
    assert "N-1" in schema_source


if __name__ == "__main__":
    test_builder()
    test_seam_audit_contract()
    test_final_group_writeback_contract()
    print("enhanced continuity injection tests passed")

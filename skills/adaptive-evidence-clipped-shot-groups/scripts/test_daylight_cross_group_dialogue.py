#!/usr/bin/env python3
"""Local regression test for time-of-day fields and unique cross-group dialogue assembly."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args: object) -> None:
    completed = subprocess.run([sys.executable, *map(str, args)], check=False, capture_output=True, text=True)
    if completed.returncode:
        raise AssertionError(f"command failed ({completed.returncode}): {completed.stdout}\n{completed.stderr}")


def compact_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def main() -> int:
    runner_source = (HERE / "bai_compact_timeline.py").read_text(encoding="utf-8")
    bai = load_module("bai_compact_timeline", HERE / "bai_compact_timeline.py")
    prompt = bai.prompt("09", 3.0)
    assert bai.PROMPT_CONTRACT_VERSION == "3.9-mouth-motion-speech-sync"
    injected_prompt = bai.prompt(
        "30",
        32.1,
        range_start=25.5,
        range_end=32.1,
        dialogue_injection={"analysis_events": [{"dialogue_id": "EP30-D0011", "speaker": "助理"}]},
    )
    assert "反应镜头必须执行“声音人物与画面人物解耦”" in injected_prompt
    assert "只有双掌掌面持续贴合才可写“双手合十”" in injected_prompt
    assert '"time_of_day":"day|night|dawn|dusk|unclear"' in prompt
    assert '"time_of_day_evidence"' in prompt
    assert '"anchor_presence":{"start":true,"middle":true,"end":true}' in prompt
    assert '"camera_view_evidence"' in prompt
    trajectory_prompt = bai.prompt("09", 3.0, has_context_sheet=True, evidence_roles=["person_trajectory"])
    assert "PAGE_ROLE=person_trajectory" in trajectory_prompt
    assert "不能直接对应人物姓名" in trajectory_prompt
    assert "camera_angle只表示摄影机高度方向" in prompt
    assert "camera_view单独表示水平观察方向" in prompt
    assert "人物沿画面纵深迎着摄影机走来" in prompt
    assert "单帧侧脸或“前方偏左/偏右”不足以证明侧视" in prompt
    assert "硬切前后可以同为“2 正视”" in prompt
    assert "分屏模板、边框或版式持续存在不等于同一镜头" in prompt
    assert "character_action必须严格写成三个由“→”连接的可见阶段" in prompt
    assert "室内灯亮不能单独证明夜晚" in prompt
    assert '"appearance":"匹配人物-服装态时固定写asset_bound；未匹配时仅写最小识别依据"' in prompt
    assert '"transient_visual_details"' in prompt
    assert '"fixed_scene_evidence"' in prompt
    assert '"generation_facts"' in prompt
    assert '"subject_lighting"' in prompt
    assert '"prop_continuity"' in prompt
    assert '"screen_order_left_to_right"' in prompt
    assert '"position_transition"' in prompt
    assert '"mouth_visual_action"' in prompt
    assert '"speech_sync_status"' in prompt
    assert '"mouth_action_evidence"' in prompt
    assert "上一逻辑核心尾状态" in runner_source
    assert "从画面哪侧/哪层→经过谁的前方或后方→到画面哪侧/哪层" in prompt
    assert "--continuity-injection" in runner_source
    assert '"instance_id"' in prompt
    assert '"visible_instance_count"' in prompt
    assert '"exclusive_holder_after"' in prompt
    assert "交接完成后禁止让双方各自保留一件" in prompt
    assert "pre-roll已出现的道具不得" in prompt
    assert '"depth_of_field":"shallow|deep|rack_focus|unclear"' in prompt
    assert "不得复述固定装修、家具、墙面颜色、材质、常设陈设" in prompt
    assert "固定灯带、吊灯、顶光、霓虹灯和彩色氛围灯由场景资产负责" in prompt
    assert "未匹配资产的真实人物仍必须保留" in prompt
    assert "visible_characters只能填写人" in prompt

    validator = load_module("validate_compact_timeline", HERE / "validate_compact_timeline.py")
    warning_record = {
        "camera_view": "2 正视",
        "visible_characters": [{
            "anchor_presence": {"start": False, "middle": True, "end": False},
            "character_action": "画面边缘可见，动作不明",
        }],
    }
    warnings = validator.collect_lightweight_warnings([warning_record])
    assert any("camera_view_evidence" in item for item in warnings)
    assert any("middle-only person" in item for item in warnings)
    reaction_warning = validator.collect_lightweight_warnings([{
        "camera_view": "2 正视",
        "camera_view_evidence": "正面固定机位",
        "dialogue_utterances": [{
            "speaker": "助理",
            "speaker_visibility": "off_screen",
            "text": "这是规矩",
        }],
        "visible_characters": [{
            "identity": "胖子",
            "mouth_state": "speaking",
            "mouth_visual_action": "briefly opens then closes",
            "speech_sync_status": "matched_on_screen_dialogue",
            "mouth_action_evidence": "26.62s open; 27.21s closed",
            "character_action": "双手交握并开口说话",
            "anchor_presence": {"start": True, "middle": True, "end": True},
        }],
        "beat_summary": "胖子说话",
        "primary_visible_subject": "胖子说话特写",
        "visible_action": "胖子开口说话",
        "mouth_dynamics": "嘴唇配合台词说话",
        "prop_continuity": [],
        "screen_order_left_to_right": {"start": ["胖子"], "middle": ["胖子"], "end": ["胖子"]},
        "position_transition": {"type": "stable", "description": "位置不变", "evidence_timestamps": [0.0, 1.0]},
    }])
    assert any("off-screen locked dialogue conflicts with a visible speaking mouth/action" in item for item in reaction_warning)
    assert any("off-screen locked dialogue conflicts with record-level speaking prose" in item for item in reaction_warning)
    assert any("matched_on_screen_dialogue conflicts with off-screen-only locked dialogue" in item for item in reaction_warning)
    clean_record = {
        "camera_view": "3 侧视",
        "camera_view_evidence": "摄影机位于主体侧面，可见人物侧脸轮廓与侧向构图重心",
        "screen_order_left_to_right": {"start": [], "middle": ["背景路人A"], "end": []},
        "position_transition": {
            "type": "crosses_behind",
            "description": "人物从画面右侧进入，经过主体身后并向画面后方离开",
            "evidence_timestamps": [0.2, 0.8],
        },
        "prop_continuity": [],
        "visible_characters": [{
            "identity": "背景路人A",
            "anchor_presence": {"start": False, "middle": True, "end": False},
            "character_action": "从画面右侧进入→从主体身边交错经过→向画面后方离开",
        }],
    }
    assert not validator.collect_lightweight_warnings([clean_record])

    delivery = {
        "speech_rate": "medium",
        "intonation": "先低平后下沉",
        "timbre": "年轻女声、清晰",
        "emotion": "克制威胁",
        "rhythm_pause": "转折处短停顿",
        "pause_profile": [{"position_ratio": 0.55, "duration": "short", "function": "emphasis"}],
        "confidence": "high",
    }
    event = {
        "dialogue_id": "EP09-D0001",
        "start_seconds": 0.5,
        "end_seconds": 2.5,
        "speaker": "金莲",
        "text": "你要是还想继续，就现在回家。",
        "basis": "dialogue_injection",
        "speaker_evidence": "locked_dialogue_ledger",
        "delivery": delivery,
    }
    base_record = {
        "visible_characters": [{"identity": "金莲", "appearance": "黑色亮片礼服与金色项链", "screen_position": "画面中央"}],
        "scene_observation": "宴会厅内有白色墙面、环形吊灯与常设长桌",
        "fixed_scene_evidence": "白色墙面、环形吊灯与常设长桌",
        "visual_details": "黑色亮片礼服、金色项链、白色墙面与环形吊灯",
        "transient_visual_details": "人物手持临时出现的折叠报告",
        "generation_facts": {
            "subject_lighting": "主体受光正常，背景蓝色霓虹灯带持续发光",
            "contrast_exposure": "中等反差、主体曝光正常",
            "depth_of_field": "shallow",
            "focus_transition": "无变化",
            "composition_change": "主体保持居中",
            "dynamic_environment": "无",
        },
        "lighting_composition": "白色墙面和环形吊灯构成固定背景，黑色礼服衣料清晰",
        "time_of_day": "day",
        "time_of_day_evidence": "落地窗外可见明亮天空，室内有明确方向性日光",
        "camera_view": "2 正视",
        "confidence": "high",
        "warnings": [],
        "on_screen_text": "源片中文字幕与身份花字",
    }
    compact = {
        "episode": "09",
        "dialogue_events": [event],
        "records": [
            {**base_record, "start_seconds": 0.0, "end_seconds": 1.5},
            {**base_record, "start_seconds": 1.5, "end_seconds": 3.0},
        ],
        "warnings": [],
    }
    config = {
        "episode": "09",
        "default_scene": "modern British banquet hall",
        "groups": [
            {"start": 0.0, "end": 1.5, "summary": "金莲开始威胁"},
            {"start": 1.5, "end": 3.0, "summary": "金莲说完威胁"},
        ],
        "people_rules": [{"start": 0.0, "end": 3.0, "aliases": ["金莲"], "asset": "Vanessa Kardashian - black evening dress"}],
        "prop_rules": [],
        "translations_by_dialogue_id": {"EP09-D0001": "Stay, come home."},
    }

    with tempfile.TemporaryDirectory(prefix="daylight-dialogue-test-") as temporary:
        root = Path(temporary)
        compact_path = root / "compact.json"
        config_path = root / "config.json"
        output_path = root / "shot_groups.json"
        compact_path.write_text(json.dumps(compact, ensure_ascii=False), encoding="utf-8")
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        run(HERE / "expand_compact_timeline.py", "--input", compact_path, "--config", config_path, "--output", output_path)
        output = json.loads(output_path.read_text(encoding="utf-8"))
        rows = output["rows"]
        assert [row["time_of_day"] for row in rows] == ["day", "day"]
        assert all(row["time_of_day_evidence"] for row in rows)
        segments = [item for row in rows for item in row["dialogue_delivery"]]
        assert [item["dialogue_segment_id"] for item in segments] == ["EP09-D0001-S01", "EP09-D0001-S02"]
        assert [item["continuation"] for item in segments] == ["starts_here", "ends_here"]
        assert len({item["dialogue_segment_id"] for item in segments}) == 2
        assert compact_text("".join(item["source_text"] for item in segments)) == compact_text(event["text"])
        assert compact_text("".join(item["localized_text"] for item in segments)) == compact_text(config["translations_by_dialogue_id"]["EP09-D0001"])
        assert all(item["source_delivery"]["speech_rate"] == "medium" for item in segments)
        assert all(item["source_delivery"]["intonation"] == "先低平后下沉" for item in segments)
        assert all(item["source_delivery"]["timbre"] == "年轻女声、清晰" for item in segments)
        assert all(item["source_delivery"]["emotion"] == "克制威胁" for item in segments)
        assert all(item["source_delivery"]["rhythm_pause"] == "转折处短停顿" for item in segments)
        assert "无明确句内停顿" in segments[0]["performance_direction"]
        assert "节奏/停顿=转折处短停顿" in segments[0]["performance_direction"]
        assert all(event["text"] not in row["chinese_dialogue"] for row in rows)
        visual_text = " ".join(shot["description"] for row in rows for shot in row["subshots"])
        assert "黑色亮片礼服" not in visual_text
        assert "金色项链" not in visual_text
        assert "白色墙面" not in visual_text
        assert "环形吊灯" not in visual_text
        assert "人物手持临时出现的折叠报告" in visual_text
        assert "Vanessa Kardashian - black evening dress" in visual_text
        assert "源片中文字幕与身份花字" not in visual_text
        assert "画面文字：" not in visual_text
        assert all(shot["description"].count("Vanessa Kardashian - black evening dress") == 1 for row in rows for shot in row["subshots"])
        assert all("白色墙面" not in row["composition"] and "环形吊灯" not in row["composition"] for row in rows)
        assert all("主体受光正常" in row["composition"] for row in rows)
        assert all("蓝色" not in row["composition"] and "霓虹" not in row["composition"] and "灯带" not in row["composition"] for row in rows)
        assert output["asset_binding_contract"]["person_fixed_appearance_source"] == "exact person-wardrobe/state asset"
        run(HERE / "validate_expanded_shot_groups.py", "--input", output_path, "--duration", 3.0)

        locked_path = root / "locked.json"
        retained_path = root / "retained.json"
        merged_path = root / "merged.json"
        locked_path.write_text(json.dumps({
            "prompt_contract_version": "2.6-daylight-dialogue-segmentation",
            "dialogue_injection_contract": {"version": "2.4-dialogue-injection-delivery-locked"},
            "dialogue_events": [event],
            "records": [{
                **base_record,
                "id": "E001",
                "start_seconds": 0.0,
                "end_seconds": 1.5,
                "narrative_group": 1,
                "scene_observation": "室内大堂",
                "dialogue_utterances": [{
                    "dialogue_id": event["dialogue_id"],
                    "start_seconds": event["start_seconds"],
                    "end_seconds": 1.5,
                    "speaker": event["speaker"],
                    "text": "你要是还想继续，",
                }],
            }],
            "warnings": [],
            "errors": [],
        }, ensure_ascii=False), encoding="utf-8")
        retained_path.write_text(json.dumps({
            "prompt_contract_version": "2.6-daylight-dialogue-segmentation",
            "dialogue_events": [{key: value for key, value in event.items() if key != "delivery"}],
            "records": [{
                **base_record,
                "id": "E002",
                "start_seconds": 1.5,
                "end_seconds": 3.0,
                "narrative_group": 1,
                "scene_observation": "室内大堂",
                "dialogue_utterances": [],
            }],
            "warnings": [],
            "errors": [],
        }, ensure_ascii=False), encoding="utf-8")
        run(
            HERE / "merge_compact_ranges.py",
            "--inputs", locked_path, retained_path,
            "--duration", 3.0,
            "--episode", "09",
            "--output", merged_path,
        )
        merged = json.loads(merged_path.read_text(encoding="utf-8"))
        assert merged["dialogue_events"][0]["delivery"] == delivery
        assert merged["dialogue_injection_contract"]["version"] == "2.4-dialogue-injection-delivery-locked"

    expand = load_module("expand_compact_timeline", HERE / "expand_compact_timeline.py")
    tiny_tail_event = {**event, "end_seconds": 1.53}
    by_group, assembly, warnings = expand.build_dialogue_segments(
        config["groups"],
        [tiny_tail_event],
        {},
        config["translations_by_dialogue_id"],
        0.15,
    )
    assert len(by_group[1]) == 1 and not by_group[2]
    assert assembly[0]["segment_count"] == 1
    assert warnings and "snapped 0.030s" in warnings[0]

    cleaned = expand.strip_redundant_bound_appearance(
        "Vanessa Kardashian - 黑色礼服，身穿黑色亮片礼服；两名女子穿着礼服交替向前走来",
        ["Vanessa Kardashian - 黑色礼服"],
    )
    assert "黑色亮片礼服" not in cleaned and "穿着礼服" not in cleaned
    assert "交替向前走来" in cleaned
    assert expand.replace_people(
        "Vanessa Kardashian - black evening dress看向镜头",
        1.0,
        config["people_rules"],
    ) == "Vanessa Kardashian - black evening dress看向镜头"

    supporting_rules = [{
        "start": 0.0,
        "end": 3.0,
        "aliases": ["女医生"],
        "asset": "Private Clinic Doctor - consultant state",
    }]
    resolved_speaker = expand.resolve_dialogue_speaker_asset(
        {
            "dialogue_id": "EP09-D0002",
            "start_seconds": 1.0,
            "end_seconds": 2.0,
            "speaker": "unclear",
            "text": "请做好心理准备",
        },
        [{
            "start_seconds": 1.0,
            "end_seconds": 2.0,
            "dialogue_placements": [{"dialogue_id": "EP09-D0002", "speaker_visibility": "on_screen"}],
            "visible_characters": [{"identity": "女医生", "character_action": "女医生开口说请做好心理准备"}],
        }],
        supporting_rules,
    )
    assert resolved_speaker == "Private Clinic Doctor - consultant state"

    relations = [{
        "subject": f"人物{index}",
        "relative_to": f"人物{index + 1}",
        "horizontal_relation": "left_of",
        "depth_relation": "in_front_of" if index % 2 else "same_plane",
        "occlusion": "blocks" if index % 3 == 0 else "none",
        "facing_relationship": "face_to_face",
        "evidence": "直接视频证据" * 30,
    } for index in range(10)]
    rendered_relations = expand.relative_blocking_text({"relative_blocking": relations})
    assert rendered_relations.count("相对") == 4
    assert len(rendered_relations) < 900
    assert len(relations) == 10

    print(json.dumps({"status": "passed", "checks": 49}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

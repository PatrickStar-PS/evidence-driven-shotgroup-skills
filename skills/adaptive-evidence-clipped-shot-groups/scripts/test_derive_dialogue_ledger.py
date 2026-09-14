#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_module():
    spec = importlib.util.spec_from_file_location("derive_dialogue_ledger_tested", HERE / "derive_dialogue_ledger.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(identifier, start, end, speaker, text):
    return {
        "dialogue_id": identifier,
        "start_seconds": start,
        "end_seconds": end,
        "speaker_id": speaker,
        "speaker_chinese_name": speaker,
        "chinese_text": text,
        "evidence": ["audible_speech"],
        "warnings": [],
    }


def main() -> int:
    module = load_module()
    payload = {"events": [
        event("D1", 64.0, 72.5, "母亲", "不过妍妍啊 你既然是女孩子 陆泽为你多花点钱 也是应该的 阿姨也不想你吃亏"),
        event("D2", 67.285, 70.485, "母亲", "陆泽为你多花点钱，也是应该的"),
        event("D3", 71.885, 74.185, "母亲", "阿姨也不想你吃亏"),
        event("D4", 80.0, 82.0, "甲", "今天"),
        event("D5", 80.2, 85.0, "乙", "今天就算你喊破喉咙也不会有人来救你"),
        event("D6", 90.0, 92.0, "丙", "第一句"),
        event("D7", 91.8, 94.0, "丙", "完全不同的第二句"),
    ]}
    result, audit = module.derive(payload, 0.52, 0.25)
    events = result["events"]
    assert [item["dialogue_id"] for item in events] == ["D1", "D5", "D6", "D7"]
    assert events[0]["start_seconds"] == 64.0 and events[0]["end_seconds"] == 74.185
    assert set(events[0]["derived_dedup"]["absorbed_dialogue_ids"]) == {"D2", "D3"}
    assert events[1]["start_seconds"] == 80.0 and events[1]["end_seconds"] == 85.0
    assert any(item.get("speaker_conflict") for item in audit["decisions"])
    assert events[2]["end_seconds"] == events[3]["start_seconds"] == 91.8
    assert all(float(left["end_seconds"]) <= float(right["start_seconds"]) for left, right in zip(events, events[1:]))
    print("derived dialogue ledger: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

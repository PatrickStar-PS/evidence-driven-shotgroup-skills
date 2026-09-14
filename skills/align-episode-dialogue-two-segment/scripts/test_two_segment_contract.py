#!/usr/bin/env python3
"""Local contract test for planning, overlap dedupe, seam retention, and quarantine."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from plan_two_segments import build_manifest, choose_split
from merge_two_segment_ledgers import normalize_confidence


def event(start: float, end: float, text: str, confidence: str = "high") -> dict:
    return {"dialogue_id": "temporary", "start_seconds": start, "end_seconds": end, "speaker_id": "char-001",
            "speaker_chinese_name": "测试人物", "speaker_english_name": "Test Person", "speaker_label": "测试人物", "chinese_text": text,
            "delivery": {"speech_rate": "medium", "intonation": "平稳后下沉", "timbre": "清晰男声", "emotion": "平静",
                         "rhythm_pause": "连贯无明显停顿", "pause_profile": [], "confidence": confidence},
            "evidence": ["audible_speech"], "confidence": confidence, "warnings": []}


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_merge(root: Path, manifest: Path, p1: Path, p2: Path, characters: Path, output: Path, quarantine: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "merge_two_segment_ledgers.py"), "--manifest", str(manifest),
        "--part01", str(p1), "--part02", str(p2), "--character-input", str(characters), "--episode", "30", "--output", str(output),
        "--quarantine-output", str(quarantine)], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    scripts = Path(__file__).resolve().parent
    assert (scripts / "tos_video_transport.py").is_file()
    nested_only = event(1.0, 2.0, "仅嵌套置信度")
    nested_only.pop("confidence")
    normalize_confidence(nested_only)
    assert nested_only["confidence"] == "high"
    split, reason, silence = choose_split(120.0, [(57.0, 58.0), (64.0, 65.0)], 10.0)
    assert (split, reason, silence) == (57.5, "silence_midpoint", (57.0, 58.0))
    fallback = choose_split(120.0, [(10.0, 11.0)], 10.0)
    assert fallback[:2] == (60.0, "midpoint_fallback")
    with tempfile.TemporaryDirectory(prefix="dialogue-two-segment-test-") as temporary:
        root = Path(temporary)
        manifest_value = build_manifest(root / "episode.mp4", 120.0, 60.0, 3.0, "silence_midpoint", (59.5, 60.5), root / "clips", "abc123")
        manifest, p1, p2 = root / "manifest.json", root / "p1.json", root / "p2.json"
        characters, output, quarantine = root / "characters.json", root / "merged.json", root / "quarantine.json"
        write(manifest, manifest_value)
        write(characters, {"episode": "30", "characters": [{"character_id": "char-001", "chinese_name": "测试人物", "english_name": "Test Person"}]})
        write(p1, {"events": [event(58.0, 61.0, "跨接缝的一句完整台词"), event(61.4, 62.4, "只在第一段出现的短句")]})
        # part02 has absolute offset 57 seconds, so local 1.1 -> absolute 58.1.
        write(p2, {"events": [event(1.1, 4.1, "跨接缝的一句完整台词"), event(5.0, 6.0, "第二段正常台词"), event(130.0, 131.0, "不可能的越界事件")]})
        completed = run_merge(root, manifest, p1, p2, characters, output, quarantine)
        assert completed.returncode == 2, completed.stderr or completed.stdout
        merged = json.loads(output.read_text(encoding="utf-8"))
        quarantined = json.loads(quarantine.read_text(encoding="utf-8"))["quarantined_events"]
        texts = [item["chinese_text"] for item in merged["events"]]
        assert texts.count("跨接缝的一句完整台词") == 1
        assert "只在第一段出现的短句" in texts
        assert "第二段正常台词" in texts
        assert len(quarantined) == 1
        assert [item["dialogue_id"] for item in merged["events"]] == ["EP30-D0001", "EP30-D0002", "EP30-D0003"]
        # A clean rerun must complete without quarantine.
        write(p2, {"events": [event(1.1, 4.1, "跨接缝的一句完整台词"), event(5.0, 6.0, "第二段正常台词")]})
        completed = run_merge(root, manifest, p1, p2, characters, output, quarantine)
        assert completed.returncode == 0, completed.stderr or completed.stdout
        assert json.loads(output.read_text(encoding="utf-8"))["analysis"]["overlap_duplicates_removed"] == 1
        # Some relay responses label all part02 events with whole-episode absolute seconds.
        # Accept that basis only when the complete part is internally consistent and provable.
        write(p1, {"events": [event(58.0, 61.0, "跨接缝的一句完整台词")]})
        write(p2, {"events": [event(58.1, 61.1, "跨接缝的一句完整台词"), event(65.0, 66.0, "绝对时标台词")]})
        completed = run_merge(root, manifest, p1, p2, characters, output, quarantine)
        assert completed.returncode == 0, completed.stderr or completed.stdout
        absolute_payload = json.loads(output.read_text(encoding="utf-8"))
        absolute_event = next(item for item in absolute_payload["events"] if item["chinese_text"] == "绝对时标台词")
        assert absolute_event["start_seconds"] == 65.0
        assert "normalized_absolute_timestamp_basis" in absolute_event["warnings"]
        assert json.loads(quarantine.read_text(encoding="utf-8"))["quarantined_events"] == []
        # A part may mix valid local seconds with provable absolute seconds.
        write(p1, {"events": []})
        write(p2, {"events": [event(2.0, 3.0, "局部时标台词"), event(65.0, 66.0, "混合绝对时标台词")]})
        completed = run_merge(root, manifest, p1, p2, characters, output, quarantine)
        assert completed.returncode == 0, completed.stderr or completed.stdout
        mixed_payload = json.loads(output.read_text(encoding="utf-8"))
        mixed_event = next(item for item in mixed_payload["events"] if item["chinese_text"] == "混合绝对时标台词")
        assert mixed_event["start_seconds"] == 65.0
        assert "normalized_mixed_absolute_timestamp_basis" in mixed_event["warnings"]
        csv_output, report = root / "ledger.csv", root / "validation.json"
        validator = Path(__file__).resolve().parent / "validate_dialogue_ledger.py"
        validated = subprocess.run([sys.executable, str(validator), "--input", str(output), "--character-input", str(characters),
            "--duration", "120", "--csv-output", str(csv_output), "--report", str(report)], cwd=root, capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        assert validated.returncode == 0, validated.stderr or validated.stdout
        report_payload = json.loads(report.read_text(encoding="utf-8"))
        assert report_payload["status"] == "passed"
        assert report_payload["schema_version"] == "2.1-dialogue-ledger-validation"
    print(json.dumps({"status": "passed", "checks": ["bundled_tos_transport", "confidence_normalization", "silence_split", "midpoint_fallback", "overlap_dedupe", "unique_seam_retention", "timestamp_quarantine", "absolute_timestamp_basis_normalization", "mixed_timestamp_basis_normalization", "consecutive_ids", "canonical_validation"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

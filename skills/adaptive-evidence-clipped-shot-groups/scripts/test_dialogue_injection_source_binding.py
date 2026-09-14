#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_module():
    spec = importlib.util.spec_from_file_location("adaptive_bai_compact", HERE / "bai_compact_timeline.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HERE))
    spec.loader.exec_module(module)
    return module


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dialogue-source-binding-") as temporary:
        root = Path(temporary)
        ledger_path = root / "dialogue_ledger_final.json"
        injection_path = root / "dialogue_injection.json"
        ledger = {
            "schema_version": "2.1-video-dialogue-ledger-delivery",
            "episode": "30",
            "events": [{
                "dialogue_id": "EP30-D0011",
                "start_seconds": 33.0,
                "end_seconds": 33.8,
                "speaker_chinese_name": "金莲",
                "chinese_text": "谢谢。",
                "delivery": {"speech_rate": "medium"},
            }],
        }
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run([
            sys.executable,
            str(HERE / "build_dialogue_injection.py"),
            "--ledger", str(ledger_path),
            "--start", "32.1",
            "--end", "42.467",
            "--output", str(injection_path),
        ], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr

        injection = json.loads(injection_path.read_text(encoding="utf-8"))
        assert injection["source_ledger"]["sha256"]
        module = load_module()
        loaded = module.load_dialogue_injection(injection_path, ledger_path, "30", 32.1, 42.467)
        assert loaded["analysis_events"][0]["speaker"] == "金莲"

        ledger["events"][0]["speaker_chinese_name"] = "许蔓倪"
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        try:
            module.load_dialogue_injection(injection_path, ledger_path, "30", 32.1, 42.467)
        except RuntimeError as exc:
            assert "stale dialogue injection" in str(exc)
        else:
            raise AssertionError("stale injection was accepted")

    print(json.dumps({"status": "passed", "checks": 4}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

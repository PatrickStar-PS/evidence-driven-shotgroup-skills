#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="relay-wrapper-test-") as temporary:
        root = Path(temporary)
        preflight = root / "preflight.json"
        preflight.write_text(json.dumps({
            "results": [
                {"slot": 1, "fingerprint": "key-a", "status": "usable"},
                {"slot": 2, "fingerprint": "key-b", "status": "usable"},
            ]
        }), encoding="utf-8")
        output = root / "selected.txt"
        command = [
            sys.executable,
            str(HERE / "run_with_relay_lease.py"),
            "--preflight", str(preflight),
            "--database", str(root / "leases.sqlite3"),
            "--per-key-concurrency", "2",
            "--global-limit", "4",
            "--owner", "test-owner",
            "--wait-seconds", "1",
            "--command-attempts", "1",
            "--",
            sys.executable,
            "-c",
            "import pathlib,sys;assert sys.argv[1] in {'0','1'};pathlib.Path(sys.argv[2]).write_text(sys.argv[1],encoding='utf-8')",
            "{key_offset}",
            str(output),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        assert completed.returncode == 0, completed.stderr or completed.stdout
        assert output.read_text(encoding="utf-8") in {"0", "1"}
    print("run with relay lease: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

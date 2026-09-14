#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from preflight_bai_key_pool import fingerprint, pool_fingerprint


HERE = Path(__file__).resolve().parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="key-preflight-cache-") as temporary:
        root = Path(temporary)
        keys = ["fake-key-a", "fake-key-b"]
        key_file = root / "keys.txt"
        key_file.write_text("\n".join(keys), encoding="utf-8")
        output = root / "preflight.json"
        output.write_text(json.dumps({
            "schema_version": "0.1-bai-key-preflight",
            "model": "gemini-3.6-flash",
            "endpoint": "https://api.b.ai/v1/chat/completions",
            "pool_fingerprint": pool_fingerprint(keys),
            "checked_at_epoch": time.time(),
            "key_count": 2,
            "usable_slots": [1, 2],
            "results": [
                {"slot": 1, "fingerprint": fingerprint(keys[0]), "status": "usable"},
                {"slot": 2, "fingerprint": fingerprint(keys[1]), "status": "usable"},
            ],
        }), encoding="utf-8")
        completed = subprocess.run([
            sys.executable,
            str(HERE / "preflight_bai_key_pool.py"),
            "--key-pool-file", str(key_file),
            "--output", str(output),
            "--cache-seconds", "300",
        ], capture_output=True, text=True, encoding="utf-8")
        assert completed.returncode == 0, completed.stderr or completed.stdout
        result = json.loads(completed.stdout)
        assert result["cache_status"] == "reused"
        assert result["usable_slots"] == [1, 2]
    print("key preflight cache: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

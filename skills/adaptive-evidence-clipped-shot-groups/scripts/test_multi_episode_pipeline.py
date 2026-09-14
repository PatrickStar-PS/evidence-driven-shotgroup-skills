#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="multi-episode-test-") as temporary:
        root = Path(temporary)
        episodes = []
        for episode in ("01", "02", "03"):
            commands = []
            for index in range(4):
                output = root / f"ep{episode}-part{index}.txt"
                workspace_probe = root / f"ep{episode}-part{index}-workspace.json"
                commands.append({
                    "id": f"part{index}",
                    "argv": [
                        sys.executable,
                        "-c",
                        "import json,os,pathlib,time,sys;time.sleep(0.05);pathlib.Path(sys.argv[1]).write_text('ok',encoding='utf-8');pathlib.Path(sys.argv[2]).write_text(json.dumps({'cwd':str(pathlib.Path.cwd()),'env':os.environ['ADAPTIVE_RANGE_WORKDIR']}),encoding='utf-8')",
                        str(output),
                        str(workspace_probe),
                    ],
                })
            episodes.append({
                "episode": episode,
                "stages": [{"name": "primary", "kind": "relay", "commands": commands}],
            })
        manifest = root / "batch.json"
        manifest.write_text(json.dumps({
            "schema_version": "1.0-adaptive-batch-command-manifest",
            "episodes": episodes,
        }), encoding="utf-8")
        status = root / "status.json"
        command = [
            sys.executable,
            str(HERE / "run_multi_episode_pipeline.py"),
            "--manifest", str(manifest),
            "--status", str(status),
            "--logs-dir", str(root / "logs"),
            "--episode-workers", "2",
            "--range-workers", "3",
            "--local-workers", "2",
        ]
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        assert first.returncode == 0, first.stderr or first.stdout
        state = json.loads(status.read_text(encoding="utf-8"))
        assert all(item["status"] == "complete" for item in state["episodes"].values())
        for episode in ("01", "02", "03"):
            for index in range(4):
                workspace = root / "workspaces" / episode / "primary" / f"part{index}"
                probe = json.loads((root / f"ep{episode}-part{index}-workspace.json").read_text(encoding="utf-8"))
                assert Path(probe["cwd"]) == workspace
                assert Path(probe["env"]) == workspace
                assert (workspace / "workspace.json").is_file()
                for subdir in ("inputs", "evidence", "request", "response", "normalized", "audit", "retry", "logs"):
                    assert (workspace / subdir).is_dir()
                record = state["episodes"][episode]["stages"]["primary"]["commands"][f"part{index}"]
                assert Path(record["workspace"]) == workspace
                assert record["workspace_contract_sha256"]
        started = time.perf_counter()
        second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        elapsed = time.perf_counter() - started
        assert second.returncode == 0, second.stderr or second.stdout
        assert elapsed < 1.0, elapsed
    print("multi episode pipeline: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

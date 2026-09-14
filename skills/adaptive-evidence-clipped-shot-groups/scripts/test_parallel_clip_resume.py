#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent


def run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr or completed.stdout


def main() -> int:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("parallel clip resume: SKIP (ffmpeg/ffprobe unavailable)")
        return 0
    with tempfile.TemporaryDirectory(prefix="parallel-clip-test-") as temporary:
        root = Path(temporary)
        source = root / "测试 视频.mp4"
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
            "-t", "4", "-c:v", "libx264", "-threads", "1",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
        ])
        ranges = root / "ranges.json"
        ranges.write_text(json.dumps({
            "ranges": [
                {"id": "part01", "logical_start_seconds": 0.0, "logical_end_seconds": 1.5, "clip_start_seconds": 0.0, "clip_end_seconds": 2.0},
                {"id": "part02", "logical_start_seconds": 1.5, "logical_end_seconds": 2.5, "clip_start_seconds": 1.0, "clip_end_seconds": 3.0},
                {"id": "part03", "logical_start_seconds": 2.5, "logical_end_seconds": 4.0, "clip_start_seconds": 2.0, "clip_end_seconds": 4.0},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        output_dir = root / "clips"
        manifest = root / "clips.json"
        command = [
            sys.executable, str(HERE / "clip_analysis_ranges.py"),
            "--input", str(source), "--ranges-file", str(ranges),
            "--output-dir", str(output_dir), "--manifest", str(manifest),
            "--workers", "2", "--ffmpeg-threads", "1",
        ]
        run(command)
        first = json.loads(manifest.read_text(encoding="utf-8"))
        assert first["execution"]["built_count"] == 3
        assert first["execution"]["workers"] == 2
        mtimes = {item["id"]: Path(item["clip_path"]).stat().st_mtime_ns for item in first["ranges"]}
        run(command)
        second = json.loads(manifest.read_text(encoding="utf-8"))
        assert second["execution"]["built_count"] == 0
        assert second["execution"]["reused_count"] == 3
        assert mtimes == {item["id"]: Path(item["clip_path"]).stat().st_mtime_ns for item in second["ranges"]}
    print("parallel clip resume: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

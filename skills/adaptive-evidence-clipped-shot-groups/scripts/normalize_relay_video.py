#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a complete episode for a small inline relay request.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--target-mb", type=float, default=6.0)
    parser.add_argument("--height", type=int, default=854)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--audio-kbps", type=int, default=64)
    parser.add_argument("--ffmpeg", default="")
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if args.duration <= 0 or args.target_mb <= 0:
        raise ValueError("duration and target-mb must be positive")

    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found; pass --ffmpeg with its full path")

    total_kbps = int(args.target_mb * 8192 * 0.94 / args.duration)
    video_kbps = max(160, total_kbps - args.audio_kbps)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="relay-normalize-") as temp_dir:
        passlog = str(Path(temp_dir) / "ffmpeg2pass")
        vf = f"scale=-2:'min({args.height},ih)',fps={args.fps}"
        common = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map_metadata", "-1", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.15)}k",
            "-bufsize", f"{video_kbps * 2}k", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]
        first = common + ["-pass", "1", "-passlogfile", passlog, "-an", "-f", "null", "NUL"]
        second = common + [
            "-pass", "2", "-passlogfile", passlog, "-c:a", "aac", "-b:a", f"{args.audio_kbps}k",
            "-ac", "2", str(output),
        ]
        subprocess.run(first, check=True)
        subprocess.run(second, check=True)

    result = {
        "input": str(source),
        "output": str(output),
        "target_mb": args.target_mb,
        "actual_mb": round(output.stat().st_size / 1048576, 3),
        "video_kbps": video_kbps,
        "audio_kbps": args.audio_kbps,
        "fps": args.fps,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

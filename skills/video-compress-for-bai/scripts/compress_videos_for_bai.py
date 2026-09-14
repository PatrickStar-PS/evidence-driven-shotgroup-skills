#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def natural_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.stem.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def episode_label(index: int, path: Path) -> str:
    m = re.search(r"(?:ep|e|第)?\s*0*(\d{1,4})\s*(?:集|episode)?", path.stem, re.I)
    number = int(m.group(1)) if m else index
    return f"EP{number:02d}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_json(cmd: list[str]) -> dict[str, Any]:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "command failed")
    return json.loads(p.stdout)


def probe_video(path: Path, ffprobe: str) -> dict[str, Any]:
    data = run_json([
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_entries", "format=duration,size:stream=index,codec_type,width,height,r_frame_rate",
        str(path),
    ])
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or 0)
    fps_text = str(video.get("r_frame_rate") or "0/1")
    try:
        a, b = fps_text.split("/", 1)
        source_fps = float(a) / float(b) if float(b) else 0.0
    except Exception:
        source_fps = 0.0
    return {
        "duration_seconds": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "source_fps": round(source_fps, 3),
        "has_audio": audio is not None,
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
    }


def relative_safe(root: Path, output: Path) -> None:
    output.resolve().relative_to(root.resolve())


def compress_candidate(source: Path, out: Path, duration: float, args: argparse.Namespace, ffmpeg: str) -> tuple[bool, str, dict[str, Any]]:
    best_error = ""
    for safety in (0.92, 0.84, 0.76):
        total_kbps = max(220, int(args.target_mb * 8192 * safety / duration))
        video_kbps = max(120, total_kbps - args.audio_kbps)
        vf = f"scale=-2:'min({args.height},ih)',fps={args.fps}"
        with tempfile.TemporaryDirectory(prefix="bai-compress-") as temp_dir:
            passlog = str(Path(temp_dir) / "ffmpeg2pass")
            common = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                "-map_metadata", "-1", "-vf", vf, "-c:v", "libx264", "-preset", args.preset,
                "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.12)}k",
                "-bufsize", f"{video_kbps * 2}k", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            ]
            first = common + ["-pass", "1", "-passlogfile", passlog, "-an", "-f", "null", "NUL"]
            second = common + ["-pass", "2", "-passlogfile", passlog, "-c:a", "aac", "-b:a", f"{args.audio_kbps}k", "-ac", "2", str(out)]
            p1 = subprocess.run(first, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if p1.returncode != 0:
                best_error = p1.stderr.strip() or "ffmpeg pass 1 failed"
                continue
            p2 = subprocess.run(second, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if p2.returncode != 0:
                best_error = p2.stderr.strip() or "ffmpeg pass 2 failed"
                continue
        out_mb = out.stat().st_size / 1048576
        details = {"video_kbps": video_kbps, "audio_kbps": args.audio_kbps, "output_mb": round(out_mb, 3)}
        if out_mb <= args.target_mb:
            return True, "", details
        best_error = f"output {out_mb:.3f} MB exceeds target {args.target_mb} MB"
    return False, best_error or "compression failed", {}


def replace_source(source: Path, candidate: Path, row: dict[str, Any]) -> None:
    if source.resolve() == candidate.resolve():
        row["source_replace_status"] = "already_source_path"
        row["source_replaced"] = False
        return
    row["source_sha256_before_replace"] = row.get("source_sha256", "")
    row["candidate_sha256"] = sha256_file(candidate)
    row["candidate_size_bytes"] = candidate.stat().st_size
    os.replace(str(candidate), str(source))
    row["source_replaced"] = True
    row["source_replace_status"] = "replaced"
    row["source_sha256_after_replace"] = sha256_file(source)
    row["source_size_bytes_after_replace"] = source.stat().st_size
    row["source_mb_after_replace"] = round(source.stat().st_size / 1048576, 3)
    row["final_video_path"] = str(source)


def compress_one(item: tuple[int, Path], args: argparse.Namespace, ffmpeg: str, ffprobe: str, project_root: Path, output_dir: Path) -> dict[str, Any]:
    index, source = item
    ep = episode_label(index, source)
    out = output_dir / f"{ep}_{source.stem}.mp4"
    row: dict[str, Any] = {
        "episode": ep,
        "source_path": str(source),
        "compressed_candidate_path": str(out),
        "final_video_path": str(source if not args.keep_source else out),
        "target_mb": args.target_mb,
        "keep_source": bool(args.keep_source),
        "source_replaced": False,
        "source_replace_status": "not_attempted",
        "status": "pending",
        "error": "",
    }
    try:
        relative_safe(project_root, out)
        info = probe_video(source, ffprobe)
        row.update(info)
        row["source_sha256"] = sha256_file(source)
        source_mb = info["size_bytes"] / 1048576
        row["source_mb"] = round(source_mb, 3)
        out.parent.mkdir(parents=True, exist_ok=True)
        if source_mb <= args.target_mb and not args.force_normalize:
            row["status"] = "already_under_limit"
            row["source_replace_status"] = "not_needed"
            return row
        if args.dry_run:
            row["status"] = "dry_run"
            row["source_replace_status"] = "dry_run_no_replace"
            return row
        duration = float(info.get("duration_seconds") or 0)
        if duration <= 0:
            raise RuntimeError("duration_seconds is not positive")
        ok, error, details = compress_candidate(source, out, duration, args, ffmpeg)
        if not ok:
            row["status"] = "failed"
            row["error"] = error
            row["source_replace_status"] = "not_replaced_failed"
            return row
        row.update(details)
        row["output_size_bytes"] = out.stat().st_size
        row["output_sha256"] = sha256_file(out)
        if args.keep_source:
            row["status"] = "compressed_keep_source"
            row["source_replace_status"] = "kept_by_request"
            row["final_video_path"] = str(out)
            return row
        replace_source(source, out, row)
        row["status"] = "compressed_and_replaced"
        return row
    except Exception as exc:
        row["status"] = "failed"
        row["error"] = str(exc)
        row["source_replace_status"] = "not_replaced_error"
        return row


def collect_videos(input_dir: Path) -> list[Path]:
    if input_dir.is_file() and input_dir.suffix.lower() in VIDEO_EXTS:
        return [input_dir.resolve()]
    return sorted([p.resolve() for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS], key=natural_key)


def write_manifests(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "video_compress_manifest.json"
    csv_path = output_dir / "video_compress_manifest.csv"
    json_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-compress project videos for 中转站 workflows; default replaces sources after success.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--target-mb", type=float, default=10.0)
    parser.add_argument("--height", type=int, default=854)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--audio-kbps", type=int, default=64)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--ffprobe", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-source", action="store_true", help="Do not replace source videos; keep compressed candidates as handoff files.")
    parser.add_argument("--force-normalize", action="store_true", help="Re-encode even when a source is already under target size.")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    output_dir = (args.output_dir or (project_root / "资产输出" / "01_BAI压缩视频")).resolve()
    relative_safe(project_root, output_dir)
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    ffprobe = args.ffprobe or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("ffmpeg/ffprobe not found; pass --ffmpeg and --ffprobe or add them to PATH")
    videos = collect_videos(args.input_dir.resolve())
    if not videos:
        raise SystemExit(f"no supported videos found: {args.input_dir}")
    rows: list[dict[str, Any]] = []
    items = list(enumerate(videos, start=1))
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(compress_one, item, args, ffmpeg, ffprobe, project_root, output_dir) for item in items]
        for fut in as_completed(futures):
            rows.append(fut.result())
    order = {str(path): i for i, path in enumerate(videos)}
    rows.sort(key=lambda r: order.get(str(Path(str(r.get("source_path", ""))).resolve()), 999999))
    write_manifests(rows, output_dir)
    summary = {
        "output_dir": str(output_dir),
        "total": len(rows),
        "compressed_and_replaced": sum(1 for r in rows if r.get("status") == "compressed_and_replaced"),
        "already_under_limit": sum(1 for r in rows if r.get("status") == "already_under_limit"),
        "compressed_keep_source": sum(1 for r in rows if r.get("status") == "compressed_keep_source"),
        "failed": sum(1 for r in rows if r.get("status") == "failed"),
        "dry_run": bool(args.dry_run),
        "keep_source": bool(args.keep_source),
        "manifest_json": str(output_dir / "video_compress_manifest.json"),
        "manifest_csv": str(output_dir / "video_compress_manifest.csv"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

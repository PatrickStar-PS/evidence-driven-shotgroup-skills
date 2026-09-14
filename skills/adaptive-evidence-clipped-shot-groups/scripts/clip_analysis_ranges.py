#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    return json.loads(
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )


def duration_of(data: dict) -> float:
    return float((data.get("format") or {}).get("duration") or 0.0)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=path.stem + "_", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def cache_key(
    source_sha256: str,
    item: dict,
    crf: int,
    preset: str,
    ffmpeg_threads: int,
) -> str:
    payload = {
        "schema_version": "1.1-overlap-clip-cache",
        "source_sha256": source_sha256,
        "range_id": str(item["id"]),
        "clip_start_seconds": round(float(item["clip_start_seconds"]), 6),
        "clip_end_seconds": round(float(item["clip_end_seconds"]), 6),
        "crf": crf,
        "preset": preset,
        "video_codec": "libx264",
        "pixel_format": "yuv420p",
        "audio_codec": "aac-128k",
        # Thread count is recorded for audit but intentionally does not change pixels.
        "ffmpeg_threads": ffmpeg_threads,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_one_clip(
    item: dict,
    source: Path,
    output_dir: Path,
    source_sha256: str,
    crf: int,
    preset: str,
    ffmpeg_threads: int,
    duration_tolerance: float,
    resume: bool,
) -> dict:
    started = time.perf_counter()
    range_id = str(item["id"])
    clip_start = float(item["clip_start_seconds"])
    clip_end = float(item["clip_end_seconds"])
    expected_duration = clip_end - clip_start
    if expected_duration <= 0:
        raise RuntimeError(f"{range_id}: invalid clip range")
    filename = (
        f"{range_id}__abs_{round(clip_start * 1000):07d}_"
        f"{round(clip_end * 1000):07d}.mp4"
    )
    output = output_dir / filename
    metadata_path = output.with_suffix(output.suffix + ".clipmeta.json")
    expected_cache_key = cache_key(
        source_sha256, item, crf, preset, ffmpeg_threads
    )

    reused = False
    clip_probe: dict | None = None
    clip_sha256 = ""
    if resume and output.is_file() and metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
            if metadata.get("cache_key") == expected_cache_key:
                clip_probe = probe(output)
                actual_duration = duration_of(clip_probe)
                if abs(actual_duration - expected_duration) <= duration_tolerance:
                    clip_sha256 = fingerprint(output)
                    reused = clip_sha256 == metadata.get("clip_sha256")
        except Exception:
            reused = False

    if not reused:
        temporary = output.with_name(
            output.stem + f".building-{uuid.uuid4().hex}.mp4"
        )
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{clip_start:.3f}",
            "-i",
            str(source),
            "-t",
            f"{expected_duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-threads",
            str(ffmpeg_threads),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            str(temporary),
        ]
        try:
            subprocess.run(command, check=True)
            clip_probe = probe(temporary)
            actual_duration = duration_of(clip_probe)
            if abs(actual_duration - expected_duration) > duration_tolerance:
                raise RuntimeError(
                    f"{range_id}: clip duration {actual_duration:.3f}s differs "
                    f"from expected {expected_duration:.3f}s"
                )
            clip_sha256 = fingerprint(temporary)
            os.replace(temporary, output)
            atomic_json(
                metadata_path,
                {
                    "schema_version": "1.1-overlap-clip-cache",
                    "cache_key": expected_cache_key,
                    "source_sha256": source_sha256,
                    "range_id": range_id,
                    "clip_start_seconds": clip_start,
                    "clip_end_seconds": clip_end,
                    "clip_sha256": clip_sha256,
                    "clip_bytes": output.stat().st_size,
                    "crf": crf,
                    "preset": preset,
                    "ffmpeg_threads": ffmpeg_threads,
                },
            )
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    if clip_probe is None:
        clip_probe = probe(output)
    actual_duration = duration_of(clip_probe)
    streams = clip_probe.get("streams") or []
    return {
        **item,
        "clip_path": str(output.resolve()),
        "clip_sha256": clip_sha256 or fingerprint(output),
        "clip_bytes": output.stat().st_size,
        "actual_clip_duration_seconds": round(actual_duration, 3),
        "has_video": any(stream.get("codec_type") == "video" for stream in streams),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "status": "ready",
        "cache_status": "reused" if reused else "built",
        "build_elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create accurate overlap-aware relay clips from an absolute range plan."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ranges-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--range-id", help="Create only one named range for a bounded canary test"
    )
    parser.add_argument("--crf", type=int, default=22)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ffmpeg-threads", type=int, default=3)
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--duration-tolerance", type=float, default=0.15)
    args = parser.parse_args()
    if args.workers < 1 or args.ffmpeg_threads < 1:
        raise RuntimeError("workers and ffmpeg-threads must be positive")

    started = time.perf_counter()
    source = args.input.resolve()
    if not source.is_file():
        raise RuntimeError(f"Input video not found: {source}")
    plan = json.loads(args.ranges_file.read_text(encoding="utf-8-sig"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_probe = probe(source)
    source_fingerprint = fingerprint(source)
    planned_ranges = list(plan.get("ranges") or [])
    if args.range_id:
        planned_ranges = [
            item for item in planned_ranges if str(item.get("id")) == args.range_id
        ]
        if len(planned_ranges) != 1:
            raise RuntimeError(
                f"expected exactly one planned range named {args.range_id!r}"
            )

    ordered_results: list[dict | None] = [None] * len(planned_ranges)
    max_workers = min(args.workers, max(1, len(planned_ranges)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_indexes = {
            pool.submit(
                build_one_clip,
                item,
                source,
                args.output_dir.resolve(),
                source_fingerprint,
                args.crf,
                args.preset,
                args.ffmpeg_threads,
                args.duration_tolerance,
                args.resume,
            ): index
            for index, item in enumerate(planned_ranges)
        }
        for future in concurrent.futures.as_completed(future_indexes):
            ordered_results[future_indexes[future]] = future.result()
    output_ranges = [item for item in ordered_results if item is not None]

    manifest = {
        "schema_version": "1.1-overlap-clips-resumable",
        "transport_mode": "overlap_clipped_video",
        "source": {
            "path": str(source),
            "sha256": source_fingerprint,
            "duration_seconds": round(duration_of(source_probe), 3),
        },
        "ranges_file": str(args.ranges_file.resolve()),
        "selection_mode": (
            "single_range_canary" if args.range_id else "all_planned_ranges"
        ),
        "selected_range_id": args.range_id,
        "execution": {
            "workers": max_workers,
            "ffmpeg_threads_per_worker": args.ffmpeg_threads,
            "resume_enabled": args.resume,
            "built_count": sum(
                item["cache_status"] == "built" for item in output_ranges
            ),
            "reused_count": sum(
                item["cache_status"] == "reused" for item in output_ranges
            ),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        },
        "ranges": output_ranges,
    }
    atomic_json(args.manifest.resolve(), manifest)
    print(
        json.dumps(
            {
                "manifest": str(args.manifest.resolve()),
                "ranges": len(output_ranges),
                "built": manifest["execution"]["built_count"],
                "reused": manifest["execution"]["reused_count"],
                "workers": max_workers,
                "clip_seconds": round(
                    sum(
                        float(item["actual_clip_duration_seconds"])
                        for item in output_ranges
                    ),
                    3,
                ),
                "source_seconds": manifest["source"]["duration_seconds"],
                "elapsed_seconds": manifest["execution"]["elapsed_seconds"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

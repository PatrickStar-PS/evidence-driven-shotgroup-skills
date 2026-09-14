#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from cv_geometry import analyze_frame, annotate_frame, create_detectors, estimate_global_motion
from timeline_contract import build_boundary_contract, interval_label


def timecode(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    minutes, remainder = divmod(milliseconds, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def read_frame(capture: cv2.VideoCapture, seconds: float) -> Image.Image:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"Could not extract frame at {seconds:.3f}s")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def dedupe_times(values: list[float], start: float, end: float, minimum_gap: float = 0.07) -> list[float]:
    cleaned = sorted(min(end - 0.001, max(start, float(value))) for value in values)
    kept: list[float] = []
    for value in cleaned:
        if not kept or value - kept[-1] >= minimum_gap:
            kept.append(value)
    return kept


def motion_sample_times(input_path: Path, start: float, end: float, fps: float, threshold: float) -> list[float]:
    if fps <= 0:
        return []
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video for motion sampling: {input_path}")
    interval = 1.0 / fps
    times: list[float] = []
    previous: np.ndarray | None = None
    timestamp = start
    try:
        while timestamp < end - 0.001:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (96, 160), interpolation=cv2.INTER_AREA)
            if previous is not None:
                score = float(cv2.absdiff(previous, gray).mean())
                if score >= threshold:
                    times.append(timestamp)
            previous = gray
            timestamp += interval
    finally:
        capture.release()
    return times


def adaptive_sample_times(
    input_path: Path,
    boundary_contract: dict,
    boundary_data: dict,
    start: float,
    end: float,
    base_fps: float,
    motion_fps: float,
    motion_threshold: float,
    max_gap: float,
    boundary_offset: float,
) -> tuple[list[float], dict]:
    required = [start + 0.05, end - 0.05]
    for item in boundary_contract.get("evidence_intervals") or []:
        required.extend([
            float(item["start_anchor_seconds"]),
            float(item["middle_anchor_seconds"]),
            float(item["end_anchor_seconds"]),
        ])
    for raw in boundary_data.get("boundaries") or []:
        candidate = float(raw)
        if start < candidate < end:
            required.extend([candidate - boundary_offset, candidate + boundary_offset])
    required = dedupe_times(required, start, end)

    motion_raw = motion_sample_times(input_path, start, end, motion_fps, motion_threshold)
    motion: list[float] = []
    for value in motion_raw:
        if any(abs(value - anchor) < 0.25 for anchor in required):
            continue
        if motion and value - motion[-1] < 0.4:
            continue
        motion.append(value)
    selected = dedupe_times([*required, *motion], start, end)

    gap_limit = min(max_gap, 1.0 / base_fps) if base_fps > 0 else max_gap
    filled: list[float] = []
    for left, right in zip(selected, selected[1:]):
        filled.append(left)
        cursor = left + gap_limit
        while right - cursor > 0.07:
            filled.append(cursor)
            cursor += gap_limit
    if selected:
        filled.append(selected[-1])
    selected = dedupe_times(filled, start, end)
    return selected, {
        "required_anchor_frames": len(required),
        "motion_frames_before_dedupe": len(motion_raw),
        "motion_frames_after_anchor_suppression": len(motion),
        "selected_frames": len(selected),
        "base_sample_fps": base_fps,
        "motion_sample_fps": motion_fps,
        "motion_threshold": motion_threshold,
        "maximum_gap_seconds": gap_limit,
        "boundary_offset_seconds": boundary_offset,
    }


def labelled_thumb(image: Image.Image, seconds: float, width: int, label: str = "", screen_axis: bool = False) -> Image.Image:
    height = max(1, round(image.height * width / image.width))
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    text = f"{label} {timecode(seconds)}".strip()
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.rectangle((2, 2, bbox[2] + 8, bbox[3] + 7), fill=(0, 0, 0))
    draw.text((5, 4), text, fill=(255, 255, 255), font=font)
    if screen_axis:
        border = max(3, width // 48)
        draw.rectangle((0, 0, border, image.height - 1), fill=(220, 45, 45))
        draw.rectangle((image.width - border - 1, 0, image.width - 1, image.height - 1), fill=(45, 110, 230))
        axis_text = "<- SCREEN LEFT | SCREEN RIGHT ->"
        axis_bbox = draw.textbbox((0, 0), axis_text, font=font)
        axis_y = max(0, image.height - (axis_bbox[3] - axis_bbox[1]) - 7)
        draw.rectangle((border + 1, axis_y - 2, image.width - border - 2, image.height - 1), fill=(0, 0, 0))
        draw.text(((image.width - (axis_bbox[2] - axis_bbox[0])) // 2, axis_y), axis_text, fill=(255, 255, 255), font=font)
    return image


def save_pages(items: list[tuple[float, Image.Image]], output_dir: Path, prefix: str, frames_per_page: int, columns: int, quality: int) -> list[dict]:
    pages: list[dict] = []
    page_size = max(1, frames_per_page)
    columns = max(1, columns)
    for offset in range(0, len(items), page_size):
        page_items = items[offset: offset + page_size]
        rows = math.ceil(len(page_items) / columns)
        thumb_height = max(image.height for _, image in page_items)
        sheet = Image.new("RGB", (columns * page_items[0][1].width, rows * thumb_height), (18, 18, 18))
        for index, (_timestamp, image) in enumerate(page_items):
            sheet.paste(image, ((index % columns) * image.width, (index // columns) * thumb_height))
        page_path = output_dir / f"{prefix}_{len(pages) + 1:03d}.jpg"
        sheet.save(page_path, format="JPEG", quality=quality, optimize=True)
        pages.append({
            "file": str(page_path),
            "first_seconds": round(page_items[0][0], 3),
            "last_seconds": round(page_items[-1][0], 3),
            "frame_count": len(page_items),
        })
    return pages


def build_relay_pages(edge_path: Path, pages: list[dict], spatial_pages: list[dict], output_dir: Path) -> list[dict]:
    """Keep relay image attachments at four or fewer without dropping evidence."""
    direct = [
        {"file": str(edge_path), "role": "range_edges"},
        *[{"file": item["file"], "role": "chronological"} for item in pages],
        *[{"file": item["file"], "role": "spatial"} for item in spatial_pages],
    ]
    if len(direct) <= 4:
        return direct

    relay_pages = [{"file": str(edge_path), "role": "range_edges"}]
    if spatial_pages:
        if len(spatial_pages) == 1:
            relay_pages.append({"file": spatial_pages[0]["file"], "role": "spatial"})
        else:
            opened = [Image.open(item["file"]).convert("RGB") for item in spatial_pages]
            try:
                cell_width = max(image.width for image in opened)
                cell_height = max(image.height for image in opened)
                columns = min(2, len(opened))
                rows = math.ceil(len(opened) / columns)
                bundle = Image.new("RGB", (cell_width * columns, cell_height * rows), (18, 18, 18))
                for index, image in enumerate(opened):
                    bundle.paste(image, ((index % columns) * cell_width, (index // columns) * cell_height))
                spatial_bundle = output_dir / "spatial_bundle.jpg"
                bundle.save(spatial_bundle, format="JPEG", quality=90, optimize=True)
            finally:
                for image in opened:
                    image.close()
            relay_pages.append({"file": str(spatial_bundle), "role": "spatial"})

    chronological_slots = 4 - len(relay_pages)
    if len(pages) > chronological_slots:
        combine_count = len(pages) - chronological_slots + 1
        opened = [Image.open(item["file"]).convert("RGB") for item in pages[:combine_count]]
        try:
            width = sum(image.width for image in opened)
            height = max(image.height for image in opened)
            bundle = Image.new("RGB", (width, height), (18, 18, 18))
            x = 0
            for image in opened:
                bundle.paste(image, (x, 0))
                x += image.width
            chronological_bundle = output_dir / "contact_bundle_001.jpg"
            bundle.save(chronological_bundle, format="JPEG", quality=88, optimize=True)
        finally:
            for image in opened:
                image.close()
        relay_pages.append({"file": str(chronological_bundle), "role": "chronological"})
        remaining_pages = pages[combine_count:]
    else:
        remaining_pages = pages
    relay_pages.extend({"file": item["file"], "role": "chronological"} for item in remaining_pages)
    if len(relay_pages) > 4:
        raise RuntimeError("Relay evidence exceeds four attachments; reduce the range length or increase chronological frames per page")
    return relay_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Build paginated fixed-FPS contact sheets and range edge evidence.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ranges-file", type=Path, required=True)
    parser.add_argument("--boundaries-file", type=Path, help="Accepted for command compatibility; timestamps are sampled continuously.")
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--range-start", type=float, required=True)
    parser.add_argument("--range-end", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sample-fps", type=float, default=2.0, help="Base coverage rate; adaptive anchors and motion frames are added")
    parser.add_argument("--motion-sample-fps", type=float, default=5.0)
    parser.add_argument("--motion-threshold", type=float, default=10.0)
    parser.add_argument("--max-gap", type=float, default=0.6)
    parser.add_argument("--boundary-offset", type=float, default=0.15)
    parser.add_argument("--frames-per-page", type=int, default=36)
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--columns", type=int, default=6)
    parser.add_argument("--frame-width", type=int, default=240)
    parser.add_argument("--edge-width", type=int, default=480)
    parser.add_argument("--spatial-frames-per-page", type=int, default=20)
    parser.add_argument("--spatial-columns", type=int, default=4)
    parser.add_argument("--spatial-frame-width", type=int, default=360)
    args = parser.parse_args()

    if args.sample_fps <= 0 or args.motion_sample_fps <= 0 or args.max_gap <= 0 or args.range_end <= args.range_start:
        raise RuntimeError("Invalid sampling rate or analysis range")
    if args.range_start < 0 or args.range_end > args.duration + 0.01:
        raise RuntimeError("Analysis range exceeds the source duration")
    plan = json.loads(args.ranges_file.read_text(encoding="utf-8-sig"))
    if not any(abs(float(item["start_seconds"]) - args.range_start) <= 0.01 and abs(float(item["end_seconds"]) - args.range_end) <= 0.01 for item in plan.get("ranges", [])):
        raise RuntimeError("Requested range is absent from the range plan")
    boundary_data = (
        json.loads(args.boundaries_file.read_text(encoding="utf-8-sig"))
        if args.boundaries_file and args.boundaries_file.exists()
        else {}
    )
    boundary_contract = build_boundary_contract(boundary_data, args.range_start, args.range_end)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.output_dir.glob("contact_page_*.jpg"):
        stale.unlink()
    for stale in args.output_dir.glob("spatial_page_*.jpg"):
        stale.unlink()
    edge_path = args.output_dir / "range_edges.jpg"
    capture = cv2.VideoCapture(str(args.input))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {args.input}")
    cv_detectors = create_detectors()

    interval = 1.0 / args.sample_fps
    max_frames = max(1, args.frames_per_page) * max(1, args.max_pages)
    timestamps, sampling_stats = adaptive_sample_times(
        args.input,
        boundary_contract,
        boundary_data,
        args.range_start,
        args.range_end,
        args.sample_fps,
        args.motion_sample_fps,
        args.motion_threshold,
        args.max_gap,
        args.boundary_offset,
    )
    requested_count = len(timestamps)
    if requested_count > max_frames:
        raise RuntimeError(f"Range needs {requested_count} frames at {args.sample_fps:g}fps, exceeding the configured {max_frames}-frame cap")
    thumbs: list[tuple[float, Image.Image]] = []
    for timestamp in timestamps:
        thumbs.append((timestamp, labelled_thumb(
            read_frame(capture, timestamp),
            timestamp,
            args.frame_width,
            interval_label(boundary_contract, timestamp),
            True,
        )))

    spatial_times: list[float] = []
    if boundary_data:
        internal = sorted(float(value) for value in (boundary_data.get("boundaries") or []) if args.range_start + 0.05 < float(value) < args.range_end - 0.05)
        interval_edges = [args.range_start, *internal, args.range_end]
        for left, right in zip(interval_edges, interval_edges[1:]):
            length = right - left
            stable = left + min(0.15, max(0.03, length * 0.25))
            spatial_times.append(min(stable, right - 0.001))
            if length >= 2.0:
                spatial_times.append((left + right) / 2.0)
    if not spatial_times:
        spatial_times = [args.range_start + index for index in range(max(1, math.ceil(args.range_end - args.range_start)))]
    spatial_times = sorted({round(min(args.range_end - 0.001, max(args.range_start, value)), 3) for value in spatial_times})
    spatial_thumbs: list[tuple[float, Image.Image]] = []
    cv_geometry_frames: list[dict] = []
    previous_spatial_frame: Image.Image | None = None
    previous_spatial_timestamp: float | None = None
    for timestamp in spatial_times:
        frame = read_frame(capture, timestamp)
        geometry = analyze_frame(frame, cv_detectors)
        geometry["timestamp"] = timestamp
        geometry["global_motion_hint"] = estimate_global_motion(
            previous_spatial_frame,
            frame,
            previous_spatial_timestamp,
            timestamp,
        )
        cv_geometry_frames.append(geometry)
        thumb = labelled_thumb(
            frame,
            timestamp,
            args.spatial_frame_width,
            f"{interval_label(boundary_contract, timestamp)} SHOT SPACE".strip(),
            True,
        )
        spatial_thumbs.append((timestamp, annotate_frame(thumb, geometry)))
        previous_spatial_frame = frame
        previous_spatial_timestamp = timestamp

    edge_times = [min(args.range_end - 0.001, args.range_start + 0.05), max(args.range_start, args.range_end - 0.05)]
    edge_images = [
        labelled_thumb(
            read_frame(capture, value),
            value,
            args.edge_width,
            f"{label} {interval_label(boundary_contract, value)}".strip(),
        )
        for value, label in zip(edge_times, ("RANGE START", "RANGE END"))
    ]
    capture.release()

    edge_height = max(image.height for image in edge_images)
    edge_sheet = Image.new("RGB", (args.edge_width * 2, edge_height), (18, 18, 18))
    for index, image in enumerate(edge_images):
        edge_sheet.paste(image, (index * args.edge_width, 0))
    edge_sheet.save(edge_path, format="JPEG", quality=92, optimize=True)

    pages = save_pages(thumbs, args.output_dir, "contact_page", args.frames_per_page, args.columns, 88)
    spatial_pages = save_pages(spatial_thumbs, args.output_dir, "spatial_page", args.spatial_frames_per_page, args.spatial_columns, 92)
    relay_pages = build_relay_pages(edge_path, pages, spatial_pages, args.output_dir)

    manifest = {
        "schema_version": "2.2",
        "purpose": "adaptive anchor-and-motion relay evidence with locked intervals",
        "source": str(args.input),
        "duration_seconds": args.duration,
        "range_start_seconds": args.range_start,
        "range_end_seconds": args.range_end,
        "requested_sample_fps": args.sample_fps,
        "motion_sample_fps": args.motion_sample_fps,
        "effective_sample_fps": len(thumbs) / max(0.001, args.range_end - args.range_start),
        "interval_seconds": interval,
        "total_sampled_frames": len(thumbs),
        "sampling_strategy": sampling_stats,
        "edge_sheet": str(edge_path),
        "pages": pages,
        "spatial_pages": spatial_pages,
        "relay_pages": relay_pages,
        "cv_geometry_contract_version": "1.0-observation-only",
        "cv_geometry_frames": cv_geometry_frames,
        "boundary_contract": boundary_contract,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "frames": len(thumbs), "pages": len(pages), "spatial_frames": len(spatial_thumbs), "spatial_pages": len(spatial_pages), "relay_pages": len(relay_pages), "edge_sheet": str(edge_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

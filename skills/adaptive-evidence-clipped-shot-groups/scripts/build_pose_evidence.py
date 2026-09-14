#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".matplotlib-cache"))

import cv2
import mediapipe as mp
import numpy as np


@dataclass
class Sample:
    timestamp: float
    shot_id: str
    frame: np.ndarray
    gray: np.ndarray
    motion_score: float = 0.0
    pose_score: float = 0.0
    landmarks: list | None = None
    pose_metrics: dict | None = None


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    tmp.replace(path)


def frame_at(cap: cv2.VideoCapture, timestamp: float) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(timestamp, 0.0) * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError(f"cannot decode frame at {timestamp:.3f}s")
    return frame


def shot_ranges(boundaries: list[float], start: float, end: float) -> list[tuple[str, float, float]]:
    internal = sorted({round(float(x), 6) for x in boundaries if start < float(x) < end})
    points = [start, *internal, end]
    return [(f"S{i + 1:02d}", points[i], points[i + 1]) for i in range(len(points) - 1)]


def timestamp_grid(a: float, b: float, fps: float) -> list[float]:
    step = 1.0 / fps
    values = [a + 0.06]
    t = math.ceil((a + 0.08) / step) * step
    while t < b - 0.06:
        values.append(t)
        t += step
    values.extend([(a + b) / 2.0, b - 0.06])
    return sorted({round(min(max(x, a), b - 0.001), 3) for x in values})


def pose_metrics(landmarks) -> dict:
    ids = {"nose": 0, "left_ear": 7, "right_ear": 8, "left_shoulder": 11,
           "right_shoulder": 12, "left_hip": 23, "right_hip": 24}
    pts = {name: landmarks[idx] for name, idx in ids.items()}
    shoulder_width = abs(pts["left_shoulder"].x - pts["right_shoulder"].x)
    hip_width = abs(pts["left_hip"].x - pts["right_hip"].x)
    torso_height = abs(((pts["left_shoulder"].y + pts["right_shoulder"].y) / 2.0) -
                       ((pts["left_hip"].y + pts["right_hip"].y) / 2.0))
    shoulder_ratio = shoulder_width / max(torso_height, 1e-6)
    visibility = float(np.mean([pts[k].visibility for k in ids]))
    shoulder_z_delta = pts["left_shoulder"].z - pts["right_shoulder"].z
    nearer_shoulder = "left" if shoulder_z_delta < -0.12 else "right" if shoulder_z_delta > 0.12 else "unclear"
    return {
        "mean_visibility": round(visibility, 4),
        "shoulder_width_norm": round(shoulder_width, 4),
        "hip_width_norm": round(hip_width, 4),
        "shoulder_to_torso_ratio": round(shoulder_ratio, 4),
        "left_minus_right_shoulder_z": round(shoulder_z_delta, 4),
        "nearer_shoulder_candidate": nearer_shoulder,
        "left_minus_right_ear_visibility": round(pts["left_ear"].visibility - pts["right_ear"].visibility, 4),
    }


def analyze(video: Path, ranges, sample_fps: float) -> tuple[list[Sample], list[str]]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    samples: list[Sample] = []
    warnings: list[str] = []
    pose = None
    try:
        pose = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=0,
                                      enable_segmentation=False, min_detection_confidence=0.42,
                                      min_tracking_confidence=0.42)
    except (AttributeError, FileNotFoundError, RuntimeError) as exc:
        warnings.append(
            f"MediaPipe Lite unavailable; action selection falls back to optical motion only: {type(exc).__name__}"
        )
    try:
        for shot_id, a, b in ranges:
            previous_gray = None
            previous_landmarks = None
            for timestamp in timestamp_grid(a, b, sample_fps):
                frame = frame_at(cap, timestamp)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(frame, (288, 512), interpolation=cv2.INTER_AREA)
                result = pose.process(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)) if pose is not None else None
                landmarks = list(result.pose_landmarks.landmark) if result and result.pose_landmarks else None
                metrics = pose_metrics(landmarks) if landmarks else None
                frame_motion = 0.0 if previous_gray is None else float(np.mean(cv2.absdiff(gray, previous_gray)) / 255.0)
                joint_motion = 0.0
                if landmarks and previous_landmarks:
                    stable_ids = [0, 11, 12, 13, 14, 15, 16, 23, 24]
                    distances = [math.hypot(landmarks[i].x - previous_landmarks[i].x,
                                            landmarks[i].y - previous_landmarks[i].y)
                                 for i in stable_ids
                                 if landmarks[i].visibility > 0.35 and previous_landmarks[i].visibility > 0.35]
                    joint_motion = float(np.mean(distances)) if distances else 0.0
                score = frame_motion + min(joint_motion * 2.5, 0.35)
                samples.append(Sample(timestamp, shot_id, frame, gray, score,
                                      metrics["mean_visibility"] if metrics else 0.0,
                                      landmarks, metrics))
                previous_gray = gray
                previous_landmarks = landmarks
    finally:
        if pose is not None:
            pose.close()
        cap.release()
    if not any(s.landmarks for s in samples):
        warnings.append("MediaPipe Lite detected no pose in the selected range.")
    warnings.append("MediaPipe Pose Lite is single-person; secondary, cropped, defocused, or occluded people may be absent.")
    warnings.append("Side-on candidate is geometric evidence only; front/back and named facing relationships remain semantic judgments.")
    return samples, warnings


def fit_tile(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = min(width / w, height / h)
    resized = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    tile = np.zeros((height, width, 3), dtype=np.uint8)
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    tile[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return tile


def label_frame(frame: np.ndarray, text: str) -> np.ndarray:
    result = frame.copy()
    cv2.rectangle(result, (0, 0), (result.shape[1], 32), (0, 0, 0), -1)
    cv2.putText(result, text, (7, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
    return result


def draw_pose(sample: Sample) -> np.ndarray:
    frame = sample.frame.copy()
    if sample.landmarks:
        h, w = frame.shape[:2]
        points = [(int(lm.x * w), int(lm.y * h)) for lm in sample.landmarks]
        for a, b in mp.solutions.pose.POSE_CONNECTIONS:
            if sample.landmarks[a].visibility > 0.35 and sample.landmarks[b].visibility > 0.35:
                cv2.line(frame, points[a], points[b], (50, 220, 255), 3, cv2.LINE_AA)
        for idx in [0, 7, 8, 11, 12, 23, 24]:
            if sample.landmarks[idx].visibility > 0.35:
                cv2.circle(frame, points[idx], 6, (0, 255, 80), -1, cv2.LINE_AA)
        m = sample.pose_metrics or {}
        evidence = (f"SW/T={m.get('shoulder_to_torso_ratio', 0):.2f} "
                    f"zL-R={m.get('left_minus_right_shoulder_z', 0):+.2f} "
                    f"near={m.get('nearer_shoulder_candidate', 'unclear')}")
        cv2.rectangle(frame, (0, 32), (frame.shape[1], 62), (0, 0, 0), -1)
        cv2.putText(frame, evidence, (7, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (80, 255, 255), 1, cv2.LINE_AA)
    return label_frame(frame, f"{sample.shot_id} {sample.timestamp:06.3f}s pose={sample.pose_score:.2f}")


def make_sheet(items: list[np.ndarray], output: Path, columns: int, tile_w: int = 300, tile_h: int = 540) -> None:
    if not items:
        raise RuntimeError(f"no items for {output.name}")
    rows = math.ceil(len(items) / columns)
    canvas = np.zeros((rows * tile_h, columns * tile_w, 3), dtype=np.uint8)
    for i, item in enumerate(items):
        tile = fit_tile(item, tile_w, tile_h)
        y = (i // columns) * tile_h
        x = (i % columns) * tile_w
        canvas[y:y + tile_h, x:x + tile_w] = tile
    output.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 91])
    if not ok:
        raise RuntimeError(f"failed encoding {output}")
    encoded.tofile(str(output))


def bounded_sheet_layout(item_count: int, max_width: int = 1800, max_height: int = 2160) -> tuple[int, int, int]:
    """Choose the largest readable tiles that keep one contact sheet bounded."""
    best = None
    for columns in range(5, 13):
        tile_w = max_width // columns
        tile_h = int(round(tile_w * 1.8))
        rows = math.ceil(item_count / columns)
        if rows * tile_h <= max_height:
            candidate = (tile_w, columns, tile_w, tile_h)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        columns = 12
        tile_w = max_width // columns
        tile_h = max(180, max_height // math.ceil(item_count / columns))
        return columns, tile_w, tile_h
    return best[1], best[2], best[3]


def closest(samples: list[Sample], timestamp: float) -> Sample:
    return min(samples, key=lambda s: abs(s.timestamp - timestamp))


def select_by_shot(samples: list[Sample], ranges) -> tuple[list[Sample], list[Sample], list[tuple[Sample, str]], list[Sample]]:
    raw_events: list[Sample] = []
    pose_reps: list[Sample] = []
    orientation_candidates: list[tuple[Sample, str]] = []
    ranked_shots: list[tuple[float, list[Sample]]] = []
    for shot_id, a, b in ranges:
        group = [s for s in samples if s.shot_id == shot_id]
        if not group:
            continue
        start = group[0]
        end = group[-1]
        peak = max(group, key=lambda s: s.motion_score)
        raw_events.extend([start, peak, end] if b - a >= 0.9 else [start, end])
        pose_candidates = [s for s in group if s.landmarks]
        pose_reps.append(max(pose_candidates, key=lambda s: s.pose_score) if pose_candidates else closest(group, (a + b) / 2))
        seen_candidates = set()
        for candidate, role in ((start, "start"), (peak, "motion_peak"), (end, "end")):
            key = (candidate.shot_id, candidate.timestamp)
            if key not in seen_candidates:
                orientation_candidates.append((candidate, role))
                seen_candidates.add(key)
        ranked_shots.append((peak.motion_score, [start, peak, end]))
    dedup = []
    seen = set()
    for s in raw_events:
        key = (s.shot_id, s.timestamp)
        if key not in seen:
            dedup.append(s)
            seen.add(key)
    triplets = [s for _, group in sorted(ranked_shots, key=lambda x: x[0], reverse=True)[:4] for s in group]
    return dedup, pose_reps, orientation_candidates, triplets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--sample-fps", type=float, default=5.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.end <= args.start:
        raise SystemExit("--end must be greater than --start")
    data = read_json(args.boundaries.resolve())
    ranges = shot_ranges(data.get("boundaries") or [], args.start, args.end)
    samples, warnings = analyze(args.input.resolve(), ranges, args.sample_fps)
    raw_events, pose_reps, orientation_candidates, triplets = select_by_shot(samples, ranges)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    edges = [label_frame(closest(samples, args.start).frame, f"RANGE START {args.start:.3f}s"),
             label_frame(closest(samples, args.end).frame, f"RANGE END {args.end:.3f}s")]
    raw = [label_frame(s.frame, f"{s.shot_id} {s.timestamp:06.3f}s motion={s.motion_score:.3f}") for s in raw_events]
    poses = [draw_pose(s) for s in pose_reps]
    motion = [label_frame(s.frame, f"{s.shot_id} {s.timestamp:06.3f}s motion={s.motion_score:.3f}") for s in triplets]

    pages = {
        "range_edges": out / "range_edges.jpg",
        "event_keyframes": out / "event_keyframes.jpg",
        "pose_evidence": out / "pose_evidence.jpg",
        "motion_triplets": out / "motion_triplets.jpg",
    }
    make_sheet(edges, pages["range_edges"], 2, 520, 900)
    event_columns, event_tile_w, event_tile_h = bounded_sheet_layout(len(raw))
    make_sheet(raw, pages["event_keyframes"], event_columns, event_tile_w, event_tile_h)
    make_sheet(poses, pages["pose_evidence"], 5)
    make_sheet(motion, pages["motion_triplets"], 6)

    manifest = {
        "schema_version": "0.2-multiperson-candidates",
        "source": {"name": args.input.name, "size_bytes": args.input.stat().st_size},
        "range": {"start_seconds": args.start, "end_seconds": args.end},
        "sample_fps": args.sample_fps,
        "pose_model": "MediaPipe Pose solution, model_complexity=0 (Lite), single-person",
        "shot_ranges": [{"id": sid, "start_seconds": a, "end_seconds": b} for sid, a, b in ranges],
        "pages": {k: v.name for k, v in pages.items()},
        "selected_event_frames": [{"shot_id": s.shot_id, "timestamp": s.timestamp,
                                   "motion_score": round(s.motion_score, 5)} for s in raw_events],
        "pose_frames": [{"shot_id": s.shot_id, "timestamp": s.timestamp,
                         "pose_metrics": s.pose_metrics} for s in pose_reps],
        "orientation_candidate_frames": [
            {"shot_id": sample.shot_id, "timestamp": sample.timestamp,
             "candidate_role": role, "motion_score": round(sample.motion_score, 5)}
            for sample, role in orientation_candidates
        ],
        "event_sheet_layout": {"columns": event_columns, "tile_width": event_tile_w,
                               "tile_height": event_tile_h, "max_height": 2160},
        "warnings": warnings,
        "errors": [],
    }
    write_json(out / "pose_evidence_manifest.json", manifest)
    print(json.dumps({"status": "complete", "pages": {k: v.name for k, v in pages.items()},
                      "shots": len(ranges), "samples": len(samples),
                      "orientation_candidates": len(orientation_candidates),
                      "pose_frames": sum(bool(s.landmarks) for s in samples)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

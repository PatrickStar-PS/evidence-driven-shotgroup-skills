#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


def load_shots(path: Path, start: float, end: float) -> list[tuple[float, float]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    edges = sorted({float(x) for x in value.get("boundaries", []) if start <= float(x) <= end})
    if not edges or edges[0] > start + 1e-6:
        edges.insert(0, start)
    if edges[-1] < end - 1e-6:
        edges.append(end)
    return [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 0.02]


def frame_at(cap: cv2.VideoCapture, seconds: float) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    ok, frame = cap.read()
    return frame if ok else None


def representative_time(left: float, right: float) -> float:
    return left + max(0.0, right - left) / 2.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create shot-bounded BoT-SORT person trajectory evidence.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--boundaries", required=True, type=Path)
    parser.add_argument("--start", required=True, type=float)
    parser.add_argument("--end", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--sample-fps", type=float, default=3.0)
    parser.add_argument("--model", default="yolo11n.pt")
    args = parser.parse_args()
    if args.end <= args.start:
        raise RuntimeError("--end must be greater than --start")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.input.resolve()))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {args.input}")
    model = YOLO(args.model)
    font = ImageFont.load_default()
    shots_out = []
    warnings: list[str] = []
    try:
        for shot_index, (left, right) in enumerate(load_shots(args.boundaries, args.start, args.end), 1):
            shot_id = f"S{shot_index:03d}"
            sample_count = max(2, int(np.ceil((right - left) * args.sample_fps)))
            times = np.linspace(left, max(left, right - 0.001), sample_count)
            paths: dict[int, list[tuple[float, float, float]]] = {}
            boxes_latest: dict[int, tuple[float, float, float, float]] = {}
            representative_seconds = representative_time(left, right)
            representative = frame_at(cap, representative_seconds)
            if representative is not None:
                representative = representative.copy()
            model.predictor = None  # reset BoT-SORT state at every supplied cut
            for timestamp in times:
                frame = frame_at(cap, float(timestamp))
                if frame is None:
                    continue
                result = model.track(frame, persist=True, tracker="botsort.yaml", classes=[0], conf=0.18,
                                     iou=0.45, imgsz=640, verbose=False)[0]
                if result.boxes is None or result.boxes.id is None:
                    continue
                xyxy = result.boxes.xyxy.cpu().numpy()
                ids = result.boxes.id.int().cpu().tolist()
                for track_id, box in zip(ids, xyxy):
                    x1, y1, x2, y2 = map(float, box)
                    foot = ((x1 + x2) / 2.0, y2)
                    paths.setdefault(track_id, []).append((float(timestamp), foot[0], foot[1]))
                    boxes_latest[track_id] = (x1, y1, x2, y2)
            if representative is None:
                representative = np.zeros((360, 640, 3), dtype=np.uint8)
                warnings.append(f"{shot_id}: no readable sampled frame")
            rgb = cv2.cvtColor(representative, cv2.COLOR_BGR2RGB)
            canvas = Image.fromarray(rgb)
            draw = ImageDraw.Draw(canvas)
            palette = [(255, 90, 90), (75, 210, 255), (255, 210, 70), (145, 255, 130), (220, 130, 255)]
            tracks = []
            for ordinal, track_id in enumerate(sorted(paths), 1):
                colour = palette[(ordinal - 1) % len(palette)]
                points = [(x, y) for _t, x, y in paths[track_id]]
                if len(points) > 1:
                    draw.line(points, fill=colour, width=max(2, canvas.width // 280))
                for x, y in points:
                    draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=colour)
                x1, y1, x2, y2 = boxes_latest[track_id]
                draw.rectangle((x1, y1, x2, y2), outline=colour, width=max(2, canvas.width // 320))
                label = f"{shot_id}-T{ordinal:02d}"
                draw.text((x1 + 3, max(1, y1 - 14)), label, fill=colour, font=font)
                tracks.append({
                    "track_id": label,
                    "source_tracker_id": int(track_id),
                    "samples": [{"timestamp": round(t, 3), "foot_x": round(x, 1), "foot_y": round(y, 1)} for t, x, y in paths[track_id]],
                    "entry_seconds": round(paths[track_id][0][0], 3),
                    "exit_seconds": round(paths[track_id][-1][0], 3),
                })
            page = args.output_dir / f"{shot_id.lower()}_trajectory.jpg"
            draw.rectangle((0, 0, canvas.width, 28), fill=(15, 23, 42))
            draw.text((10, 8), f"{shot_id} {left:.3f}-{right:.3f}s | mid-frame base {representative_seconds:.3f}s | BoT-SORT IDs reset at cut", fill="white", font=font)
            canvas.save(page, format="JPEG", quality=88, optimize=True)
            shots_out.append({
                "shot_id": shot_id,
                "start_seconds": round(left, 3),
                "end_seconds": round(right, 3),
                "boundary": "cut",
                "tracks": tracks,
                "encounters": [],
                "evidence_page": str(page.resolve()),
                "warnings": [] if tracks else ["no person track detected at sampled frames"],
            })
    finally:
        cap.release()
    payload = {
        "schema_version": "1.0-shot-bounded-person-trajectories",
        "source_video": str(args.input.resolve()),
        "tracker": "Ultralytics BoT-SORT, person class only",
        "sample_fps": args.sample_fps,
        "analysis": {"start_seconds": args.start, "end_seconds": args.end, "shots": shots_out},
        "warnings": warnings + ["track IDs are anonymous and valid only inside one supplied shot partition"],
        "errors": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "shots": len(shots_out), "tracks": sum(len(x["tracks"]) for x in shots_out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

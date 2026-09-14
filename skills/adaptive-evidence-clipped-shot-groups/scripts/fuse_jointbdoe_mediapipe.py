#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(os.environ.get("TEMP", ".")) / "pose-fusion-mpl"))

import cv2
import mediapipe as mp
import numpy as np


ORIGINAL = re.compile(r"^frame_\d{2}_\d{6}ms\.jpg$", re.IGNORECASE)
CORE = [0, 11, 12, 13, 14, 23, 24]


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"cannot read {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError(f"cannot encode {path}")
    encoded.tofile(str(path))


def draw_body_arrow(image: np.ndarray, bbox, orientation: float) -> None:
    x1, y1, x2, y2 = bbox
    width, height = x2 - x1, y2 - y1
    length = min(int((width + height) / math.pi / 2), int(min(width, height) / 3))
    sx, sy = int((x1 + x2) / 2), int((y1 + y2) / 2)
    ex = int(sx - length * math.sin(math.radians(orientation)))
    ey = int(sy - length * math.cos(math.radians(orientation)))
    cv2.arrowedLine(image, (sx, sy), (ex, ey), (0, 230, 255), 4, cv2.LINE_AA, tipLength=0.28)


def box_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = width * height
    union = max(1.0, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
    return intersection / union


def touches_edge(bbox, frame_width: int, frame_height: int, margin: float = 0.06) -> bool:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return x1 <= frame_width * margin or y1 <= frame_height * margin or x2 >= frame_width * (1 - margin) or y2 >= frame_height * (1 - margin)


def unique_high_confidence(detections: list[dict], threshold: float = 0.4) -> list[dict]:
    result = []
    for detection in sorted(detections, key=lambda item: float(item.get("confidence", 0)), reverse=True):
        if float(detection.get("confidence", 0)) < threshold:
            continue
        if all(box_iou(detection["bbox_xyxy"], kept["bbox_xyxy"]) < 0.55 for kept in result):
            result.append(detection)
    return result


def selection_score(record: dict) -> float:
    unique = unique_high_confidence(record["detections"])
    verified = sum(d["mediapipe"]["status"] == "verified" for d in unique)
    weak = sum(d["mediapipe"]["status"] == "weak_pose" for d in unique)
    edge = sum(bool(d.get("edge_contact")) for d in unique)
    confidence = sum(float(d.get("confidence", 0)) for d in unique)
    role_bonus = {"motion_peak": 0.35, "start": 0.1, "end": 0.05}.get(record.get("candidate_role"), 0.0)
    return round(len(unique) * 10 + edge * 4 + verified * 3 + weak + confidence + role_bonus, 4)


def analyze_crop(pose, frame: np.ndarray, bbox) -> tuple[list | None, dict]:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    pad_x = (x2 - x1) * 0.08
    pad_y = (y2 - y1) * 0.05
    cx1, cy1 = max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))
    cx2, cy2 = min(w, int(x2 + pad_x)), min(h, int(y2 + pad_y))
    if cx2 - cx1 < 70 or cy2 - cy1 < 120:
        return None, {"status": "too_small", "crop_xyxy": [cx1, cy1, cx2, cy2]}
    crop = frame[cy1:cy2, cx1:cx2]
    result = pose.process(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    if not result.pose_landmarks:
        return None, {"status": "no_pose", "crop_xyxy": [cx1, cy1, cx2, cy2]}
    landmarks = list(result.pose_landmarks.landmark)
    visible_core = sum(landmarks[i].visibility >= 0.45 for i in CORE)
    mean_core = float(np.mean([landmarks[i].visibility for i in CORE]))
    status = "verified" if visible_core >= 5 and mean_core >= 0.55 else "weak_pose"
    mapped = []
    for landmark in landmarks:
        mapped.append({
            "x": cx1 + landmark.x * (cx2 - cx1),
            "y": cy1 + landmark.y * (cy2 - cy1),
            "z": float(landmark.z),
            "visibility": float(landmark.visibility),
        })
    return mapped, {
        "status": status,
        "crop_xyxy": [cx1, cy1, cx2, cy2],
        "visible_core_landmarks": visible_core,
        "mean_core_visibility": round(mean_core, 4),
    }


def draw_pose(image: np.ndarray, mapped: list[dict]) -> None:
    for a, b in mp.solutions.pose.POSE_CONNECTIONS:
        if mapped[a]["visibility"] >= 0.45 and mapped[b]["visibility"] >= 0.45:
            pa = (int(mapped[a]["x"]), int(mapped[a]["y"]))
            pb = (int(mapped[b]["x"]), int(mapped[b]["y"]))
            cv2.line(image, pa, pb, (70, 255, 80), 3, cv2.LINE_AA)
    for idx in CORE:
        if mapped[idx]["visibility"] >= 0.45:
            cv2.circle(image, (int(mapped[idx]["x"]), int(mapped[idx]["y"])), 5, (255, 220, 40), -1, cv2.LINE_AA)


def tile(image: np.ndarray, width=300, height=500, label="") -> np.ndarray:
    bar = 34
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    h, w = image.shape[:2]
    scale = min(width / w, (height - bar) / h)
    resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    x = (width - resized.shape[1]) // 2
    y = bar + (height - bar - resized.shape[0]) // 2
    canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    cv2.putText(canvas, label, (7, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in args.input_dir.iterdir() if p.is_file() and ORIGINAL.match(p.name))
    frame_index_path = args.input_dir / "representative_frames.json"
    frame_index = {}
    if frame_index_path.exists():
        frame_index = {
            str(item["file"]): item
            for item in json.loads(frame_index_path.read_text(encoding="utf-8-sig")).get("frames", [])
        }
    pose = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=0,
                                  enable_segmentation=False, min_detection_confidence=0.42,
                                  min_tracking_confidence=0.42)
    records = []
    annotated_frames = {}
    try:
        for name in names:
            path = args.input_dir / name
            frame = read_image(path)
            sidecar = path.with_name(path.stem + "_body_orientation.json")
            body = json.loads(sidecar.read_text(encoding="utf-8"))
            detections = []
            for index, detection in enumerate(body.get("detections", []), start=1):
                bbox = detection["bbox_xyxy"]
                mapped, pose_meta = analyze_crop(pose, frame, bbox)
                x1, y1, x2, y2 = [int(v) for v in bbox]
                edge_contact = touches_edge(bbox, frame.shape[1], frame.shape[0])
                confidence = float(detection.get("confidence", 0))
                rendered = confidence >= 0.4 or pose_meta["status"] == "verified" or edge_contact
                color = (40, 220, 40) if pose_meta["status"] == "verified" else (0, 100, 255)
                if rendered:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3, cv2.LINE_AA)
                    draw_body_arrow(frame, bbox, float(detection["body_orientation_degrees"]))
                    if mapped:
                        draw_pose(frame, mapped)
                    label = (f"P{index:02d} axis={detection['body_orientation_degrees']:.1f} "
                             f"pose={pose_meta['status']}")
                    cv2.rectangle(frame, (x1, max(0, y1 - 27)), (min(frame.shape[1], x1 + 285), y1), (0, 0, 0), -1)
                    cv2.putText(frame, label, (x1 + 4, max(17, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX,
                                0.42, (255, 255, 255), 1, cv2.LINE_AA)
                detections.append({**detection, "proposal_id": f"P{index:02d}", "mediapipe": pose_meta,
                                   "edge_contact": edge_contact, "rendered": rendered})
            timestamp = int(path.stem.split("_")[-1].replace("ms", "")) / 1000.0
            index_meta = frame_index.get(name, {})
            record = {"frame": name, "timestamp_seconds": timestamp,
                      "shot_id": str(index_meta.get("shot_id") or f"F{len(records) + 1:02d}"),
                      "candidate_role": str(index_meta.get("candidate_role") or "unknown"),
                      "motion_score": float(index_meta.get("motion_score") or 0.0),
                      "detections": detections}
            record["selection_score"] = selection_score(record)
            records.append(record)
            annotated_frames[name] = frame
    finally:
        pose.close()

    selected_records = []
    for shot_id in dict.fromkeys(record["shot_id"] for record in records):
        candidates = [record for record in records if record["shot_id"] == shot_id]
        selected_records.append(max(candidates, key=lambda record: (record["selection_score"], record["motion_score"])))
    page_items = [
        tile(annotated_frames[record["frame"]],
             label=f"{record['shot_id']} {record['timestamp_seconds']:06.3f}s {record['candidate_role']}")
        for record in selected_records
    ]
    rows = math.ceil(len(page_items) / 5)
    page = np.zeros((rows * 500, 5 * 300, 3), dtype=np.uint8)
    for i, item in enumerate(page_items):
        y, x = (i // 5) * 500, (i % 5) * 300
        page[y:y + 500, x:x + 300] = item
    page_path = output / "jointbdoe_mediapipe_fusion.jpg"
    write_image(page_path, page)
    manifest = {
        "schema_version": "0.2-multiperson-selection",
        "body_model": "JointBDOE-S",
        "pose_model": "MediaPipe Pose Lite per JointBDOE crop",
        "device": "cpu",
        "candidate_records": records,
        "selected_records": [
            {key: record[key] for key in ("shot_id", "frame", "timestamp_seconds", "candidate_role", "motion_score", "selection_score")}
            for record in selected_records
        ],
        "page": page_path.name,
        "warnings": [
            "No-pose detections are retained as unverified because a cropped edge person may be real.",
            "Pose verification does not establish identity, gaze target, action intent, or facing relationship.",
            "Reset proposal IDs at every frame and every hard cut.",
        ],
    }
    (output / "jointbdoe_mediapipe_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    counts = [d["mediapipe"]["status"] for r in records for d in r["detections"]]
    print(json.dumps({"candidate_frames": len(records), "selected_frames": len(selected_records),
                      "body_detections": len(counts),
                      "verified": counts.count("verified"), "weak_pose": counts.count("weak_pose"),
                      "no_pose": counts.count("no_pose"), "too_small": counts.count("too_small"),
                      "page": str(page_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

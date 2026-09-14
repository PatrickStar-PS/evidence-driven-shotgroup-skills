from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class CvDetectors:
    frontal: cv2.CascadeClassifier
    profile: cv2.CascadeClassifier
    hog: cv2.HOGDescriptor


def create_detectors() -> CvDetectors:
    frontal = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    if frontal.empty() or profile.empty():
        raise RuntimeError("Required OpenCV Haar cascades are unavailable")
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return CvDetectors(frontal=frontal, profile=profile, hog=hog)


def _iou(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def _nms(items: list[dict[str, Any]], threshold: float = 0.35) -> list[dict[str, Any]]:
    ordered = sorted(items, key=lambda item: float(item.get("score", 1.0)), reverse=True)
    kept: list[dict[str, Any]] = []
    for item in ordered:
        if any(_iou(item["box_px"], other["box_px"]) >= threshold for other in kept):
            continue
        kept.append(item)
    return kept


def _edge_contacts(box: list[int], width: int, height: int, margin_ratio: float = 0.04) -> list[str]:
    x, y, box_width, box_height = box
    margin_x = width * margin_ratio
    margin_y = height * margin_ratio
    contacts: list[str] = []
    if x <= margin_x:
        contacts.append("left")
    if x + box_width >= width - margin_x:
        contacts.append("right")
    if y <= margin_y:
        contacts.append("top")
    if y + box_height >= height - margin_y:
        contacts.append("bottom")
    return contacts


def _zone(value: float) -> str:
    if value < 1 / 3:
        return "left"
    if value > 2 / 3:
        return "right"
    return "center"


def _vertical_zone(value: float) -> str:
    if value < 1 / 3:
        return "top"
    if value > 2 / 3:
        return "bottom"
    return "middle"


def _sharpness(gray: np.ndarray, box: list[int]) -> float:
    x, y, width, height = box
    roi = gray[max(0, y):max(0, y + height), max(0, x):max(0, x + width)]
    if roi.size < 64:
        return 0.0
    return round(float(cv2.Laplacian(roi, cv2.CV_64F).var()), 2)


def _decorate(item: dict[str, Any], proposal_id: str, gray: np.ndarray, width: int, height: int) -> dict[str, Any]:
    x, y, box_width, box_height = (int(value) for value in item["box_px"])
    center_x = (x + box_width / 2) / width
    center_y = (y + box_height / 2) / height
    result = {
        "proposal_id": proposal_id,
        "detector": item["detector"],
        "box_px": [x, y, box_width, box_height],
        "center_norm": [round(center_x, 4), round(center_y, 4)],
        "size_norm": [round(box_width / width, 4), round(box_height / height, 4)],
        "area_ratio": round((box_width * box_height) / (width * height), 4),
        "horizontal_zone": _zone(center_x),
        "vertical_zone": _vertical_zone(center_y),
        "edge_contacts": _edge_contacts([x, y, box_width, box_height], width, height),
        "sharpness_laplacian": _sharpness(gray, [x, y, box_width, box_height]),
    }
    return result


def analyze_frame(image: Image.Image, detectors: CvDetectors) -> dict[str, Any]:
    rgb = np.asarray(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]

    person_items: list[dict[str, Any]] = []
    boxes, weights = detectors.hog.detectMultiScale(
        bgr,
        winStride=(4, 4),
        padding=(8, 8),
        scale=1.05,
    )
    for raw, weight in zip(boxes, weights):
        x, y, box_width, box_height = (int(value) for value in raw)
        if box_height < height * 0.28 or box_width < width * 0.10:
            continue
        if (box_width * box_height) / (width * height) < 0.025:
            continue
        person_items.append({
            "detector": "opencv_hog_person_candidate",
            "box_px": [x, y, box_width, box_height],
            "score": float(weight),
        })
    person_items = sorted(_nms(person_items, 0.35), key=lambda item: item["box_px"][2] * item["box_px"][3], reverse=True)[:4]

    minimum = max(36, round(width * 0.07))
    face_items: list[dict[str, Any]] = []
    for raw in detectors.frontal.detectMultiScale(gray, scaleFactor=1.06, minNeighbors=6, minSize=(minimum, minimum)):
        face_items.append({"detector": "haar_frontal_face_candidate", "box_px": [int(value) for value in raw], "score": 1.0})
    for direction, source in (("screen_left", gray), ("screen_right", cv2.flip(gray, 1))):
        for raw in detectors.profile.detectMultiScale(source, scaleFactor=1.05, minNeighbors=5, minSize=(minimum, minimum)):
            x, y, box_width, box_height = (int(value) for value in raw)
            if direction == "screen_right":
                x = width - x - box_width
            face_items.append({
                "detector": "haar_profile_face_region",
                "box_px": [x, y, box_width, box_height],
                "score": 1.05,
            })
    face_items = [
        item for item in _nms(face_items, 0.30)
        if (
            (item["box_px"][2] * item["box_px"][3]) / (width * height) >= 0.008
            or _edge_contacts(item["box_px"], width, height)
        )
        and (item["box_px"][1] + item["box_px"][3] / 2) / height <= 0.75
    ]
    anatomically_plausible: list[dict[str, Any]] = []
    for item in face_items:
        face_x, face_y, face_width, face_height = item["box_px"]
        center_x = face_x + face_width / 2
        center_y = face_y + face_height / 2
        containing_people = [
            person for person in person_items
            if person["box_px"][0] <= center_x <= person["box_px"][0] + person["box_px"][2]
            and person["box_px"][1] <= center_y <= person["box_px"][1] + person["box_px"][3]
        ]
        if containing_people:
            upper_body_match = any(
                (center_y - person["box_px"][1]) / max(1, person["box_px"][3]) <= 0.52
                for person in containing_people
            )
            if not upper_body_match:
                continue
        anatomically_plausible.append(item)
    face_items = anatomically_plausible
    face_items = sorted(face_items, key=lambda item: item["box_px"][2] * item["box_px"][3], reverse=True)[:3]

    people = [_decorate(item, f"P{index:02d}", gray, width, height) for index, item in enumerate(person_items, 1)]
    faces = [_decorate(item, f"F{index:02d}", gray, width, height) for index, item in enumerate(face_items, 1)]
    pair_source = people if len(people) >= 2 else faces
    pair_basis = "person_proposals" if len(people) >= 2 else "face_proposals"
    pairs: list[dict[str, Any]] = []
    for left_index in range(len(pair_source)):
        for right_index in range(left_index + 1, len(pair_source)):
            first, second = pair_source[left_index], pair_source[right_index]
            first_x, second_x = first["center_norm"][0], second["center_norm"][0]
            if abs(first_x - second_x) <= 0.03:
                relation = "overlapping_or_aligned"
            elif first_x < second_x:
                relation = "left_of"
            else:
                relation = "right_of"
            first_area = max(0.0001, float(first["area_ratio"]))
            second_area = max(0.0001, float(second["area_ratio"]))
            pairs.append({
                "subject": first["proposal_id"],
                "relative_to": second["proposal_id"],
                "basis": pair_basis,
                "horizontal_relation": relation,
                "box_iou": round(_iou(first["box_px"], second["box_px"]), 4),
                "area_ratio_subject_to_other": round(first_area / second_area, 3),
                "semantic_depth_or_occlusion": "not_determined",
            })

    return {
        "frame_width": width,
        "frame_height": height,
        "person_proposals": people,
        "face_proposals": faces,
        "pairwise_geometry": pairs,
    }


def estimate_global_motion(previous: Image.Image | None, current: Image.Image, previous_timestamp: float | None, timestamp: float) -> dict[str, Any]:
    if previous is None or previous_timestamp is None:
        return {"from_timestamp": None, "classification": "first_frame", "tracked_points": 0}

    def small_gray(image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        target_width = min(320, gray.shape[1])
        target_height = max(1, round(gray.shape[0] * target_width / gray.shape[1]))
        return cv2.resize(gray, (target_width, target_height), interpolation=cv2.INTER_AREA)

    left = small_gray(previous)
    right = small_gray(current)
    points = cv2.goodFeaturesToTrack(left, maxCorners=160, qualityLevel=0.01, minDistance=7)
    if points is None:
        return {"from_timestamp": round(previous_timestamp, 3), "classification": "insufficient_features", "tracked_points": 0}
    moved, status, _error = cv2.calcOpticalFlowPyrLK(left, right, points, None)
    if moved is None or status is None:
        return {"from_timestamp": round(previous_timestamp, 3), "classification": "flow_failed", "tracked_points": 0}
    valid = status.reshape(-1) == 1
    if int(valid.sum()) < 6:
        return {"from_timestamp": round(previous_timestamp, 3), "classification": "insufficient_tracks", "tracked_points": int(valid.sum())}
    delta = moved.reshape(-1, 2)[valid] - points.reshape(-1, 2)[valid]
    dx = float(np.median(delta[:, 0])) / left.shape[1]
    dy = float(np.median(delta[:, 1])) / left.shape[0]
    magnitude = float(np.hypot(dx, dy))
    if magnitude < 0.003:
        classification = "nearly_static"
    elif abs(dx) >= abs(dy) * 1.4:
        classification = "global_shift_screen_right" if dx > 0 else "global_shift_screen_left"
    elif abs(dy) >= abs(dx) * 1.4:
        classification = "global_shift_down" if dy > 0 else "global_shift_up"
    else:
        classification = "mixed_global_motion"
    return {
        "from_timestamp": round(previous_timestamp, 3),
        "to_timestamp": round(timestamp, 3),
        "median_dx_norm": round(dx, 5),
        "median_dy_norm": round(dy, 5),
        "magnitude_norm": round(magnitude, 5),
        "classification": classification,
        "tracked_points": int(valid.sum()),
        "interpretation_limit": "may include actor motion; not authoritative camera motion",
    }


def annotate_frame(image: Image.Image, evidence: dict[str, Any]) -> Image.Image:
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    font = ImageFont.load_default()
    width, height = annotated.size
    source_width = max(1, int(evidence.get("frame_width", width)))
    source_height = max(1, int(evidence.get("frame_height", height)))
    scale_x = width / source_width
    scale_y = height / source_height
    grid = (120, 210, 255)
    for x in (width / 3, width * 2 / 3):
        draw.line((x, 0, x, height), fill=grid, width=max(1, width // 360))
    for y in (height / 3, height * 2 / 3):
        draw.line((0, y, width, y), fill=grid, width=max(1, width // 360))
    margin_x, margin_y = round(width * 0.04), round(height * 0.04)
    draw.rectangle((margin_x, margin_y, width - margin_x, height - margin_y), outline=(255, 115, 90), width=max(1, width // 300))

    for collection, colour in ((evidence.get("person_proposals", []), (40, 225, 225)), (evidence.get("face_proposals", []), (255, 215, 0))):
        for item in collection:
            raw_x, raw_y, raw_width, raw_height = item["box_px"]
            x = round(raw_x * scale_x)
            y = round(raw_y * scale_y)
            box_width = round(raw_width * scale_x)
            box_height = round(raw_height * scale_y)
            draw.rectangle((x, y, x + box_width, y + box_height), outline=colour, width=max(2, width // 180))
            zone = item["horizontal_zone"][0].upper()
            label = f"{item['proposal_id']} {zone} A{item['area_ratio'] * 100:.1f}% S{item['sharpness_laplacian']:.0f}"
            if item.get("edge_contacts"):
                label += " edge=" + "/".join(item["edge_contacts"])
            bbox = draw.textbbox((0, 0), label, font=font)
            label_y = max(0, y - (bbox[3] - bbox[1]) - 5)
            draw.rectangle((x, label_y, min(width - 1, x + bbox[2] - bbox[0] + 6), y), fill=(0, 0, 0))
            draw.text((x + 3, label_y + 1), label, fill=colour, font=font)
    return annotated

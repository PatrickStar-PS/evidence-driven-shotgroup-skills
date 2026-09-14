#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=path.parent)
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


def proposal_count(frame: dict[str, Any]) -> int:
    # Person and face boxes may describe the same subject. The larger count is a
    # conservative presence estimate and avoids summing duplicate detectors.
    return max(len(frame.get("person_proposals") or []), len(frame.get("face_proposals") or []))


def frame_edges(frame: dict[str, Any]) -> set[str]:
    edges: set[str] = set()
    for proposal in [*(frame.get("person_proposals") or []), *(frame.get("face_proposals") or [])]:
        edges.update(str(value) for value in proposal.get("edge_contacts") or [])
    return edges


def shot_for_timestamp(shots: list[dict[str, Any]], timestamp: float) -> dict[str, Any] | None:
    for shot in shots:
        start = float(shot["start_seconds"])
        end = float(shot["end_seconds"])
        if start <= timestamp < end or abs(timestamp - end) <= 0.001:
            return shot
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide whether one clipped range needs auxiliary multi-person pose evidence.")
    parser.add_argument("--cv-evidence", required=True, type=Path)
    parser.add_argument("--event-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threshold", type=int, default=5)
    args = parser.parse_args()

    cv = load_json(args.cv_evidence.resolve())
    events = load_json(args.event_manifest.resolve())
    frames = list(cv.get("cv_geometry_frames") or [])
    shots = list(events.get("shot_ranges") or [])
    if not frames:
        raise RuntimeError("cv evidence has no cv_geometry_frames")
    if not shots:
        raise RuntimeError("event manifest has no shot_ranges")

    counts = [proposal_count(frame) for frame in frames]
    multi_frames = [frame for frame in frames if proposal_count(frame) >= 2]
    edge_frames = [frame for frame in frames if frame_edges(frame)]
    overlap_frames = [
        frame for frame in frames
        if any(float(pair.get("box_iou") or 0.0) >= 0.10 for pair in frame.get("pairwise_geometry") or [])
    ]
    scale_complex_frames = [
        frame for frame in frames
        if any(
            max(float(pair.get("area_ratio_subject_to_other") or 1.0), 1.0 / max(float(pair.get("area_ratio_subject_to_other") or 1.0), 1e-6)) >= 1.8
            for pair in frame.get("pairwise_geometry") or []
        )
    ]
    all_faces = [proposal for frame in frames for proposal in frame.get("face_proposals") or []]
    profile_count = sum(str(item.get("detector")) == "haar_profile_face_region" for item in all_faces)
    frontal_count = sum(str(item.get("detector")) == "haar_frontal_face_candidate" for item in all_faces)

    reasons: list[str] = []
    score = 0
    if len(multi_frames) >= 2:
        score += 3
        reasons.append("multi_person_in_multiple_frames")
    if edge_frames:
        score += 2
        reasons.append("frame_edge_contact_or_crop")
    if overlap_frames:
        score += 2
        reasons.append("proposal_overlap")
    if counts and max(counts) - min(counts) >= 2:
        score += 2
        reasons.append("person_count_instability")
    if profile_count >= 2 and profile_count > frontal_count:
        score += 2
        reasons.append("profile_dominant_face_evidence")
    if scale_complex_frames:
        score += 1
        reasons.append("large_same_frame_scale_difference")

    direct_trigger = bool(multi_frames and edge_frames) or bool(overlap_frames and multi_frames)
    pose_enabled = bool(direct_trigger or score >= args.threshold)

    triggered_shots: list[dict[str, Any]] = []
    for shot in shots:
        shot_id = str(shot.get("id") or "")
        shot_frames = [
            frame for frame in frames
            if (match := shot_for_timestamp([shot], float(frame.get("timestamp") or 0.0))) is not None
        ]
        shot_reasons: list[str] = []
        if any(proposal_count(frame) >= 2 for frame in shot_frames):
            shot_reasons.append("multi_person")
        if any(frame_edges(frame) for frame in shot_frames):
            shot_reasons.append("edge_crop")
        if any(any(float(pair.get("box_iou") or 0.0) >= 0.10 for pair in frame.get("pairwise_geometry") or []) for frame in shot_frames):
            shot_reasons.append("overlap")
        if shot_reasons:
            triggered_shots.append({
                "shot_id": shot_id,
                "start_seconds": float(shot["start_seconds"]),
                "end_seconds": float(shot["end_seconds"]),
                "reasons": shot_reasons,
            })

    payload = {
        "schema_version": "1.0-adaptive-pose-gate",
        "range": {
            "start_seconds": float(cv.get("range_start_seconds", events.get("range", {}).get("start_seconds", 0.0))),
            "end_seconds": float(cv.get("range_end_seconds", events.get("range", {}).get("end_seconds", 0.0))),
        },
        "pose_enabled": pose_enabled,
        "score": score,
        "threshold": args.threshold,
        "direct_trigger": direct_trigger,
        "reasons": reasons,
        "triggered_shots": triggered_shots,
        "metrics": {
            "geometry_frame_count": len(frames),
            "multi_person_frame_count": len(multi_frames),
            "edge_frame_count": len(edge_frames),
            "overlap_frame_count": len(overlap_frames),
            "scale_complex_frame_count": len(scale_complex_frames),
            "minimum_presence_count": min(counts),
            "maximum_presence_count": max(counts),
            "profile_face_candidates": profile_count,
            "frontal_face_candidates": frontal_count,
        },
        "evidence_boundary": "This gate only controls whether an auxiliary pose page is attached; it does not assign identity, orientation, depth, action, or dialogue.",
        "warnings": [],
        "errors": [],
    }
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({"pose_enabled": pose_enabled, "score": score, "triggered_shots": len(triggered_shots)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

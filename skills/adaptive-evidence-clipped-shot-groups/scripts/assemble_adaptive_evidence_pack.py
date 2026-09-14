#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
    return {"width": width, "height": height, "bytes": path.stat().st_size, "sha256": sha256(path)}


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble role-labelled evidence for clipped adaptive analysis.")
    parser.add_argument("--range-edges", required=True, type=Path)
    parser.add_argument("--event-keyframes", required=True, type=Path)
    parser.add_argument("--motion-triplets", required=True, type=Path)
    parser.add_argument("--spatial-page", required=True, type=Path)
    parser.add_argument("--trajectory-page", required=True, type=Path)
    parser.add_argument("--trajectory-json", required=True, type=Path)
    parser.add_argument("--gate-file", required=True, type=Path)
    parser.add_argument("--pose-page", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    gate = load_json(args.gate_file.resolve())
    pose_enabled = bool(gate.get("pose_enabled"))
    if pose_enabled and not args.pose_page:
        raise RuntimeError("pose gate enabled but --pose-page was not provided")
    trajectory = load_json(args.trajectory_json.resolve())
    if trajectory.get("schema_version") != "1.0-shot-bounded-person-trajectories":
        raise RuntimeError("unsupported trajectory schema")
    trajectory_shots = ((trajectory.get("analysis") or {}).get("shots") or [])
    if not trajectory_shots:
        raise RuntimeError("trajectory evidence has no shots")
    trajectory_summary = {
        "shot_count": len(trajectory_shots),
        "track_count": sum(len(shot.get("tracks") or []) for shot in trajectory_shots),
        "encounter_count": sum(len(shot.get("encounters") or []) for shot in trajectory_shots),
        "warnings": list(trajectory.get("warnings") or []),
    }

    specifications = [
        ("range_boundaries", args.range_edges.resolve(), "page_01_range_edges.jpg"),
        ("action_events", args.event_keyframes.resolve(), "page_02_event_keyframes.jpg"),
        ("high_motion_triplets", args.motion_triplets.resolve(), "page_03_motion_triplets.jpg"),
        ("shot_space", args.spatial_page.resolve(), "page_04_shot_space.jpg"),
        ("person_trajectory", args.trajectory_page.resolve(), "page_05_person_trajectory.jpg"),
    ]
    if pose_enabled:
        specifications.append(("multi_person_geometry", args.pose_page.resolve(), "page_06_jointbdoe_mediapipe.jpg"))

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    pages = []
    for order, (role, source, filename) in enumerate(specifications, start=1):
        if not source.exists():
            raise RuntimeError(f"evidence image does not exist: {source}")
        destination = output / filename
        shutil.copy2(source, destination)
        page = {"order": order, "role": role, "file": filename, **image_metadata(destination)}
        if role == "person_trajectory":
            page["summary"] = trajectory_summary
        pages.append(page)

    payload = {
        "schema_version": "1.0-adaptive-clipped-evidence",
        "range": gate.get("range") or {},
        "pose_gate": {
            "pose_enabled": pose_enabled,
            "score": gate.get("score"),
            "threshold": gate.get("threshold"),
            "reasons": gate.get("reasons") or [],
            "triggered_shots": gate.get("triggered_shots") or [],
        },
        "relay_pages": pages,
        "trajectory_evidence": {
            "source": str(args.trajectory_json.resolve()),
            "sha256": sha256(args.trajectory_json.resolve()),
            **trajectory_summary,
        },
        "priority": ["original_clipped_video", "action_events_and_shot_space", "person_trajectory", "multi_person_geometry"],
        "warnings": [],
        "errors": [],
    }
    atomic_json(args.manifest.resolve(), payload)
    print(json.dumps({"pages": len(pages), "pose_enabled": pose_enabled, "manifest": str(args.manifest.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

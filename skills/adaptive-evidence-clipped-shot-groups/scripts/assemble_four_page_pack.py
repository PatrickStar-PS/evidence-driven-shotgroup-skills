#!/usr/bin/env python3
"""Assemble and validate the selected four-page experimental evidence pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image


PAGE_SPECS = (
    ("range_edges.jpg", "page_01_range_edges.jpg", "range_boundaries"),
    ("event_keyframes.jpg", "page_02_event_keyframes.jpg", "action_events"),
    ("motion_triplets.jpg", "page_03_motion_triplets.jpg", "high_motion_triplets"),
    ("jointbdoe_mediapipe_fusion.jpg", "page_04_jointbdoe_mediapipe.jpg", "multi_person_geometry"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-evidence-dir", required=True, type=Path)
    parser.add_argument("--fusion-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_meta(path: Path) -> dict:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
    return {
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    args = parse_args()
    base_dir = args.base_evidence_dir.resolve()
    fusion_dir = args.fusion_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base_manifest = load_json(base_dir / "pose_evidence_manifest.json")
    fusion_manifest = load_json(fusion_dir / "jointbdoe_mediapipe_manifest.json")
    pages = []

    for source_name, output_name, role in PAGE_SPECS:
        source_dir = fusion_dir if source_name.startswith("jointbdoe_") else base_dir
        source = source_dir / source_name
        if not source.is_file():
            raise FileNotFoundError(f"Required evidence page is missing: {source}")
        destination = output_dir / output_name
        shutil.copy2(source, destination)
        pages.append(
            {
                "order": len(pages) + 1,
                "role": role,
                "file": output_name,
                "source_set": "fusion" if source_dir == fusion_dir else "base_evidence",
                "source_file": source_name,
                **image_meta(destination),
            }
        )

    payload = {
        "schema_version": "0.2-four-page-fusion-canary",
        "episode": base_manifest.get("episode", fusion_manifest.get("episode", "09")),
        "range": base_manifest.get("range", fusion_manifest.get("range")),
        "relay_pages": pages,
        "warnings": [
            "Experimental local canary only; no relay call was made.",
            "JointBDOE and MediaPipe outputs are geometric evidence, not semantic truth.",
            "A failed MediaPipe crop remains present as an unverified JointBDOE proposal.",
            "Action-event and high-motion pages remain independent temporal evidence.",
        ],
    }
    manifest_path = output_dir / "four_page_evidence_manifest.json"
    atomic_json(manifest_path, payload)
    print(json.dumps({"manifest": str(manifest_path), "pages": len(pages)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

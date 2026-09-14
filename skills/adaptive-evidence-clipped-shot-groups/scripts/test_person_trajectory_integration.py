#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


HERE = Path(__file__).resolve().parent


def run(*args: object) -> None:
    completed = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, check=False)
    if completed.returncode:
        raise AssertionError(f"command failed: {completed.stdout}\n{completed.stderr}")


def load_bai():
    spec = importlib.util.spec_from_file_location("bai_compact_timeline_trajectory_test", HERE / "bai_compact_timeline.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_image(path: Path, label: str) -> None:
    image = Image.new("RGB", (720, 240), "#172033")
    draw = ImageDraw.Draw(image)
    draw.text((24, 24), label, fill="white")
    image.save(path, format="JPEG", quality=90)


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        shot_pages = []
        shots = []
        for index, (start, end) in enumerate(((0.0, 2.7), (2.7, 5.2)), 1):
            page = root / f"shot_{index:03d}_trajectory.jpg"
            make_image(page, f"S{index:03d} anonymous trajectory")
            shot_pages.append(page)
            shots.append({
                "shot_id": f"E{index:03d}",
                "start_seconds": start,
                "end_seconds": end,
                "boundary": "cut",
                "tracks": [{"track_id": f"S{index:03d}-T01"}],
                "encounters": [] if index == 1 else [{"event": "crossed_screen_order"}],
                "evidence_page": str(page),
                "warnings": [],
            })
        trajectory_json = root / "trajectory.json"
        trajectory_json.write_text(json.dumps({
            "schema_version": "1.0-shot-bounded-person-trajectories",
            "analysis": {"shots": shots},
            "warnings": ["track_id is valid only inside one semantic shot"],
            "errors": [],
        }), encoding="utf-8")
        trajectory_page = root / "person_trajectory.jpg"
        run(HERE / "assemble_trajectory_page.py", "--trajectory-json", trajectory_json, "--output", trajectory_page)
        assert trajectory_page.exists()

        static_pages = []
        for name in ("range_edges", "event_keyframes", "motion_triplets", "shot_space"):
            path = root / f"{name}.jpg"
            make_image(path, name)
            static_pages.append(path)
        gate = root / "pose_gate.json"
        gate.write_text(json.dumps({"pose_enabled": False, "score": 0.2, "threshold": 0.6, "range": {"start_seconds": 0.0, "end_seconds": 5.2}}), encoding="utf-8")
        pack_dir = root / "pack"
        manifest = pack_dir / "adaptive_evidence_manifest.json"
        run(
            HERE / "assemble_adaptive_evidence_pack.py",
            "--range-edges", static_pages[0],
            "--event-keyframes", static_pages[1],
            "--motion-triplets", static_pages[2],
            "--spatial-page", static_pages[3],
            "--trajectory-page", trajectory_page,
            "--trajectory-json", trajectory_json,
            "--gate-file", gate,
            "--output-dir", pack_dir,
            "--manifest", manifest,
        )
        pack = json.loads(manifest.read_text(encoding="utf-8"))
        assert [page["role"] for page in pack["relay_pages"]] == [
            "range_boundaries", "action_events", "high_motion_triplets", "shot_space", "person_trajectory"
        ]
        assert pack["trajectory_evidence"]["track_count"] == 2
        assert pack["trajectory_evidence"]["encounter_count"] == 1
        bai = load_bai()
        pages, loaded = bai.load_evidence_pack(manifest)
        assert [page["role"] for page in pages][-1] == "person_trajectory"
        assert pages[-1]["summary"]["shot_count"] == 2
        assert loaded["priority"][2] == "person_trajectory"

    print(json.dumps({"status": "passed", "checks": 8}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

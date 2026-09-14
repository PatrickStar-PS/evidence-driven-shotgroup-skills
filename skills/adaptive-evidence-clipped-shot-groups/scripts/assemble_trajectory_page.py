#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_trajectory(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != "1.0-shot-bounded-person-trajectories":
        raise RuntimeError("unsupported trajectory schema")
    shots = ((value.get("analysis") or {}).get("shots") or [])
    if not shots:
        raise RuntimeError("trajectory JSON has no shots")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine shot-bounded trajectory pages into one relay evidence page.")
    parser.add_argument("--trajectory-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-width", type=int, default=1800)
    parser.add_argument("--jpeg-quality", type=int, default=88)
    args = parser.parse_args()
    if args.max_width < 720:
        raise RuntimeError("--max-width must be at least 720")

    trajectory_path = args.trajectory_json.resolve()
    payload = load_trajectory(trajectory_path)
    shots = payload["analysis"]["shots"]
    pages: list[tuple[dict, Image.Image]] = []
    for shot in shots:
        source = Path(str(shot.get("evidence_page") or ""))
        source = source if source.is_absolute() else trajectory_path.parent / source
        source = source.resolve()
        if not source.exists():
            raise RuntimeError(f"trajectory evidence page does not exist: {source}")
        with Image.open(source) as opened:
            image = opened.convert("RGB")
        if image.width > args.max_width:
            height = max(1, round(image.height * args.max_width / image.width))
            image = image.resize((args.max_width, height), Image.Resampling.LANCZOS)
        pages.append((shot, image))

    banner_height = 54
    gap = 12
    width = max(image.width for _, image in pages)
    height = banner_height + sum(image.height for _, image in pages) + gap * (len(pages) - 1)
    canvas = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    track_count = sum(len(shot.get("tracks") or []) for shot, _ in pages)
    encounter_count = sum(len(shot.get("encounters") or []) for shot, _ in pages)
    title = f"PERSON TRAJECTORY | shots={len(pages)} tracks={track_count} encounters={encounter_count} | IDs reset at every cut"
    draw.text((16, 18), title, fill="white", font=font)
    y = banner_height
    for shot, image in pages:
        x = (width - image.width) // 2
        canvas.paste(image, (x, y))
        y += image.height + gap

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, format="JPEG", quality=args.jpeg_quality, optimize=True)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "shots": len(pages),
        "tracks": track_count,
        "encounters": encounter_count,
        "width": width,
        "height": height,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

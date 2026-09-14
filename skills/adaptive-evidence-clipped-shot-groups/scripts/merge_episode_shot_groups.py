#!/usr/bin/env python3
"""Merge validated per-episode expanded shot-group JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


EPISODE_RE = re.compile(r"^(?:EP)?0*(\d+)$", re.IGNORECASE)


def parse_expected(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    result: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start, end = int(left), int(right)
            if start > end:
                raise ValueError(f"invalid episode range: {part}")
            result.update(range(start, end + 1))
        else:
            result.add(int(part))
    if not result or min(result) < 1:
        raise ValueError("expected episodes must be positive integers")
    return sorted(result)


def episode_number(value: object) -> int:
    match = EPISODE_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"invalid episode value: {value!r}")
    number = int(match.group(1))
    if number < 1:
        raise ValueError(f"invalid episode value: {value!r}")
    return number


def discover(args: argparse.Namespace) -> list[Path]:
    if args.inputs:
        paths = [Path(item).resolve() for item in args.inputs]
    else:
        root = Path(args.input_dir).resolve()
        paths = sorted(root.rglob(args.filename))
    output = Path(args.output).resolve()
    paths = [path for path in paths if path.resolve() != output]
    if not paths:
        raise ValueError("no episode shot-group JSON files found")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"input files do not exist: {missing}")
    return paths


def load_document(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0":
        raise ValueError(f"{path}: unsupported schema_version")
    if document.get("errors"):
        raise ValueError(f"{path}: input contains errors")
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: rows must be a non-empty array")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--inputs", nargs="+")
    source.add_argument("--input-dir")
    parser.add_argument("--filename", default="shot_groups.json")
    parser.add_argument("--expected-episodes")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        expected = parse_expected(args.expected_episodes)
        paths = discover(args)
        episodes: dict[int, tuple[Path, dict, list[dict]]] = {}
        all_videos: list[dict] = []
        all_warnings: list[str] = []
        backends: set[str] = set()

        for path in paths:
            document = load_document(path)
            rows = document["rows"]
            numbers = {episode_number(row.get("episode")) for row in rows}
            if len(numbers) != 1:
                raise ValueError(f"{path}: one file must contain exactly one episode, found {sorted(numbers)}")
            number = numbers.pop()
            if number in episodes:
                raise ValueError(f"duplicate episode {number}: {episodes[number][0]} and {path}")
            episodes[number] = (path, document, rows)
            source_info = document.get("source") or {}
            backend = str(source_info.get("backend") or "").strip()
            if backend:
                backends.add(backend)
            for video in source_info.get("videos") or []:
                if isinstance(video, dict):
                    all_videos.append(video)
            all_warnings.extend(f"EP{number:02d}: {warning}" for warning in document.get("warnings") or [])

        actual = sorted(episodes)
        if expected is not None and actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise ValueError(f"episode set mismatch; missing={missing}, extra={extra}")

        merged_rows: list[dict] = []
        for number in actual:
            path, _, rows = episodes[number]
            ordered = sorted(rows, key=lambda row: (float(row.get("start_seconds", -1)), float(row.get("end_seconds", -1))))
            previous_end: float | None = None
            for index, source_row in enumerate(ordered, start=1):
                row = dict(source_row)
                start = float(row.get("start_seconds"))
                end = float(row.get("end_seconds"))
                if start < 0 or end <= start:
                    raise ValueError(f"{path}: invalid time range at row {index}")
                if previous_end is not None and start < previous_end - 0.001:
                    raise ValueError(f"{path}: overlapping groups at row {index}")
                row["episode"] = f"{number:02d}"
                row["group_id"] = f"EP{number:02d}-G{index:03d}"
                merged_rows.append(row)
                previous_end = end

        unique_videos: dict[tuple[str, str], dict] = {}
        for video in all_videos:
            key = (str(video.get("episode") or ""), str(video.get("fingerprint") or video.get("name") or ""))
            unique_videos[key] = video

        output_document = {
            "schema_version": "1.0",
            "source": {
                "backend": " + ".join(sorted(backends)) or "merged validated episode outputs",
                "videos": sorted(unique_videos.values(), key=lambda item: episode_number(item.get("episode", 0))),
            },
            "rows": merged_rows,
            "warnings": all_warnings,
            "errors": [],
            "batch": {
                "episodes": [f"{number:02d}" for number in actual],
                "episode_count": len(actual),
                "row_count": len(merged_rows),
                "inputs": [str(episodes[number][0]) for number in actual],
            },
        }
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(output_document, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(output), "episodes": actual, "rows": len(merged_rows), "warnings": len(all_warnings)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

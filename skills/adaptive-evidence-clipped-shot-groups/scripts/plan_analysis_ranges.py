#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def count_candidates(candidates: list[float], start: float, end: float) -> int:
    return sum(1 for value in candidates if start < value < end)


def choose_candidate(
    candidates: list[float],
    scores: dict[float, float],
    target: float,
    low: float,
    high: float,
    window_seconds: float,
) -> tuple[float, str, float] | None:
    viable = [value for value in candidates if low <= value <= high]
    window = [value for value in viable if abs(value - target) <= window_seconds]
    high_confidence = [value for value in window if scores.get(round(value, 3), 0.0) >= 0.55]
    pool = high_confidence or window or viable
    if not pool:
        return None
    selected = min(pool, key=lambda value: (abs(value - target), -scores.get(round(value, 3), 0.0)))
    source = "high_confidence_boundary" if high_confidence else "boundary_candidate"
    return selected, source, scores.get(round(selected, 3), 0.0)


def plan_split_points(
    duration: float,
    candidates: list[float],
    scores: dict[float, float],
    *,
    max_ranges: int,
    target_range_seconds: float,
    max_range_seconds: float,
    max_candidates_per_range: int,
    min_range_seconds: float,
    auto_expand: bool = True,
) -> tuple[list[float], dict[float, dict], list[str]]:
    feasible_capacity = max(1, int(duration // min_range_seconds))
    default_max = max(1, min(max_ranges, feasible_capacity))
    feasible_max = feasible_capacity if auto_expand else default_max
    desired = max(
        1,
        math.ceil(duration / target_range_seconds),
        math.ceil(len(candidates) / max_candidates_per_range) if candidates else 1,
    )
    range_count = min(feasible_max, desired)
    split_points: list[float] = []
    seam_metadata: dict[float, dict] = {}

    for index in range(1, range_count):
        target = duration * index / range_count
        remaining = range_count - index
        low = (split_points[-1] if split_points else 0.0) + min_range_seconds
        high = duration - remaining * min_range_seconds
        selected = choose_candidate(
            [value for value in candidates if value not in split_points],
            scores,
            target,
            low,
            high,
            max(2.0, target_range_seconds * 0.35),
        )
        if selected:
            value, source, score = selected
        else:
            value = min(high, max(low, target))
            source, score = "nominal_transport_seam", 0.0
        value = round(value, 3)
        split_points.append(value)
        seam_metadata[value] = {"selection_source": source, "candidate_score": round(score, 6)}

    warnings: list[str] = []
    while len(split_points) + 1 < feasible_max:
        boundaries = [0.0, *sorted(split_points), duration]
        violations: list[tuple[float, float, float, int]] = []
        for start, end in zip(boundaries, boundaries[1:]):
            candidate_count = count_candidates(candidates, start, end)
            duration_ratio = (end - start) / max_range_seconds
            density_ratio = candidate_count / max_candidates_per_range
            if duration_ratio > 1.0001 or density_ratio > 1.0001:
                violations.append((max(duration_ratio, density_ratio), start, end, candidate_count))
        if not violations:
            break
        _, start, end, candidate_count = max(violations)
        low, high = start + min_range_seconds, end - min_range_seconds
        if low > high + 0.001:
            warnings.append(
                f"range {start:.3f}-{end:.3f}s exceeds a planning target but cannot be split without violating the minimum range length"
            )
            break
        target = (start + end) / 2.0
        viable = [value for value in candidates if low <= value <= high and value not in split_points]
        if viable:
            def split_cost(value: float) -> tuple[float, float]:
                left_count = count_candidates(candidates, start, value)
                right_count = count_candidates(candidates, value, end)
                density_balance = abs(left_count - right_count) / max(1, candidate_count)
                duration_balance = abs(value - target) / max(0.001, end - start)
                confidence_bonus = scores.get(round(value, 3), 0.0) * 0.15
                return density_balance + duration_balance - confidence_bonus, abs(value - target)

            value = min(viable, key=split_cost)
            source = "density_refinement_boundary"
            score = scores.get(round(value, 3), 0.0)
        else:
            value, source, score = target, "density_refinement_nominal", 0.0
        value = round(value, 3)
        split_points.append(value)
        split_points.sort()
        seam_metadata[value] = {"selection_source": source, "candidate_score": round(score, 6)}

    boundaries = [0.0, *sorted(split_points), duration]
    for start, end in zip(boundaries, boundaries[1:]):
        candidate_count = count_candidates(candidates, start, end)
        if end - start > max_range_seconds + 0.001 or candidate_count > max_candidates_per_range:
            warnings.append(
                f"range {start:.3f}-{end:.3f}s remains above target with {candidate_count} candidates; "
                f"effective-max-ranges={feasible_max}"
            )
    return sorted(split_points), seam_metadata, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan adaptive bounded relay ranges from duration and boundary density.")
    parser.add_argument("--boundaries-file", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-ranges",
        type=int,
        default=8,
        help="Default soft range limit; the planner expands beyond it when targets still require more ranges",
    )
    parser.add_argument(
        "--disable-auto-expand",
        action="store_true",
        help="Treat --max-ranges as a hard cap instead of the default auto-expanding soft limit",
    )
    parser.add_argument("--target-range-seconds", type=float, default=9.0)
    parser.add_argument("--max-range-seconds", type=float, default=12.0)
    parser.add_argument("--max-candidates-per-range", type=int, default=8)
    parser.add_argument("--min-range-seconds", type=float, default=5.0)
    parser.add_argument("--context-seconds", type=float, default=1.5, help="Pre/post-roll included only in the physical relay clip")
    args = parser.parse_args()
    if not (0 < args.min_range_seconds <= args.target_range_seconds <= args.max_range_seconds):
        parser.error("require 0 < min-range-seconds <= target-range-seconds <= max-range-seconds")
    if args.max_ranges < 1 or args.max_candidates_per_range < 1 or args.context_seconds < 0:
        parser.error("range counts must be positive and context-seconds cannot be negative")

    data = json.loads(args.boundaries_file.read_text(encoding="utf-8-sig"))
    candidates = sorted(
        {round(float(value), 3) for value in (data.get("boundaries") or []) if 0.05 < float(value) < args.duration - 0.05}
    )
    scores = {
        round(float(item.get("seconds")), 3): float(item.get("score", 0))
        for item in (data.get("peaks") or [])
        if isinstance(item, dict) and item.get("seconds") is not None
    }
    split_points, seam_metadata, warnings = plan_split_points(
        args.duration,
        candidates,
        scores,
        max_ranges=args.max_ranges,
        target_range_seconds=args.target_range_seconds,
        max_range_seconds=args.max_range_seconds,
        max_candidates_per_range=args.max_candidates_per_range,
        min_range_seconds=args.min_range_seconds,
        auto_expand=not args.disable_auto_expand,
    )
    boundaries = [0.0, *split_points, args.duration]
    ranges = []
    for index in range(len(boundaries) - 1):
        logical_start = round(boundaries[index], 3)
        logical_end = round(boundaries[index + 1], 3)
        clip_start = round(max(0.0, logical_start - args.context_seconds), 3)
        clip_end = round(min(args.duration, logical_end + args.context_seconds), 3)
        seam = seam_metadata.get(logical_start, {}) if index > 0 else {}
        ranges.append({
            "id": f"part{index + 1:02d}" if len(boundaries) > 2 else "full",
            "start_seconds": logical_start,
            "end_seconds": logical_end,
            "logical_start_seconds": logical_start,
            "logical_end_seconds": logical_end,
            "logical_duration_seconds": round(logical_end - logical_start, 3),
            "estimated_candidate_count": count_candidates(candidates, logical_start, logical_end),
            "clip_start_seconds": clip_start,
            "clip_end_seconds": clip_end,
            "clip_duration_seconds": round(clip_end - clip_start, 3),
            "absolute_offset_seconds": clip_start,
            "core_start_clip_seconds": round(logical_start - clip_start, 3),
            "core_end_clip_seconds": round(logical_end - clip_start, 3),
            "context_before_seconds": round(logical_start - clip_start, 3),
            "context_after_seconds": round(clip_end - logical_end, 3),
            "seam_owner": "start" if index > 0 else "none",
            "start_seam_selection_source": seam.get("selection_source", "none"),
            "start_seam_candidate_score": seam.get("candidate_score"),
        })
    auto_expanded = not args.disable_auto_expand and len(ranges) > args.max_ranges
    reason = (
        f"adaptive plan: {len(candidates)} candidates, {args.duration:.3f}s, target {args.target_range_seconds:.1f}s, "
        f"hard max {args.max_range_seconds:.1f}s and <= {args.max_candidates_per_range} candidates per range; "
        f"default limit {args.max_ranges}, final count {len(ranges)}"
    )
    result = {
        "schema_version": "1.1",
        "duration_seconds": args.duration,
        "candidate_count": len(candidates),
        "mode": "segmented" if len(ranges) > 1 else "single",
        "transport_mode": "adaptive_overlap_clipped_video",
        "context_seconds": args.context_seconds,
        "planner": {
            "default_max_ranges": args.max_ranges,
            "max_ranges": args.max_ranges,
            "auto_expand_enabled": not args.disable_auto_expand,
            "auto_expanded": auto_expanded,
            "final_range_count": len(ranges),
            "target_range_seconds": args.target_range_seconds,
            "max_range_seconds": args.max_range_seconds,
            "max_candidates_per_range": args.max_candidates_per_range,
            "min_range_seconds": args.min_range_seconds,
        },
        "reason": reason,
        "transport_seams": [
            {"seconds": value, **seam_metadata[value]} for value in sorted(seam_metadata)
        ],
        "ranges": ranges,
        "warnings": warnings,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

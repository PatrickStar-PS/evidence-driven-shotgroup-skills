#!/usr/bin/env python3
from __future__ import annotations

from plan_analysis_ranges import count_candidates, plan_split_points


def assert_plan(duration: float, candidates: list[float]) -> None:
    scores = {round(value, 3): 0.65 for value in candidates}
    split_points, _, warnings = plan_split_points(
        duration,
        candidates,
        scores,
        max_ranges=8,
        target_range_seconds=9.0,
        max_range_seconds=12.0,
        max_candidates_per_range=8,
        min_range_seconds=5.0,
    )
    boundaries = [0.0, *split_points, duration]
    assert 1 <= len(boundaries) - 1 <= 8
    assert boundaries == sorted(boundaries)
    for start, end in zip(boundaries, boundaries[1:]):
        assert end > start
        assert end - start <= 12.001
        assert count_candidates(candidates, start, end) <= 8
    assert not warnings


def assert_auto_expansion() -> None:
    duration = 110.0
    split_points, _, warnings = plan_split_points(
        duration,
        [],
        {},
        max_ranges=8,
        target_range_seconds=9.0,
        max_range_seconds=12.0,
        max_candidates_per_range=8,
        min_range_seconds=5.0,
    )
    boundaries = [0.0, *split_points, duration]
    assert len(boundaries) - 1 > 8
    assert all(end - start <= 12.001 for start, end in zip(boundaries, boundaries[1:]))
    assert not warnings

    capped_points, _, capped_warnings = plan_split_points(
        duration,
        [],
        {},
        max_ranges=8,
        target_range_seconds=9.0,
        max_range_seconds=12.0,
        max_candidates_per_range=8,
        min_range_seconds=5.0,
        auto_expand=False,
    )
    assert len(capped_points) + 1 == 8
    assert capped_warnings


def main() -> int:
    dense_candidates = [round(index * 1.3, 3) for index in range(1, 47)]
    assert_plan(60.7, dense_candidates)
    assert_plan(60.7, [])
    assert_auto_expansion()
    print("adaptive range planner: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

from bai_compact_timeline import normalize_clipped_timestamps


MAPPING = {
    "logical_start_seconds": 17.533,
    "logical_end_seconds": 39.967,
    "clip_start_seconds": 15.033,
    "clip_end_seconds": 42.467,
    "absolute_offset_seconds": 15.033,
    "core_start_clip_seconds": 2.5,
    "core_end_clip_seconds": 24.934,
}


def main() -> int:
    local = {
        "records": [
            {"start_seconds": 2.5, "end_seconds": 10.0, "anchor_evidence_timestamps": [2.6, 6.0, 9.9]},
            {"start_seconds": 10.0, "end_seconds": 24.934, "anchor_evidence_timestamps": [10.1, 17.0, 24.8]},
        ],
        "boundary_audit": [{"candidate_seconds": 8.0, "observed_seconds": 8.0}],
    }
    assert normalize_clipped_timestamps(local, MAPPING) == "local_shifted"
    assert local["records"][0]["start_seconds"] == 17.533
    assert local["records"][-1]["end_seconds"] == 39.967
    assert local["boundary_audit"][0]["candidate_seconds"] == 23.033

    absolute = {
        "records": [
            {"start_seconds": 17.533, "end_seconds": 30.0},
            {"start_seconds": 30.0, "end_seconds": 39.967},
        ],
        "boundary_audit": [],
    }
    assert normalize_clipped_timestamps(absolute, MAPPING) == "model_absolute"
    assert absolute["records"][0]["start_seconds"] == 17.533

    invalid = {"records": [{"start_seconds": 0.0, "end_seconds": 5.0}], "boundary_audit": []}
    try:
        normalize_clipped_timestamps(invalid, MAPPING)
    except RuntimeError:
        pass
    else:
        raise AssertionError("invalid mixed coverage must fail")
    print("clipped transport timestamp contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

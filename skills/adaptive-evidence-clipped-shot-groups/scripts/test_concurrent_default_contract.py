#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
STABLE_MODE = HERE.parent / "references" / "stable-relay-mode.md"
SEAM_SCRIPT = HERE / "bai_audit_range_seam.py"
CLIP_SCRIPT = HERE / "clip_analysis_ranges.py"
LEASE_SCRIPT = HERE / "relay_slot_leases.py"
LEASE_RUNNER = HERE / "run_with_relay_lease.py"
BATCH_RUNNER = HERE / "run_multi_episode_pipeline.py"
EXPAND_SCRIPT = HERE / "expand_compact_timeline.py"
VALIDATE_SCRIPT = HERE / "validate_expanded_shot_groups.py"
WORKBOOK_SCRIPT = HERE / "build_shot_group_workbook.mjs"
MERGE_SCRIPT = HERE / "merge_compact_ranges.py"


def main() -> int:
    skill_text = SKILL.read_text(encoding="utf-8-sig")
    stable_text = STABLE_MODE.read_text(encoding="utf-8-sig")
    seam_text = SEAM_SCRIPT.read_text(encoding="utf-8-sig")
    clip_text = CLIP_SCRIPT.read_text(encoding="utf-8-sig")
    lease_text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")
    lease_runner_text = LEASE_RUNNER.read_text(encoding="utf-8-sig")
    batch_runner_text = BATCH_RUNNER.read_text(encoding="utf-8-sig")
    expand_text = EXPAND_SCRIPT.read_text(encoding="utf-8-sig")
    validate_text = VALIDATE_SCRIPT.read_text(encoding="utf-8-sig")
    workbook_text = WORKBOOK_SCRIPT.read_text(encoding="utf-8-sig")
    merge_text = MERGE_SCRIPT.read_text(encoding="utf-8-sig")
    ast.parse(seam_text)
    assert "resumable two-level pipeline" in skill_text
    assert "per_key_concurrency" in skill_text
    assert "shared SQLite lease database" in skill_text
    assert "three episode workers" in skill_text
    assert "calls concurrently" in skill_text
    assert "Full-episode primary analysis is concurrent by default" in stable_text
    assert "two lanes per healthy key" in stable_text
    assert "--workers" in clip_text and "--ffmpeg-threads" in clip_text
    assert "ThreadPoolExecutor" in clip_text and "cache_status" in clip_text
    assert "BEGIN IMMEDIATE" in lease_text and "UNIQUE(key_fingerprint, lane)" in lease_text
    assert "{key_offset}" in lease_runner_text
    assert "episode_workers" in batch_runner_text and "range_workers" in batch_runner_text
    assert '"--continuity-injection", type=Path, required=True' in seam_text
    assert 'continuity.get("target_range_id")' in seam_text
    assert 'continuity.get("source_end_seconds"' in seam_text
    assert 'current["boundary_audit"]' not in seam_text
    assert 'current.setdefault("transport", {})["start_seam_audit"] = audit' in seam_text
    assert "default five-phase execution contract is mandatory" in skill_text
    assert "attach_group_continuity_handoffs" in expand_text
    assert "validate_group_continuity_handoffs" in validate_text
    assert "上一组尾态→本组首态" in workbook_text
    assert "inherit_state" in workbook_text and "new_scene" in workbook_text and "verify" in workbook_text
    assert "transport_continuity_contract" in merge_text
    assert "lacks a valid second-wave continuity decision" in merge_text
    print("concurrent default contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

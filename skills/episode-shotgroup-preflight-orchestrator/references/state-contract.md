# State contract

The orchestrator is state-first. Every episode has an independent folder:

```text
资产输出/06_镜头组预处理调度/
  EP01/
    episode_state.json
    prepare_manifest.json
    dependency_check.json
    lightweight_qa.json
  batch_state.json
```

## Episode statuses

- `pending`: discovered but not prepared.
- `prepared`: deterministic local preparation completed.
- `waiting_assets`: asset workbook is missing.
- `waiting_dialogue`: episode dialogue ledger is missing.
- `ready_for_semantic`: prepared and dependencies present.
- `semantic_running`: handed to the semantic parser.
- `semantic_complete`: parser output exists.
- `qa_failed`: lightweight QA blocks merge.
- `exported`: episode is allowed into whole-drama output.
- `skipped`: user explicitly skipped this episode.
- `failed`: deterministic preparation or validation failed.

When more than one dependency is missing, set `status=waiting_assets` if the asset workbook is missing and list every missing item in `waiting_for`.

## Prepare manifest

```json
{
  "episode": "EP01",
  "source_video": "D:\\project\\001.mp4",
  "source_fingerprint": "sha256...",
  "duration_seconds": 59.3,
  "mode": "prepare-only",
  "prepared_steps": ["fingerprint", "probe", "boundary_detection", "adaptive_range_plan", "clip_materialization"],
  "bai_called": false,
  "tos_uploaded": false,
  "ready_for_bai": false,
  "adaptive_local_prepare": {
    "status": "prepared",
    "work_dir": ".../adaptive_local_prepare",
    "probe_json": ".../probe.json",
    "boundaries_json": ".../boundaries.json",
    "ranges_json": ".../ranges.json",
    "clip_manifest": ".../clip_manifest.json",
    "clip_count": 7
  }
}
```

When `adaptive_local_prepare.probe_json` exists, the canonical source duration is `probe_json.videos[0].duration_seconds`. A semantic dispatch check must reject manifests that use a missing/root-level duration or contain prepared ranges whose end time exceeds the canonical duration by more than 0.01 seconds.

`bai_called` must stay `false` unless the mode is `semantic-from-prepare` and the external parser is actually dispatched. Simulation must always keep it `false`.

## Dependency check

```json
{
  "episode": "EP01",
  "asset_table": {"path": "...xlsx", "exists": true},
  "dialogue_ledger": {"path": "...json", "exists": true},
  "waiting_for": [],
  "ready_for_semantic": true
}
```

## Batch state

The batch state lists every discovered episode and must include skipped episodes. A whole-drama merge may only include `exported` or explicitly completed episodes and must exclude `skipped`.

## Semantic dispatch plan

`semantic_dispatch_plan.json` is a dry-run handoff contract unless `--execute-semantic` is explicitly supplied with `--authorize-external` and `--adaptive-command-manifest`, or `--direct-run` is supplied with `--adaptive-command-manifest`. It records ready episodes and every blocker. In dry-run mode, the orchestrator keeps `bai_called=false` and `tos_uploaded=false`.

When execution is requested, the adaptive command manifest must use `schema_version=1.0-adaptive-batch-command-manifest`, contain only dispatch-ready episodes, and be executed by the existing `adaptive-evidence-clipped-shot-groups/scripts/run_multi_episode_pipeline.py` runner. The orchestrator validates and launches this manifest; it does not rewrite the adaptive parser's commands, prompts, schemas, or range semantics.

`--direct-run` represents an explicit user instruction such as “直接实跑”. It enables external authorization and semantic execution, but it does not waive validation. If no adaptive command manifest is supplied, the orchestrator may build one only from current-project prepared artifacts and only when the required TOS/key inputs are present.

When `--compare-project` is supplied, every planned episode may include:

```json
{
  "comparison": {
    "compare_project": "D:\\reference",
    "video_fingerprint_match": true,
    "reference_ranges_exists": true,
    "ranges_match": true,
    "current_range_count": 7,
    "reference_range_count": 7
  }
}
```

Any fingerprint mismatch or existing reference-range mismatch blocks dispatch.

When execution starts, `batch_state.json` may include:

```json
{
  "adaptive_runner_invoked": true,
  "auto_adaptive_command_manifest": {
    "path": ".../adaptive_command_manifest_auto_YYYYMMDD_HHMMSS.json"
  },
  "adaptive_runner": {
    "ok": true,
    "status": ".../adaptive_runner_status.json",
    "logs_dir": ".../adaptive_runner_logs",
    "work_dir": ".../adaptive_runner_workspaces"
  }
}
```

If the adaptive command manifest contains relay stages, `bai_called` and `tos_uploaded` may be marked true after the runner is invoked. A failed runner clears `ready_episodes` and moves those episodes to `blocked_episodes`.

If primary compact outputs exist but local validation/finalization fails, the orchestrator must prefer `scripts/finalize_adaptive_outputs.py` before rerunning the whole adaptive manifest. The finalizer may include:

```json
{
  "adaptive_finalize": {
    "ok": true,
    "report": ".../orchestrator_finalize_report.json"
  },
  "final_outputs": {
    "json": ".../全剧_英国本地化镜头组.json",
    "workbook": ".../全剧_英国本地化镜头组_12列.xlsx",
    "report": ".../orchestrator_finalize_report.json"
  }
}
```

The local finalizer is allowed to repair only structural contract problems that do not invent narrative facts or retime intervals: boundary audit before/after subjects, safe subject-lighting wording, static asset-owned wording in generation facts, screen-direction wording, valid depth-layer values, missing `relative_blocking` placeholders marked `unclear`, interval IDs that can be mapped back to locked intervals, deep focus when multiple sharp depth layers are present, and burned-subtitle utterance records that are already visible in the compact output. It must then merge compact ranges and build expansion config by contiguous `narrative_group`, not one final shot group per compact record.

## Evidence-pack precondition

If an episode preflight folder contains canary or prebuilt semantic evidence packages, validate them before semantic handoff. The adaptive parser resolves relative page filenames against the directory containing `evidence_pack_manifest.json`; therefore the manifest must live in the same directory as `page_01_range_edges.jpg`, `page_02_event_keyframes.jpg`, `page_03_motion_triplets.jpg`, `page_04_shot_space.jpg`, and `page_05_person_trajectory.jpg`.

Block dispatch when:

- a manifest references a missing page;
- a referenced page checksum differs from `relay_pages[].sha256`;
- required roles are missing: `range_boundaries`, `action_events`, `high_motion_triplets`, `shot_space`, `person_trajectory`;
- `pose_gate.pose_enabled=true` but `multi_person_geometry` is absent, or vice versa.

This catches wrapper mistakes before any TOS/中转站 call.

## Lightweight QA result

When a semantic output exists, `lightweight_qa.json` may include the latest final JSON and Excel QA report:

```json
{
  "episode": "EP01",
  "status": "passed",
  "duration_seconds": 59.3,
  "final_group_json": ".../shot_groups.expanded.json",
  "final_group_count": 14,
  "excel_qa": {
    "path": ".../EP01_英国本地化镜头组_12列.qa.json",
    "exists": true,
    "rows": 14,
    "errors": [],
    "warnings": [],
    "continuity_boundaries": 13
  },
  "errors": [],
  "warnings": []
}
```

Block on hard Excel QA errors, JSON/Excel row-count mismatch, continuity boundary count not equal to `N-1`, skipped episodes with outputs, or abnormal group counts.

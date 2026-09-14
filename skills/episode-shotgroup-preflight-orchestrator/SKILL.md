---
name: episode-shotgroup-preflight-orchestrator
description: "Orchestrate per-episode shot-group preflight for short-drama projects: prepare local video metadata/range manifests while waiting for current-project asset and dialogue outputs, then hand ready episodes to the existing adaptive evidence shot-group parser without changing that parser. Use when Codex needs to 边预处理边等资产台词, prepare shot-group work without 中转站, resume per episode, skip selected episodes, or guard against abnormal final shot-group counts before whole-drama merge."
---

# Episode Shot-Group Preflight Orchestrator

Use this skill as a project-level scheduler in front of `adaptive-evidence-clipped-shot-groups`. It must not replace, fork, or weaken the existing shot-group parser. Its job is to prepare local deterministic inputs early, wait for the current project's required asset/dialogue files, and only then dispatch the mature semantic parser.

## Hard boundaries

- Do not call 中转站, relay models, or seam-audit model scripts during `prepare-only` or simulation.
- Do not upload to TOS unless the user explicitly asks for transport prewarming or the active project workflow already authorizes it.
- Do not copy assets, dialogue ledgers, shot groups, or caches from another project.
- Do not merge an episode into a whole-drama shot table when its lightweight QA fails.
- Keep skipped episodes as explicit state records; never silently parse or merge them.

## Modes

Read [references/state-contract.md](references/state-contract.md) before changing state files or interpreting a run manifest.

- `prepare-only`: scan episodes, fingerprint/probe videos, create deterministic episode folders, write range/preparation manifests, and check dependencies. With `--adaptive-local-prepare`, it may reuse the existing adaptive parser's local-only scripts for probe, boundary detection, adaptive range planning, and clip materialization. No 中转站 and no TOS.
- `prepare-transport`: all `prepare-only` work plus authorized TOS URL prewarming. Still no 中转站.
- `semantic-from-prepare`: verify prepared fingerprints and current-project dependencies, then write a safe dispatch plan for ready episodes. By default this remains a dry-run handoff. With explicit `--authorize-external --execute-semantic`, call the existing `adaptive-evidence-clipped-shot-groups` batch runner. If `--adaptive-command-manifest` is not supplied, the orchestrator may build a current-project manifest from prepared ranges/clips when `--tos-env` is supplied.
- `direct-run`: when the user explicitly says `直接实跑`, `实跑`, `生产跑`, or otherwise clearly authorizes immediate execution for the current project, do not stop after a successful dry-run. Run the same semantic guards, auto-build the adaptive command manifest from current-project prepared artifacts when needed, invoke the existing adaptive runner, then run the local finalizer. If blockers or required transport/key inputs are missing, stop and report the blocker.
- `lightweight-qa`: validate existing expanded JSON/Excel outputs before allowing whole-drama merge.
- `simulate`: exercise the scheduler and dependency logic with fake or existing local files; must not call external services.

## Required project inputs

The user or current context must identify a project root. Within that root, prefer these project-local defaults:

- source videos: `<project_root>/*.mp4|*.mov|*.mkv`
- British asset workbook: `资产输出/02_英国本地化资产/全剧_英国本地化资产表.xlsx`
- dialogue ledgers: `资产输出/04_完整台词台账/EPxx/dialogue_ledger.json`
- preflight output: `资产输出/06_镜头组预处理调度/`
- final shot outputs: produced by `adaptive-evidence-clipped-shot-groups`, usually under `资产输出/05_自适应证据镜头组/`

## Workflow

1. Resolve the current project root and episode list. Record absolute paths and source fingerprints.
2. Apply explicit skip rules first. A skipped episode gets `status=skipped` and is never sent downstream.
3. For unskipped episodes, run or simulate deterministic preparation and write `episode_state.json` plus `prepare_manifest.json`. Prefer `--adaptive-local-prepare` when testing readiness against real videos, because it uses the same local range/clip preparation shape as the downstream adaptive parser.
   - When reading adaptive `probe.json`, use `videos[0].duration_seconds` as the canonical source duration. Do not read a root-level `duration_seconds`; current adaptive probe manifests store duration per video item.
   - Block semantic handoff if any prepared range end exceeds the canonical probe duration by more than 0.01 seconds.
4. Check dependencies per episode:
   - asset workbook exists and belongs to the current project;
   - dialogue ledger exists for the episode;
   - optional key/TOS prerequisites exist only when the requested mode needs them.
5. If dependencies are missing, set `waiting_assets`, `waiting_dialogue`, or both. Continue other ready episodes instead of blocking the whole batch.
6. In `semantic-from-prepare`, inspect existing prepare manifests, verify source/clip fingerprints, and write `semantic_dispatch_plan.json`. Dispatch only episodes with `ready_for_semantic=true`. Use the existing adaptive parser; do not rebuild its prompts or schemas in this skill.
   - If semantic canary or prebuilt evidence-pack artifacts exist under the episode preflight folder, validate every `evidence_pack_manifest.json` before handoff: each `relay_pages[].file` must resolve relative to the manifest's own directory, all checksums must match when provided, required roles must include `range_boundaries`, `action_events`, `high_motion_triplets`, `shot_space`, and `person_trajectory`, and `pose_gate.pose_enabled` must agree with the presence of `multi_person_geometry`.
   - When creating a canary evidence pack, write `evidence_pack_manifest.json` inside the same directory as its copied relay pages, e.g. `semantic_canary_part05/evidence_pack/evidence_pack_manifest.json`, not beside that directory.
   - For production execution, prefer a supplied `adaptive-evidence-clipped-shot-groups` command manifest when present. If none is supplied and the user has authorized production execution, generate one with `scripts/build_adaptive_command_manifest.py` from current-project prepared ranges/clips, the current-project asset workbook, episode dialogue ledgers, key pool, and explicit `--tos-env`. The generated manifest must use the original full episode video for local evidence, the prepared overlap clip only for TOS/中转站 primary parsing, and sequential stages for dependent finalize work.
   - If the user's request explicitly says to run directly and the active project has a valid command manifest, execute immediately after the guards pass. Do not require a second confirmation just to move from handoff to execution.
7. After primary compact outputs exist, run `scripts/finalize_adaptive_outputs.py`. This finalizer validates compact outputs, applies local contract-only fixes when the strict validator rejects otherwise usable primary results, merges compact ranges, builds expansion config by contiguous `narrative_group`, expands to formal shot groups, validates, exports per-episode Excel, and writes whole-drama JSON/XLSX. It must not rerun 中转站 when only local contract/finalization failed.
8. After semantic outputs exist, run lightweight QA. If QA fails, set `qa_failed` and stop before merge.
9. When validating a copied project or regression test, pass `--compare-project <reference_project>` to compare source-video fingerprints and prepared adaptive ranges against a known reference. Treat mismatch as a dispatch blocker.

## Lightweight QA guardrails

For 45-75 second short-drama episodes, use these defaults unless a project config overrides them:

- 8-18 final groups: normal
- 19-22 final groups: warning
- more than 22 final groups: block merge
- more than 28 final groups: classify as likely compact-record export leakage

Also block when continuity handoffs are not `N-1`, when hard Excel QA errors exist, when the output includes skipped episodes, or when final rows cannot be tied back to the current project.

The helper chooses the newest episode `shot_groups.expanded.json` by modification time, reads the nearest/latest `.qa.json` report when present, and compares JSON row count, Excel QA row count, hard errors, and continuity boundary count. A missing final output is allowed during preflight because the episode may not have reached semantic parsing yet.

## Helper script

Use `scripts/preflight_orchestrator.py` for deterministic state creation, dependency checks, simulation, adaptive local preflight, lightweight QA summaries, guarded handoff execution, automatic command-manifest creation, and local finalization. It sends 中转站/TOS work only when `--execute-semantic` is combined with explicit external authorization/direct-run and either a valid adaptive command manifest or enough current-project inputs to generate one.

Example local-only readiness test:

```powershell
python scripts/preflight_orchestrator.py --project-root <project> --mode prepare-only --adaptive-local-prepare --lightweight-qa
```

Example semantic dispatch dry-run:

```powershell
python scripts/preflight_orchestrator.py --project-root <project> --mode semantic-from-prepare --lightweight-qa
```

Example guarded production execution:

```powershell
python scripts/preflight_orchestrator.py --project-root <project> --mode semantic-from-prepare --lightweight-qa --authorize-external --execute-semantic --tos-env <tos_env_file>
```

Equivalent direct-run shorthand after preparation:

```powershell
python scripts/preflight_orchestrator.py --project-root <project> --mode semantic-from-prepare --lightweight-qa --direct-run --tos-env <tos_env_file>
```

If a manifest was already hand-built and validated, it can still be supplied:

```powershell
python scripts/preflight_orchestrator.py --project-root <project> --mode semantic-from-prepare --lightweight-qa --direct-run --adaptive-command-manifest <adaptive_batch_manifest.json>
```

Example regression comparison against a reference project:

```powershell
python scripts/preflight_orchestrator.py --project-root <copy_project> --mode semantic-from-prepare --compare-project <reference_project> --lightweight-qa
```

The dry-run writes both `semantic_dispatch_plan.json` and `handoff_to_adaptive_parser.md/json`. These are handoff artifacts, not permission to call external services. Production execution additionally writes `adaptive_runner_status.json`, `adaptive_runner_logs/`, and `adaptive_runner_workspaces/` under the preflight output root.

# Resumable multi-episode execution

Use this reference for folders containing multiple episodes or whenever one relay key may serve more than one simultaneous request.

## Resource pools

Keep four independent limits:

- `episode_workers`: active episode state machines; default 3.
- `local_workers`: local FFmpeg/evidence producers; default 2. Use one worker for heavy pose or trajectory inference.
- `range_workers`: concurrent commands inside one episode relay stage; default 8.
- Relay slots: `healthy_keys * per_key_concurrency`, capped by `global_limit`; default two lanes per key and global limit 30 for 15 keys.

Never multiply local FFmpeg workers by relay slots. On a 12-thread, 16 GB workstation use two FFmpeg workers with three FFmpeg threads each.

## Batch manifest

Create a UTF-8 JSON manifest with `schema_version=1.0-adaptive-batch-command-manifest`. Each episode contains ordered stages; stages execute sequentially inside the episode, while commands inside one stage execute concurrently. Mark clip/evidence stages `kind=local`; mark primary and seam stages `kind=relay`.

```json
{
  "schema_version": "1.0-adaptive-batch-command-manifest",
  "episodes": [
    {
      "episode": "01",
      "stages": [
        {"name": "prepare", "kind": "local", "commands": []},
        {"name": "primary", "kind": "relay", "commands": []},
        {"name": "seam", "kind": "relay", "commands": []},
        {"name": "finalize", "kind": "local", "workers": 1, "commands": []}
      ]
    }
  ]
}
```

Every command has a stable `id`, an argument-vector `argv`, and optional `cwd` and non-secret `environment`. Do not place keys in the manifest. Run with:

```text
python scripts/run_multi_episode_pipeline.py --manifest batch.json --status batch-status.json --logs-dir logs --episode-workers 3 --range-workers 8 --local-workers 2 --resume
```

Pass `--work-dir <current-run>/workspaces` when the run root is not the status file's parent. The default is `<status-parent>/workspaces`. The runner creates one stable workspace per command at `<work-dir>/<episode>/<stage>/<command-id>/`, with `inputs`, `evidence`, `request`, `response`, `normalized`, `audit`, `retry`, and `logs` subdirectories. It sets `ADAPTIVE_RANGE_WORKDIR`, `ADAPTIVE_EPISODE_ID`, `ADAPTIVE_STAGE_ID`, and `ADAPTIVE_RANGE_ID` for the child. Omit `cwd` in new manifests so the child runs inside its isolated workspace; retain `cwd` only to resume a legacy command that depends on a different process directory. Use absolute paths in `argv`.

The status file is atomic and resumes only commands whose argument-vector fingerprint and workspace contract fingerprint are unchanged. Do not scan sibling workspaces for missing artifacts and do not share a workspace between source-video or derived-dialogue fingerprints. Put those fingerprints in the command's non-secret environment or argument vector so a change invalidates resume.

## Relay lease wrapper

Preflight once per key-pool fingerprint. The default five-minute cache avoids repeated probes but is invalidated by a changed pool, model, or endpoint. Wrap each primary or seam command:

```text
python scripts/run_with_relay_lease.py --preflight key-preflight.json --per-key-concurrency 2 --global-limit 30 --owner EP01-part01 --phase primary -- python scripts/bai_compact_timeline.py ... --key-offset {key_offset} --single-key-only
```

The wrapper acquires one fingerprinted lane from the shared SQLite database, renews its lease while the child runs, releases it afterward, and retries once on another key when the command fails. It never prints or stores key contents. Expired leases are reclaimed after abnormal exits.

## Backpressure and correctness

- Allow an episode to enter its relay stage immediately after that episode's local preparation completes; do not wait for every other episode to finish local preparation. Range-level streaming inside one episode remains opt-in because the shared clip manifest must stay atomic.
- Start an episode's seam stage only after all its own primary ranges validate.
- Reuse clips only when source, range, encoder contract, duration, and output SHA-256 match cache metadata.
- Reuse uploaded objects by clip SHA-256. Do not upload again for retry or seam audit.
- Preserve exact half-open absolute times and do not default to stream-copy cuts unless keyframe alignment is separately proven.
- Reduce `per_key_concurrency` to 1 after repeated 429/timeouts; restore 2 only after a stable canary. Do not silently exceed `global_limit`.

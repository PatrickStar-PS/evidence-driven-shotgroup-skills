# Overlap-clipped transport contract

## Range model

Keep two intervals for every job:

- Logical core: the only interval allowed to produce records.
- Physical clip: logical core plus 1.5 seconds of pre-roll and post-roll by default.

Plan logical cores from both duration and whole-episode boundary density. Target 8-10 seconds, keep a 12-second hard planning target, allow at most about eight candidate cuts per core, and use eight ranges as the ordinary default soft limit. If eight ranges cannot satisfy the duration or boundary-density targets, automatically expand to the minimum additional range count needed. Record whether expansion occurred, the final range count, and any remaining pressure warning. Prefer high-confidence candidates near the target time, but remember that a transport seam is not a final visual cut.

Keep `start_seconds` and `end_seconds` as the logical absolute interval for compatibility. Add:

- `clip_start_seconds`
- `clip_end_seconds`
- `absolute_offset_seconds`
- `core_start_clip_seconds`
- `core_end_clip_seconds`
- `context_before_seconds`
- `context_after_seconds`
- `seam_owner`

Use half-open logical intervals. Adjacent logical ranges must cover the original duration continuously without gaps or overlaps. Physical clips may overlap.

## Clip production

Re-encode each physical clip for frame-accurate starts. Preserve aspect ratio, rotation interpretation, video, and optional audio. Validate actual duration against the planned physical duration within 0.15 seconds. Record source SHA-256, clip SHA-256, byte size, stream presence, and exact absolute mapping.

For controlled tests, materialize exactly one named range with `--range-id`. Do not generate the remaining clips merely to prove that the plan contains them. Materialize all ranges only for an explicitly requested full production run.

## Model contract

Tell the relay that clip-local `0.000` maps to `clip_start_seconds`. Provide the logical absolute core and its clip-local equivalent. Permit pre/post-roll only as context. Require records to cover the logical core, not the physical clip.

Prefer original absolute timestamps. If the returned first/last record instead matches the clip-local core within 0.20 seconds, shift all record, anchor, and boundary-audit times by `absolute_offset_seconds` before dialogue hydration. Reject mixed or ambiguous coverage.

## Seam ownership

The right-hand range owns its logical start seam because its pre-roll and core show both sides. It must place one audit item at that absolute time:

- `keep_cut`
- `keep_reframe`
- `merge_false`

Do not create a seam audit locally. A missing seam audit invalidates the merged timeline. `merge_false` still requires same-shot evidence and compatible before/after subjects.

For full-episode runs, primary range analysis is concurrent by default and therefore does not wait for same-run preceding outputs. After the primary wave is normalized, build every right-hand continuity injection from the immediately preceding selected range and run all internal seam audits concurrently in a second wave. Pass the matching file through `bai_audit_range_seam.py --continuity-injection`. The seam wave may update only the model-authored transport audit. Sequential primary analysis is not the default and requires an explicit user request.

The left-side continuity injection is text-only. Include scene/daylight state, action and contact handoff, principal character pose/orientation/gaze/contact state, end screen order, and transient prop state. Set its initial decision to `verify_from_video`; do not infer the right side and do not attach a tail-frame image. The overlap seam audit must compare the injected state with right-side pixels and append `seam_type`, `continuity_mode`, `scene_match`, `action_continues`, and `character_state_continues` under the transport seam audit. These fields are transport audit metadata and must not rewrite model-authored shot semantics. After the final shot groups are fixed, a separate deterministic writer must consume these audits plus final-group states and attach exactly one `continuity_handoff` to each right-hand target group. This writeback is a derived generation constraint, not a semantic rewrite.

## Dialogue continuity

Build dialogue from the validated whole-episode ledger. Inject every event intersecting the logical core plus context events. Preserve absolute event times and IDs. Hydrate dialogue only after visual record times have been normalized to absolute time. Deduplicate root dialogue events by ID during merge; visual records may reference the same ID on both sides of a real visual cut.

After narrative shot groups are fixed, assemble dialogue locally from root events rather than collecting full event text independently inside each group. When one event materially crosses a group boundary, split source and localized text once into ordered `dialogue_segment_id` values using overlap duration with punctuation preference. Assign every segment to exactly one group and preserve the parent `dialogue_id`. Ignore only seam overlaps at or below 0.15 seconds, assign the complete line to the material side, and record the snapped duration. Never duplicate the full event in both groups.

## Evidence

Generate OpenCV boundaries and context/spatial pages from the original episode. Label evidence with original absolute timestamps. Use the clip only as relay video transport. Do not regenerate boundary candidates independently per clip.

## Validation

Require:

- source and clip fingerprints;
- clip duration and stream checks;
- complete logical-core coverage per range;
- absolute full-episode coverage after merge;
- one semantic audit per internal candidate and transport seam;
- stable dialogue projection and no invented dialogue IDs;
- no transport seam forced to a cut;
- resumable per-range outputs.

Also validate planner-level pressure: record logical duration and estimated candidate count per range. Automatically expand beyond the default eight-range limit when needed. If the feasible capacity imposed by minimum range length still prevents the targets from being met, emit a warning instead of silently claiming the plan is bounded.

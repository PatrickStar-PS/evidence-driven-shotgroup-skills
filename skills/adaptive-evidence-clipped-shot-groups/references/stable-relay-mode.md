# 稳定中转模式

Use this mode when the authorized backend is the 中转站 OpenAI-compatible relay.

## Transport boundary

- Preserve the complete original episode, but send bounded overlap clips to the relay by default.
- Require explicit user authorization before uploading to TOS or another object store.
- When TOS is authorized, create accurate overlap clips locally, upload each clip once, reuse object metadata by clip fingerprint, generate a short-lived signed GET URL, and give only the assigned clip URL to 中转站 in pass 1. Pass 2 is text-only.
- Treat signed URLs as temporary access credentials: do not print them in commentary or final responses, and do not save them in permanent manifests.
- When TOS is not authorized, normalize a large source to H.264/AAC MP4, 480x854 or equivalent orientation, 24 fps, with a target file size of 6 MB. Preserve duration, audio, subtitle legibility, and aspect ratio, then inline it once in pass 1.
- Record the source fingerprint, TOS bucket/host/object key or normalized-video fingerprint, byte size, relay endpoint label, model label, attempt count, and output paths. Never record keys or a permanent signed URL.

## Pass 1: compact evidence timeline

Ask the relay to watch one bounded physical clip and return JSON only for its logical core. Do not ask it to localize, write production prose, repeat constraints, or emit the final 12-column structure.

Before pass 1, automatically plan output ranges from both duration and boundary density, using eight as the default soft limit. Target 8-10 second logical cores, a 12-second hard planning target, and no more than about eight internal candidates per range; if those targets cannot be met in eight ranges, automatically expand to the minimum additional count and record the expansion. Choose nearby high-confidence visual boundaries while keeping cores at least 5 seconds when possible. Give each physical clip 1.5 seconds of pre/post-roll by default. Generate adaptive chronological evidence with 2 fps base coverage, 5 fps local motion scanning, forced start/middle/end interval anchors, and forced boundary-before/boundary-after frames. Generate spatial evidence separately, then attach only the manifest's ordered `relay_pages`. The current adaptive pack contains five required pages—range edges, action events, high-motion triplets, shot space, and one consolidated anonymous person-trajectory page—and one optional multi-person pose page. Preserve all interval labels and evidence; never solve attachment pressure by dropping range edges, shot space, or the trajectory page. Every request outputs only its logical absolute core without resetting timestamps to zero. Full-episode primary analysis is concurrent by default: preflight the key pool, expose a configured number of reusable lanes per healthy key, and acquire every lane through the shared cross-window lease database. Default to two lanes per healthy key and a global limit of 30 for a 15-key pool. Run up to three episode state machines concurrently, up to eight relay commands inside each active episode, and no more than two local media producers on a 12-thread/16-GB workstation. As soon as one episode's primary ranges are normalized, build that episode's right-hand continuity injections and audit its internal seams concurrently with `bai_audit_range_seam.py --continuity-injection`; other episodes may remain in primary analysis. Only a materially contradictory seam may trigger one targeted continuity-aware full-range rerun under a newly acquired lease. Do not serialize all episodes merely to make same-run continuity available. Merge an episode locally only after every one of its right-hand ranges has a valid overlap seam audit; no transport seam may be forced to a cut. After final shot-group expansion, deterministically materialize exactly one `continuity_handoff` on every right-hand target group and validate all `N-1` final-group boundaries before export.

Required shape:

```json
{
  "schema_version": "1.0",
  "prompt_contract_version": "1.1-visible-speaker",
  "episode": "01",
  "duration_seconds": 59.3,
  "boundary_audit": [
    {"candidate_seconds": 0.433, "decision": "keep_cut", "observed_seconds": 0.433, "before_visible_subject": "woman holding a wine glass", "after_visible_subject": "man in a grey suit", "same_shot_evidence": false, "reason": "hard cut to reverse angle"}
  ],
  "records": [
    {
      "id": "E001",
      "narrative_group": 1,
      "beat_summary": "complete dramatic action or reveal",
      "start_seconds": 0.0,
      "end_seconds": 2.4,
      "boundary": "cut|reframe|continuous",
      "transition": "cut, reverse, whip, insert, dissolve, or subject entrance/exit",
      "scene_observation": "specific factual setting and dressing",
      "primary_visible_subject": "main visible person or object in this interval",
      "focus_subject": "actual sharp focal subject",
      "focus_policy": "locked|rack_focus|unclear",
      "visible_characters": [{"identity": "source identity or stable appearance label", "appearance": "visible clothing and appearance", "screen_position": "screen position", "mouth_state": "speaking|not_speaking|unclear", "body_posture": "standing|sitting|walking|kneeling|crouching|lying|leaning|unclear", "body_orientation": "front/back/left/right and facing whom", "support_contact": "ground/chair/table/person contact", "visibility_scope": "full/half/bust/partial/background blur", "depth_layer": "foreground|midground|background", "relative_camera_distance": "closer_than_focus|same_plane|farther_than_focus|unclear", "frame_occupancy": "dominant|large|medium|small|tiny", "frame_crop": "exact body and frame-edge crop", "occlusion_relation": "who occludes whom or none", "depth_evidence": "physical size/perspective/crop/occlusion evidence only", "focus_state": "sharp|slightly_soft|heavily_defocused|unclear", "focus_evidence": "optical eye/edge/hair/clothing detail or blur evidence only", "gaze_direction": "actual gaze target or unclear", "facial_expression": "this person's visible expression or unclear", "character_action": "this person's action chain or explicit inactive state"}],
      "relative_blocking": [{"subject": "visible identity A", "relative_to": "visible identity B", "horizontal_relation": "left_of|right_of|overlapping|unclear", "depth_relation": "in_front_of|behind|same_plane|unclear", "occlusion": "blocks|blocked_by|none|unclear", "evidence": "size/crop/perspective/occlusion evidence only"}],
      "edge_character_audit": {"status": "present|none|uncertain", "observations": [{"edge": "left|right|top|bottom", "identity": "identity or stable appearance label", "visible_fragment": "visible face/shoulder/clothing/body fragment", "screen_position": "exact edge position"}]},
      "visual_details": "specific colours, materials, objects, foreground/background and positions",
      "lighting_composition": "light colour, depth, occlusion, reflection and composition",
      "visible_action": "ordered visible action chain",
      "shot_size": "wide|full|medium|close-up|extreme-close-up|unknown",
      "camera_angle": "eye-level|high-angle|low-angle|overhead|unknown",
      "camera_motion": "static|pan|tilt|push-in|pull-out|tracking|handheld|unknown",
      "camera_view": "1 俯瞰/俯视|2 正视|3 侧视|4 反打|待确认",
      "spatial_positions": "short factual positions and body orientation",
      "contact_actions": "exact person-person or person-object contact",
      "initial_frame": "short visible state at interval start",
      "final_frame": "short visible state at interval end",
      "expression_gaze": "short factual expression and gaze change",
      "mouth_dynamics": "visible speaking or mouth movement",
      "speaker": "source identity or unknown",
      "dialogue_utterances": [{"start_seconds": 0.2, "end_seconds": 0.7, "speaker": "source identity", "speaker_visibility": "on_screen|off_screen|unclear", "text": "one exact Chinese utterance", "basis": "audio|burned_subtitle|both"}],
      "chinese_dialogue": "audible or burned-in Chinese line",
      "on_screen_text": "readable text or empty",
      "sound": "meaningful sound or empty",
      "asset_hints": ["source names only"],
      "confidence": "high|medium|low",
      "warnings": []
    }
  ],
  "warnings": [],
  "errors": []
}
```

Keep records continuous from 0 to the locally probed duration within 0.10 seconds. Preserve every hard cut, reverse, insert, or dominant reframing; a one-minute drama will often need 25-45 evidence records. Keep every visual field concise but evidence-bearing; do not omit colours, materials, foreground/background objects, camera, blocking, transitions, or ordered contact actions merely to reduce output length. Empty uncertain fields instead of emitting `unknown` prose. The relay may identify likely source characters, but asset authority remains the supplied workbook.

For exact character-state matches, write `appearance=asset_bound`; keep appearance prose only for suspected or unmatched people. Asset matching must never remove a visible human. Inventory people before binding assets; retain unmatched, tiny, blurred, edge, background, and middle-only people as `背景路人A/B/C`, and never use a scene or object as a `visible_characters.identity`. Keep `scene_observation`, `fixed_scene_evidence`, and `visual_details` as internal recognition evidence. Add `transient_visual_details` for temporary plot objects or states that are not already owned by a bound character-state or scene asset. Under prompt contract `3.3-background-people-static-light-filter`, final composition may read only `generation_facts`: subject-lighting condition, contrast/exposure, depth of field, focus transition, composition change, and dynamic environment. Never place bound wardrobe details, fixed scene dressing, fixed lamps, chandeliers, light strips, neon, or static coloured ambience in `generation_facts`. Retain light only when it changes narratively, including switching on/off, flashing warning lights, sweeping headlights, or screen light reaching a face.

Under contract `3.5-spatial-prop-instance-soft-audit`, record `screen_order_left_to_right` before deriving named positions or pairwise horizontal relations. Also record every handled transient prop in `prop_continuity` with stable `instance_id`, `visible_instance_count`, appearance invariants, holder, physical contact, start/middle/end state, visible source, adjacent-record inheritance, and `exclusive_holder_after`. A hard cut does not explain a prop appearing, changing size, opening, closing, changing face colour, or changing holder. Treat a different face/lining as the same object unless two instances are simultaneously visible. A handoff has one instance: giver only before, shared contact during, receiver only after, with the giver's relevant hand empty. Pre-roll is continuity evidence for the logical-core start. Use `unclear` plus a warning when the source is not visible. Local assembly may surface these findings, but must not fail export, rewrite the observation, or trigger an automatic relay retry.

Use prompt contract `2.3-dialogue-injection-locked` for experimental runs. Require a validated `2.0-dialogue-injection`, lock every injected dialogue ID, time, speaker, and text, and ask the relay only for visual records, cut decisions, and per-record speaker visibility. Hydrate the root dialogue events and record utterances deterministically after the relay returns. Pin high-confidence scene-score candidates to their original times when kept, label all contact evidence with candidate evidence-interval IDs, and require start/middle/end anchor subjects.

`boundary_audit` must cover every supplied internal candidate exactly once. Its decision must be `keep_cut`, `keep_reframe`, or `merge_false`; a kept candidate should correspond to a record boundary within 0.10 seconds unless the audit explains a transition interval. Missing audit entries invalidate pass 1.

For every audit item, identify the primary visible subject immediately before and after the candidate. `merge_false` requires `same_shot_evidence=true` and matching stable subject labels. Continuous dialogue or subtitles never prove visual continuity. For every record, identify visible characters before assigning dialogue; every utterance must state whether its speaker is on screen, off screen, or unclear.

## Pass 2: local expansion

Use Codex reasoning without another video upload:

1. Validate and order the compact records.
2. Merge adjacent records into dramatic shot groups while retaining every boundary as a subshot candidate.
3. Match source asset hints and observations to exact localized asset names.
4. Expand spatial positions, contact actions, camera trajectory, composition, initial/final frames, expressions, mouth dynamics, dialogue localization, and linked assets only as supported by pass-1 evidence.
5. Put unsupported detail in warnings instead of inventing it.
6. Export through `build_shot_group_workbook.mjs` and preserve the normal `.qa.json` report.

In production mode, pass 2 is text-only. The automatically generated pass-1 context sheet is allowed, but do not manually open the source video, inspect context frames, extract additional stable frames, or rewrite identities through a second visual pass. If the compact evidence is structurally valid but semantically uncertain, preserve the uncertainty in `warnings` and continue. Reserve local visual inspection and semantic correction for explicitly requested audit mode.

Apply these mandatory expansion rules:

- Determine the scene for every evidence record before grouping. Prefer the relay's consecutive `narrative_group` suggestion when it describes one complete action, reveal, recollection, or reaction. A brief insert or rapid scene transition may remain inside the group when it is necessary to complete that dramatic beat; record the internal scene transition explicitly and use the dominant scene asset in the row.
- Prefer explicit visual location words over dialogue or off-screen sound. For example, an exterior car-park shot remains the car park even when dialogue comes from inside a vehicle.
- Resolve source-name aliases from on-screen labels, dialogue context, asset descriptions, and recurring identity. Never default an unidentified person to the protagonist merely to satisfy a non-empty field.
- Bind every visible character to the exact `person - wardrobe/state` value from `资产本地化英文名`. Use that complete value not only in `main_characters` and `linked_assets`, but also whenever the character is named in narrative summaries, subshot descriptions, spatial positions, contact actions, initial/final frames, expressions, mouth dynamics, and sound descriptions. Do not leave source names or bare base identities in final visual prose when a visible state asset exists.
- Treat costume/state changes for the same character as hard group boundaries. Never include both a base character asset and one of its state-specific assets in the same row when the state is visible.
- Inspect all subshots in a group before selecting people and assets. A character appearing in a later subshot must still be included.
- Require a non-empty British-localized line for every non-empty Chinese dialogue line. Translate each utterance before joining records so punctuation or record splitting cannot break lookup or translation.
- Treat `dialogue_utterances` as the dialogue authority. Split every audible or burned-in sentence, address term, greeting, interjection, and trailing fragment into its own timed element; never keep only the final sentence from a multi-sentence record. `chinese_dialogue` must be a chronological `；` join of every utterance text. Cross-check dialogue subtitles and visible speaking mouth dynamics against the array before expansion.
- Preserve legitimate missing locations as `（候选新增）` instead of collapsing them into the nearest known room.
- Preserve every pass-1 action, spatial, contact, initial/final, expression/gaze, mouth, text, sound, shot-size, angle, camera, and transient-object fact in the final reconstruction. Keep fixed person appearance and fixed scene-detail evidence internally for matching, but do not copy it into final prose after exact assets are bound.
- Write group-level camera trajectory, composition, expression/gaze, mouth dynamics, and sound as time-ordered evidence sequences when the group contains multiple records. Do not deduplicate away changes or repeated states that establish continuity.
- Begin each final group with a concise narrative-purpose sentence, then convert evidence into fluent reconstruction prose. Do not expose field labels repeatedly for every subshot, and never write `unknown`, `未知`, or `待确认` inside visible workbook prose.
- After expansion, run `scripts/validate_expanded_shot_groups.py` before the workbook builder. Fix all errors; do not waive them as warnings.

## Resume files

Write these atomically in one episode output directory:

- `relay_manifest.json`: source identity, TOS object metadata or normalized input, model, status, attempts, and paths.
- `pass1_raw_response.json`: untouched relay response envelope or returned text.
- `pass1_timeline.json`: normalized compact evidence timeline.
- `shot_groups.json`: pass-2 final contract.
- final `.xlsx`, preview, and `.qa.json`.

Skip a completed stage when its source fingerprints and model label still match. A formatting or export failure must never trigger another video upload.

## Bounded recovery ladder

1. Retry one transient `429`, `500`, `502`, `503`, `504`, `520`, `522`, or `524` failure with backoff, reusing the same TOS object or normalized file.
2. On a response-format failure, run one text-only JSON repair against the saved raw response; do not resend video.
3. On `400` or likely safety rejection, do not loop. Use locally extracted keyframes and burned-in subtitles for the affected evidence gap and mark the limitation.
4. If one bounded request still cannot complete, split only that failed logical core near a high-density candidate region, process its two recovery clips, and merge them into the same compact timeline.

## Prompt constraints

- Allow up to 30,000 output tokens per request and target about 20,000 useful tokens for a dense range; prefer concrete visual evidence over repetition. If the relay rejects the configured ceiling, lower `--max-output-tokens` to the provider-supported value without changing the range plan unless truncation recurs.
- Set low temperature.
- Request `json_object` when the relay supports it; avoid strict schemas if the relay rejects them.
- Do not include the complete asset workbook in pass 1. Filter the current episode's character rows and include only compact bilingual recognition cards made from `资产中文原名`, exact `资产本地化英文名`, and `原始中文解析描述`; omit every non-character asset. Keep compact-timeline identities in Chinese and treat the English name only as a fixed localization cross-reference. Treat the cards as candidate-matching aids after visual detection, never as proof that a person appears.
- Put the asset table and localization rules exclusively in pass 2.

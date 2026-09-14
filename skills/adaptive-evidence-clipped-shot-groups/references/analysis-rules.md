# Analysis and transcreation rules

## Evidence hierarchy

Use synchronized evidence in this order:

1. visible frame sequence and exact cut timing;
2. audible speech and sound;
3. readable on-screen text;
4. asset-workbook descriptions and episode occurrences;
5. narrative inference.

When evidence conflicts, preserve the directly observed fact and add a warning. Do not use an asset merely because its episode occurrence matches.

## Shot detection

Treat high-confidence local cut candidates as pinned time anchors when kept; allow `merge_false` only with direct same-shot evidence. Label every evidence frame with its candidate evidence-interval ID. Require the semantic record to echo the covered IDs plus start/middle/end anchor subjects and evidence timestamps. Do not move content from the next interval into the previous interval merely because a subtitle, voice, gesture, or reaction continues across the cut. Lower-confidence candidates remain advisory.

Mark a new subshot when there is a hard cut, dissolve to a distinct composition, major reframing, or continuous move that changes the dominant view enough to need a separate description. Do not split on minor hand shake, blink, or ordinary actor motion.

For every subshot describe:

- shot size and camera angle;
- who and what is visible;
- screen position, screen-relative torso orientation, head orientation, gaze direction/target, posture, and support point;
- exact contact actions;
- environment, vehicle, and camera motion;
- expression, gaze, mouth movement, readable text, dialogue, and sound when present.

For every subshot record `time_of_day=day|night|dawn|dusk|unclear` and `time_of_day_evidence`. Use visible sky, exterior conditions, directional natural light, daylight/nightscape visibility, or an explicit continuous story-time cue. Interior practical lights, cool grading, low exposure, or a dark room alone do not prove night. Keep `unclear` when there is no direct basis. A shot group containing conflicting explicit day/night values must be split locally rather than exported as `mixed`.

Separate spatial depth from optical focus. Record each visible person's `depth_layer` independently from `focus_state=sharp|slightly_soft|heavily_defocused|unclear`. Record one `focus_subject` for the interval and `focus_policy=locked|rack_focus|unclear`. Do not mark several people sharp merely because they are all identifiable; follow the actual focal plane and visible blur.

Require `focus_evidence` for every visible person. Determine the sharpest subject first, then compare eye detail, facial edges, individual hair strands, clothing texture, contour softness, and background bokeh for every other person. Identifiability is not evidence of sharpness. In shallow-depth shots, default to one sharp focal subject. Allow sharp people at different depth layers only when the frame visibly uses deep focus or large depth of field and record that fact in `lighting_composition`.

Determine physical camera distance before optical focus. Use apparent size, perspective enlargement, frame-edge cropping, and occlusion to set `depth_layer`, `relative_camera_distance`, `frame_occupancy`, `frame_crop`, `occlusion_relation`, and `depth_evidence`. A large, cropped, blurred person at the frame edge is usually close foreground, not background. Keep all spatial words out of `focus_evidence`; keep all sharpness claims out of `depth_evidence`. Audit all four frame edges and include every identifiable fragment in `visible_characters`.

After detecting all visible people, write `screen_order_left_to_right` once for the start/middle/end anchors of the subshot, using only the viewer-coordinate axis printed on the evidence page. Then derive each person's `screen_position`, every pair's `horizontal_relation`, and `spatial_positions` from that same order. Never fill these independently. If identity mapping or overlap makes the order uncertain, write `unclear` instead of reversing it. Build `relative_blocking` for every unordered pair exactly once. Record `horizontal_relation=left_of|right_of|overlapping|unclear`, `depth_relation=in_front_of|behind|same_plane|unclear`, `occlusion=blocks|blocked_by|none|unclear`, and direct size/crop/perspective/occlusion evidence. Do not infer a same-plane arrangement merely because two people are both identifiable or share a coarse depth label. A person marked `blocks` cannot be behind the blocked person; a person marked `blocked_by` cannot be in front.

Treat a changing screen order as a timed event, not a static position. Add `position_transition` to every subshot with `type=stable|crosses_behind|crosses_in_front|reblocked_after_cut|unclear`, a concise visible path, and evidence timestamps. A reversal between start/middle/end anchors inside one continuous shot must state which person passes in front of or behind whom and the resulting side. A reversal across a hard cut belongs to the following subshot as `reblocked_after_cut`; do not invent a crossing action between disconnected shots. Preserve the three anchor orders in downstream prose as a high-priority viewer-coordinate blocking timeline.

Record visual state per person, not only per shot. Define left/right exclusively in the unmirrored viewer coordinates printed on every evidence frame: red `SCREEN LEFT`, blue `SCREEN RIGHT`. Use nose-tip/ear direction for the head, shoulder/chest/clothing axes for the torso, and pupils for gaze. Separate `torso_orientation`, `head_orientation`, `gaze_direction`, and `gaze_target`; never infer that a person faces someone merely because that person occupies the corresponding side of frame. Every pairwise relationship must also state `facing_relationship=face_to_face|same_direction|back_to_back|crossing|unclear` based on torso/head evidence. Every `visible_characters` item must include these fields plus `facial_expression` and `character_action` in addition to posture, support/contact, visibility, depth, and focus. Describe an inactive person with an explicit visible state such as standing still, sitting still, or observing in the background. Never copy the primary subject's gaze, expression, or action onto another visible person. Keep record-level `visible_action` and `expression_gaze` only as multi-person summaries.

Inventory visible humans before asset matching. Preserve every real human seen in the original clip or evidence pages, including unmatched passers-by, tiny/background people, blurred people, edge fragments, and people present only at the middle anchor. Name unmatched people `背景路人A/B/C` within the shot, keep their blocking and motion, and exclude them from asset bindings. `visible_characters` may contain only people; scenes, buildings, vehicles, fountains, furniture, lamps, and objects are invalid identities.

Treat fixed lighting fixtures and continuous coloured ambience as scene-owned. Do not send chandeliers, ceiling lights, light strips, neon, static blue/red glow, or coloured ambience into generation prose. Keep only subject-lighting condition, overall brightness/exposure/contrast, time of day, depth of field, focus/composition changes, and narrative light changes such as switching on/off, flashing warning lights, sweeping headlights, or screen light reaching a face.

Track handled transient props as physical instances, not nouns. Give each continuing object a stable `instance_id`, record `visible_instance_count`, appearance invariants, holder, exact hand/body/surface contact, start/middle/end state, visible source, inheritance, and `exclusive_holder_after`. Preserve the same instance when it is flipped, opened, closed, or shows a different face/lining; do not create a second object unless two separate instances are simultaneously visible. For a handoff, encode three phases: before transfer only the giver holds the single instance; during transfer both may contact that same instance; after transfer only the receiver holds it and the giver's relevant hand is empty. Before describing a handoff or use, verify where the prop already was. Preserve size, orientation, open/closed state, and holder across a cut unless a visible action changes them. Pre-roll is continuity evidence: an object already visible before the logical core cannot be labelled `hard-cut first reveal` at the core start. If the source cannot be seen, mark it `unclear`; do not invent it. Treat local continuity findings as warnings only.

Identify the visible subject before interpreting audio. Record visible characters independently from dialogue speakers. A reaction shot of person A remains a shot of A when person B's speech continues across the cut; mark B as off-screen instead of replacing A with B. In production mode, ask the relay to compare the visible subject immediately before and after every locally detected candidate. A `merge_false` decision is valid only when the primary visible subject and continuous composition remain the same. Do not extract or manually inspect stable frames after the relay result. Use a stable appearance label and a warning when identity remains uncertain.

When every locked dialogue event intersecting a record is `off_screen`, and there is no separate on-screen event for a visible person, treat the visible people as reacting rather than speaking. Do not write `mouth_state=speaking` or use speaking verbs in `character_action`, `visible_action`, `beat_summary`, `primary_visible_subject`, or `mouth_dynamics`. Burned subtitles over a face, a single open-mouth frame, visible teeth, or a hand gesture are not lip-sync evidence. Describe the observed reaction and hand contact instead. Use “双手合十” only when the palms visibly remain pressed together; distinguish it from interlaced fingers, touching fingertips, rubbing hands, pinching fingers, or neutral gesturing.

Under contract `3.9-mouth-motion-speech-sync`, separate visible mouth motion from speech ownership for every visible person. `mouth_visual_action` is observation-only: closed, briefly opens then closes, continuous opening-closing, smiling with teeth visible, pursed lips, or `unclear`. `speech_sync_status` is one of `matched_on_screen_dialogue`, `off_screen_audio_reaction`, `non_speech_mouth_motion`, `no_visible_mouth_motion`, or `unclear`. `mouth_action_evidence` must name at least one timestamp or a start/middle/end comparison. Set `mouth_state=speaking` only when the same person owns an intersecting locked `on_screen` event and continuous frames show speech-like mouth motion. A visible person may briefly open their mouth during another person's off-screen line; keep them `not_speaking`, record the visible motion, and use `off_screen_audio_reaction`.

Create dialogue as root-level events before attaching it to visual records. Reuse one `dialogue_id` across every reaction shot covered by the same audible utterance. Keep speaker identity stable across cuts; change only per-record visibility. Identical adjacent subtitle text assigned to different speakers is a blocking conflict unless direct audio or lip-sync evidence proves a deliberate repetition.

Do not rebuild row dialogue by concatenating every record's compatibility utterance. After groups are known, intersect each root dialogue event with the group ranges once. Material cross-group events receive ordered unique segments; seam-only overlaps of at most 0.15 seconds are snapped to the material owner. Reconstructing all segments in order must yield the original source and localized text exactly, ignoring whitespace. Treat duplicated, missing, reordered, or multiply owned segments as blocking local assembly errors.

After the final shot groups are fixed, audit every adjacent final-group boundary as its own layer. Attach exactly one derived handoff to the right-hand group and classify it as `inherit_state`, `new_scene`, or `verify`. Use overlap-pixel transport evidence when the final boundary coincides with an audited range seam; otherwise compare the previous group's resolved final state and the target group's resolved initial state. Never duplicate the instruction in both groups, never leave a boundary unclassified, and never turn `verify` into an invented continuity fact.

Resolve those boundary states from the last and first record respectively. Never compare whole-group composite strings to infer a scene change. Composite scene components must be ordered by time; only use the first component as an unresolved head fallback and the last component as an unresolved tail fallback. Preserve complete pairwise blocking as structured evidence, but render only the most important relations into generation prose. Keep observed source on-screen text in analysis evidence; exclude source subtitles, identity graphics, warnings, watermarks, and non-localized overlays from generation prose unless an explicit British-English text mapping exists.

Only in explicitly requested audit mode may Codex extract or inspect stable frames, reinterpret character identities, compare the result against a reference workbook, or perform a semantic correction pass. Audit findings may improve prompts and validators, but audit-mode corrections must not become a hidden mandatory stage in production.

Avoid vague phrases such as “两人互动” when the contact can be stated precisely.

## Shot-group boundaries

Group adjacent subshots only when they form one continuous dramatic beat. Break on scene change, time jump, reveal, decisive reaction, speaker-power reversal, new action goal, or strong transition. Keep coverage continuous; do not duplicate overlap content from analysis windows.

## Asset matching

Match identity and base name first, then visible costume/state, then episode occurrence. A state-specific row outranks a base-character row only when clothing or state is visible. Include the scene, all principal visible characters, and plot-relevant props in `linked_assets`.

For pass-1 identity assistance, provide only episode-filtered bilingual character recognition cards containing the source character/state name, exact British-localized name, and concise original visual description. First detect each visible person independently across foreground, midground, and background; then compare clothing, hair, age, gender, and accessories with the cards. Keep compact-timeline identities in Chinese, use the British name only as a fixed mapping reference, mark partial matches as suspected, and keep unmatched people under stable appearance labels.

After an exact person-wardrobe/state match, set `appearance=asset_bound`. The asset owns fixed clothing colour, material, style, and accessories; do not repeat them in action, spatial, focus, or final generation prose. Keep minimal appearance evidence only for suspected or unmatched people.

Use `scene_observation` as internal scene-recognition evidence. After an exact scene match, the scene asset owns fixed décor, furniture, wall colours/materials, and permanent dressing. Do not copy those facts into final generation prose. Put only shot-specific temporary props or state changes not covered by the person/scene assets in `transient_visual_details`.

Never combine fragments of several localized names. Never translate an absent asset into a confident new British asset. Mark it `（候选新增）` and explain the source observation in warnings.

## British localization

Preserve causal structure and physical choreography. Localize the production design, not the event itself. Replace culture-specific architecture, clothing, rituals, institutions, signs, money, food, transport, etiquette, and interfaces with coherent modern British equivalents supported by the asset workbook.

Maintain family surnames, titles, class relationships, and established character names across every episode. Use natural British vocabulary and register. Keep dialogue short enough for the original speaking duration. Do not add exposition absent from the source.

When a locked dialogue event contains `delivery`, preserve its source `speech_rate`, `intonation`, `timbre`, `emotion`, `rhythm_pause`, and relative `pause_profile`. The original event duration is the hard timing window. Keep localized English as pure speakable text and store performance direction separately. Compute the English word rate required after reserving audible pauses. If it exceeds the hard limit, condense the translation without changing meaning before export; never hide a timing failure by instructing an unnaturally fast delivery. A visual cut does not reset delivery or create a second vocal performance for the same `dialogue_id`.

Readable text must be natural British English. Otherwise keep it visually unreadable. Exclude Chinese text, platform logos, watermarks, and unlicensed brands from localized generation descriptions.

## Required fixed suffix in `画面内容`

Append:

`人物住宅陈设、社交礼仪、饮食和日常生活方式必须符合当代英国语境，不混入中式元素。画面内不出现中文字幕、中文、logo或水印；合同、报告、杯身、招牌、车牌、手机界面等如必须可读，只使用自然 British English，否则保持模糊不可读。`

# Adaptive evidence contract

Use one role-labelled evidence manifest per logical clipped range.

## Always attach

1. `range_boundaries`: range entry and exit only.
2. `action_events`: unmarked start/change/end frames for each local shot.
3. `high_motion_triplets`: unmarked before/peak/after frames for the strongest motion.
4. `shot_space`: enlarged original-pixel representatives for screen position, crop, edge presence, depth cues, and optical focus.
5. `person_trajectory`: one consolidated page containing shot-bounded BoT-SORT boxes and foot-point paths. Track IDs reset at each supplied cut and remain anonymous.

## Conditionally attach

Attach `multi_person_geometry` only when `score_pose_complexity.py` returns `pose_enabled=true`. The gate may use multi-person frequency, edge contacts, overlap, count instability, profile-dominant evidence, and same-frame scale differences. It only controls an attachment; it never creates semantic labels.

Treat the clipped video and unmarked pages as higher priority than overlays. JointBDOE and MediaPipe may support person presence, coarse posture, and body-joint geometry. They must not determine identity, head orientation, gaze, facing relationship, physical depth, action meaning, or dialogue.

Use trajectory paths only to nominate entry, pass, crossing, stop, approach, exit, or short-occlusion processes for video verification. A supplied trajectory partition is not final cut truth. Never map a track ID directly to an asset or carry it across a cut.

Keep final cut decisions, absolute times, identity, actions, dialogue visibility, orientation, blocking, focus, and narrative grouping under multimodal-model authority.

# Output contract

## Asset workbook input

Require one sheet with these eight headers in this exact order:

1. `资产类型`
2. `资产中文原名`
3. `资产本地化英文名`
4. `资产简介`
5. `原始中文解析描述`
6. `角色状态中文参考描述`
7. `角色状态本地化参考`
8. `出现集号`

`资产类型` must be `人物`, `场景`, or `道具`. Treat `资产本地化英文名` as the canonical value used by the shot-group output.

Build expansion `people_rules` from all exact episode person-state assets, including supporting speaking roles. Do not limit speaker resolution to principal-character cards.

For visible characters, select the most specific canonical `person - wardrobe/state` asset. The complete identifier must appear in `main_characters`, `linked_assets`, and all visual prose fields that name that character; do not shorten it to a base name or revert to a Chinese source name.

## Structured JSON input to the builder

Use this shape:

```json
{
  "schema_version": "1.0",
  "source": {
    "backend": "provider/model label without secrets",
    "videos": [
      {
        "episode": "01",
        "name": "EP01.mp4",
        "fingerprint": "sha256-based stable id",
        "duration_seconds": 91.2
      }
    ]
  },
  "rows": [
    {
      "episode": "01",
      "group_id": "EP01-G001",
      "start_seconds": 0.0,
      "end_seconds": 8.5,
      "scene": "exact localized scene asset",
      "time_of_day": "day",
      "time_of_day_evidence": "direct visible sky/natural-light/story-time evidence",
      "main_characters": ["exact localized character-state asset"],
      "subshots": [
        {
          "start_seconds": 0.0,
          "end_seconds": 1.8,
          "shot_size": "全景",
          "camera_angle": "平视",
          "time_of_day": "day",
          "time_of_day_evidence": "direct per-subshot evidence",
          "description": "可直接观察的画面动作",
          "screen_order_left_to_right": {"start": ["人物A", "人物B"], "middle": ["人物A", "人物B"], "end": ["人物B", "人物A"]},
          "position_transition": {"type": "crosses_behind", "description": "人物B从人物A左后方经过其身后移动至右后方", "evidence_timestamps": [1.0, 2.64]},
          "spatial_positions": "人物及物体站位、姿态、支点和朝向",
          "contact_actions": "人与人、人与物的接触动作；无则明确写无",
          "environment_motion": "环境、载具与摄影机可见运动",
          "evidence": ["frame@00:00.900"],
          "confidence": "high"
        }
      ],
      "camera_trajectory": "组内机位与运动变化",
      "composition": "构图、光线、景深、遮挡",
      "initial_frame": "首帧可见状态",
      "final_frame": "末帧可见状态",
      "mouth_dynamics": "嘴部动作及是否与台词同步",
      "expressions_gaze": "表情和视线变化",
      "sound_dialogue": "Localized Speaker: audible English line | sound event",
      "chinese_dialogue": "“忠实中文原台词”",
      "british_localized_dialogue": "Localized Speaker: natural British English line",
      "dialogue_delivery": [
        {
          "dialogue_id": "EP09-D0001",
          "dialogue_segment_id": "EP09-D0001-S01",
          "segment_index": 1,
          "segment_count": 2,
          "continuation": "starts_here",
          "start_seconds": 1.25,
          "end_seconds": 2.4,
          "speaker": "exact localized character-state asset",
          "localized_text": "pure speakable British English",
          "source_delivery": {
            "speech_rate": "medium",
            "intonation": "低平后下沉",
            "timbre": "年轻男声、清晰、略紧",
            "emotion": "克制愤怒",
            "rhythm_pause": "转折前短停顿，末词加重",
            "pause_profile": [{"position_ratio": 0.58, "duration": "short", "function": "emphasis"}],
            "confidence": "high"
          },
          "source_window_seconds": 2.55,
          "english_word_count": 7,
          "required_words_per_second": 2.95,
          "timing_status": "fits_source_rate",
          "performance_direction": "non-spoken delivery instruction"
        }
      ],
      "linked_assets": ["exact localized asset", "未知物（候选新增）"],
      "camera_view": "1 俯瞰/俯视",
      "within_group_view_change": null,
      "warnings": []
    }
  ],
  "warnings": [],
  "errors": []
}
```

Use numeric seconds as canonical time. Intervals are half-open: `start_seconds <= t < end_seconds`. Preserve millisecond precision when evidence supports it.

## Text-only seam continuity audit

Keep the continuity injection compatible with `schema_version=1.0-seam-continuity-injection` and add `contract_version=1.1-text-state`. Include `scene_state`, `action_handoff`, end-visible principal character state, `screen_order_end`, and `prop_tail_states`. Set the left-only values to `seam_type=pending_target_video_verification` and `continuity_mode=verify_from_video`. Do not include a real tail-frame image.

After inspecting overlap pixels, append this shape under `transport.start_seam_audit` without rewriting records:

```json
{
  "continuity_decision": {
    "seam_type": "continuous_action|same_scene_cut|scene_transition|time_jump|unclear",
    "continuity_mode": "inherit_state|new_scene|verify_from_video",
    "scene_match": "true|false|unclear",
    "action_continues": "true|false|unclear",
    "character_state_continues": "true|false|unclear"
  }
}
```

## Final-group continuity handoff

After final shot-group boundaries are fixed, write one root `continuity_handoffs` array and attach the identical handoff object to each right-hand target row as `continuity_handoff`. The first row owns none. Contract version is `1.0-group-boundary-handoff`; for `N` rows, `expected_boundary_count` and the array length must both equal `N-1`. Each adjacent pair must appear exactly once and use exactly one mode: `inherit_state`, `new_scene`, or `verify`. Include `previous_final_state`, `target_initial_state`, `persistent_assets`, a generation-ready `instruction`, and mode-specific `inherited_state` or `reset_fields`. Map transport `verify_from_video` to final-group `verify`. If no transport audit lies on that final boundary, derive conservatively from resolved scene/daylight state; unresolved evidence remains `verify`.

## Excel output

Treat `scripts/lib/shot_content_contract.mjs::composeShotContent` as the sole executable authority for `画面内容`. Every standard workbook, styled/formal workbook, whole-series workbook, canary workbook, and web adapter must import it rather than reimplementing the ordered prose. Record the composer version, resolved file, and SHA-256 fingerprint in the build report. A missing import or any validator error is blocking; do not emit a workbook through a simplified fallback.

Write one sheet named `Sheet` with these 12 headers in exact order:

1. `集数`
2. `镜头组序号`
3. `时间段`
4. `场景`
5. `主要人物`
6. `画面内容`
7. `台词/声音`
8. `中文原台词`
9. `英国本地化台词`
10. `关联资产`
11. `镜头景别`
12. `镜头内景别变化`

Join `主要人物` with `、` and `关联资产` with `；`. Leave dialogue cells blank only when there is no audible dialogue or meaningful sound event.

Keep `英国本地化台词` as pure speakable text. Put timing, voice, emotion, intonation, and pause directions only in `dialogue_delivery` and in the non-spoken instruction portion of `台词/声音`. Never append directions to the localized line itself. Reject `timing_status=needs_condense`; shorten the localized wording first.

Keep `time_of_day` structured at row and subshot level. Excel remains a fixed 12-column workbook, so render `昼夜/光景：<value>；依据：<evidence>` and exactly one `上一组尾态→本组首态（source→target，mode）：<instruction>` inside each non-first row's `画面内容` rather than adding columns.

For cross-group dialogue, preserve one parent `dialogue_id` but emit unique ordered `dialogue_segment_id` values. Each segment belongs to exactly one row. Concatenating all `source_text` and all `localized_text` fragments by `segment_index` must reproduce the full event once. Full-line duplication across rows is an error.

`镜头景别` accepts only:

- `1 俯瞰/俯视`
- `2 正视`
- `3 侧视`
- `4 反打`
- `待确认`

Compose `画面内容` in this fixed order:

1. A concise `镜头{n}:时间段，` narrative-purpose sentence describing the complete action, reveal, or reaction.
2. `组内画面序列：` with every timestamped subshot written as fluent reconstruction prose. Each subshot should naturally cover concrete objects and colours, composition, positions, ordered contact actions, environment/camera movement, expression/gaze, mouth movement, text, and sound without repeating empty field labels.
3. `摄影机轨迹：`
4. `画面构图：`
5. `上一组尾态→本组首态：` (all non-first groups only; exactly once)
6. `起初：`
7. `最终：`
8. `嘴部动态：`
9. `表情/视线：`
10. `声音/台词：`
11. British-setting and readable-text constraints.

Treat bound assets as the sole source of fixed appearance. If a visible person is bound to an exact `person - wardrobe/state` asset, name that complete asset once and omit separate clothing colour, material, style, and accessory descriptions. If the row scene is an exact scene asset, omit fixed décor, furniture, wall colour/material, and permanent-setting descriptions. Preserve only shot-specific action, position, posture, orientation, blocking, depth/focus state, lighting change, camera change, and transient plot objects in the reconstructed prose.

For contract `3.3-background-people-static-light-filter`, keep `scene_observation`, `fixed_scene_evidence`, `visual_details`, person `appearance`, `depth_evidence`, and `focus_evidence` as recognition/audit fields. Do not concatenate them into generation prose. Build final composition only from `generation_facts`, and use the complete bound person-state asset at most once per subshot; subsequent references use the base localized character name. `subject_lighting` records only whether the subject is normally lit or visibly backlit, underexposed, overexposed, or briefly affected by a changing source. Fixed lamps, chandeliers, light strips, neon, static coloured ambience, and continuously glowing blue/red light belong to the scene asset and must not enter generation prose. Preserve a light only when it changes narratively, such as switching on/off, flashing, sweeping headlights, or screen light reaching a face.

Asset binding never controls visual-person inclusion. Keep every visible human in `visible_characters`, including unmatched background people, edge fragments, tiny or soft people, and people visible only at the middle anchor. Name unmatched people `背景路人A/B/C` within the shot, preserve their position/action chain, and keep them out of `asset_hints`. Reject scenes, buildings, vehicles, fountains, furniture, lamps, and other objects used as character identities.

Under contract `3.5-spatial-prop-instance-soft-audit`, add `screen_order_left_to_right` to every record and derive named screen positions plus all pairwise horizontal relations from it. Add `prop_continuity` to every record. Use an empty array when no handled transient prop is present. For each handled prop record `instance_id`, `visible_instance_count`, `identity`, `appearance_invariants`, `holder`, `support_contact`, `start_state`, `middle_action`, `end_state`, `source`, `continuity_from_previous`, `continuity_to_next`, and `exclusive_holder_after`. Keep the same instance through flipping, opening, closing, or a visible face/lining colour change. Create a second instance only when two separate objects are simultaneously visible. A handoff contains one instance: giver-only before, shared contact during, receiver-only after, and the giver's relevant hand empty. A hard cut is not itself a physical transfer, and pre-roll visibility counts as previous continuity at a logical-core boundary. When the source is not visible, write `unclear` and a warning rather than inventing a pocket, bag, drawer, or off-screen handoff. Local expansion may warn about missing source, inheritance, duplicate instances, or transfer, but these warnings must never block output or alter semantic fields.

Under contract `3.7-screen-order-transition`, also add `position_transition` to every record. Preserve start/middle/end orders and render them in `spatial_positions` as `站位时间轴（观众画面坐标）`. Use `stable` only when the relative order of common visible people does not reverse. Use `crosses_behind` or `crosses_in_front` for a visible continuous crossing, `reblocked_after_cut` for a changed arrangement introduced by a cut/reframe, and `unclear` when the evidence cannot establish the path. Local checks remain warning-only.

Under contract `3.9-mouth-motion-speech-sync`, every `visible_characters` item also requires `mouth_visual_action`, `speech_sync_status`, and `mouth_action_evidence`. Treat these as separate from `mouth_state`: the first is a visible fact, the second is the relation to locked audio, and the third is timestamped evidence. `speaking` requires `matched_on_screen_dialogue`; a reaction shot with another person's off-screen line remains `not_speaking` even when the visible mouth briefly opens. Render the visual mouth action and sync status into subshot prose, but never move technical evidence timestamps or dialogue ownership guesses into the speakable localized dialogue.

Never expose `unknown`, `未知`, `待确认`, or generic missing-evidence boilerplate inside `画面内容`. Omit a genuinely unavailable detail and keep material uncertainty in the QA warnings.

Do not place JSON warnings or confidence labels in the Excel prose unless they affect a visible candidate name. Put them in the `.qa.json` report.

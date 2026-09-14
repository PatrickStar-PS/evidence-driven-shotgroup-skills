import assert from "node:assert/strict";
import { composeShotContent, validateShotContentContract } from "./lib/shot_content_contract.mjs";

function fixture(soundDialogue = "Edward Clarke: You're awake.") {
  return {
    group_id: "EP01-G004", start_seconds: 24.05, end_seconds: 31.783,
    narrative_summary: "Edward Clarke wakes Clara Hartley.", camera_trajectory: "static then hard cut",
    time_of_day: "unclear", time_of_day_evidence: "interior only", composition: "shot/reverse-shot",
    initial_frame: "Edward leans beside the bed", final_frame: "Clara sits up",
    mouth_dynamics: "Edward speaks; Clara listens", expressions_gaze: "Edward looks right; Clara looks left",
    sound_dialogue: soundDialogue,
    subshots: [{ start_seconds: 24.05, end_seconds: 31.783, shot_size: "medium", camera_angle: "eye-level", description: "Edward speaks to Clara", spatial_positions: "Edward left, Clara right", contact_actions: "none", environment_motion: "none" }],
  };
}

for (const soundDialogue of ["Edward Clarke: You're awake.", ""]) {
  const errors = [];
  const row = fixture(soundDialogue);
  const content = composeShotContent(row, errors);
  assert.deepEqual(errors, []);
  assert.equal(content.split("声音/台词：").length - 1, 1);
  assert.ok(content.indexOf("表情/视线：") < content.indexOf("声音/台词："));
  assert.ok(content.startsWith("镜头4:"));
}

const invalidErrors = [];
validateShotContentContract("表情/视线：calm。raw dialogue", fixture(), invalidErrors);
assert.ok(invalidErrors.some((value) => value.includes("声音/台词")));
console.log(JSON.stringify({ passed: true, cases: 3 }));

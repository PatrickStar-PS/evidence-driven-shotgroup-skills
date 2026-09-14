import crypto from "node:crypto";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

export const CONTENT_CONTRACT_VERSION = "1.0-canonical-shot-content";
export const BRITISH_SUFFIX = "人物住宅陈设、社交礼仪、饮食和日常生活方式必须符合当代英国语境，不混入中式元素。画面内不出现中文字幕、中文、logo或水印；合同、报告、杯身、招牌、车牌、手机界面等如必须可读，只使用自然 British English，否则保持模糊不可读。";

const SECTION_MARKERS = ["组内画面序列：", "摄影机轨迹：", "昼夜/光景：", "画面构图：", "起始：", "最终：", "嘴部动态：", "表情/视线：", "声音/台词："];

export function cleanText(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

export function cleanMouthDynamics(value) {
  let text = cleanText(value);
  if (!text) return "";
  text = text
    .replace(/与台词[“"'].*?[”"']同步/g, "与对应英文台词同步")
    .replace(/与台词[‘'].*?[’']同步/g, "与对应英文台词同步")
    .replace(/口型与台词[“"'].*?[”"']完全同步/g, "口型与对应英文台词完全同步")
    .replace(/口型与台词[‘'].*?[’']完全同步/g, "口型与对应英文台词完全同步")
    .replace(/配合台词[“"'].*?[”"']/g, "配合对应英文台词")
    .replace(/配合台词[‘'].*?[’']/g, "配合对应英文台词")
    .replace(/发出[“"'].*?[”"']的声音/g, "发出非台词性声音")
    .replace(/发出[‘'].*?[’']的声音/g, "发出非台词性声音")
    .replace(/说[“"'].*?[”"']/g, "说出对应英文台词")
    .replace(/说[‘'].*?[’']/g, "说出对应英文台词");
  return text;
}

export function timecode(seconds) {
  const numeric = Number(seconds);
  if (!Number.isFinite(numeric) || numeric < 0) return "INVALID";
  const rounded = Math.round(numeric * 1000) / 1000;
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  let secondText = secs.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  if (secs < 10) secondText = `0${secondText}`;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${secondText}`
    : `${String(minutes).padStart(2, "0")}:${secondText}`;
}

function requiredText(row, key, errors) {
  const value = cleanText(row?.[key]);
  if (!value) errors.push(`${row?.group_id ?? "unknown"}: missing ${key}`);
  return value;
}

function composeContinuityHandoff(row, errors) {
  const handoff = row.continuity_handoff;
  if (!handoff || typeof handoff !== "object" || Array.isArray(handoff)) return "";
  const mode = cleanText(handoff.mode);
  const source = cleanText(handoff.source_group_id);
  const target = cleanText(handoff.target_group_id);
  const instruction = cleanText(handoff.instruction);
  if (!["inherit_state", "new_scene", "verify"].includes(mode)) errors.push(`${row.group_id ?? "unknown"}: invalid continuity mode ${mode}`);
  if (target !== cleanText(row.group_id)) errors.push(`${row.group_id ?? "unknown"}: continuity target does not match row`);
  if (!source) errors.push(`${row.group_id ?? "unknown"}: continuity source is missing`);
  if (!instruction) errors.push(`${row.group_id ?? "unknown"}: continuity instruction is missing`);
  return instruction ? `上一组尾态→本组首态（${source}→${target}，${mode}）：${instruction}` : "";
}

function markerCount(content, marker) {
  return content.split(marker).length - 1;
}

export function validateShotContentContract(content, row, errors = []) {
  const groupId = cleanText(row?.group_id) || "unknown";
  const text = cleanText(content);
  if (!/^镜头\d+:[0-9:.]+-[0-9:.]+，/.test(text)) errors.push(`${groupId}: 画面内容未使用标准镜头标题`);
  let previousIndex = -1;
  for (const marker of SECTION_MARKERS) {
    const count = markerCount(text, marker);
    if (count < 1) errors.push(`${groupId}: 画面内容缺少“${marker}”`);
    if (["表情/视线：", "声音/台词："].includes(marker) && count !== 1) errors.push(`${groupId}: 画面内容必须且只能包含一个“${marker}”，实际 ${count}`);
    const index = text.indexOf(marker, previousIndex + 1);
    if (index >= 0 && index <= previousIndex) errors.push(`${groupId}: 画面内容章节顺序错误，${marker}位置异常`);
    if (index >= 0) previousIndex = index;
  }
  const handoffCount = markerCount(text, "上一组尾态→本组首态");
  const expectedHandoffCount = row?.continuity_handoff ? 1 : 0;
  if (handoffCount !== expectedHandoffCount) errors.push(`${groupId}: 连续性字段数量应为 ${expectedHandoffCount}，实际 ${handoffCount}`);
  if (markerCount(text, BRITISH_SUFFIX) !== 1) errors.push(`${groupId}: 英国场景与可读文字约束必须且只能出现一次`);
  return errors;
}

export function composeShotContent(row, errors = []) {
  if (!Array.isArray(row?.subshots) || !row.subshots.length) {
    errors.push(`${row?.group_id ?? "unknown"}: subshots must be a non-empty array`);
    return "";
  }
  const pieces = row.subshots.map((shot, index) => {
    const start = Number(shot.start_seconds);
    const end = Number(shot.end_seconds);
    if (!(start >= Number(row.start_seconds) && end <= Number(row.end_seconds) + 0.001 && end > start)) errors.push(`${row.group_id}: subshot ${index + 1} is outside its parent range`);
    return `[${timecode(start)}-${timecode(end)}] ${requiredText(shot, "shot_size", errors)}，${requiredText(shot, "camera_angle", errors)}。${requiredText(shot, "description", errors)} 空间站位：${requiredText(shot, "spatial_positions", errors)} 接触动作：${requiredText(shot, "contact_actions", errors)} 环境/载具运动：${requiredText(shot, "environment_motion", errors)}`;
  });
  const groupNumber = Number.parseInt(cleanText(row.group_id).match(/G(\d+)$/)?.[1] ?? "", 10);
  const narrativeSummary = cleanText(row.narrative_summary);
  const content = [
    narrativeSummary ? `镜头${Number.isFinite(groupNumber) ? groupNumber : cleanText(row.group_id)}:${timecode(row.start_seconds)}-${timecode(row.end_seconds)}，${narrativeSummary}` : "",
    `组内画面序列：${pieces.join(" ")}`,
    `摄影机轨迹：${requiredText(row, "camera_trajectory", errors)}`,
    `昼夜/光景：${requiredText(row, "time_of_day", errors)}；依据：${requiredText(row, "time_of_day_evidence", errors)}`,
    `画面构图：${requiredText(row, "composition", errors)}`,
    composeContinuityHandoff(row, errors),
    `起始：${requiredText(row, "initial_frame", errors)}`,
    `最终：${requiredText(row, "final_frame", errors)}`,
    `嘴部动态：${cleanMouthDynamics(requiredText(row, "mouth_dynamics", errors))}`,
    `表情/视线：${requiredText(row, "expressions_gaze", errors)}`,
    `声音/台词：${cleanText(row.sound_dialogue) || "无可辨识台词；仅保留可观察环境声。"}`,
    BRITISH_SUFFIX,
  ].filter(Boolean).join(" ");
  validateShotContentContract(content, row, errors);
  return content;
}

export async function contentContractMetadata() {
  const composerFile = fileURLToPath(import.meta.url);
  const bytes = await fs.readFile(composerFile);
  return {
    content_contract_version: CONTENT_CONTRACT_VERSION,
    composer_file: composerFile,
    composer_sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
  };
}

#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";
import { composeShotContent as canonicalComposeShotContent, contentContractMetadata } from "./lib/shot_content_contract.mjs";

const HEADERS = ["集数", "镜头组序号", "时间段", "场景", "主要人物", "画面内容", "台词/声音", "中文原台词", "英国本地化台词", "关联资产", "镜头景别", "镜头内景别变化"];
const ASSET_HEADERS = ["资产类型", "资产中文原名", "资产本地化英文名", "资产简介", "原始中文解析描述", "角色状态中文参考描述", "角色状态本地化参考", "出现集号"];
const CAMERA_VIEWS = new Set(["1 俯瞰/俯视", "2 正视", "3 侧视", "4 反打", "待确认"]);
const TIME_OF_DAY_VALUES = new Set(["day", "night", "dawn", "dusk", "unclear"]);
const CONTINUITY_MODES = new Set(["inherit_state", "new_scene", "verify"]);
const CONTINUITY_CONTRACT_VERSION = "1.0-group-boundary-handoff";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    if (!key?.startsWith("--") || argv[index + 1] === undefined) throw new Error(`Invalid argument near ${key ?? "end"}`);
    result[key.slice(2)] = argv[index + 1];
  }
  for (const required of ["input", "assets", "output"]) if (!result[required]) throw new Error(`Missing --${required}`);
  return result;
}

function cleanText(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function timecode(seconds) {
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
  const value = cleanText(row[key]);
  if (!value) errors.push(`${row.group_id ?? "unknown"}: missing ${key}`);
  return value;
}

function candidate(value) {
  return /（候选新增(?:\/[^）]+)?）$/.test(value);
}

const args = parseArgs(process.argv.slice(2));
const inputPath = path.resolve(args.input);
const assetPath = path.resolve(args.assets);
const outputPath = path.resolve(args.output);
const document = JSON.parse(await fs.readFile(inputPath, "utf8"));

const assetWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(assetPath));
const assetSheet = assetWorkbook.worksheets.getItemAt(0);
const assetValues = assetSheet.getUsedRange()?.values ?? [];
const actualAssetHeaders = (assetValues[0] ?? []).slice(0, 8).map(cleanText);
if (JSON.stringify(actualAssetHeaders) !== JSON.stringify(ASSET_HEADERS)) {
  throw new Error(`Asset workbook headers do not match the required eight-column contract: ${JSON.stringify(actualAssetHeaders)}`);
}
const localizedAssets = new Set(assetValues.slice(1).map((row) => cleanText(row[2])).filter(Boolean));

const errors = [];
const warnings = [...(Array.isArray(document.warnings) ? document.warnings.map(cleanText).filter(Boolean) : [])];
if (document.schema_version !== "1.0") errors.push(`Unsupported schema_version: ${document.schema_version}`);
if (!Array.isArray(document.rows) || !document.rows.length) errors.push("rows must be a non-empty array");
const continuityContract = document.continuity_handoff_contract;
const rootHandoffs = document.continuity_handoffs;
if (!continuityContract || typeof continuityContract !== "object" || Array.isArray(continuityContract)) {
  errors.push("continuity_handoff_contract must be an object");
} else {
  if (cleanText(continuityContract.version) !== CONTINUITY_CONTRACT_VERSION) errors.push(`Unsupported continuity handoff contract: ${continuityContract.version}`);
  const expectedBoundaryCount = Math.max(0, (document.rows?.length ?? 0) - 1);
  if (Number(continuityContract.expected_boundary_count) !== expectedBoundaryCount) errors.push(`continuity expected_boundary_count must be ${expectedBoundaryCount}`);
}
if (!Array.isArray(rootHandoffs)) errors.push("continuity_handoffs must be an array");
else if (rootHandoffs.length !== Math.max(0, (document.rows?.length ?? 0) - 1)) errors.push(`expected ${(document.rows?.length ?? 0) - 1} continuity handoffs, found ${rootHandoffs.length}`);
const durations = new Map((document.source?.videos ?? []).map((video) => [String(video.episode).padStart(2, "0"), Number(video.duration_seconds)]));
const seenIds = new Set();
const seenDialogueSegments = new Set();
const sequenceByEpisode = new Map();
const previousEndByEpisode = new Map();
const continuityModeCounts = { inherit_state: 0, new_scene: 0, verify: 0 };
const rootHandoffByTarget = new Map();
for (const handoff of Array.isArray(rootHandoffs) ? rootHandoffs : []) {
  const handoffId = cleanText(handoff?.handoff_id);
  const target = cleanText(handoff?.target_group_id);
  if (!handoffId || !target) errors.push("continuity handoff is missing handoff_id or target_group_id");
  if (rootHandoffByTarget.has(target)) errors.push(`duplicate continuity handoff target: ${target}`);
  rootHandoffByTarget.set(target, handoff);
}

const outputRows = (document.rows ?? []).map((row, rowIndex) => {
  const episode = String(row.episode ?? "").padStart(2, "0");
  const groupId = cleanText(row.group_id);
  const start = Number(row.start_seconds);
  const end = Number(row.end_seconds);
  if (!/^\d{2,4}$/.test(episode)) errors.push(`${groupId || "unknown"}: invalid episode ${episode}`);
  if (!new RegExp(`^EP${episode}-G\\d{3}$`).test(groupId)) errors.push(`${groupId || "unknown"}: group_id must match episode`);
  if (seenIds.has(groupId)) errors.push(`${groupId}: duplicate group_id`);
  seenIds.add(groupId);
  const sequence = Number(groupId.match(/-G(\d{3})$/)?.[1]);
  const expected = (sequenceByEpisode.get(episode) ?? 0) + 1;
  if (sequence !== expected) errors.push(`${groupId}: expected group sequence G${String(expected).padStart(3, "0")}`);
  sequenceByEpisode.set(episode, Number.isFinite(sequence) ? sequence : expected);
  if (!(Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start)) errors.push(`${groupId}: invalid time range`);
  const previousEnd = previousEndByEpisode.get(episode);
  if (previousEnd !== undefined && start < previousEnd - 0.001) errors.push(`${groupId}: overlaps previous group`);
  if (previousEnd !== undefined && start > previousEnd + 0.1) warnings.push(`${groupId}: gap of ${(start - previousEnd).toFixed(3)} seconds before group`);
  previousEndByEpisode.set(episode, end);
  const duration = durations.get(episode);
  if (Number.isFinite(duration) && end > duration + 0.1) errors.push(`${groupId}: end exceeds episode duration ${duration}`);

  const scene = requiredText(row, "scene", errors);
  const timeOfDay = requiredText(row, "time_of_day", errors);
  if (!TIME_OF_DAY_VALUES.has(timeOfDay)) errors.push(`${groupId}: invalid or mixed time_of_day ${timeOfDay}`);
  requiredText(row, "time_of_day_evidence", errors);
  for (const item of Array.isArray(row.dialogue_delivery) ? row.dialogue_delivery : []) {
    const segmentId = cleanText(item?.dialogue_segment_id);
    if (!segmentId) errors.push(`${groupId}: dialogue segment is missing dialogue_segment_id`);
    else if (seenDialogueSegments.has(segmentId)) errors.push(`${groupId}: duplicate dialogue segment ${segmentId}`);
    else seenDialogueSegments.add(segmentId);
  }
  const mainCharacters = Array.isArray(row.main_characters) ? row.main_characters.map(cleanText).filter(Boolean) : [];
  const linkedAssets = Array.isArray(row.linked_assets) ? row.linked_assets.map(cleanText).filter(Boolean) : [];
  const sceneAssets = scene.replaceAll("、", "；").split("；").map(cleanText).filter(Boolean);
  if (!mainCharacters.length) errors.push(`${groupId}: main_characters must be non-empty`);
  if (!linkedAssets.length) errors.push(`${groupId}: linked_assets must be non-empty`);
  for (const value of new Set([...sceneAssets, ...mainCharacters, ...linkedAssets])) {
    if (!value) continue;
    if (/^背景路人[A-ZＡ-Ｚ0-9一二三四五六七八九十]*$/.test(value)) continue;
    if (!localizedAssets.has(value) && !candidate(value)) errors.push(`${groupId}: asset is neither canonical nor marked candidate: ${value}`);
    if (candidate(value)) warnings.push(`${groupId}: candidate asset requires review: ${value}`);
  }
  const cameraView = cleanText(row.camera_view);
  if (!CAMERA_VIEWS.has(cameraView)) errors.push(`${groupId}: invalid camera_view ${cameraView}`);
  if (Array.isArray(row.warnings)) for (const warning of row.warnings.map(cleanText).filter(Boolean)) warnings.push(`${groupId}: ${warning}`);

  if (rowIndex === 0) {
    if (row.continuity_handoff !== null && row.continuity_handoff !== undefined && row.continuity_handoff !== "") errors.push(`${groupId}: first group must not own a continuity handoff`);
  } else {
    const handoff = row.continuity_handoff;
    const previousGroupId = cleanText(document.rows[rowIndex - 1]?.group_id);
    if (!handoff || typeof handoff !== "object" || Array.isArray(handoff)) errors.push(`${groupId}: missing continuity handoff`);
    else {
      const mode = cleanText(handoff.mode);
      if (!CONTINUITY_MODES.has(mode)) errors.push(`${groupId}: invalid continuity mode ${mode}`);
      else continuityModeCounts[mode] += 1;
      if (cleanText(handoff.source_group_id) !== previousGroupId) errors.push(`${groupId}: continuity source must be ${previousGroupId}`);
      if (cleanText(handoff.target_group_id) !== groupId) errors.push(`${groupId}: continuity target must match group`);
      if (rootHandoffByTarget.get(groupId) !== handoff && JSON.stringify(rootHandoffByTarget.get(groupId)) !== JSON.stringify(handoff)) errors.push(`${groupId}: row continuity handoff disagrees with root contract`);
    }
  }

  return [
    episode,
    groupId,
    `${timecode(start)}-${timecode(end)}`,
    scene,
    mainCharacters.join("、"),
    canonicalComposeShotContent(row, errors),
    cleanText(row.sound_dialogue),
    cleanText(row.chinese_dialogue),
    cleanText(row.british_localized_dialogue),
    linkedAssets.join("；"),
    cameraView,
    cleanText(row.within_group_view_change),
  ];
});

for (const [episode, duration] of durations) {
  const lastEnd = previousEndByEpisode.get(episode);
  if (lastEnd === undefined) warnings.push(`EP${episode}: no output rows`);
  else if (Number.isFinite(duration) && Math.abs(duration - lastEnd) > 0.1) warnings.push(`EP${episode}: last group ends at ${lastEnd}, duration is ${duration}`);
}

const contractMetadata = await contentContractMetadata();
const qaPath = outputPath.replace(/\.xlsx$/i, "") + ".qa.json";
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(qaPath, JSON.stringify({ schema_version: "1.0", ...contractMetadata, input: inputPath, assets: assetPath, rows: outputRows.length, continuity_boundaries: Math.max(0, outputRows.length - 1), continuity_mode_counts: continuityModeCounts, errors, warnings: [...new Set(warnings)] }, null, 2), "utf8");
if (errors.length) {
  console.error(JSON.stringify({ qa: qaPath, errors: errors.length, warnings: warnings.length }, null, 2));
  process.exit(2);
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Sheet");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.getRangeByIndexes(0, 0, 1, HEADERS.length).values = [HEADERS];
if (outputRows.length) sheet.getRangeByIndexes(1, 0, outputRows.length, HEADERS.length).values = outputRows;
const used = sheet.getRangeByIndexes(0, 0, outputRows.length + 1, HEADERS.length);
used.format = { font: { typeface: "Carlito", fontSize: 11 }, verticalAlignment: "top" };
const header = sheet.getRange("A1:L1");
header.format = { fill: "#1F4E78", font: { typeface: "Carlito", fontSize: 11, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
header.format.rowHeight = 24;
if (outputRows.length) {
  const body = sheet.getRangeByIndexes(1, 0, outputRows.length, HEADERS.length);
  body.format.wrapText = true;
  body.format.borders = { insideHorizontal: { style: "thin", color: "#D9E2F3" } };
  for (let rowIndex = 1; rowIndex <= outputRows.length; rowIndex += 2) {
    sheet.getRangeByIndexes(rowIndex, 0, 1, HEADERS.length).format.fill = "#C6E6F3";
  }
}
const widths = [8, 16, 18, 48, 44, 100, 48, 38, 48, 64, 16, 48];
for (let column = 0; column < widths.length; column += 1) sheet.getRangeByIndexes(0, column, outputRows.length + 1, 1).format.columnWidth = widths[column];
for (let rowIndex = 0; rowIndex < outputRows.length; rowIndex += 1) {
  const row = outputRows[rowIndex];
  const estimatedLines = Math.max(
    cleanText(row[3]).length / 48,
    cleanText(row[4]).length / 44,
    cleanText(row[5]).length / 50,
    cleanText(row[6]).length / 48,
    cleanText(row[7]).length / 38,
    cleanText(row[8]).length / 48,
    cleanText(row[9]).length / 64,
  );
  sheet.getRangeByIndexes(rowIndex + 1, 0, 1, HEADERS.length).format.rowHeight = Math.min(420, Math.max(60, Math.ceil(estimatedLines) * 18));
}
sheet.getRange(`A1:E${outputRows.length + 1}`).format.verticalAlignment = "top";
sheet.getRange(`K2:K${outputRows.length + 1}`).format.horizontalAlignment = "center";
sheet.getRange(`A2:C${outputRows.length + 1}`).format.horizontalAlignment = "center";
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(outputPath);

if (args.preview) {
  const preview = await workbook.render({ sheetName: "Sheet", range: `A1:L${outputRows.length + 1}`, scale: 1, format: "png" });
  await fs.mkdir(path.dirname(path.resolve(args.preview)), { recursive: true });
  await fs.writeFile(path.resolve(args.preview), new Uint8Array(await preview.arrayBuffer()));
}
const formulaErrorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(JSON.stringify({
  output: outputPath,
  qa: qaPath,
  preview: args.preview ? path.resolve(args.preview) : null,
  rows: outputRows.length,
  warnings: [...new Set(warnings)].length,
  formula_error_scan: formulaErrorScan.ndjson,
}, null, 2));

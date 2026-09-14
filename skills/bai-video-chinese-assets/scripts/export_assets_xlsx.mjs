import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith("--")) out[argv[i].slice(2)] = argv[++i];
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
if (!args.csv || !args.xlsx) throw new Error("Usage: --csv INPUT.csv --xlsx OUTPUT.xlsx [--preview OUTPUT.png]");

const csvText = await fs.readFile(args.csv, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "中文资产表" });
const sheet = workbook.worksheets.getItem("中文资产表");
const used = sheet.getUsedRange();
if (!used || used.rowCount < 1 || used.columnCount !== 5) throw new Error("CSV must contain exactly five columns");

const expected = ["资产类型", "资产中文原名", "原始中文解析描述", "角色状态中文参考描述", "出现集号"];
const actual = sheet.getRange("A1:E1").values[0].map((value) => String(value ?? "").replace(/^\uFEFF/, ""));
if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`Unexpected headers: ${JSON.stringify(actual)}`);
sheet.getRange("A1:E1").values = [actual];

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
used.format = {
  font: { typeface: "Carlito", fontSize: 10, color: "#1F2937" },
  wrapText: true,
  verticalAlignment: "top",
  borders: { insideHorizontal: { style: "thin", color: "#E5E7EB" } },
};
sheet.getRange("A1:E1").format = {
  fill: "#1F4E78",
  font: { typeface: "Carlito", fontSize: 11, bold: true, color: "#FFFFFF" },
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#17365D" },
  rowHeight: 28,
};

for (let row = 2; row <= used.rowCount; row += 1) {
  const range = sheet.getRange(`A${row}:E${row}`);
  range.format.fill = row % 2 === 0 ? "#FFFFFF" : "#D9EEF7";
  range.format.rowHeight = 42;
}

sheet.getRange(`A1:A${used.rowCount}`).format.columnWidth = 12;
sheet.getRange(`B1:B${used.rowCount}`).format.columnWidth = 24;
sheet.getRange(`C1:C${used.rowCount}`).format.columnWidth = 64;
sheet.getRange(`D1:D${used.rowCount}`).format.columnWidth = 52;
sheet.getRange(`E1:E${used.rowCount}`).format.columnWidth = 18;

const table = sheet.tables.add(`A1:E${used.rowCount}`, true, "ChineseAssetTable");
table.style = "TableStyleMedium2";
table.showFilterButton = true;
table.showBandedRows = true;

const check = await workbook.inspect({ kind: "table", range: `中文资产表!A1:E${Math.min(used.rowCount, 12)}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 5, maxChars: 6000 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);

await fs.mkdir(path.dirname(path.resolve(args.xlsx)), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(args.xlsx);

if (args.preview) {
  const preview = await workbook.render({ sheetName: "中文资产表", autoCrop: "all", scale: 1.5, format: "png" });
  await fs.mkdir(path.dirname(path.resolve(args.preview)), { recursive: true });
  await fs.writeFile(args.preview, new Uint8Array(await preview.arrayBuffer()));
}

console.log(`Saved ${args.xlsx}`);

// Render smoke for the demo page: stubs a minimal DOM, runs the page script,
// and asserts the three scenes render with badges, tables, and masked captions.
import { readFileSync } from "node:fs";

const html = readFileSync(process.argv[2], "utf-8");
const dataMatch = html.match(/<script id="demo-data"[^>]*>([\s\S]*?)<\/script>/);
if (!dataMatch) throw new Error("no demo-data script");
const source = dataMatch[1];
JSON.parse(source); // must parse as is (no entity decoding in browsers)
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const pageJs = scripts[scripts.length - 1][1];

let stagesHtml = "";
const buttons = [];
globalThis.document = {
  querySelectorAll: () => [],
  getElementById: (id) => {
    if (id === "demo-data") return { textContent: source };
    if (id === "scenes") return { appendChild: (b) => buttons.push(b) };
    if (id === "stages") return { insertAdjacentHTML: (_p, h) => { stagesHtml += h; } };
    return { classList: { add() {}, remove() {} } };
  },
  createElement: () => ({}),
};
// eslint-disable-next-line no-eval
eval(pageJs);

function assert(cond, msg) {
  if (!cond) throw new Error(`smoke: ${msg}`);
}
const sections = stagesHtml.match(/<section class="scene/g) || [];
assert(sections.length === 4, `4 scenes, got ${sections.length}`);
assert(buttons.length === 4, `4 nav buttons, got ${buttons.length}`);
assert(stagesHtml.includes(">PAID<"), "PAID badge");
assert(stagesHtml.includes(">PARTIAL<"), "PARTIAL badge");
assert(stagesHtml.includes(">not adjudicated<"), "not-adjudicated badge");
assert(stagesHtml.includes("matches the engine"), "deductible line");
assert(stagesHtml.includes("22,500"), "deductible amount");
assert(stagesHtml.includes("2,216,050 KRW"), "A amount");
assert(stagesHtml.includes("pre-existing open-source engine, pinned"), "pinned label");
assert(stagesHtml.includes("We do not have your policy"), "policy line");
assert(stagesHtml.includes("check against your passport/ID"), "PII mark");
assert(stagesHtml.includes("(masked copy)"), "masked caption");
assert(!stagesHtml.includes("# Claim decision"), "no raw markdown");
assert(!stagesHtml.includes("<iframe"), "no iframe");
const billTable = stagesHtml.match(/<table class="bill">([\s\S]*?)<\/table>/);
assert(billTable, "bill table");
const rows = billTable[1].match(/<tr>/g) || [];
assert(rows.length === 14, `12 items + header + total, got ${rows.length}`);
assert(stagesHtml.includes("15,000,000"), "pack total");
assert(stagesHtml.includes("Agent timeline"), "agent timeline");
assert(stagesHtml.includes("Step 4 — ask_user"), "ask_user step");
assert(stagesHtml.includes("cell_1=45000, cell_2=45000"), "copay answer");
console.log("demo smoke: OK (4 scenes, badges, bill table, masked captions, timeline)");

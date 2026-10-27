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
  addEventListener: () => {},
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
assert(sections.length === 5, `5 scenes, got ${sections.length}`);
assert(buttons.length === 5, `5 nav buttons, got ${buttons.length}`);
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
assert(stagesHtml.includes("Voice intake"), "voice scene");
assert(stagesHtml.includes(">work_injury<"), "work_injury badge");
assert(stagesHtml.includes("industrial accident compensation insurance first"), "next step");
assert(stagesHtml.includes("<audio"), "audio player");
assert(stagesHtml.includes("hurt my left wrist"), "en transcript");
assert(stagesHtml.includes("to confirm"), "confirmation marks");
assert(stagesHtml.includes("I heard 20 October"), "confirmation question");
assert(!stagesHtml.includes("WHO J20.9 + None"), "no None in timeline");
const headlines = stagesHtml.match(/<p class="headline">/g) || [];
assert(headlines.length === 5, `5 headlines, got ${headlines.length}`);
assert(stagesHtml.includes("Claim Pack ·"), "pack headline");
assert(stagesHtml.includes("15,000,000"), "pack headline total");
// Provenance coverage: every bare number on A/S2/S3/Agent must sit inside
// a .num span or a .noprov region. Identifiers (cell_1, row1, S72) excluded.
const SKIP_SECTIONS = new Set(["voice_factory_fall"]);
const VOID = new Set(["img", "br", "hr", "audio", "source"]);
for (const part of stagesHtml.split("<section")) {
  const idMatch = part.match(/id="([^"]+)"/);
  if (!idMatch || SKIP_SECTIONS.has(idMatch[1])) continue;
  const stack = [];
  const inProv = () => stack.some((c) => c.prov);
  const inNoprov = () => stack.some((c) => c.noprov);
  const token = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?(\/?)>|([^<>]+)/g;
  let tok;
  while ((tok = token.exec(part))) {
    if (tok[5] !== undefined) {
      if (inProv() || inNoprov()) continue;
      const bare = tok[5].match(/(?<![A-Za-z_0-9-])\d[\d,]*(\.\d+)?/g) || [];
      assert(bare.length === 0, `${idMatch[1]}: bare number ${bare[0]} in ${tok[5].trim().slice(0, 60)}`);
    } else if (tok[1] === "/") {
      stack.pop();
    } else if (tok[4] !== "/" && !VOID.has(tok[2])) {
      const attrs = tok[3] || "";
      stack.push({
        prov: attrs.includes("data-prov="),
        noprov: /class="[^"]*\bnoprov\b/.test(attrs),
      });
    }
  }
}
// Every data-prov id resolves to a record with operands that resolve too.
const payload = JSON.parse(source);
const records = {};
payload.scenes.forEach((s) => Object.assign(records, s.provenance || {}));
const refs = [...stagesHtml.matchAll(/data-prov="([^"]+)"/g)].map((m) => m[1]);
assert(refs.length > 20, `provenance spans, got ${refs.length}`);
for (const id of new Set(refs)) {
  assert(records[id], `record for ${id}`);
  for (const op of records[id].operands || []) assert(records[op], `operand ${op} of ${id}`);
}
assert(records["s2-amount"].operands.includes("s2-ded0"), "amount lights up terms");
assert(records["s2-amount"].operands.includes("s2-c1"), "amount lights up cell 1");
assert(stagesHtml.includes('tabindex="0" data-prov='), "keyboard-focusable numbers");
assert(html.includes('id="prov-panel"'), "provenance panel element");
console.log("demo smoke: OK (5 scenes, badges, bill table, masked captions, timeline, voice, provenance)");

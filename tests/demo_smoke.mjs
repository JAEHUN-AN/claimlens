// Render smoke for the demo page: stubs a minimal DOM, runs the page script,
// and asserts the six scenes render with badges, tables, and masked captions.
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
const els = {};
globalThis.document = {
  addEventListener: () => {},
  querySelectorAll: () => [],
  getElementById: (id) => {
    if (id === "demo-data") return { textContent: source };
    if (id === "scenes") return { appendChild: (b) => { if (b.tag === "button") buttons.push(b); } };
    if (id === "stages") {
      return {
        set innerHTML(v) { stagesHtml = v; },
        insertAdjacentHTML: (_p, h) => { stagesHtml += h; },
      };
    }
    if (!els[id]) els[id] = { classList: { add() {}, remove() {} } };
    return els[id];
  },
  createElement: (tag) => ({ tag }),
};
// eslint-disable-next-line no-eval
eval(pageJs + "\n;globalThis.__UI=UI;globalThis.__setLang=setLang;");

function assert(cond, msg) {
  if (!cond) throw new Error(`smoke: ${msg}`);
}
const sections = stagesHtml.match(/<section class="scene/g) || [];
assert(sections.length === 6, `6 scenes, got ${sections.length}`);
assert(buttons.length === 7, `7 nav buttons, got ${buttons.length}`);
assert(stagesHtml.includes('id="flow-view"'), "flow first screen");
assert(els["flow-steps"].innerHTML.includes("Reading"), "preselect fills steps");
assert(els["flow-play"].disabled === false, "preselect enables play");
assert(stagesHtml.includes("Want to try your own document?"), "drop zone");
assert(stagesHtml.includes("every number is clickable"), "number tip");
assert((stagesHtml.match(/class="fpick"/g) || []).length === 5, "5 example pickers");
assert(html.includes("prefers-reduced-motion"), "reduced-motion guard");
assert(html.includes("live mode needs an API key"), "unknown-file message");
assert(stagesHtml.includes(">PAID<"), "PAID badge");
assert(stagesHtml.includes(">PARTIAL<"), "PARTIAL badge");
assert(stagesHtml.includes(">not adjudicated<"), "not-adjudicated badge");
assert(stagesHtml.includes("matches the engine"), "deductible line");
assert(stagesHtml.includes("22,500"), "deductible amount");
assert(stagesHtml.includes("2,216,050 KRW"), "A amount");
assert(stagesHtml.includes("pre-existing open-source engine, pinned"), "pinned label");
assert(stagesHtml.includes("We do not have your policy"), "policy line");
assert(!html.includes("Tiếng Việt"), "no Vietnamese UI");
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
assert(stagesHtml.includes("— ask_user"), "ask_user step");
assert(stagesHtml.includes("cell_1=45000, cell_2=45000"), "copay answer");
assert(stagesHtml.includes("Voice intake"), "voice scene");
assert(stagesHtml.includes(">work_injury<"), "work_injury badge");
assert(stagesHtml.includes("industrial accident compensation insurance first"), "next step");
assert(stagesHtml.includes("<audio"), "audio player");
assert(stagesHtml.includes("hurt my left wrist"), "en transcript");
assert(stagesHtml.includes("AI reads, reasons and asks; code counts."), "product thesis");
assert(stagesHtml.includes("Muse Spark reads &amp; reasons"), "thesis strip reads");
assert(stagesHtml.includes("code counts"), "thesis strip counts");
assert(stagesHtml.includes("people decide"), "thesis strip decides");
assert(stagesHtml.includes("Reading accuracy (offline eval)"), "eval subtitle");
assert(stagesHtml.includes("Open weights match hosted on A/B"), "eval open line");
assert(stagesHtml.includes("<td>S3</td>"), "eval S3 row");
assert(stagesHtml.includes("Verify &amp; re-read"), "recovery panel");
assert(stagesHtml.includes("Corrected: line_items"), "recovery corrected");
assert(stagesHtml.includes("0/12"), "recovery before lines");
assert(html.includes("<title>ClaimLens</title>"), "tab title");
assert(html.includes('name="viewport"'), "viewport meta");
assert(html.includes('class="topbar"'), "topbar header");
assert(!stagesHtml.includes('class="brand"'), "no duplicate brand");
assert(html.includes('<svg class="mark"'), "own svg mark");
assert(html.includes('rel="icon" href="data:image/svg+xml,'), "favicon data url");
assert(!html.includes('class="lens"'), "no blue ring");
assert(html.indexOf('class="topbar"') < html.indexOf('id="scenes"'), "hero above tabs");
assert((stagesHtml.match(/>work_injury</g) || []).length === 1, "one work_injury badge");
assert(stagesHtml.includes("to confirm"), "confirmation marks");
assert(stagesHtml.includes("I heard 20 October"), "confirmation question");
assert(stagesHtml.includes("10월 20일로 들었습니다 — 맞나요?"), "ko confirmation question");
assert(!stagesHtml.includes("WHO J20.9 + None"), "no None in timeline");
const headlines = stagesHtml.match(/<p class="headline">/g) || [];
assert(headlines.length === 6, `6 headlines, got ${headlines.length}`);
assert(stagesHtml.includes("Scene Mismatch"), "mismatch scene");
assert(stagesHtml.includes("Cross-document findings"), "mismatch findings");
assert(stagesHtml.includes("NGUYEN VAN AN"), "mismatch receipt quote");
assert(stagesHtml.includes("Michael J. CARTER"), "mismatch cert quote");
assert(stagesHtml.includes(">needs review<"), "mismatch badge");
assert(stagesHtml.includes("Which patient is this claim for?"), "mismatch ask");
assert(html.includes("/api/health"), "live probe");
assert(html.includes("topnote_live"), "live topnote key");
assert(html.includes("flow_note_live"), "live flow-note key");
assert(html.includes("j.result.note"), "live result note");
assert(html.includes("live_reused"), "live reused key");
assert(stagesHtml.includes("Verification"), "verification heading");
assert(stagesHtml.includes("Scripted walkthrough"), "walkthrough heading");
assert(stagesHtml.includes("refuse → fix"), "walkthrough refusal");
assert(stagesHtml.includes("Handoff"), "handoff card");
assert(stagesHtml.includes("return with notes"), "reviewer return");
assert(stagesHtml.includes("approve: approved"), "reviewer approve");
assert(stagesHtml.includes("claims-check"), "claims check line");
assert(stagesHtml.includes("dropped — not supported by its quotes"), "claims drop line");
assert(stagesHtml.includes("Claim Pack ·"), "pack headline");
assert(stagesHtml.includes("15,000,000"), "pack headline total");
// Provenance coverage: every bare number on A/S2/S3/Agent must sit inside
// a .num span or a .noprov region. Identifiers (cell_1, row1, S72) excluded.
const SKIP_SECTIONS = new Set(["voice_factory_fall"]);
const VOID = new Set(["img", "br", "hr", "audio", "source"]);
for (const part of stagesHtml.split("<section")) {
  const idMatch = part.match(/id="([^"]+)"/);
  if (!idMatch || SKIP_SECTIONS.has(idMatch[1])) continue;
  const body = part.split('<div id="flow-view">')[0]; // stub appends flow-view last
  const stack = [];
  const inProv = () => stack.some((c) => c.prov);
  const inNoprov = () => stack.some((c) => c.noprov);
  const token = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?(\/?)>|([^<>]+)/g;
  let tok;
  while ((tok = token.exec(body))) {
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
assert(html.includes("--paper"), "design tokens");
assert(html.includes("prefers-color-scheme"), "dark mode stays readable");
assert(html.includes("max-width:640px"), "phone layout");
assert(html.includes("data-goto"), "panel lists related values");
assert(html.includes("scrollIntoView"), "related values scroll to target");
// Item 25/30: UI chrome switches between en/ko; document contents stay.
assert(html.includes('id="langswitch"'), "language switcher");
const uiKeys = Object.keys(globalThis.__UI);
assert(uiKeys.length > 50, `UI keys, got ${uiKeys.length}`);
for (const k of uiKeys) {
  const row = globalThis.__UI[k];
  assert(Array.isArray(row) && row.length === 2, `UI row ${k} has 2 langs`);
  assert(row.every((v) => typeof v === "string" && v.length > 0), `UI row ${k} non-empty`);
}
globalThis.__setLang("ko");
assert(stagesHtml.includes("청구 처리"), "ko flow header");
assert(stagesHtml.includes("장면 A"), "ko scene title");
assert(stagesHtml.includes("확인 필요"), "ko to-confirm tag");
assert(stagesHtml.includes("판독 정확도 (오프라인 평가)"), "ko eval subtitle");
assert(!stagesHtml.includes("Process a claim"), "flow re-rendered, not appended");
assert(!stagesHtml.includes("Scene S2 — insured worker"), "scene re-rendered, not appended");
assert((stagesHtml.match(/<section class="scene/g) || []).length === 6, "still 6 scenes");
assert(stagesHtml.includes("장면 Mismatch"), "ko mismatch title");
assert((stagesHtml.match(/id="flow-view"/g) || []).length === 1, "single flow card");
globalThis.__setLang("en");
assert(stagesHtml.includes("2,216,050 KRW"), "amounts unchanged by switch");
console.log("demo smoke: OK (6 scenes, badges, bill table, masked captions, timeline, voice, mismatch, provenance)");

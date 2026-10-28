// Fault smoke: with the network down, the live page shows the error
// and never a stale result. Usage: node tests/fault_smoke.mjs docs/demo.html
import { readFileSync } from "node:fs";

const html = readFileSync(process.argv[2], "utf-8");
const dataMatch = html.match(/<script id="demo-data"[^>]*>([\s\S]*?)<\/script>/);
const source = dataMatch[1];
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const pageJs = scripts[scripts.length - 1][1];

const els = {};
function el(id) {
  if (!els[id]) {
    els[id] = { innerHTML: "", value: "", textContent: "",
      classList: { add() {}, remove() {}, toggle() {} },
      style: {}, appendChild() {}, scrollIntoView() {} };
  }
  return els[id];
}
globalThis.document = {
  addEventListener: () => {},
  querySelectorAll: () => [],
  querySelector: () => null,
  getElementById: (id) => {
    if (id === "demo-data") return { textContent: source };
    if (id === "scenes") return { appendChild: () => {}, setAttribute: () => {} };
    if (id === "stages") {
      return { set innerHTML(v) {}, insertAdjacentHTML: () => {} };
    }
    return el(id);
  },
  createElement: (tag) => ({ tag }),
  documentElement: { lang: "" },
};
globalThis.window = { matchMedia: () => ({ matches: false }) };
globalThis.location = { protocol: "http:" };
// Network down: every fetch rejects. FileReader "reads" one fake file.
globalThis.fetch = () => Promise.reject(new Error("network down"));
globalThis.FileReader = class {
  readAsDataURL() {
    this.result = "data:image/jpeg;base64,AA==";
    this.onload();
  }
};

function assert(cond, msg) {
  if (!cond) throw new Error(`fault smoke: ${msg}`);
}
// eslint-disable-next-line no-eval
eval(pageJs + `
;LIVE=true;
globalThis.__fault = (async () => {
  // A stale result from an earlier run must not survive a failed run.
  document.getElementById('flow-result').innerHTML = '<p class="amount">STALE</p>';
  await liveDrop({dataTransfer: {files: [{name: 'x.jpg'}, {name: 'y.jpg'}]}});
  await new Promise((r) => setTimeout(r, 50));
  return {
    msg: document.getElementById('flow-msg').textContent,
    result: document.getElementById('flow-result').innerHTML,
    steps: document.getElementById('flow-steps').innerHTML,
  };
})();
`);
const out = await globalThis.__fault;
assert(out.msg.startsWith("Live run failed: "), `error shown, got ${JSON.stringify(out.msg)}`);
assert(out.msg.includes("network down"), "cause shown");
assert(out.result === "", `no stale result, got ${JSON.stringify(out.result)}`);
assert(out.steps === "", "no stale steps");
console.log("fault smoke: OK");

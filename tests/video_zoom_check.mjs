import { readFileSync } from "node:fs";

// Stub browser globals; overlay_fx only touches document at load time,
// and __zoomFit is pure (no DOM needed).
globalThis.window = {};
globalThis.document = { getElementById: () => null, addEventListener: () => {} };
const src = readFileSync(new URL("../docs/video/overlay_fx.js", import.meta.url), "utf8");
eval(src);

const fit = globalThis.window.__zoomFit;
const close = (a, b) => Math.abs(a - b) < 1e-6;
function assert(cond, msg) {
  if (!cond) {
    console.error(`FAIL: ${msg}`);
    process.exit(1);
  }
}

assert(typeof fit === "function", "__zoomFit is exposed");
// Verify-like: a wide centered box shrinks until it fits with margin.
assert(close(fit(640, 360, 1000, 300, 1.5, 1280, 720, 24), (640 - 24) / 500), "wide box shrinks");
// A small box keeps the requested scale.
assert(close(fit(640, 360, 200, 100, 1.6, 1280, 720, 24), 1.6), "small box keeps scale");
// An edge box floors at 1 instead of cropping.
assert(close(fit(1200, 360, 400, 100, 2, 1280, 720, 24), 1), "edge box floors at 1");
// Missing dims (old callers) keep the requested scale.
assert(close(fit(640, 360, 0, 0, 1.6, 1280, 720, 24), 1.6), "no dims keeps scale");
console.log("zoom fit: OK");

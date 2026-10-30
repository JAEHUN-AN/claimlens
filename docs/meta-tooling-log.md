# Meta tooling log

Dated record of what Meta tooling (Muse Code, Muse Spark) did for ClaimLens.
Judged under "Use of Meta AI Tooling": everything below was produced with Meta
tools during the hackathon. All documents read are synthetic samples.

## 2026-10-27 — Day 1: skeleton and the first Spark reads

### Muse Code (coding agent)

- Project skeleton: `pyproject.toml` (Python 3.12+, `uv`, src layout), `ruff`,
  `pytest`, `claimlens` CLI entry point. Small modules, each under ~200 lines.
- Reading schema (`src/claimlens/schema.py`, SPEC 3.1): documents in image order,
  doc type, country, currency, total, line items with the 13 closed categories,
  diagnoses with code and code system, PII fields; plus `strict_schema_of()`
  (SPEC 3.2) which turns a pydantic model into the strict JSON Schema form
  (root object, `additionalProperties: false` everywhere, every key required,
  nullable via `anyOf`, `$ref`s inlined).
- Korean bill schema (`src/claimlens/kr_bill.py`, SPEC 3.4): cells 1-10 as
  nullable integers, the institution checkbox as a 4-value enum, patient type
  text. Attached as `kr_bill` on receipt documents.
- Meta provider (`src/claimlens/providers/meta.py`): `muse-spark-1.3` over
  `POST /v1/responses` with two images per request (receipt + certificate, in
  order), images downscaled to 1280 px JPEG, `html.unescape` before validation,
  usage tokens recorded per call.
- Replay cache (`src/claimlens/cache.py`): raw responses under `cache/` keyed by
  sha256 of prepared image bytes + instructions + schema + model; with
  `CLAIMLENS_PROVIDER=replay` tests and the demo run with no key.
- CLI (`src/claimlens/cli.py`): `claimlens read <sample-folder>
  [--variant photo|clean]` prints the parsed JSON plus the receipt checks.
- Receipt arithmetic check (`src/claimlens/checks.py`, SPEC 5.6): recomputes
  cells 6, 7, 8, 10 from the read cells, each reported pass/fail.
- Tests: replay-mode reads (A_niseko_wrist total JPY 235,000, two documents in
  order; S2 cells + 종합병원 checkbox; S2 checks pass) and pure arithmetic
  tests (pass on S2 cells, fail when one cell is altered or missing).

### Muse Spark (model API)

- Live reads: 2 calls to `muse-spark-1.3` (A_niseko_wrist photo pair, S2 photo pair).
  A: two documents in order, total JPY 235,000. S2: cells 1-10 and the 종합병원 checkbox,
  receipt checks 6/7/8/10 all pass. 3,785 input / 976 output tokens for A.
  These two calls were run by the owner from a normal terminal: Muse Code's Windows
  sandbox could not spawn a shell on this machine (local banking-security software
  blocked the sandboxed PowerShell launch). The responses are in `cache/` and the
  replay tests (9) pass.
- Cost: about $0.02 today (Meta free credits).
- Verification (Muse Code, same day): replay suite passes 9/9 against the
  recorded responses with no key. Two live probe re-reads (scratch cache dir,
  discarded) returned identical input tokens (A 3,785, S2 3,567) and
  re-verified outputs (JPY 235,000; S2 cells + 종합병원 + checks pass); probe
  cache keys matched the committed filenames exactly, proving this code
  reproduces the recorded requests bit-for-bit. Day-1 total: 4 Spark calls,
  20,503 tokens. (The working-tree `cache/` was nevertheless overwritten by a
  re-read at 09:26 KST; it was reverted so the committed first recordings stay
  the replay source.)

## 2026-10-27 — Day 2: inpatient bill, verify loop, eval, eligibility

### Muse Code (coding agent)

- Part 1, Scene 3 bill (`kr_bill.py`, `schema.py`, `prompts.py`, `checks.py`):
  visit checkbox (외래/입원), treatment period, charge rows with four nullable
  columns, KCD system plus final-diagnosis flag on certificates; new
  `rows_sum_1..4` checks next to 6/7/8/10. Replay tests for S3 (KRW
  15,000,000, 12 rows, 상급종합병원, S72.120, checks pass) and extended S2
  coverage (visit, period, rows, final flag).
- Part 2, verify-and-re-read (`verify.py`, SPEC 5.6): on any failed check, one
  narrow re-read naming only involved cells with a tiny strict schema, merge
  only fresh values (never arithmetic), then `verified` or `needs_manual_check`.
  Providers accept `result_model`; replay logs usage per call. Stub-provider
  tests for fix and still-wrong paths, both with 2 logged calls.
- Part 3, measurement (`eval.py`, `cli.py`): `claimlens eval` reads all 5
  samples by photo/clean (replay first, live only for missing cache entries)
  and prints a Markdown accuracy table (docs, currency, total, lines, amounts,
  diags, KR cells, institution, checks, PII, calls, tokens, cost).
- Part 4, eligibility (`eligibility.py`, SPEC 3.5): pure `check_eligibility`
  with 3 outcomes, rule id and English basis; 7 row tests (S2 member via
  workplace, S3 unknown via short stay).
- Tests: 32 passed (`ruff check` clean before each commit). No push.

### Muse Spark (model API)

- Live calls: 14 to `muse-spark-1.3` (7 in Part 1 including 4 discarded
  intermediates, 7 in eval for the missing variants; Parts 2 and 4 used no
  live calls). Committed cache (10 files): 38,179 input / 17,870 output /
  56,049 total tokens. Discarded intermediates: about 15,162 / 7,643 / 22,805
  (one output estimated; the file was deleted before its usage was logged).
  Day-2 total about 78,854 tokens.
- Cost: 14 calls at $0.006-0.009 each, about $0.08-0.13, under the $1 budget
  (Meta free credits). No per-token rates are configured, so stored `cost_usd`
  is null and eval prints "-" for cost.
- What failed: S2 re-record 1 returned null for blank row cells (prompt said
  blank means null); fixed to blank means 0 for charge rows. Re-record 2
  included the 합계 total row in `charge_rows` (sums doubled); fixed to exclude
  it. Eval is honest about two misses: S3 clean has 0/12 line items (model
  omitted the redundant list; 12 charge rows and all cells pass) and S3 photo
  PII is 3/4 (passport off by one zero; clean is 4/4). Both were kept, not
  re-recorded.

## 2026-10-27 — Backlog session: eval file and engine connection

Backlog items 1, 2 and 4 already met their done-when on Day 2; this session
closed item 3 and item 5. Boxes stay unchecked for the owner to tick on push.

### Muse Code (coding agent)

- Item 3 remainder: `claimlens eval --output` writes the Markdown table with a
  header; `docs/eval.md` generated from replay (5 samples x 2 variants).
- Item 5, engine connection: `clausegraph[graph]` pinned to tag
  `claimlens-base-20261026` (commit a7f6b9a...; archive URL, same commit —
  sandbox git TLS is broken, equivalent git+ URL noted in pyproject).
- New `src/claimlens/engine.py` (SPEC 3.3): categorical Korean narrative from
  the 13 closed categories, demo-FX conversion to KRW (fails on unknown
  currency), institution through `parse_institution`, copay 1/(1+2) through
  `parse_copay_rate`, eligibility gate first (S3 not sent), data-root chdir
  only for the call, driver open/close per call, outputs cached under
  `cache/engine/` with input verification on replay load.
- New `claimlens adjudicate <sample-id> [--variant]` printing the envelope.
- Tests: 43 passed. Replay pins A PAID 2216050, S2 PARTIAL 22500,
  B HUMAN_REVIEW (guardrail uncertain_exclusion), C DENIED, S3 not sent.

### Live runs (owner, normal terminal) and sandbox blockers

- Spark calls this session: 0 ($0). Engine readings come from the pinned
  replay cache, so adjudication costs no model calls.
- The 5 live adjudications were run by the owner from a normal terminal; all
  matched the backlog targets. The sandbox cannot open loopback sockets, so
  Neo4j at localhost:7688 was unreachable from here (WinError 10013).
- `uv add` via git+https failed the same way (git.exe TLS); the tag was
  resolved to a7f6b9a over the API and installed from the commit archive.
- The sandbox user cannot delete owner-created `.venv` files, so `uv sync`
  fails removing the editable `.pth`; deps were locked with `uv lock` and
  installed with `uv pip install` (new files only, versions match the lock).
  All sandbox runs used `uv run --no-sync`. Normal terminals are unaffected.
- Owner fix kept: `[tool.hatch.metadata] allow-direct-references = true`,
  needed for the direct-URL dependency at build time.

## 2026-10-27 — Backlog session: review fixes and code conversion

Items 0 and 7. The review premise checked out with one correction: S3 clean
had 0 line items but 12 charge rows, so the gap was line-item coverage, not
the row sums (those already fail on empty rows).

### Muse Code (coding agent)

- Item 0a: new `lines_present` / `lines_count` / `lines_sum` checks for Korean
  receipts. Line amounts are per-row totals, so the sum compares against cell 6
  (this first broke S2, whose line sum is 90,000 against a 45,000 patient
  total, and was corrected). Verify went receipt-level with a line-item
  re-read path (tiny schema carries the item table); `claimlens read` now
  reports a verification block. Replay test pins the S3 clean recovery.
- Item 0b: eval loaded `.env` only on the live path, so replay costs were
  null; rates now load up front and `docs/eval.md` shows $0.0090-0.0171.
- Item 7: new `src/claimlens/codes.py` (SPEC 5.5) — KCD normalize/edition,
  U-code refusal, WHO truncation, fracture open/closed attribute, I84 to K64,
  CM candidates with FY2027 defaults plus narrowing questions, and the
  three-row prefix pitfall table. Limits: no WHO 2019 terminal list locally,
  so no general terminal check; the 254-code fracture set is a documented
  family heuristic; CM rules shipped for S72.1 only; HIRA English names are
  out of scope.
- Tests: 65 passed (`ruff check` clean before each commit). No push.

### Muse Spark (model API)

- Live calls: 1 narrow re-read (S3 clean item table, single receipt image):
  1,846 input / 1,217 output tokens, about $0.008. It returned all 12 rows
  summing to 15,000,000, so the reading verified with `corrected:
  ["line_items"]` instead of ending in manual review. Session total $0.008.

## 2026-10-27 — Backlog session: I84 fix, rationale, Claim Pack

Items 0b, 6, and 8.

### Muse Code (coding agent)

- Item 0b: I84.x now maps to bare K64 with "subdivision must be re-coded
  from the certificate" (subdivisions do not correspond across the move).
  Audit: truncation is the WHO-endorsed rule and K35 only warns, so no
  other chapter-move rule needed the same treatment.
- Item 6: new `src/claimlens/rationale.py` plus `claimlens rationale`.
  The model rephrases engine text under a strict schema (summary, per-step
  lines, cited clause IDs); code copies amounts, step names, and clause IDs
  and rejects any number or ID the engine did not emit. The text-only
  provider path now records cache and usage like the reading path, so both
  drafts replay offline. A and S2 cards render from replay.
- Item 8: new `src/claimlens/claimpack.py` plus `claimlens claimpack
  --format md|html`. Only `not_member_or_unknown` cases are accepted. One
  strict-schema call translates the 12 row labels; amounts, codes, and dates
  come from the reading by code. The pack carries the policy line, codes
  with the CM pitfall warning, the itemized bill with check status, the
  checklist, deadlines, and the translation disclaimer. Fixed while here:
  the HTML renderer silently returned only its first chunk (an unparenthesized
  multi-line return); a test now pins the closing tag.
- Tests: 76 passed (`ruff check` clean before each commit). No push.

### Muse Spark (model API)

- Live calls: 3 text-only writes, 1,184 input / 3,668 output tokens total
  (A rationale 523/1,648; S2 rationale 540/1,174; S3 labels 121/846).
  Session total about $0.02-0.03.

## 2026-10-27 — Backlog session: PII marks, deductible check, masking

Items 0c and 9.

### Muse Code (coding agent)

- Item 0c-a: every pack PII line with a value now ends in "check against
  your passport/ID" (Markdown and HTML). A new cross-document check collects
  each PII kind per document; conflicting values print both readings with a
  "differs between documents" flag instead of one as if certain. S3 replay
  test pins four marks.
- Item 0c-b: S2 rationale cards carry a deductible section computed by code
  from engine inputs (flat 20,000/10,000 by institution, 20% of claimed,
  claimed times copay rate). The card shows
  "max(20,000, 9,000, 22,500) = 22,500 — matches the engine"; a mismatch
  would show both figures flagged while the engine amount stands. Travel
  cards have no such section. Tests pin the match, the absence, and the
  mismatch branch.
- Item 9: new `src/claimlens/masking.py` plus `claimlens mask`. One noun
  phrase per SAM 3.1 request over the same responses endpoint; box tags
  parsed in both the recorded `key=value` form and the bare six-number
  form; filled boxes painted on a copy scaled from the tag w/h. Responses
  cached under `cache/sam/` by image bytes, phrase, and model. S2 seal
  (receipt photo) and S3 signature (cert clean) mask from replay; after
  images saved to `docs/masking/` (before images are the samples; working
  copies live in git-ignored `out/masking/`). Text-field PII stays in
  reading results and never enters the image path, so no redaction code
  was added.
- Tests: 87 passed (`ruff check` clean before each commit). No push.

### Muse Spark and SAM (model APIs)

- SAM live calls: 6. S2 receipt clean returned empty text three times for
  "red circular seal" (raw SSE confirmed genuinely empty, not a parse
  miss) plus once for "red seal", against the 10/26 probe record; the
  photo variant succeeded first try, so the S2 seal pins the photo. S3
  "signature" succeeded first try. The stream reports no usage block, so
  only the call count is recorded; cost is within the $1 session budget
  on Spark-equivalent rates.

## 2026-10-27 — Backlog session: replay demo and Spark Open step

Items 10 and 11.

### Muse Code (coding agent)

- Item 10: new `claimlens demo` exporting self-contained `docs/demo.html`
  from replay caches only (no key, no Neo4j, no external requests — the
  test asserts no `https://` in the bytes). Three scene tabs with reading
  check marks, eligibility, the engine card labelled "pre-existing
  open-source engine, pinned" or the Claim Pack in an iframe, plus sample
  and masked images by relative path. The embedded script passed a Node
  DOM-harness smoke (init, three scenes rendered, tab toggle).
- Item 11: new Baseten provider on exactly
  `meta-models/muse-spark-open-1026` via Chat Completions with a forced
  `submit_labels` tool call (no JSON mode). The S3 row-label step runs on
  both models from replay caches; `claimlens eval` appends a one-row
  comparison section to `docs/eval.md`: 8/12 identical, the four diffs all
  legitimate phrasing variants (room fee/fee, Treatment/Procedure, Lab
  test/Examination, charge/cost).
- Tests: 92 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: 1 Baseten tool-calling request (797 input / 240 completion
  tokens, reasoning empty on this response) on granted credits. Spark: 0.

## 2026-10-27 — Backlog session: demo browser fix and README final

Items 0d and 12.

### Muse Code (coding agent)

- Item 0d: `demo_template.py` emitted the payload through `html.escape`,
  so real browsers threw on `JSON.parse` and rendered nothing (script text
  is not entity-decoded). It now emits raw `json.dumps` with only `</`
  neutralized; the test parses the script text as is, with no unescaping.
  `docs/demo.html` regenerated. The owner re-checks in a real browser.
- Item 12: README final — what it does, 60-second offline run, the
  built-vs-pre-existing table, which Meta model does which step, the eval
  table, limitations. Every command in it was verified under
  `CLAIMLENS_PROVIDER=replay` with no keys.
- Fixed while verifying: `claimpack --format html` crashed on cp949
  consoles (em-dash in the pack). All CLI text output now goes through
  `_emit`, which falls back to a stderr note when the console cannot
  encode the text; the `--output` file contract is unchanged.
- Tests: 94 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: 0 ($0). Everything verified from replay caches.

## 2026-10-27 — Backlog session: README gaps and demo polish

Items 13 and 14.

### Muse Code (coding agent)

- Item 13: README model table now leads with the Muse Code row (wrote the
  code from the backlog; owner reviewed and ran live/engine calls) linking
  the tooling log as the main "Use of Meta AI Tooling" evidence; added the
  SAM limitation (S2 seal found on photo, not on clean after four attempts,
  so the demo masks the photo variant).
- Item 14: demo page polish. The rationale card renders as HTML (badge,
  large amount, steps, cited clauses, deductible line) instead of raw
  Markdown; each scene is a two-column layout (document images left with
  masked-copy captions, results right); check marks are a compact strip;
  the Claim Pack is a styled panel (cover, patient/visit, codes, itemized
  bill table, checklist, deadlines) instead of a bare iframe. Payloads are
  structured (no Markdown/HTML blobs); all numbers still come from the
  replay caches. `docs/demo.html` regenerated; the owner checks it in a
  real browser.
- New `tests/demo_smoke.mjs` render harness, run by pytest when `node`
  exists (skipped otherwise): 3 scenes, PAID/PARTIAL/not-adjudicated
  badges, 12-row bill table, deductible match, masked captions, no raw
  Markdown, no iframe. Windows `\\?\` paths are stripped for node.
- Tests: 95 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: 0 ($0). Everything verified from replay caches.

## 2026-10-27 — Backlog session: clarifying agent and voice intake

Round 2 items 15 and 17.

### Muse Code (coding agent)

- Item 15: new `src/claimlens/agent.py` — a tool-calling loop on hosted
  `muse-spark-1.3` (Responses API tools work; only `tool_choice: "auto"`
  is accepted). Eight tools: read documents, run checks, re-read cells,
  decide eligibility, convert codes, adjudicate (replay cache), build
  Claim Pack, ask_user(question, why_needed). Hard step cap of 12; unknown
  tools and crashes become error results. Recorded dialogue: S2 with copay
  cells hidden → read, checks, eligibility, ask_user for cell_1/cell_2 with
  the reason, codes, adjudicate → PARTIAL ₩22,500. The trace renders in
  `docs/demo.html` as a step-by-step timeline (4th scene). First recording
  failed: the adjudicate tool demanded sum_insured, which the engine never
  needed (its recording has null); the check now matches the engine.
- Item 17: new `src/claimlens/voice.py` — ASR (`muse-voice-transcribe-1.0`,
  multipart, stdlib only) plus Spark fact extraction with per-fact quotes
  (separate required quote_* fields; a quotes dict came back empty twice).
  WAVs are converted to mono s16le 24 kHz in code (the clips are 22050 Hz).
  Both clips transcribed and cached; en facts match the truth, work_injury
  with "industrial accident compensation insurance first". 5th demo scene
  with audio players, transcripts, and the fact/quote table.
- Two ASR findings: the endpoint is not deterministic (same clip returned
  October 21, then July 21 for the ko date), so transcripts are never
  re-recorded; the ko clip needs re-synthesis ("10월 20일" heard as 21st,
  E-9 read letter by letter), which the owner will do — the ko test pins
  the injury path only until then. Re-synthesis from the sandbox failed
  (SAPI blocked, no loopback for edge-tts).
- Tests: 105 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: Spark 15 (2 tool probes, 11 + 7 agent turns across two
  recordings, 6 fact extractions across three), about $0.10; ASR 3
  (1 probe, 2 clips; no usage block). Session total about $0.10-0.15.

## 2026-10-27 — Backlog session: voice confirmation and Spark Open reads

Round 2 items 17b and 16.

### Muse Code (coding agent)

- Item 17b: re-transcribed the owner's re-synthesized ko clip (24 kHz
  mono, spelled-out date; en recording untouched) — incident date now
  2026-10-20, matching the truth. Heard date/visa/number-like facts are
  marked `needs_confirmation` with quoted words; `intake()` returns
  ask_user-shaped confirmations ("I heard 20 October — is that right?")
  to be asked before use. The work_injury outcome stands. Demo voice
  scene shows "to confirm" tags plus the questions; agent timeline hides
  None parts ("WHO J20.9" instead of "WHO J20.9 + None; CM None").
- Item 16: `BasetenProvider.read_documents` runs the full reading on
  `meta-models/muse-spark-open-1026` (forced `submit_reading` tool call,
  images as data URLs, latency recorded). All 5 samples x 2 variants
  cached; `claimlens eval` gained the open column set (total, lines,
  checks, tokens with reasoning, latency ms, cost) next to hosted Spark.
  Checks and the verify loop run on either model (same provider shape;
  a stub re-read verifies the open S2 reading in tests).
- Open vs hosted: match on A/B (both variants) and all S2/S3 cells;
  short on C photo total (0 vs 3,200), S2 line amounts at half value,
  S3 photo 13 charge rows (summary row included); open wins S3 clean
  12/12 where hosted base has 0/12. README states this plainly.
- Tests: 112 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: ASR 1 (ko re-transcription), Spark 1 (ko facts),
  Baseten 10 (all open readings, $0 on granted credits; no rates
  configured so open cost shows `-`). Session total about $0.01.

## 2026-10-27 — Backlog session: pack language and final polish

Round 2 items 18 and 20 (19 waits on owner phone-photo files).

### Muse Code (coding agent)

- Item 18: new `src/claimlens/packlang.py` — one strict-schema call
  translates the 12 row labels plus 33 pack sentences into Vietnamese;
  amounts, codes, and dates stay copied by code. `build_pack(...,
  lang="vi")` and `claimlens claimpack --lang vi` render Markdown and
  HTML (`<html lang="vi">`); English output is unchanged (existing tests
  pin the wording).
  S3 pack recorded in English + Vietnamese from replay.
- Item 20: README refresh — five scenes, agent loop and Voice Transcribe
  rows in the model table, agent/voice/pack-language rows in the
  built-vs-pre-existing table, Vietnamese pack command. Demo polish:
  every scene opens with a result headline (badge + amount above the
  fold), document images capped to fit 720p, timeline type up to
  0.95rem with roomier lines, one shared h4 scale. `docs/demo.html`
  regenerated; the owner checks it in a real browser.
- Tests: 116 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: Spark 1 (Vietnamese pack translation, about $0.01).

## 2026-10-27 — Backlog session: provenance and product flow

Round 3 items 21 and 22.

### Muse Code (coding agent)

- Item 21: new `src/claimlens/provenance.py` — every demo number on
  A/S2/S3/Agent carries a record (reading, check, clausegraph, rule,
  user) built in Python where the number is produced, with source text
  and, for checks, the formula plus operand ids. Clicking PARTIAL
  22,500 lights up the deductible terms, cells 1-2, the copay formula,
  and the matched engine line. Keyboard-focusable spans, Esc closes.
  Model prose, PII, dates, and the voice scene stay out of scope and
  are marked noprov. Tests: payload reference integrity plus a render
  harness asserting no bare number is missing a record. The owner
  checks the panel in a real browser.
- Item 22: the demo opens on a guided flow — pick one of five samples
  (or drop a photo, which answers "live mode needs an API key — run
  `claimlens` locally"), play the recorded pipeline steps lighting up
  one by one, then land on the result card with a link to the full
  example. Step badges show recorded tokens (or "deterministic");
  durations do not exist in the recordings and are not invented —
  per-step latency is future work. prefers-reduced-motion plays
  instantly. The owner plays all five in a real browser at 1280x720.
- Tests: 119 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: 0 ($0). Everything from replay caches.

## 2026-10-27 — Backlog session: desk design and agent scorecard

Round 3 items 23 and 24.

### Muse Code (coding agent)

- Item 23: "document desk" design system — paper background with a
  CSS-only texture, ink text, tabular monospace for amounts and codes,
  highlighter "to confirm" marks, green/red check ticks, rubber-stamp
  decision badges, shadowed document photos. Colors and type scale are
  CSS custom properties; dark mode stays readable; 640px breakpoint
  stacks the grids. The provenance panel now lists related values
  (each clickable to scroll to it) and check formulas. The owner
  checks 1280x720 and 375px widths.
- Item 24: `claimlens agent-eval` runs 8 scripted cases (hidden copay,
  complete S2/A/S3, hidden enrolment, hidden fracture side, voice
  confirmation, contradictory answer) and saves `docs/agent-eval.md`,
  linked from the README. Agent fixes along the way: ask only on
  tool-reported missing (never to refine completed conversions),
  convert-first ordering, traveller pack refusal at the tool, enrolled
  and laterality answers parsed, contradictory cells rolled back with
  a retry. All 8 replay green: asked-when-needed, no needless
  questions, no invented numbers.
- Cache lesson: scorecard cases sharing one history key overwrote each
  other's turn caches (call_ids diverged, replays took wrong paths).
  Model-turn keys now carry a case namespace. Two recordings were
  thrown away learning this.
- Tests: 122 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: Spark about 120 agent turns across 4 recordings
  (3 discarded: prompt fixes, namespace lesson), about $0.40.

## 2026-10-27 — Backlog session: final touches

Round 3 item 27.

### Muse Code (coding agent)

- (a) First screen: product name, the "crosses borders" tagline, and a
  Read → Verify → Decide-or-pack strip above the sample picker; the
  page title drops "replay demo" (replay stays a small note).
- (b) Honest scorecard notes in `docs/agent-eval.md` and the README:
  each case is one recorded dialogue replayed, and
  confirm-voice-date is the voice-intake rule, not the agent loop.
- (c) Vietnamese pack stay line now uses the translated "to" (đến);
  the pack translation was re-recorded for the new sentence key.
- (d) Voice scene keeps one `work_injury` badge (headline only).
- Tests: 122 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: Spark 1 (Vietnamese pack re-translation, about $0.01).

## 2026-10-27 — Backlog session: Meta-inspired visual style

Round 3 item 28. The owner restyled `demo_template.py` first (light
palette, sticky topbar, pill chips, tab highlight); the agent completed
the item on top: tab title "ClaimLens", removed the duplicate brand
line in the flow hero (topbar keeps the single product name above the
tabs, tagline and strip stay), and calm button/step transitions. No
Meta logo, infinity symbol, wordmark, or font; palette and cards are
inspired-by only.

### Muse Code (coding agent)

- `demo.py` `_rel` now strips the Windows extended-length (`\\?\`)
  prefix before `relpath`, so exports work when the shell reports
  extended paths (same location, previously a hard failure).
- Smoke harness asserts the tab title, topbar, hero-above-tabs order,
  and no duplicate brand.
- Tests: 122 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: own mark, UI language switch, MCP server

Round 3 items 29, 25, 26.

### Muse Code (coding agent)

- Item 29: the blue ring is now our own inline-SVG mark (a lens over
  a document corner) in the accent colour, shared by construction
  with the favicon data URL. Harness asserts the mark, the favicon,
  and no ring.
- Item 25: demo chrome (labels, step names, buttons, tagline, section
  headers, provenance labels — not document contents) switches
  between English, Korean, and Vietnamese from a topbar switcher;
  the page re-renders in place. Harness checks every UI row has
  three non-empty entries and renders ko/vi. Phone layout unchanged
  (375 px media query, wrapping topbar).
- Item 26: new `claimlens mcp` serves read_documents, run_checks,
  decide_eligibility, convert_codes, adjudicate, and
  build_claim_pack over stdio JSON-RPC with no extra dependencies;
  every result carries provenance records. A client test lists and
  calls all six tools in replay mode.
- Tests: 131 passed (`ruff check` clean before each commit). No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: language-switch re-render fix

Round 3 item 25b. The owner found in Edge that `render()` cleared the
nav but appended stages, so stale English copies stayed visible and a
second flow card survived tab switches. The fix clears `#stages` on
every render and hides the provenance panel; `hideProv` is now
null-safe for the Node stub.

### Muse Code (coding agent)

- New `tests/test_browser_lang.py` (Playwright, Edge `msedge`
  channel): clicks the ko/vi switcher, opens all five scenes, and
  asserts translated chrome, no stale English UI strings, and
  exactly one visible view. The Node harness now models the stages
  clear and asserts single copies too.
- `playwright` added as a dev dependency (no browser download; uses
  installed Edge).
- Tests: 131 passed in the sandbox plus 2 browser tests run by the
  owner in a normal terminal (sandbox blocks the loopback sockets
  Playwright needs). `ruff check` clean. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: AX and product tracks P0+P1

`docs/track-ax-p0p1.md` (AX-1..AX-4) and `docs/track-product-p0p1.md`
(P-1..P-3), implemented from the sibling session's specs.

### Muse Code (coding agent)

- AX-1: flow view preselects A on every render (steps shown, Play
  enabled, `.fpick.active` ring); no autoplay, reduced-motion intact.
- AX-2: `tip_numbers` hint line under the flow note (en/ko/vi).
- AX-3: drop-zone copy replaced with the expectation-setting text;
  drop behaviour and `live_msg` unchanged.
- AX-4: `@media print` (chrome hidden, light vars forced,
  break-inside avoids, smaller doc images). Manual check by owner.
- P-1: `intake(..., lang)`, `confirmations_for(facts, lang)`,
  `heard_as(field, value, lang)`; ko clip asks in Korean from `facts`
  values, en unchanged, other langs raise (no vi clip).
- P-2: flow view embeds a 5-row photo eval table plus open-weights
  and footnote lines from `eval_all()`; the open line is generated
  from the rows' `open_*` fields per owner answer
  ("differ on C total, S2 checks, S3 checks"); headers switch en/ko/vi.
- P-3: S3 pack panel gains an EN | Tiếng Việt toggle reusing the
  `.langswitch` style; vi swaps recorded labels/sentences while
  amounts, codes, dates, and provenance ids stay identical.
- Tests: 132 passed in the sandbox plus 2 browser tests run by the
  owner in a normal terminal. `ruff check` clean. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: demo is English + Korean only

Round 3 item 30 (owner decision). The Vietnamese UI switch and the S3
EN | Tiếng Việt pack toggle did not fit the scenes, so they are out
of the demo: the topbar switcher is EN/한국어, UI rows are [en, ko],
and the pack panel renders one language again (the VI overlay,
toggle, and helpers are gone from template and payload). The demo UI
is English/Korean; `packlang.py`, `claimlens claimpack --lang vi`,
and its recorded translation stay as a library/CLI feature.

### Muse Code (coding agent)

- Browser test covers ko (+en default, asserting the two-button
  switcher); Node harness asserts 2-element UI rows and no
  "Tiếng Việt" in the page; README says the demo UI is
  English/Korean.
- Tests: 132 passed in the sandbox plus 1 browser test run by the
  owner in a normal terminal. `ruff check` clean. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: fail-to-recovery panel (P2-B)

`docs/track-p2-ambition.md` option B (the recommended one; A stays
out). The S3 scene now shows a "Verify & re-read" panel under
Reading: clean base reading (lines 0/12, amounts FAIL, checks FAIL)
beside the narrow re-read (12/12, ok, pass), the corrected-cells
line, the clean receipt image, and the story line. New numbers are
`check`-kind provenance records, so they click like the rest. New UI
keys are en/ko only (item 30 dropped vi from the demo).

### Muse Code (coding agent)

- `demo.py` builds `recovery` from `replay_reading(S3, clean)` +
  `verify_receipt` with an explicit `ReplayProvider`; before/after
  metrics come from `eval.compare`, matching the eval table.
- Browser test S3 header list updated for the new panel.
- Tests: 132 passed in the sandbox plus 1 browser test run by the
  owner in a normal terminal. `ruff check` clean. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: scripted demo video

Round 3 item 31. `scripts/record_video.py` + `docs/video/storyboard.json`
record the 3-minute submission video: Playwright with the Edge channel
at 1280x720, repo root served on 127.0.0.1 inside the script, 12
segments (180 s) with verbatim captions, a bottom caption bar and a
cursor dot injected as the only overlay (no demo behaviour change).
Targets use stable selectors, never pixels; durations come from the
storyboard. Local doc shots (README table, agent scorecard, masking
pairs, trimmed eval table, tooling log) render at record time with
URLs stripped, so `out/` stays https-free and is never committed.

### Muse Code (coding agent)

- `--dry-run` validates durations, captions, ops, and every
  selector's tokens against `docs/demo.html` / the shot pages
  without a browser; a committed test runs it. The sandbox cannot
  launch a browser, so the owner runs the real recording.
- Tests: 133 passed in the sandbox (`ruff check` clean) plus the
  owner's recording run producing the .webm, timeline.txt, and 12
  midpoint PNGs. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: video fixes from first recording

Round 3 item 31b (owner reviewed the midpoint PNGs). (1) Midpoint
shots on action-less segments fired at segment start, before the
caption fade — the clock now waits for the true midpoint, and the
recording fails fast if no caption is visible there. Every navigation
re-injects the overlay, re-applies the caption, and restores the
cursor to its last spot (center at first). (2) Shot pages no longer
repeat the markdown title, and the README table cell drops "(EN +
VI)". (3) A MutationObserver lifts the provenance panel above the
caption bar whenever it opens. (4) seg07/seg11 captions replaced with
the shorter verbatim lines; dry run caps every caption at 190 chars
for two lines at 720p. Stale `out/video/` artifacts are cleared at
the start of a run.

### Muse Code (coding agent)

- Tests: 134 passed in the sandbox (`ruff check` clean) plus the
  owner's re-recording run. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-27 — Backlog session: demo video v2 + vertical cut

Round 4 items 32 and 33. The v1 recorder was split into shared
modules (`scripts/video_lib.py` validation/planning, `video_run.py`
browser runner, `video_shots.py` doc shots, `video_sound.py` ffmpeg
mux) with the caption/cursor overlay extracted to
`docs/video/overlay.js` and the camera/spotlight/micro-motion FX to
`docs/video/overlay_fx.js`; v1 keeps working unchanged on top.

Item 32: `scripts/record_video_v2.py` +
`docs/video/storyboard-v2.json` (22 segments, exactly 180 s) add a
cold-open card, six ~1 s chapter cards, CSS-transform camera zoom
with a spotlight and eased 400-700 ms moves, flow-step pop and
provenance pulse micro-motion, a 15 s phone-frame segment (demo in
an iframe at 390x844), a six-tile Meta tools card, and ffmpeg sound
(the en voice clip's first 6 s at the voice segment, optional
`--music` bed at -18 dB ducked under the voice). Output:
`claimlens_demo_v2.mp4` (H.264 + AAC) plus the silent .webm,
`timeline_v2.txt`, and 22 midpoint PNGs. v1 captions kept verbatim
except the cold/chapter/tool-segment short lines the new structure
needs; the spec's "Scene B" does not exist, so the owner approved
showing Scene Voice's two real confirmations instead.

Item 33: `scripts/record_vertical.py` + `docs/video/vertical.json`
(7 segments, exactly 45 s) record at 360x640 CSS with mobile
emulation to a sharp 720x1280, 34 px captions capped at 44 chars
for two lines: hook card, S2 Play, 22,500 provenance tap, agent
ask, S3 warning, built-with and link cards. Output:
`claimlens_vertical.mp4` (+ silent .webm, timeline, PNGs), optional
`--music`. Each product cleans only its own `out/video/` files.

### Muse Code (coding agent)

- Dry runs validate cards (offline, no remote refs, images exist),
  selectors incl. iframe frames, nav uniqueness, caption caps, and
  exact totals; negative tests cover bad card ids, long captions,
  and ambiguous nav. Mux tests (voice+music, music-only, silent)
  are committed but skip where ffmpeg cannot run.
- Tests: 138 passed, 3 skipped (ffmpeg blocked in the sandbox),
  browser test deselected in the sandbox (`ruff check` clean),
  plus the owner's two recording runs producing both .mp4 files.
  No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-28 — Backlog session: Round 5 consistency, live server, thesis

Round 5 items 34–36 (done before Round 4 per the backlog order note;
the committed v2/vertical storyboards predate them and do not show
the new scene yet).

Item 34: `src/claimlens/consistency.py` compares a claim bundle's
receipt and certificate in two layers: deterministic exact checks
(patient name, birth date, visit dates, visit type as blockers;
hospital as a note) plus one Muse Spark strict-schema pass for
narrative-vs-billed, diagnosis-vs-department, and prose-date
mismatches. Every Spark finding carries a quote from each document;
code drops findings whose quotes are not found in the readings or
that use banned wording. The Spark pass is text-only over the
verified readings (not images), so every quote stays verifiable.
Blockers stop the claim and ship as ask_user questions. Six bundles
mix existing samples (matched A/S2/S3, three mismatches);
`claimlens consistency-eval` scores blocker precision/recall into
`docs/consistency-eval.md` (1.000 everywhere; Spark extras listed).
The agent loop itself is untouched (no recording churn): blockers
surface as ask_user payloads in the CLI, the demo, and the server.

Item 35: `claimlens serve` (stdlib, 127.0.0.1 only, 10 MB cap,
images only) serves the demo and a JSON pipeline: live Spark
reading, checks + re-read, eligibility, consistency, then a live
engine call when Neo4j is up (never overwriting recordings) or a
sample-matched Claim Pack. Person facts come from the request or a
byte-matched sample. The demo probes `/api/health`, shows LIVE vs
REPLAY, and runs dropped photos through `/api/run` with real
timings and token counts; GitHub Pages stays replay.

Item 36: thesis "AI reads, reasons and asks; code counts." in the
README lead, the demo hero, and a three-column strip (Spark reads &
reasons / code counts / people decide); the Meta-tools table now
says what each model decides.

### Muse Code (coding agent)

- Tests: 163 passed, 4 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: consistency pins (deterministic + replay), Spark
  quote/fraud-drop tests, no-socket endpoint tests over the pure
  route functions plus a real-HTTP test where listen() works.
- Recordings: the owner ran `consistency-eval --output` once (6
  Spark calls, ~$0.05); the sandbox cannot reach the API.
- Owner checks: live drop of the S2 photos in a real browser,
  the browser language test, demo at 1280x720 + 375px. No push.

### Model APIs

- Live calls: 6 consistency recordings by the owner (~$0.05).

## 2026-10-28 — Backlog session: item 39 verification layer

Item 36 was already committed; verified the thesis in README and
demo hero. Item 39 adds the verification layer after Meta's
legal-agent-workshop pattern (own implementation): checks inside
the terminal tools (`src/claimlens/supervision.py` gates; the agent
loop itself untouched, so no recording churn), a second Spark pass
over rationale lines and Spark consistency findings (one call per
claim set; code still owns every number), escalation after 3
refusals or any blocker with a handoff card, resume only on answer
or new documents, reviewer sign-off with one revision, and Files
API upload-once with base64 fallback (method recorded per call).
The demo Agent scene shows re-executed guard verdicts plus a
scripted walkthrough (refuse-fix, handoff, resume, sign-off).

### Muse Code (coding agent)

- Tests: 181 passed, 4 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: guard/escalation/resume/sign-off tests with a
  scripted model, claims-verifier stub tests, Files API stub tests,
  demo verification asserts.
- Recordings: the owner ran 2 rationale + 2 consistency commands
  (4 verifier calls, ~$0.03; the Files probe was not run). Verdicts:
  rationale A/S2 8/8 supported, Ar-Cc 1 of 2 dropped, S2r-Ac empty.
  The bundle re-calls also rewrote 4 existing keys (model variance:
  S2r-Ac findings went from 6 to 0); rule precision/recall still
  1.000, eval table regenerated.
- Owner checks: browser language test, demo at 1280x720 + 375px,
  Files probe optional. No push.

### Model APIs

- Live calls: 4 verifier recordings by the owner (~$0.03).

## 2026-10-28 — Backlog session: item 35b live server fixes

Owner review fixes. (1) Live mode no longer overwrites committed
recordings: `MetaProvider(live=True)` reuses a committed (or live)
entry when the key exists and otherwise stores fresh results under
`cache/live/` (git-ignored), so the demo's replay source stays
fixed; `claimlens serve` uses the live provider. (2) Spend guard on
`POST /api/run`: the Host must be this machine's loopback with the
server port, Content-Type must be application/json, and a present
Origin must match (blocks cross-site POSTs and DNS rebinding).
(3) Body cap raised to ~14 MB for base64 inflation; the 10 MB check
stays on decoded bytes. (4) LIVE UI: the engine note moved under
the big amount, and the topbar source note plus the flow note
switch to live wordings in en and ko.

### Muse Code (coding agent)

- Tests: 188 passed, 4 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: live-reuse without network (reading + write),
  live-miss stores under `cache/live/` only, sample bytes leave
  `git diff -- cache/` empty, and one refusal test per spend
  guard (host, content-type, origin).
- Live calls: none (replay only).
- Owner checks: live S2 drop in a real browser, `git status` shows
  no cache changes. No push.

### Model APIs

- Live calls: none (replay only).

## 2026-10-28 — Backlog session: item 35c honest live labels + Files probe

(1) Honest labels in LIVE mode: when a step reuses a recording it now
says "recording reused — no model call" (en/ko) with 0 new tokens;
only a real network call may say "live", and that applies to the
reading, the consistency check, and the re-read step. (2) Safe Files
API probe: `claimlens probe-files <image>` uploads one image through
the Meta Files API, reads it once by file id, prints whether it
worked plus token counts, and writes only to `out/probe/` — the demo
cache is never touched. (3) README documents that Muse Spark's
semantic consistency findings vary between runs on the same input
(one bundle went 6 → 0 on 2026-10-28), and that blockers rest on the
deterministic layer, which is why precision/recall stays 1.000.

### Muse Code (coding agent)

- Tests: 193 passed, 4 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: honest-label cases for reused vs fresh reading plus
  re-read in both cases, and probe tests for works / unavailable /
  missing image.
- Live calls: none in the sandbox (replay only).
- Owner checks: run `claimlens probe-files <image>` once from a
  normal terminal (sandbox block), verify `out/probe/` only, and
  re-check live reuse in a real browser. No push.

### Model APIs

- Live calls: none in the sandbox. One probe call by the owner
  pending (~$0.007).

## 2026-10-28 — Backlog session: item 35d probe-files follow-ups

(1) `claimlens probe-files` now loads `.env` like every other
command, so `META_API_KEY` is found. (2) When the Files API path
fails, the provider keeps the failure (`stage` upload/read, HTTP
status, message); the probe writes it to
`out/probe/probe_result.json` as `files_error` and prints it, so the
owner's re-run will show why it fell back to base64. The README note
("documents are sent as base64 because ...") waits for that recorded
reason.

### Muse Code (coding agent)

- Tests: 196 passed, 4 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: upload failure records status + message, file-id
  rejection records a read error, probe summary and JSON carry the
  reason.
- Live calls: none in the sandbox (replay only).
- Owner checks: re-run `claimlens probe-files <image>` once from a
  normal terminal and paste the `files_error` line; the README note
  follows from it. No push.

### Model APIs

- Live calls: none in the sandbox. One probe call by the owner
  pending (~$0.007).

## 2026-10-28 — Backlog session: item 35e Files API retry with user_data

The owner's 35d probe recorded `upload status=400 - Unsupported file
purpose: vision`. Following Meta's own workshop, the provider now
uploads with `purpose="user_data"` and reads by file id trying
`input_image` first, then `input_file`; the probe records which part
worked (`file_part`) or each read error (`attempts`). Live runs keep
uploading once per document (keyed by image sha256) and remember
file ids under `cache/live/` only, so committed `cache/` recordings
stay untouched; base64 remains the fallback. The owner's probe then
recorded `files_api: works`, `file_part: input_image`, 4,023 tokens
for one S2 receipt — the README line above the model table states
this result.

### Muse Code (coding agent)

- Tests: 198 passed, 4 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: input_file used when input_image is rejected, each
  read error recorded, live file ids under `live/` only, probe
  reports the working part.
- Live calls: none in the sandbox (replay only).
- Owner checks: probe re-run done 2026-10-28 (`files_api: works`,
  `file_part: input_image`, 4,023 tokens); README line written from
  it. No push.

### Model APIs

- Live calls: one owner probe call 2026-10-28 (~$0.007).

## 2026-10-28 — Backlog session: item 40 storyboard v3 for both videos

The v3 storyboards show the Round 5 product: both open from the
thesis ("AI reads, reasons and asks; code counts." card on the main
cut), then a real live run, the Mismatch scene, and the checks the
agent cannot skip. The main cut (180 s) trims voice, scene A and the
holds, and drops the masking shot; the vertical cut (45 s final) is
hook, live drop on the phone, tap 22,500, mismatch quotes, link card.
The recording scripts start `claimlens serve` themselves, drop the
two `samples/live/` retakes (bytes match no recording, so the Spark
calls are real), keep the real wait on screen with the LIVE badge,
and fail the recording if the live call fails. The vertical live
beat is recorded in real time and played back 2× with a "2×" tag.
Demo additions, all replay-honest: the Mismatch scene shows the
Spark claims check line (A receipt + C certificate: 1 dropped — not
supported by its quotes), the walkthrough names the refused
`adjudicate` tool and renders the reviewer (return with notes, then
approve), and every engine result carries the "pre-existing
open-source engine, pinned" label, including flow results. Live
results go to `cache/live/` only; nothing in `cache/` was re-recorded.

### Muse Code (coding agent)

- Tests: 208 passed, 5 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: v3 + vertical-v3 dry runs (180 s / final cut 45 s),
  drop-file/speed validation, speedup filter, drop payload, live
  page use, live-server health (runs where listen() works), and
  demo payload pins (claims check, engine flags).
- Live calls: none in the sandbox (replay only).
- Owner checks: run both v3 recordings from a normal terminal
  (`record_video_v3.py`, `record_vertical_v3.py`, each needs
  META_API_KEY and makes real Spark calls); confirm both .mp4 files
  and midpoint PNGs. If the live wait exceeds its storyboard budget
  the cut overruns — report the real wait and the budget moves.
  No push.

### Model APIs

- Live calls: none in the sandbox. Owner recording runs make real
  Spark calls (reading + consistency per live segment).

## 2026-10-28 — Backlog session: item 40b v3 recording fixes

(1) The lead trim now cuts the measured pre-roll instead of the
`duration − total` guess (the guess ate the tail too, so 0:03 showed
the S2 flow). Both v3 recorders measure context-creation to first
segment start, pass it as `mux_sound(lead=...)`, and cut exactly
that with `-t total`; without a lead the mux keeps its legacy
full-length behavior. A frame check extracts the mp4 frame at the
first segment's midpoint and fails the recording when it does not
match the midpoint PNG (tolerant diff, no OCR). (2) A live drop now
clears the flow steps and result first, so no replay leftover shows
under "Running live…"; the live steps fill in when the run answers.
(3) The camera zoom clamps to the focused element's box: the runner
passes its size, the overlay shrinks the scale (never below 1) so
the box stays inside the viewport with a margin.

### Muse Code (coding agent)

- Tests: 212 passed, 7 skipped (ffmpeg + listen() blocked in the
  sandbox, node-gated where absent), browser test deselected in the
  sandbox (`ruff check` clean). New: mux lead/-t command shape,
  frame-diff same/different, zoom-fit clamp via node, plus
  ffmpeg-gated lead-cut and frame-check tests for the owner run.
  Both v3 dry runs pass (180 s / final cut 45 s).
- Live calls: none in the sandbox (replay only).
- Owner checks: re-record both v3 videos from a normal terminal;
  the frame check runs at the end of each recording. Confirm frames
  at 0:03 (thesis), the live scene (no replay steps under Running),
  and the verify scene (no cropped text). No push.

### Model APIs

- Live calls: none in the sandbox. Owner re-recordings make real
  Spark calls (reading + consistency per live segment).

## 2026-10-28 — Backlog session: item 40d live overrun + phone layout

(1) The live wait can no longer push the ending off the cut. The
timeline now prints actual per-segment times (planned in parens),
and both v3 recorders rush the live wait adaptively: the first
seconds stay 1×, the rest of the wait plays at the smallest of 2×/4×
that fits the limit, with a visible tag — no rush when the wait
fits (0.5 s grace). The recording fails instead of cutting the
ending when even 4× cannot fit, when the final cut exceeds the
limit, or when the last segment is not the closing card; the
timeline gains a final-cut section with post-rush times. (2) The
demo and index pages carry a viewport meta tag; small screens stack
the grids and scroll wide tables inside their panels; the browser
test checks the 375 px phone layout in Edge (meta tag, no sideways
overflow, S2 scene).

### Muse Code (coding agent)

- Tests: 224 passed, 7 skipped (ffmpeg + listen() blocked in the
  sandbox), 2 browser tests deselected in the sandbox
  (`ruff check` clean). New: rush pick (2×/4×/fail), final-cut
  times, rush validation, actual-timeline via a fake page, 4×
  filter shape, viewport asserts. Both v3 dry runs pass (180 s /
  final cut 45 s).
- Live calls: none in the sandbox (replay only).
- Owner checks: re-record both v3 videos from a normal terminal;
  confirm each ends on its closing card at ≤180 s / ≤45 s, the rush
  tag shows when the wait runs long, and the vertical frames show
  the phone layout. Run the browser tests including the new phone
  check. No push.

### Model APIs

- Live calls: none in the sandbox. Owner re-recordings make real
  Spark calls (reading + consistency per live segment).

## 2026-10-28 — Backlog session: item 37b triage fixes from the live run

(1) The owner's triage run dropped the S2 certificate over a
bracketed transliteration ("NGUYEN VAN AN (…)" vs "NGUYEN VAN AN").
Identities are now normalised before grouping: bracketed alternates
stripped, case folded, spaces and punctuation collapsed, name tokens
compared as a set, and dates matched on overlapping visit periods.
Pages differing only by such normalisation are kept with the note
"name written differently on the certificate" instead of dropped.
The recorded response `cache/e6022bfc….json` is committed as the
pin fixture (read directly: it is file-keyed from before the key
change, so replay cannot address it without its deleted index):
keep [0] and [2] with the note, drop [1] with reason, merge [3] into
[0], missing is the itemized statement only. (2) File ids are now
runtime-only: every index lives under `cache/live/`, also for CLI
runs, and recordings are keyed by image bytes whatever the
transport — replay never needs the index, and a test fails if
anything named `files_index` appears outside `cache/live/`.

### Muse Code (coding agent)

- Tests: 231 passed, 7 skipped (ffmpeg + listen() blocked in the
  sandbox), 2 browser tests deselected in the sandbox
  (`ruff check` clean). New: recorded-bundle pin, bracket/order/
  punctuation/overlap/drop unit cases, replay-survives-index-loss,
  index-under-live for CLI and live runs, repo hygiene scan.
- Live calls: none in the sandbox (replay only).
- Owner checks: push and tick 37b. No re-recording needed: the pin
  reads the kept response directly. No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-28 — Backlog session: item 37 messy bundle triage

New `claimlens triage <photos...>`: one Muse Spark strict-schema
call classifies every page in input order (kind + patient, date,
total copied from the page), then code groups pages into the claim
(majority identity), drops unrelated pages with a reason, merges
duplicates (same kind, identity, total), and names missing documents
from the expected checklist (receipt, itemized statement, medical
certificate; `--expect` overrides). Totals are compared as copied
strings, never computed. No demo or video changes (video frozen;
40c untouched while the owner records).

### Muse Code (coding agent)

- Tests: 217 passed, 7 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: stub-provider tests over a bundle built from existing
  sample images (shuffled S2 pages + duplicate receipt + other-claim
  page) pin keep/merge/drop-with-reason/"itemized statement
  missing", plus CLI report, tie determinism, and length mismatch.
- Live calls: none in the sandbox (replay only). No new recordings:
  replay honestly reports a cache miss until the owner records one
  triage call (~$0.009).
- Owner checks: optionally record once
  (`claimlens triage <photos...>` without CLAIMLENS_PROVIDER=replay)
  to get a real classification. No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-28 — Backlog session: item 40e re-runnable post-processing

The main recording finished its `.webm` but failed in post-processing with the
rush/mux stderr lost, so the run could not be redone without re-recording.
Each recorder now saves measured `*_actuals.json` (segment actuals, lead,
total) next to the `.webm`, and both recorders gained
`--post-only [--webm/--actuals/--lead]`: rush → mux → frame check re-run from
the saved files with no browser and no live call, printing the full ffmpeg
command plus stderr on failure. Missing actuals fall back to the timeline with
an explicit `--lead`, or to a content-match lead measured against the
opening-card midpoint PNG. Vertical scene A presses Escape to close the
provenance panel before clicking the element the panel covers (new `press`
storyboard op); intercepted clicks are never relied on.

### Muse Code (coding agent)

- Tests: 239 passed, 9 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). New: actuals save/load roundtrip + garbage, timeline parse
  stopping at the final-cut appendix, resolve prefers saved actuals /
  recovers from timeline + lead / rejects id mismatch, full ffmpeg
  error printed on a stubbed mux failure, press validation, plus
  ffmpeg-gated content-lead and end-to-end post tests for the owner.
- Live calls: none in the sandbox (replay only).
- Owner checks: `uv run python scripts/record_video_v3.py --post-only`
  on the existing main `.webm` should print a ≤180s `.mp4` ending on
  the closing screen; then re-record the vertical. No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-28 — Backlog session: item 40c tidy video tooling

Five recorders and five storyboards looked like sprawl, so everything
video-related now lives under `tools/video/` (recorders, storyboard
JSON, overlay JS, cards, phone frame), keeping only the main and
vertical recorders (`record_main.py`, `record_vertical.py`) and their
storyboards. The v1/v2 recorders, `storyboard.json`,
`storyboard-v2.json`, `vertical.json`, and their tests are deleted (git
history keeps them). One entry point:
`uv run python tools/video/record.py main|vertical [--dry-run]
[--music FILE]` (plus the 40e `--post-only` flags); README gained a
short "Demo video" section. No behaviour change.

### Muse Code (coding agent)

- Tests: 234 passed, 9 skipped (ffmpeg + listen() blocked in the
  sandbox), browser test deselected in the sandbox (`ruff check`
  clean). Record tests now run through the new entry point
  (main/vertical dry runs, unknown-cut rejection, drop-file and
  missing-webm failures); v1/v2 tests deleted with their recorders.
- Live calls: none in the sandbox (replay only).
- Owner checks: `uv run python tools/video/record.py main --post-only`
  on the existing main `.webm` (new path after the move). No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-28 — Backlog session: item 40f live run without person facts

A live run with no person facts dead-ended at "Human review: no decision
path" (the owner's post-only main video). The flow view now has a "Whose
claim is this?" panel next to the drop zone (visa, Korean employer yes/no,
work injury yes/no, entry date; en/ko) with presets from
`samples/scenarios_inbound.json` ("Worker in Seoul (S2)", "US tourist
(S3)"), sent as `person` (+ preset `scenario`) with `/api/run`. Missing
facts return `ask_user`-shaped questions and pause the run after the
checks; answering continues the same run with no new reading call. The
engine path accepts a preset-declared scenario context (labeled as such,
`matched_sample` stays honest), so the S2 preset + retake drop ends
PARTIAL 22,500 KRW. Long result titles no longer use the big amount font;
blocker questions now show on the page too. Both storyboards pick the S2
preset before the live drop. Committed as c2f3329 (2026-10-28).

### Muse Code (coding agent)

- Tests: 239 passed, 9 skipped (ffmpeg + listen() blocked in the
  sandbox), browser file deselected in the sandbox (`ruff check`
  clean). New: pause/questions/continue/preset-context route tests,
  two owner-run browser tests (preset → PARTIAL; no facts → questions
  → answer → PARTIAL with no second reading), person-preset demo data
  test; dry runs pass for both cuts.
- Live calls: none in the sandbox (replay only).
- Owner checks: `uv run pytest tests/test_browser_lang.py -q`, then
  re-record both videos (live runs end PARTIAL 22,500 KRW) and verify;
  only then commit once. No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-28 — Backlog session: item 41b double-read gate

Item 41's run ($1.51, 23/24 hard cases before the cap tripped) showed 47
hard + 1 normal wrong numbers leaving the single-read pipeline: checks
pass when Spark puts the right numbers in the wrong cells or "fixes"
blurred lines so they still add up. The fix is a double-read gate: two
independent verified reads in parallel, stopping on any disagreement in
total/line amounts/KR cells with both values side by side and one
ask_user question per differing field ("Double read: agree" row on the
page). Replaying the recorded runs as pairs gives 0 leaks in 96 pairs at
a stop cost of 35/66 hard + 2/30 normal. Second reads replay from new
`.read2` cache keys that never overwrite existing files; recording them
(~10 calls, ~$0.13) waits for owner approval. Committed as 205fc91 (2026-10-28).

### Muse Code (coding agent)

- Tests: full suite green (`ruff check` clean). New: gate agree/stop
  route tests, gate sim + KR-only denominator + read2 key tests,
  offline live-cache test with a seeded read2 copy; `eval-report`
  recomputes the tables from the recorded log with per-set spend and
  the simulated gated column.
- Live calls: none in the sandbox (replay only). No new recordings.
- Owner checks: approve `claimlens record-read2 --execute` (~10 calls,
  ~$0.13) to record the second reads, then commit once. No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-28 — Backlog session: Round 8 items 44 + 45

44 puts the Why block (owner-approved who line, the two sourced numbers
with their links, the paperwork line, an N-less After sentence, the
theme line) right under the thesis in README and on the demo's first
screen in en/ko. N has no committed source yet (43 not done; no live-run
step timings are committed and prose does not count), so the sentence
ships without N and the test pins that. 45 adds "What ClaimLens is not"
to README plus a scope footer on every scene and the live page and a
"Proposed — for a reviewer" label next to every PAID/PARTIAL/DENIED/
HUMAN_REVIEW badge. No API calls, no cache writes, video untouched.

### Muse Code (coding agent)

- Tests: full suite green (`ruff check` clean). New: Why-block exact
  numbers/URLs test, footer/label wiring test, owner-run browser test
  for the footer on every scene in en+ko and the label on every
  decision badge; the stale no-https assertion now allows exactly the
  two source URLs.
- Live calls: none in the sandbox (replay only).
- Owner checks: `uv run pytest tests/test_browser_lang.py -q` (now 5
  tests). No push.

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 42 fault injection

New `claimlens faults` registry plus `tests/test_faults.py`: 15 injected
faults (Spark timeout, 429/500, bad JSON, schema violation, empty
output, Files fallback, Neo4j down, serve offline, oversized/non-image
upload, single-read failure…), each pinned by a test, none making a
live call in the suite. Committed as 333228b (2026-10-29).

### Muse Code (coding agent)

- Tests: new fault tests; full suite green, `ruff check` clean.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 43 load check

New `claimlens load`: 5 concurrent live runs over the S2 retake photos
with p50/p95/cost and per-run badges, plan-only by default with
`--execute/--max-cost`. The owner ran it once:
`data/load_20261028T205112Z.json` ($0.18 total, under the $1 cap):
p50 22.97 s, p95 30.32 s, mean $0.0355 — PARTIAL 3, needs_manual_check 2.
Committed as 333228b (2026-10-29).

### Muse Code (coding agent)

- Tests: load plan math + temp isolation tests; full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 46 measured block

New `claimlens headline`: the README Measured block, the After sentence
N, the storyboard eval caption, the demo `measured` payload and the
video measured shot are all generated from `data/*.json` — no
hand-typed numbers. Committed as 333228b (2026-10-29).

### Muse Code (coding agent)

- Tests: headline pin/idempotence tests; full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 47 Meta tiles

New `claimlens` model table ("Built with Meta"): one row per Meta
tool/step with its `How` and a `Measured` fact recomputed from data
(logged sessions, spark agreement, Files tokens, masks, voice
confirmations, open-weights matches). Rendered into README, demo and
video cards by regen. Committed as 333228b (2026-10-29).

### Muse Code (coding agent)

- Tests: tile/model-table tests; full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 41c live gate eval

New `claimlens gate-eval`: the double-read gate over fresh live reads
(plan-only default, `--execute`, `--max-cost`, temp cache isolation).
First run `data/gate_live_20261028T212938Z.json` ($3.45, under the $4
cap): hard 2 leaks (38/72 stopped), normal 2 leaks (1/30 stopped),
totals only — the leaking cases were unknown. Committed as 333228b
(2026-10-29).

### Muse Code (coding agent)

- Tests: gate plan/estimate/abort/isolation tests; full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 41d per-pair gate details

Gate runs now save per-pair details (reads, verify, rotation, wrong
fields), so the next run names its leaks. Second run
`data/gate_live_20261029T004823Z.json` ($3.57): hard 2 leaks (39/72
stopped), normal 1 leak (5/30 stopped) — C clean reading total 0 with
correct lines, and S3 rot90 putting 15,000,000 in KR cell 4 instead
of 3 on both reads. Same commit also fixes the vertical recorder and
the Muse Code tile fact. Committed as 0c9096f (2026-10-29).

### Muse Code (coding agent)

- Tests: pair-detail + tile tests; full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 41e line-sum check

Every receipt gets a line-sum check (total vs items, ±0.01) with
verify-and-re-read on failure; the KR path was left for later.
Third run `data/gate_live_20261029T042335Z.json` ($3.48): normal 0
leaks (0/30 stopped), hard 4 leaks (39/72 stopped) — all four the
S3 rot90 cell swap, both reads agreeing. Committed as e5c855f plus
run data d25a4d3 (2026-10-29).

### Muse Code (coding agent)

- Tests: line-sum/verify tests; full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Backlog session: item 41f rotation probe

New `src/claimlens/rotation.py`: one small `probe_rotation(image)` call
per page on a 768 px copy, strict `{"rotation": 0|90|180|270}` schema,
own prompt and cache key. The reading schema, reading instructions and
reader are byte-identical, so every committed recording still replays.
Nonzero rotations are corrected in code (Pillow) and both reads use the
upright copy; the Reading row shows "page turned 90 upright".
Sample-matched uploads skip the probe (no new replay recordings);
probe failures read as is and are noted, never blocking. Wired into
serve, gate-eval and hard-eval; plan estimates include the probes.

### Muse Code (coding agent)

- Tests: new `tests/test_rotation.py` (20 tests: probe/0/sample-match/
  failure for serve, gate-eval and hard-eval, estimate math). Existing
  estimate assertions updated (gate-eval, hard-eval, load); the browser
  live stub answers the probe. Full suite green, `ruff check` clean.
- Live calls: none in the sandbox (replay only, BOGUS keys).
- Owner checks: approve one `gate-eval --execute` (~$3.6+) to measure:
  hard leaks should drop, clean stops must not rise.
- Committed as 749597b (2026-10-29); the measuring run is
  `data/gate_live_20261029T070828Z.json` (107708b: hard 0 leaks, 35/72
  stopped; normal 0/30).

## 2026-10-29 — Backlog session: item 38 cover letter

New `src/claimlens/letter.py`: Spark writes the cover letter as
prose-only with `{{PLACEHOLDERS}}` (any digit outside one rejects the
draft, one retry, then a code-only template); code fills values from
the Claim Pack and rejects numbers not in the pack. English only,
shown under the S3 Claim Pack as a draft for the patient to review
and send. New cache keys only; reading schema and instructions
untouched. S3 drafts (photo + clean) recorded by the owner via
`claimlens record-letter`. Committed as 2172927 (2026-10-29).

### Muse Code (coding agent)

- Tests: new `tests/test_letter.py` (13 tests); full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-30 — Backlog session: item 49 unseen layouts

New `tools/unseen/render.py` draws receipt + certificate pairs
(clean + phone-photo) for 6 held-out layouts (U1–U6) from
`samples/unseen/truth.json`; synthetic names, watermark, system
fonts only. New `gate-eval --set unseen` (rotation on, ×3,
plan-default). No product-code tuning before measuring. First run
`data/gate_live_20261029T154402Z.json`: 36 pairs, 0 leaks, 12
stopped ($0.91). Committed as d624a2d (2026-10-30).

### Muse Code (coding agent)

- Tests: new `tests/test_unseen.py` (11 tests); full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-30 — Backlog session: item 49b real trips

The unseen renderer grows 6 traveller cases (T1–T6) under
`samples/unseen/trips/` with local + fixed-FX KRW totals and
expected serve outcomes (no hand-computed payouts). New
`gate-eval --set trips` and `claimlens trips-check` (plan-default).
First runs: `data/gate_live_20261029T155458Z.json` (48 pairs,
0 leaks, 18 stopped, $1.08) and
`data/trips_check_20261029T155607Z.json` (5 PASS + T3 earlier stop
at needs_manual_check, $0.08). Committed as d624a2d (2026-10-30).

### Muse Code (coding agent)

- Tests: new `tests/test_trips.py` (20 tests); full suite green.
- Live calls: none in the sandbox (replay only, BOGUS keys).

### Model APIs

- Live calls: none in the sandbox.

## 2026-10-29 — Round 9 full review (report only, no code changes)

`out/review-round9.md` (written against the then-uncommitted 49/49b tree):
five parallel read-only passes (accuracy,
rubric/honesty, security/UX, tests, Round 9 tooling) over `src/`,
`tests/`, `tools/`, `docs/`, README and demo, every finding verified
against the cited lines — 13 high, 14 medium, ~40 low, a top-10 fix
list, dropped false positives and open unknowns. `out/round9-report.md`
stacks the 49/49b/review evidence with the dawn-run commands.

### Model APIs

- Live calls: none in the sandbox.

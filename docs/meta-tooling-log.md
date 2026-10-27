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

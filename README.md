# ClaimLens

**AI reads, reasons and asks; code counts.**

| Muse Spark reads & reasons | code counts | people decide |
|---|---|---|
| reading, consistency, agent, voice facts | checks, deductible, eligibility, codes | questions, to-confirm, human review |

**Why:** Built by a developer who works on hospital data systems in Korea — a problem I
see first-hand. Korea, 2022: an estimated ₩251.2 billion of private medical insurance
went unclaimed ([estimate from NHIS and insurer statistics](https://www.fnnews.com/news/202309060625012843)).
2.01 million foreign patients were treated in Korea in 2025
([Ministry of Health and Welfare](https://v.daum.net/v/20260424060102461)).
ClaimLens works on the paperwork step. Bill photo → checked claim in about 22.97 s, every number traceable.
Theme: Build for Your World.

Medical paperwork that crosses borders — in both directions.
ClaimLens reads hospital bills and medical certificates for people whose care crosses a border
(Koreans treated abroad, foreigners treated in Korea). When a Korean policy applies, it prepares a
claim decision with the cited policy clauses. When no policy applies, it does not decide — it builds
a claim pack the person can take to their own insurer (English, Vietnamese on request).

<!-- measured:start -->
**Measured:**
- Live double-read gate, 2026-10-30 run on the current pipeline (24 cases ×3 = 72 pairs): 0 wrong amounts left (40 stopped for a person); normal documents: 0 left, 6/30 stopped.
- Single read, 2026-10-28 run on the old pipeline (before the line-sum check and rotation probe): 47 wrong amounts left (hard set, 23/24 cases ×3).
- Unseen layouts + real trips, first run before fixes (2026-10-29): 0 wrong amounts left over 84 pairs (30 stopped for a person); after fixes (2026-10-30, wider scoring): 0 wrong values left over 84 pairs (8 stopped).
- Agent scorecard: 8/8 (7 agent dialogues + 1 voice rule, each replayed once from its recording)
- 15 fault cases injected in tests (no live calls), no wrong number
- Per claim (S2 retake photos, 5 concurrent live runs): p50 22.97 s, p95 30.32 s, $0.0355; outcomes PARTIAL 3, needs_manual_check 2 (PARTIAL = partly paid, needs_manual_check = stopped for a person); median run needs_manual_check
Fields scored in the current runs: total, line amounts, Korean bill cells, currency, country, service date, inpatient stay, diagnosis codes, charge rows. Older runs (the single-read line and the first run before fixes) scored total, line amounts, Korean bill cells only.
<!-- measured:end -->

**Live demo (no key, no server):** https://jaehun-an.github.io/claimlens/

Built for the **Meta Global AI Developer Hackathon** (Indie track, Oct 27 – Nov 4, 2026).
All documents used in this repository are **synthetic**. ClaimLens processes insurance paperwork;
it does not give medical advice and never guesses a diagnosis.

## What ClaimLens is not

- *Not medical advice* — it never suggests a diagnosis or treatment; it reads codes a doctor already wrote.
- *Not a chat-with-your-documents app* — there is no retrieval chat; readings pass deterministic checks, a pinned clause-graph engine and an agent behind a verification layer.
- *Not a single image analyzer* — it cross-checks several documents, re-reads, reads twice and stops for a person.

## Run it offline in 60 seconds

All model and engine responses are committed under `cache/`, so everything below
works with no API key and no database:

```sh
git clone https://github.com/JAEHUN-AN/claimlens.git && cd claimlens
uv sync
uv run claimlens demo --output out/demo.html   # or open the committed docs/demo.html
```

Then open the HTML file in a browser. It opens on a guided flow: pick one of
five samples, play its pipeline steps, then inspect the full example. The six
scenes (A, S2, S3, Agent, Voice, Mismatch) carry readings, check marks, eligibility, the
engine card or the Claim Pack, the agent timeline, and the spoken-intake scene.
Every number there is clickable for its provenance.
The demo UI switches between English and Korean; `claimlens claimpack
--lang vi` can still render a Vietnamese pack.
`docs/demo.html` in this repo is the same export, committed.

Other offline commands:

```sh
uv run claimlens eval --output out/eval.md                        # field-accuracy table, all samples
uv run claimlens read samples/S2_seoul_worker_bronchitis         # one reading plus receipt checks
uv run claimlens adjudicate A_niseko_wrist                       # engine decision envelope (replay)
uv run claimlens rationale A_niseko_wrist                        # English rationale card (replay)
uv run claimlens claimpack S3_us_tourist_hip_fracture --format html --output out/pack.html  # Claim Pack (replay)
uv run claimlens claimpack S3_us_tourist_hip_fracture --lang vi --output out/pack_vi.md  # Vietnamese pack
uv run claimlens consistency S2r-S3c                       # cross-document findings, one bundle
uv run claimlens consistency-eval --output out/consistency.md  # blocker precision/recall
uv run claimlens serve                                       # local live server on 127.0.0.1:8000
uv run pytest -q                                                  # full suite, replay only
```

Live calls need `META_API_KEY` (and `NEO4J_URI/USER/PASSWORD` for the engine);
copy `.env.example` to `.env`. `CLAIMLENS_PROVIDER=replay` forces cache-only mode.

## Built vs pre-existing

| Built during the hackathon (this repo) | Pre-existing (dependency, not showcased) |
|---|---|
| Document reading schema + strict-schema prompts | [clausegraph](https://github.com/JAEHUN-AN/clausegraph) — the author's MIT-licensed policy knowledge graph and adjudication engine, pinned to tag [`claimlens-base-20261026`](https://github.com/JAEHUN-AN/clausegraph/releases/tag/claimlens-base-20261026), created before the hackathon started |
| Verify-and-re-read loop, receipt arithmetic checks | |
| Eligibility rules, KCD/WHO/CM code conversion | |
| English rationale cards, Claim Pack, SAM masking | |
| Clarifying agent loop, voice intake, spoken-fact confirmation | |
| `claimlens eval`, offline replay demo, Spark Open step | |
| Cross-document consistency, local live server | |
| Held-out unseen + trips documents + renderer (Round 9) | Sample documents (synthetic bills, certificates, voice clips), prepared before the hackathon |

Using a pre-existing open-source dependency was confirmed as acceptable in the hackathon Discord
(#questions, 2026-10-26).

## Which Meta model does which step

| Step | Model | How | Measured |
|---|---|---|---|
| Wrote the code from the backlog | Muse Code (`muse-spark-1.3`) | Owner reviewed, ran live/engine calls where the Windows sandbox could not ([tooling log](docs/meta-tooling-log.md)) | 59 logged sessions |
| Send documents by file id | Files API (`purpose="user_data"`) | Upload once per image, reference as `input_image`; base64 fallback | one read by file id as input_image, 4,023 tokens |
| Read receipts + certificates | `muse-spark-1.3` (hosted) | Decides the transcription: text, amounts, categories, dates, codes; strict schema, two images | 267 fields read ×3 (33 cases, hard 23/24), 86% run-to-run agreement |
| Rephrase rationale drafts | `muse-spark-1.3` (hosted) | Decides wording only; amounts and clause IDs copied by code, checked | — |
| Translate Claim Pack row labels | `muse-spark-1.3` (hosted) | Decides label wording; amounts copied by code | — |
| Translate Claim Pack (Vietnamese) | `muse-spark-1.3` (hosted) | Decides labels + sentences; amounts, codes, dates copied by code | — |
| Clarifying agent loop | `muse-spark-1.3` (hosted) | Decides the next tool and when to ask; numbers only from tools, step cap 12 | — |
| Transcribe spoken intake | `muse-voice-transcribe-1.0` (hosted) | Decides the transcript; dates/codes marked to confirm, never certain | 2 fact types need confirmation |
| Extract facts from transcript | `muse-spark-1.3` (hosted) | Decides facts + supporting quotes; uncertain ones routed to confirm | 2 fact types need confirmation |
| Compare documents (consistency) | `muse-spark-1.3` (hosted) | Decides mismatch findings from quoted evidence; code drops unquoted claims | — |
| Translate row labels (comparison) | `meta-models/muse-spark-open-1026` (Baseten) | Decides the same labels for comparison; forced `submit_labels` tool call | — |
| Read receipts + certificates (comparison) | `meta-models/muse-spark-open-1026` (Baseten) | Decides the same reading for comparison; forced `submit_reading` tool call | 11/15 fields match hosted |
| Mask seals and signatures | `sam-3.1` (hosted) | Decides seal/signature boxes; painted on a copy | 2 masked copies |

Muse Code wrote the code from the backlog. Claude Code (Anthropic) reviewed and verified each change, ran the live measurements, and made small fixes; those commits carry a `Co-Authored-By: Claude` trailer.

Every number shown to a user comes from a document reading, a deterministic check,
or the engine — never from model arithmetic. The tooling log linked above is the
main evidence for "Use of Meta AI Tooling".

Documents reach hosted Spark through the Files API: each image is uploaded once
(`purpose="user_data"`) and referenced by file id as `input_image` — verified
live 2026-10-28 via `claimlens probe-files` (4,023 tokens for one S2 receipt).
If an upload or file-id read fails, the provider retries as `input_file` and
then falls back to base64.

## Verification

Checks the agent cannot skip, after Meta's
[legal-agent-workshop](https://github.com/meta-models/legal-agent-workshop)
pattern (own implementation): `adjudicate` and `build_claim_pack`
refuse unless receipt checks pass and no consistency blocker is open;
a second Spark pass confirms model statements against their quotes
(code still owns every number); three refusals or any blocker stop
the run for a person with a handoff, and resume only on an answer or
new documents; nothing ships without reviewer sign-off, with one
revision on return. See the Agent scene's Verification section.

## Eval

Field accuracy per sample and variant, from `claimlens eval` (full table with
tokens and cost in [docs/eval.md](docs/eval.md)):

| sample | variant | total | lines | amounts | diags | kr_cells | checks | pii |
|---|---|---|---|---|---|---|---|---|
| A_niseko_wrist | photo | ok | 6/6 | ok | 1/1 | n/a | pass | 4/4 |
| A_niseko_wrist | clean | ok | 6/6 | ok | 1/1 | n/a | pass | 4/4 |
| B_chiangmai_dogbite | photo | ok | 7/7 | ok | 2/2 | n/a | pass | 4/4 |
| B_chiangmai_dogbite | clean | ok | 7/7 | ok | 2/2 | n/a | pass | 4/4 |
| C_newyork_panic | photo | ok | 7/7 | ok | 2/2 | n/a | pass | 4/4 |
| C_newyork_panic | clean | ok | 7/7 | ok | 2/2 | n/a | pass | 4/4 |
| S2_seoul_worker_bronchitis | photo | ok | 5/5 | ok | 1/1 | 10/10 | pass | 2/2 |
| S2_seoul_worker_bronchitis | clean | ok | 5/5 | ok | 1/1 | 10/10 | pass | 2/2 |
| S3_us_tourist_hip_fracture | photo | ok | 12/12 | ok | 1/1 | 10/10 | pass | 3/4 |
| S3_us_tourist_hip_fracture | clean | ok | 0/12 | FAIL | 1/1 | 10/10 | FAIL | 4/4 |

Document reading on hosted Spark vs Spark Open (Baseten
`meta-models/muse-spark-open-1026`, forced tool call; full side-by-side with
tokens, latency, and cost in [docs/eval.md](docs/eval.md)):

| sample | variant | hosted total / lines / checks | open total / lines / checks |
|---|---|---|---|
| A_niseko_wrist | photo | ok / 6/6 / pass | ok / 6/6 / pass |
| A_niseko_wrist | clean | ok / 6/6 / pass | ok / 6/6 / pass |
| B_chiangmai_dogbite | photo | ok / 7/7 / pass | ok / 7/7 / pass |
| B_chiangmai_dogbite | clean | ok / 7/7 / pass | ok / 7/7 / pass |
| C_newyork_panic | photo | ok / 7/7 / pass | FAIL / 7/7 / FAIL |
| C_newyork_panic | clean | ok / 7/7 / pass | ok / 7/7 / pass |
| S2_seoul_worker_bronchitis | photo | ok / 5/5 / pass | ok / 5/5 / FAIL |
| S2_seoul_worker_bronchitis | clean | ok / 5/5 / pass | ok / 5/5 / FAIL |
| S3_us_tourist_hip_fracture | photo | ok / 12/12 / pass | ok / 12/12 / FAIL |
| S3_us_tourist_hip_fracture | clean | ok / 0/12 / FAIL | ok / 12/12 / pass |

Where open weights match: A and B on both variants (totals and all line
items), and all S2/S3 receipt cells 1–10 identical to hosted Spark. Where
they fall short: C photo total read as 0 (truth 3,200); S2 line amounts at
half value, so `lines_sum` fails; S3 photo includes the summary row as a
13th charge row, so `lines_count` fails. One win for open weights: S3 clean
12/12 lines with checks passing, where the hosted base reading has 0/12.
Open reads use about a third more tokens and take 5–9 s; `reasoning_tokens`
reports 0 and cost shows `-` (no Baseten rates configured).

Pack translation on hosted Spark vs Spark Open (12 S3 row labels):

| hosted model | open model | identical |
|---|---|---|
| muse-spark-1.3 | meta-models/muse-spark-open-1026 | 8/12 |

The four diffs are legitimate phrasing variants (room fee/fee, Treatment/Procedure,
Lab test/Examination, charge/cost).

Engine decisions (pinned replay): A → PAID ₩2,216,050, S2 → PARTIAL ₩22,500,
B → HUMAN_REVIEW, C → DENIED, S3 → not sent to the engine (not a member).
The S2 card shows ClaimLens's own deductible terms next to the engine's:
max(20,000, 9,000, 22,500) = 22,500 — matches the engine.

The clarifying agent is scored over 8 scripted cases (asks when it must, never
otherwise, never invents a number): see the [agent scorecard](docs/agent-eval.md),
regenerated by `claimlens agent-eval`. Two honest notes: each case is one
recorded dialogue replayed, not repeated runs; and `confirm-voice-date` is the
voice-intake rule asking for confirmation, not the agent loop (0 steps).
Hard-document eval (23/24 harsh variants ×3, cap tripped at $1.51): single read let 47 wrong amounts leave;
on those recorded pairs a double-read gate would leave 0, stopping 35/66 hard + 2/30 normal pairs
(simulated, [tables](docs/eval.md)). A 'field' in those tables is one scored bundle (a whole line table, the whole PII set), not one cell. The live gate run is in the Measured block above.

## Live upload

`claimlens serve` takes uploads from a browser: one or more receipts with an optional
certificate, by drag and drop or the phone file picker. Each receipt is read
and checked on its own, then merged — every amount keeps the photo it came
from, and a card slip matching a bill total is merged rather than added.
Bills whose lines do not add up get a narrow re-read for the printed
subtotal and the tax, discount and adjustment lines before anything stops
for a person.

The person panel asks for nationality, the foreign-resident registration
date, and the insurance product. Korean nationals treated abroad take the
traveller engine path against the chosen
product's demo terms; when facts, a product, or the engine are missing, the
run pauses with the reason and the next step instead of a bare badge.
Any pause keeps its verified reading: when reads disagree the person picks
the printed value per field, answers blocking questions, and continues the
same run with no new reading.

## What happens when something fails

15 fault cases, each pinned by a test with stubbed providers and requests — no case ever returns a wrong number.

| fault | expected | test |
|---|---|---|
| Spark call times out | RuntimeError; serve answers 503 with the error, no result | `test_fault_spark_timeout` |
| HTTP 429, then success | retries with 1s/2s backoff, returns the reading | `test_fault_429_recovers` |
| HTTP 429 three times | stops after 3 attempts, RuntimeError | `test_fault_429_stops` |
| HTTP 500 | no retry, RuntimeError on the first failure | `test_fault_500_stops` |
| malformed or truncated JSON output | RuntimeError, nothing stored or returned | `test_fault_bad_json` |
| JSON breaks the strict schema | RuntimeError, nothing stored or returned | `test_fault_schema_violation` |
| empty model output | RuntimeError, nothing stored or returned | `test_fault_empty_output` |
| Files API upload fails | base64 fallback, files_error recorded, reading returned | `test_fault_files_fallback` |
| Neo4j unreachable, member claim | engine_unreachable badge stating the reason | `test_fault_neo4j_engine` |
| Neo4j unreachable, visitor claim | Claim Pack still built, no engine call | `test_fault_pack_without_neo4j` |
| network down in claimlens serve | page shows the error, never a stale result | `test_fault_serve_offline` |
| upload over the 10 MB limit | 400 naming the limit, nothing read | `test_fault_oversized_upload` |
| non-image upload | 400 naming the file, nothing read | `test_fault_non_image_upload` |
| one of two reads fails or times out | needs_manual_check; the single read never passes alone | `test_fault_gate_single_failure` |
| reads disagree on document count | needs_manual_check with a documents question | `test_fault_gate_doc_count` |

## Limitations

- The S3 clean base reading omits the redundant item list (0/12 lines, checks
  FAIL); `claimlens read` recovers it through the verify loop (`corrected:
  ["line_items"]`), but the raw base score above is kept honest.
- S3 photo PII recall is 3/4: the passport reads `A0000000`, the document says
  `A00000000`. Every pack PII line therefore carries a "check against your
  passport/ID" mark, and conflicting values across documents print both.
- Code conversion covers the SPEC §5.5 examples; ICD-10-CM candidate rules ship
  for S72.1 only, and I84.x maps to bare K64 (subdivisions must be re-coded
  from the certificate).
- SAM finds the seal on the S2 photo variant but not on the clean render
  (four attempts, genuinely empty responses), so the demo masks the photo
  variant.
- The engine data root and Neo4j live outside this repo; only cached engine
  outputs ship here.
- Muse Spark's semantic consistency findings vary between runs on the same
  input (one bundle went from 6 findings to 0 after re-recording on
  2026-10-28). Blockers rest on the deterministic layer, which is why
  precision/recall stays 1.000.
- Rotation rests on one model judgement. A Korean bill photographed sideways used to come back
  with two charge columns swapped in both reads (sums unchanged, so checks and the double read
  passed it). A separate rotation probe now turns the page upright before reading; in the live
  gate run it judged every turned and every upright page correctly
  (`data/gate_live_20261029T070828Z.json`). If the probe misjudges a page, only the checks and
  the double read remain as guards.
- A US bill that prints both an insurance adjustment and a "patient responsibility", paid with a
  separate card slip (the Honolulu trip), still stops for a person in every live pair: the two
  reads disagree and the person picks the printed values. Nothing leaks, but it is not automatic
  (see the "After 57" rows in `docs/eval.md`).
- On a Korean bill, if one read leaves out the item list, the narrow re-read can return the
  patient-share column instead of each row's total, so the line-sum check fails and the claim
  stops for a person (found while recording on 2026-10-31: two of three live runs on the S2
  retake photos stopped this way). Nothing leaks; the charge rows the model already read would
  let code derive the row totals, which is the planned fix.

## Demo video

The demo video is recorded by `uv run python tools/video/record.py main|vertical`
from the replay caches plus one live run.

## Data sources and rights

- **Documents:** every receipt, certificate and voice sample in `samples/` is synthetic.
- **Diagnosis codes:** no code table is shipped. `src/claimlens/codes.py` holds a handful of code identifiers
  inside its conversion rules. ICD-10 © World Health Organization. ICD-10-CM is published by
  CDC/NCHS and CMS; its use here does not imply endorsement by CDC/HHS or the U.S. Government.
  KCD (Korean Standard Classification of Diseases) is issued by Statistics Korea.
- **Policy terms:** the engine reads the Korean standard insurance terms from the National Law
  Information Center open data (non-commercial use, source attributed). The demo and recordings
  show clause numbers and titles only, never the clause text.
- **Engine:** [clausegraph](https://github.com/JAEHUN-AN/clausegraph), pre-existing and pinned to
  a tag. Its code is MIT; the data it collects follows each source's terms, listed in its LICENSE.

## License

MIT — see [LICENSE](LICENSE). The license covers this repository's code; the sources above keep
their own terms.

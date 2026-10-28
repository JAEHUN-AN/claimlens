# ClaimLens

**AI reads, reasons and asks; code counts.**

| Muse Spark reads & reasons | code counts | people decide |
|---|---|---|
| reading, consistency, agent, voice facts | checks, deductible, eligibility, codes | questions, to-confirm, human review |

**Live demo (no key, no server):** https://jaehun-an.github.io/claimlens/

Medical paperwork that crosses borders — in both directions.
ClaimLens reads hospital bills and medical certificates for people whose care crosses a border
(Koreans treated abroad, foreigners treated in Korea). When a Korean policy applies, it prepares a
claim decision with the cited policy clauses. When no policy applies, it does not decide — it builds
a claim pack the person can take to their own insurer (English, Vietnamese on request).

Built for the **Meta Global AI Developer Hackathon** (Indie track, Oct 27 – Nov 4, 2026).
All documents used in this repository are **synthetic**. ClaimLens processes insurance paperwork;
it does not give medical advice and never guesses a diagnosis.

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

Using a pre-existing open-source dependency was confirmed as acceptable in the hackathon Discord
(#questions, 2026-10-26).

## Which Meta model does which step

| Step | Model | How |
|---|---|---|
| Wrote the code from the backlog | Muse Code (`muse-spark-1.3`) | Owner reviewed, ran live/engine calls where the Windows sandbox could not ([tooling log](docs/meta-tooling-log.md)) |
| Read receipts + certificates | `muse-spark-1.3` (hosted) | Decides the transcription: text, amounts, categories, dates, codes; strict schema, two images |
| Rephrase rationale drafts | `muse-spark-1.3` (hosted) | Decides wording only; amounts and clause IDs copied by code, checked |
| Translate Claim Pack row labels | `muse-spark-1.3` (hosted) | Decides label wording; amounts copied by code |
| Translate Claim Pack (Vietnamese) | `muse-spark-1.3` (hosted) | Decides labels + sentences; amounts, codes, dates copied by code |
| Clarifying agent loop | `muse-spark-1.3` (hosted) | Decides the next tool and when to ask; numbers only from tools, step cap 12 |
| Transcribe spoken intake | `muse-voice-transcribe-1.0` (hosted) | Decides the transcript; dates/codes marked to confirm, never certain |
| Extract facts from transcript | `muse-spark-1.3` (hosted) | Decides facts + supporting quotes; uncertain ones routed to confirm |
| Compare documents (consistency) | `muse-spark-1.3` (hosted) | Decides mismatch findings from quoted evidence; code drops unquoted claims |
| Translate row labels (comparison) | `meta-models/muse-spark-open-1026` (Baseten) | Decides the same labels for comparison; forced `submit_labels` tool call |
| Read receipts + certificates (comparison) | `meta-models/muse-spark-open-1026` (Baseten) | Decides the same reading for comparison; forced `submit_reading` tool call |
| Mask seals and signatures | `sam-3.1` (hosted) | Decides seal/signature boxes; painted on a copy |

Every number shown to a user comes from a document reading, a deterministic check,
or the engine — never from model arithmetic. The tooling log linked above is the
main evidence for "Use of Meta AI Tooling".

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
| A_niseko_wrist | photo | ok | 6/6 | ok | 1/1 | n/a | n/a | 4/4 |
| A_niseko_wrist | clean | ok | 6/6 | ok | 1/1 | n/a | n/a | 4/4 |
| B_chiangmai_dogbite | photo | ok | 7/7 | ok | 2/2 | n/a | n/a | 4/4 |
| B_chiangmai_dogbite | clean | ok | 7/7 | ok | 2/2 | n/a | n/a | 4/4 |
| C_newyork_panic | photo | ok | 7/7 | ok | 2/2 | n/a | n/a | 4/4 |
| C_newyork_panic | clean | ok | 7/7 | ok | 2/2 | n/a | n/a | 4/4 |
| S2_seoul_worker_bronchitis | photo | ok | 5/5 | ok | 1/1 | 10/10 | pass | 2/2 |
| S2_seoul_worker_bronchitis | clean | ok | 5/5 | ok | 1/1 | 10/10 | pass | 2/2 |
| S3_us_tourist_hip_fracture | photo | ok | 12/12 | ok | 1/1 | 10/10 | pass | 3/4 |
| S3_us_tourist_hip_fracture | clean | ok | 0/12 | FAIL | 1/1 | 10/10 | FAIL | 4/4 |

Document reading on hosted Spark vs Spark Open (Baseten
`meta-models/muse-spark-open-1026`, forced tool call; full side-by-side with
tokens, latency, and cost in [docs/eval.md](docs/eval.md)):

| sample | variant | hosted total / lines / checks | open total / lines / checks |
|---|---|---|---|
| A_niseko_wrist | photo | ok / 6/6 / n/a | ok / 6/6 / n/a |
| A_niseko_wrist | clean | ok / 6/6 / n/a | ok / 6/6 / n/a |
| B_chiangmai_dogbite | photo | ok / 7/7 / n/a | ok / 7/7 / n/a |
| B_chiangmai_dogbite | clean | ok / 7/7 / n/a | ok / 7/7 / n/a |
| C_newyork_panic | photo | ok / 7/7 / n/a | FAIL / 7/7 / n/a |
| C_newyork_panic | clean | ok / 7/7 / n/a | ok / 7/7 / n/a |
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

## License

MIT — see [LICENSE](LICENSE).

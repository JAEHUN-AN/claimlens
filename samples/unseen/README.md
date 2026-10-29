# Unseen layouts (held-out set, backlog 49)

Six synthetic cases in layouts the pipeline never saw during development.
Purpose: prove wrong numbers still cannot reach a decision on first-seen
forms. **Held out: do not tune prompts, checks, or code against these
cases; measure only.**

- Ground truth: `truth.json` (scenarios.json shape). The renderer draws
  from it; gate-eval scores against it.
- Images: per case, receipt + certificate as `*_clean.png` and
  `*_photo.jpg` (mild phone-photo effect: slight perspective, light
  falloff, JPEG grain — same kind as hard_images, own strength/seeds).
- Regen: `uv run python tools/unseen/render.py` (deterministic, seed 49).
- Every name, hospital, ID, and amount is invented; every page carries a
  SYNTHETIC SAMPLE watermark.

## Cases (what differs from A/B/C/S2/S3)

| case | documents | new vs the old samples |
|---|---|---|
| U1_hanbit_outpatient | Korean clinic outpatient bill + cert | Gridless dot-leader layout (S2/S3 are 별지 grids); Malgun Gothic; amounts differ |
| U2_mirae_inpatient | Korean 3-night inpatient bill + cert | Quantity x unit grid with a non-covered row; no circled ①-⑩ cells; KoPub Batang |
| U3_naha_clinic | Japanese clinic register-slip bill + cert | Narrow slip, not A's full-page table; subtotal/taxable rows plus a 10% consumption-tax line; Yu Gothic |
| U4_denver_bill | US itemized bill + cert | Description-first columns without Rev/CPT codes; a nonzero -212.50 prompt-pay adjustment (total = charges + adjustment); Consolas amounts |
| U5_pudong_receipt | Chinese hospital receipt + cert | New language/country (B is Thai); red masthead; CNY with a reference-only USD memo (~380.20); SimSun |
| U6_austin_urgent | compact US receipt + letter-style cert | Two-column receipt with BALANCE DUE; certificate as prose letter with codes embedded in text and written-out dates; Georgia |

Truth notes: the U3 tax line and the U4 adjustment are truth line items
(the reader is expected to read them as lines); subtotal/taxable/total
rows are not. No case uses KR circled cells, so scoring is total +
line amounts + certificate codes (kr_cells n/a).

## Real trips (49b, under trips/)

Six situations a Korean traveller runs into, drawn with the same tool
(`--truth samples/unseen/trips/truth.json`). Truth adds the traveller's
panel facts, the local total plus the KRW total at the fixed
`samples/fx_demo.json` rate, the eligibility path, and the expected
serve outcome — never a hand-computed payout.

| case | situation | documents |
|---|---|---|
| T1_bangkok_food_poisoning | ER bill + separate pharmacy slip (THB) | 2 receipts + cert |
| T2_danang_scooter | clinic bill with dotted thousands (VND) | receipt + cert |
| T3_setagaya_fever | child's clinic bill with a tax line (JPY) | receipt + cert |
| T4_paris_pharmacy | pharmacy ticket only, no certificate (EUR) | 1 receipt |
| T5_honolulu_urgent | bill with insurance adjustment + card slip (USD) | bill + payment + cert |
| T6_guam_dental | dental receipt with CDT codes (USD) | receipt + cert |

3+ receipts (T1, T5) and the missing certificate (T4) do not fit
today's exactly-2-images upload: truth records the current 400 plus
the desired behaviour. Gate pairs read one receipt with the
certificate (T4 reads the receipt alone); the trips scenario check
(`claimlens trips-check`) runs each case through the live page flow.

## Fonts (system fonts only; none stored in the repo)

| file in C:\Windows\Fonts | used for |
|---|---|
| malgun.ttf, malgunbd.ttf | U1 receipt |
| KoPubBatangMedium.ttf, KoPubBatangBold.ttf | U2 receipt |
| YuGothR.ttc, YuGothB.ttc | U3 receipt |
| calibri.ttf, calibrib.ttf, consola.ttf | U4 receipt |
| simsun.ttc | U5 receipt |
| georgia.ttf, georgiab.ttf | U6 receipt + letter cert |
| arial.ttf, arialbd.ttf | plain certificates, watermark |
| LEELAWAD.TTF, LEELAWDB.TTF | T1 Thai receipts |
| cambria.ttc, cambriab.ttf | T6 dental receipt |

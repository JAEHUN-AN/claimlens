# Synthetic sample documents

Every document here is **synthetic** — invented patients, hospitals and numbers, rendered with a
"SYNTHETIC SAMPLE" watermark and then photographed-style degraded. No real personal data.

These images and their ground-truth files were **prepared before the hackathon** as test data
(assets, not code). Nothing in this folder is counted as hackathon work; the code that reads,
checks and explains them is.

| Folder | Scene |
|---|---|
| `A_niseko_wrist` | Korean traveller, wrist fracture while skiing in Niseko (JPY bill) |
| `S2_seoul_worker_bronchitis` | Foreign worker in Seoul, general-hospital outpatient visit (Korean bill) |
| `S3_us_tourist_hip_fracture` | US tourist in Seoul, femur fracture admission (Korean bill, English certificate) |
| `B_chiangmai_dogbite`, `C_newyork_panic` | Regression cases |

Each folder has `receipt_*` and `medical_certificate_*` in two variants: `*_clean.png` (rendered)
and `*_photo.jpg` (phone-photo look). Ground truth: `scenarios.json` (A, B, C),
`scenarios_inbound.json` (S2, S3). `fx_demo.json` holds the fixed demo exchange rates.

# Retake photos for the live demo

`S2_receipt_retake.jpg` and `S2_medical_certificate_retake.jpg` are the synthetic S2 photos
re-shot digitally (slight rotation, crop, lighting and blur changed with Pillow on 2026-10-28) so
that their bytes match no recording in `cache/`. Dropping them on `claimlens serve` makes a real
Muse Spark call — this is what the live part of the demo video shows. Synthetic data; ground truth
is the S2 entry in `../scenarios_inbound.json`.

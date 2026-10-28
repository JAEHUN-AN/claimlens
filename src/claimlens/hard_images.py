"""Hard variant set: deterministic Pillow degradations of sample photos.

Derives harsh-but-fair variants from the committed sample images (no new
rendering): perspective skew, motion blur, low light with a shadow
gradient, low resolution with heavy JPEG compression, 90/180 rotation, a
glare spot over part of the totals, and a crop that cuts off one column.
Every transform is seeded: the same seed always yields the same bytes.

The receipt carries the degradation; geometric/photometric transforms
apply to both images of the pair while glare and crop target the receipt
only (their ground-truth effects are receipt cells). Crop geometry is
per-sample: KR receipts lose the right totals column (true crop), the A
receipt loses its amount column (cut-out box; a true crop would also kill
the PII block the eval scores). The manifest records the geometry and
which truth cells become "unreadable expected".
"""

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance

TRANSFORMS = (
    "perspective",
    "motion",
    "lowlight",
    "lowres",
    "rot90",
    "rot180",
    "glare",
    "crop",
)

# Receipt-only transforms: the certificate stays the committed original.
RECEIPT_ONLY = ("glare", "crop")

HARD_SAMPLES = (
    "A_niseko_wrist",
    "S2_seoul_worker_bronchitis",
    "S3_us_tourist_hip_fracture",
)

# Right-column crop (fraction of width kept) for the KR 별지 form.
KR_CROP_KEEP = 0.84

# A receipt: amount-column cut-out box as fractions (left, top, right, bottom).
A_CROP_BOX = (0.595, 0.53, 0.95, 0.905)

# Glare spot: center + radius as width fractions, per receipt kind.
GLARE = {
    "kr": {"center": (0.88, 0.45), "radius": 0.11},
    "a": {"center": (0.78, 0.66), "radius": 0.10},
}


def seed_for(seed: int, sample: str, transform: str) -> int:
    """Stable integer seed from the run seed plus case identity."""
    digest = hashlib.sha256(f"{seed}:{sample}:{transform}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _find_coeffs(target: list[tuple[float, float]],
                 source: list[tuple[float, float]]) -> list[float]:
    """Perspective coefficients mapping target corners from source corners."""
    matrix = []
    for (x1, y1), (x2, y2) in zip(target, source, strict=True):
        matrix.append([x1, y1, 1, 0, 0, 0, -x2 * x1, -x2 * y1])
        matrix.append([0, 0, 0, x1, y1, 1, -y2 * x1, -y2 * y1])
    # Solve the 8x8 system with plain Gaussian elimination (no numpy).
    vec = [p for pair in source for p in pair]
    n = 8
    aug = [row + [vec[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        aug[col] = [v / div for v in aug[col]]
        for row in range(n):
            if row != col and aug[row][col]:
                factor = aug[row][col]
                aug[row] = [a - factor * b for a, b in zip(aug[row], aug[col])]
    return [aug[i][n] for i in range(n)]


def _perspective(img: Image.Image, rng: random.Random) -> Image.Image:
    width, height = img.size
    jx = lambda: rng.uniform(-0.02, 0.02) * width
    jy = lambda: rng.uniform(-0.02, 0.02) * height
    target = [(0, 0), (width, 0), (width, height), (0, height)]
    source = [
        (0.06 * width + jx(), 0.03 * height + jy()),
        (0.90 * width + jx(), 0.08 * height + jy()),
        (0.97 * width + jx(), 0.96 * height + jy()),
        (0.02 * width + jx(), 0.90 * height + jy()),
    ]
    return img.transform((width, height), Image.Transform.PERSPECTIVE,
                         _find_coeffs(target, source), Image.BICUBIC)


def _motion(img: Image.Image, _rng: random.Random) -> Image.Image:
    """Horizontal shake: running average of 0-20 px shifted copies."""
    base = img.convert("RGB")
    width, height = base.size
    out = base
    for shift in range(1, 21):
        moved = base.transform((width, height), Image.Transform.AFFINE, (1, 0, -shift, 0, 1, 0),
                               fillcolor=(0, 0, 0))
        out = Image.blend(out, moved, 1.0 / (shift + 1))
    return out


def _lowlight(img: Image.Image, rng: random.Random) -> Image.Image:
    dimmed = ImageEnhance.Brightness(img.convert("RGB")).enhance(0.45)
    width, height = img.size
    mask = Image.new("L", (width, height))
    draw = ImageDraw.Draw(mask)
    horizontal = rng.random() < 0.5
    steps = width if horizontal else height
    for i in range(steps):
        shade = int(110 * i / max(steps - 1, 1))
        if horizontal:
            draw.line([(i, 0), (i, height)], fill=shade)
        else:
            draw.line([(0, i), (width, i)], fill=shade)
    black = Image.new("RGB", (width, height), (0, 0, 0))
    return Image.composite(dimmed, black, mask)


def _lowres(img: Image.Image, _rng: random.Random) -> Image.Image:
    import io

    width, height = img.size
    small = img.convert("RGB").resize((480, round(480 * height / width)), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=12)
    buf.seek(0)
    loaded = Image.open(buf)
    loaded.load()
    return loaded


def _glare(img: Image.Image, rng: random.Random, kind: str) -> Image.Image:
    spec = GLARE[kind]
    width, height = img.size
    cx = (spec["center"][0] + rng.uniform(-0.01, 0.01)) * width
    cy = (spec["center"][1] + rng.uniform(-0.01, 0.01)) * height
    radius = spec["radius"] * width
    glow = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(glow)
    rings = 48
    for i in range(rings, 0, -1):
        alpha = int(235 * (1 - i / rings) ** 0.8)
        box = [cx - radius * i / rings, cy - radius * i / rings,
               cx + radius * i / rings, cy + radius * i / rings]
        draw.ellipse(box, fill=alpha)
    white = Image.new("RGB", (width, height), (255, 255, 255))
    return Image.composite(white, img.convert("RGB"), glow)


def _crop_kr(img: Image.Image) -> Image.Image:
    width, height = img.size
    return img.crop((0, 0, round(KR_CROP_KEEP * width), height))


def _crop_a(img: Image.Image) -> Image.Image:
    width, height = img.size
    left, top, right, bottom = A_CROP_BOX
    box = (round(left * width), round(top * height), round(right * width), round(bottom * height))
    cut = img.convert("RGB").copy()
    draw = ImageDraw.Draw(cut)
    draw.rectangle(box, fill=(40, 40, 40))
    return cut


def apply_transform(img: Image.Image, transform: str, rng: random.Random,
                    kind: str) -> Image.Image:
    """Apply one named transform; kind is 'kr' or 'a' (receipt layout)."""
    if transform == "perspective":
        return _perspective(img, rng)
    if transform == "motion":
        return _motion(img, rng)
    if transform == "lowlight":
        return _lowlight(img, rng)
    if transform == "lowres":
        return _lowres(img, rng)
    if transform == "rot90":
        return img.transpose(Image.Transpose.ROTATE_90)
    if transform == "rot180":
        return img.transpose(Image.Transpose.ROTATE_180)
    if transform == "glare":
        return _glare(img, rng, kind)
    if transform == "crop":
        return _crop_kr(img) if kind == "kr" else _crop_a(img)
    raise ValueError(f"Unknown transform: {transform}.")


def unreadable_for(sample: str, transform: str) -> dict[str, Any]:
    """Truth cells the transform physically removes (crop only)."""
    marks: dict[str, Any] = {"total": False, "line_amounts": False, "kr_cells": []}
    if transform != "crop":
        return marks
    marks["total"] = True
    if sample.startswith(("S2", "S3")):
        marks["kr_cells"] = [6, 7, 8, 9, 10]
    else:
        marks["line_amounts"] = True
    return marks


def ensure_hard_set(seed: int, out_dir: Path, samples_dir: Path,
                    samples: tuple[str, ...] = HARD_SAMPLES,
                    transforms: tuple[str, ...] = TRANSFORMS) -> dict[str, Any]:
    """Generate the hard images plus a manifest; returns the manifest."""
    from claimlens.reader import resolve_sample_images

    out_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for sample in samples:
        kind = "kr" if sample.startswith(("S2", "S3")) else "a"
        receipt_src, cert_src = resolve_sample_images(samples_dir / sample, "photo")
        with Image.open(receipt_src) as receipt_img, Image.open(cert_src) as cert_img:
            receipt_base = receipt_img.convert("RGB")
            cert_base = cert_img.convert("RGB")
            for transform in transforms:
                rng = random.Random(seed_for(seed, sample, transform))
                receipt = apply_transform(receipt_base, transform, rng, kind)
                if transform in RECEIPT_ONLY:
                    cert = cert_base
                else:
                    cert_rng = random.Random(seed_for(seed, sample, transform + ":cert"))
                    cert = apply_transform(cert_base, transform, cert_rng, "cert")
                receipt_name = f"receipt_{sample}_{transform}.jpg"
                cert_name = f"cert_{sample}_{transform}.jpg"
                receipt.save(out_dir / receipt_name, format="JPEG", quality=88)
                cert.save(out_dir / cert_name, format="JPEG", quality=88)
                cases.append({
                    "sample": sample,
                    "transform": transform,
                    "receipt": receipt_name,
                    "cert": cert_name,
                    "unreadable": unreadable_for(sample, transform),
                })
    manifest = {"seed": seed, "cases": cases}
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest

"""Seal and signature masking with SAM 3.1 (backlog 9).

One noun phrase per request; the model answers with box tags inside text.
Boxes are drawn filled on a copy of the image. Text-field PII stays out of
the image path entirely: it is handled in reading results, never painted.
"""

import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image, ImageDraw

MODEL = "sam-3.1"
BASE_URL = "https://api.meta.ai/v1"

_BOX_KV = re.compile(
    r"<\|box;(?:\s*[a-z0-9]+\s*=\s*\d+(?:\.\d+)?\s*;?\s*)+\|>"
)
_BOX_BARE = re.compile(
    r"<\|box;\s*(\d+(?:\.\d+)?)\s*;\s*(\d+(?:\.\d+)?)\s*;"
    r"\s*(\d+(?:\.\d+)?)\s*;\s*(\d+(?:\.\d+)?)\s*;"
    r"\s*(\d+(?:\.\d+)?)\s*;\s*(\d+(?:\.\d+)?)\s*\|>"
)
_PAIR = re.compile(r"([a-z0-9]+)\s*=\s*(\d+(?:\.\d+)?)")


def parse_sam_boxes(text: str) -> list[dict[str, float]]:
    """Parse box tags; accepts key=value and bare six-number forms."""
    boxes: list[dict[str, float]] = []
    for match in _BOX_KV.finditer(text):
        pairs = dict(_PAIR.findall(match.group(0)))
        try:
            boxes.append({k: float(pairs[k]) for k in ("x1", "y1", "x2", "y2", "w", "h")})
        except KeyError:
            continue
    for match in _BOX_BARE.finditer(text):
        x1, y1, x2, y2, w, h = (float(v) for v in match.groups())
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "w": w, "h": h})
    return boxes


def sam_cache_dir() -> Path:
    return Path(os.environ.get("CLAIMLENS_SAM_CACHE_DIR", "cache/sam"))


def sam_cache_key(image_bytes: bytes, phrase: str, model: str = MODEL) -> str:
    digest = hashlib.sha256()
    digest.update(image_bytes)
    digest.update(phrase.encode("utf-8"))
    digest.update(model.encode("utf-8"))
    return digest.hexdigest()


def store_sam(key: str, payload: dict[str, Any]) -> Path:
    path = sam_cache_dir() / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_sam(key: str) -> dict[str, Any]:
    path = sam_cache_dir() / f"{key}.json"
    if not path.exists():
        raise LookupError(f"No cached SAM response for key {key} ({path}).")
    return json.loads(path.read_text(encoding="utf-8"))


def detect_live(image: Path, phrase: str) -> dict[str, Any]:
    """One SAM request; records the raw streamed text. Empty means not found."""
    from openai import OpenAI

    from claimlens.providers.meta import prepare_image

    load_dotenv()
    key = os.environ.get("META_API_KEY")
    if not key:
        raise RuntimeError("META_API_KEY is not set.")
    blob = prepare_image(image)
    data_url = f"data:image/jpeg;base64,{base64.b64encode(blob).decode('ascii')}"
    client = OpenAI(base_url=BASE_URL, api_key=key)
    stream = client.responses.create(
        model=MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": phrase},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
        stream=True,
    )
    chunks: list[str] = []
    for event in stream:
        delta = getattr(event, "delta", None)
        if isinstance(delta, str) and delta:
            chunks.append(delta)
    text = "".join(chunks)
    payload = {
        "model": MODEL,
        "phrase": phrase,
        "output_text": text,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    store_sam(sam_cache_key(blob, phrase), payload)
    return payload


def detect(image: Path, phrase: str) -> dict[str, Any]:
    """Replay a recorded SAM response, or go live when allowed."""
    from claimlens.providers.meta import prepare_image

    load_dotenv()
    blob = prepare_image(image)
    key = sam_cache_key(blob, phrase)
    if os.environ.get("CLAIMLENS_PROVIDER", "meta").lower() == "replay":
        return load_sam(key)
    try:
        return load_sam(key)
    except LookupError:
        return detect_live(image, phrase)


def mask_image(src: Path, boxes: list[dict[str, float]], dst: Path) -> Path:
    """Draw filled boxes on a copy; coordinates scale from tag w/h."""
    with Image.open(src) as img:
        rgb = img.convert("RGB")
        draw = ImageDraw.Draw(rgb)
        width, height = rgb.size
        for box in boxes:
            w, h = box["w"], box["h"]
            if w <= 0 or h <= 0:
                continue
            x1 = int(box["x1"] / w * width)
            y1 = int(box["y1"] / h * height)
            x2 = int(box["x2"] / w * width)
            y2 = int(box["y2"] / h * height)
            draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0))
        dst.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(dst)
    return dst


def mask_sample_image(
    sample_id: str, variant: str, stem: str, phrase: str, dst: Path
) -> dict[str, Any]:
    """Detect one phrase on one sample image and save the masked copy."""
    base = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / sample_id
    matches = sorted(base.glob(f"{stem}_{variant}.*"))
    if not matches:
        raise FileNotFoundError(f"No {stem}_{variant} image in {base}")
    src = matches[0]
    payload = detect(src, phrase)
    boxes = parse_sam_boxes(payload.get("output_text", ""))
    mask_image(src, boxes, dst)
    return {"src": str(src), "dst": str(dst), "phrase": phrase, "boxes": boxes}

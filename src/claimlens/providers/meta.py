"""Live Meta Model API provider (Muse Spark)."""

import base64
import html
import io
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, TypeAdapter

from claimlens import cache as replay_cache
from claimlens.schema import ReadingResult

MODEL = "muse-spark-1.3"
BASE_URL = "https://api.meta.ai/v1"
SCHEMA_NAME = "claimlens_reading"
IMAGE_LONG_SIDE = 1280


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None = None


def prepare_image(path: Path) -> bytes:
    """Downscale the long side to 1280 px and encode as JPEG bytes."""
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        rgb.thumbnail((IMAGE_LONG_SIDE, IMAGE_LONG_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def unescape_json(node: Any) -> Any:
    """Recursively HTML-unescape every string; run before schema validation."""
    if isinstance(node, str):
        return html.unescape(node)
    if isinstance(node, list):
        return [unescape_json(v) for v in node]
    if isinstance(node, dict):
        return {k: unescape_json(v) for k, v in node.items()}
    return node


def cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    """Cost from CLAIMLENS_USD_PER_1K_* rates; None when rates are not configured."""
    try:
        per_input = float(os.environ["CLAIMLENS_USD_PER_1K_INPUT"])
        per_output = float(os.environ["CLAIMLENS_USD_PER_1K_OUTPUT"])
    except (KeyError, ValueError):
        return None
    return round((input_tokens / 1000) * per_input + (output_tokens / 1000) * per_output, 6)


class MetaProvider:
    name = "meta"

    def __init__(self, api_key: str | None = None, model: str = MODEL):
        key = api_key or os.environ.get("META_API_KEY")
        if not key:
            raise RuntimeError(
                "META_API_KEY is not set. Put it in .env or use CLAIMLENS_PROVIDER=replay."
            )
        self.model = model
        self.calls: list[CallRecord] = []
        self._client = OpenAI(base_url=BASE_URL, api_key=key)

    def _request(self, blobs: list[bytes], instructions: str, schema: dict[str, Any]):
        content: list[dict[str, Any]] = [{"type": "input_text", "text": instructions}]
        for blob in blobs:
            b64 = base64.b64encode(blob).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"})
        return self._client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "schema": schema,
                    "strict": True,
                }
            },
            reasoning={"effort": "low"},
        )

    def read_documents(
        self,
        images: list[Path],
        instructions: str,
        schema: dict[str, Any],
        result_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        blobs = [prepare_image(p) for p in images]
        response = self._request(blobs, instructions, schema)
        usage = response.usage
        in_tokens = getattr(usage, "input_tokens", 0) or 0
        out_tokens = getattr(usage, "output_tokens", 0) or 0
        total = getattr(usage, "total_tokens", in_tokens + out_tokens) or 0
        key = replay_cache.cache_key(blobs, instructions, schema, self.model)
        replay_cache.store(
            key,
            {
                "model": self.model,
                "output_text": response.output_text,
                "usage": {
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "total_tokens": total,
                },
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        self.calls.append(
            CallRecord(
                model=self.model,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                total_tokens=total,
                cost_usd=cost_usd(in_tokens, out_tokens),
            )
        )
        data = unescape_json(json.loads(response.output_text))
        model = result_model or ReadingResult
        return TypeAdapter(model).validate_python(data).model_dump(mode="json")

    def write(self, instructions: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = self._request([], instructions, schema)
        return unescape_json(json.loads(response.output_text))

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
    reused: bool = False


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


def files_error_details(exc: Exception) -> dict[str, Any]:
    """HTTP status + message from an SDK error; status None when unknown."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return {"status": status, "message": str(exc)[:300]}


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

    def __init__(self, api_key: str | None = None, model: str = MODEL, live: bool = False):
        key = api_key or os.environ.get("META_API_KEY")
        if not key:
            raise RuntimeError(
                "META_API_KEY is not set. Put it in .env or use CLAIMLENS_PROVIDER=replay."
            )
        self.model = model
        self.live = live
        self.calls: list[CallRecord] = []
        self.last_files_error: dict[str, Any] | None = None
        self._client = OpenAI(base_url=BASE_URL, api_key=key)

    def _store(self, key: str, payload: dict[str, Any]) -> None:
        if self.live:
            replay_cache.store_live(key, payload)
        else:
            replay_cache.store(key, payload)

    def _reuse_any(self, keys: list[str]) -> dict[str, Any] | None:
        """Committed recording first, then live results; None when missing."""
        for key in keys:
            if replay_cache.exists(key):
                return replay_cache.load(key)
        for key in keys:
            try:
                return replay_cache.load_live(key)
            except replay_cache.CacheMissError:
                continue
        return None

    def _finish(
        self,
        payload: dict[str, Any],
        result_model: type[BaseModel] | None,
        default_model: type[BaseModel] | None,
    ) -> dict[str, Any]:
        usage = payload.get("usage", {})
        in_tokens = int(usage.get("input_tokens", 0))
        out_tokens = int(usage.get("output_tokens", 0))
        total = int(usage.get("total_tokens", in_tokens + out_tokens))
        self.calls.append(
            CallRecord(
                model=payload.get("model", self.model),
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                total_tokens=total,
                cost_usd=cost_usd(in_tokens, out_tokens),
                reused=True,
            )
        )
        data = unescape_json(json.loads(payload["output_text"]))
        model = result_model or default_model
        if model is None:
            return data
        return TypeAdapter(model).validate_python(data).model_dump(mode="json")

    def _resolve_file_ids(self, blobs: list[bytes]) -> list[str] | None:
        """Upload-once file ids for every blob, or None when uploads fail."""
        try:
            index = replay_cache.load_files_index()
            file_ids = []
            for blob in blobs:
                sha = replay_cache.blob_sha(blob)
                if sha not in index:
                    created = self._client.files.create(
                        file=(f"claimlens-{sha[:12]}.jpg", blob, "image/jpeg"),
                        purpose="vision",
                    )
                    replay_cache.store_file_id(sha, created.id)
                    index[sha] = created.id
                file_ids.append(index[sha])
        except Exception as exc:  # noqa: BLE001 - any upload failure means base64
            self.last_files_error = {"stage": "upload", **files_error_details(exc)}
            return None
        return file_ids

    def _request(
        self,
        blobs: list[bytes],
        instructions: str,
        schema: dict[str, Any],
        file_ids: list[str] | None = None,
    ):
        content: list[dict[str, Any]] = [{"type": "input_text", "text": instructions}]
        if file_ids is not None:
            for file_id in file_ids:
                content.append({"type": "input_image", "file_id": file_id})
        else:
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
        if self.live:
            keys = [replay_cache.cache_key(blobs, instructions, schema, self.model)]
            index = replay_cache.load_files_index()
            shas = [replay_cache.blob_sha(b) for b in blobs]
            if blobs and all(s in index for s in shas):
                keys.append(
                    replay_cache.cache_key(
                        replay_cache.file_key_bytes([index[s] for s in shas]),
                        instructions,
                        schema,
                        self.model,
                    )
                )
            payload = self._reuse_any(keys)
            if payload is not None:
                return self._finish(payload, result_model, ReadingResult)
        self.last_files_error = None
        file_ids = self._resolve_file_ids(blobs) if blobs else None
        refs: list[dict[str, str]] | None = None
        if file_ids is not None:
            key = replay_cache.cache_key(
                replay_cache.file_key_bytes(file_ids), instructions, schema, self.model
            )
            try:
                response = self._request(blobs, instructions, schema, file_ids=file_ids)
            except Exception as exc:  # noqa: BLE001 - file refs rejected; retry as base64
                self.last_files_error = {"stage": "read", **files_error_details(exc)}
                for blob in blobs:
                    replay_cache.drop_file_id(replay_cache.blob_sha(blob))
                file_ids = None
            else:
                refs = [{"type": "file", "id": file_id} for file_id in file_ids]
        if file_ids is None:
            key = replay_cache.cache_key(blobs, instructions, schema, self.model)
            response = self._request(blobs, instructions, schema)
            refs = [{"type": "base64", "sha256": replay_cache.blob_sha(b)} for b in blobs]
        usage = response.usage
        in_tokens = getattr(usage, "input_tokens", 0) or 0
        out_tokens = getattr(usage, "output_tokens", 0) or 0
        total = getattr(usage, "total_tokens", in_tokens + out_tokens) or 0
        self._store(
            key,
            {
                "model": self.model,
                "output_text": response.output_text,
                "usage": {
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "total_tokens": total,
                },
                "input_refs": refs,
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

    def write(
        self,
        instructions: str,
        schema: dict[str, Any],
        result_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        key = replay_cache.cache_key([], instructions, schema, self.model)
        if self.live:
            payload = self._reuse_any([key])
            if payload is not None:
                return self._finish(payload, result_model, None)
        response = self._request([], instructions, schema)
        usage = response.usage
        in_tokens = getattr(usage, "input_tokens", 0) or 0
        out_tokens = getattr(usage, "output_tokens", 0) or 0
        total = getattr(usage, "total_tokens", in_tokens + out_tokens) or 0
        self._store(
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
        if result_model is None:
            return data
        return TypeAdapter(result_model).validate_python(data).model_dump(mode="json")

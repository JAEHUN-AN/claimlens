"""Replay provider: serves recorded responses from cache/ with no network or key."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from claimlens import cache as replay_cache
from claimlens.providers.meta import MODEL, CallRecord, cost_usd, prepare_image, unescape_json
from claimlens.schema import ReadingResult


class ReplayProvider:
    name = "replay"

    def __init__(self, model: str = MODEL):
        self.model = model
        self.calls: list[CallRecord] = []

    def read_documents(
        self,
        images: list[Path],
        instructions: str,
        schema: dict[str, Any],
        result_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        blobs = [prepare_image(p) for p in images]
        index = replay_cache.load_files_index()
        shas = [replay_cache.blob_sha(b) for b in blobs]
        if blobs and all(s in index for s in shas):
            key = replay_cache.cache_key(
                replay_cache.file_key_bytes([index[s] for s in shas]),
                instructions,
                schema,
                self.model,
            )
        else:
            key = replay_cache.cache_key(blobs, instructions, schema, self.model)
        payload = replay_cache.load(key)
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
            )
        )
        data = unescape_json(json.loads(payload["output_text"]))
        model = result_model or ReadingResult
        return TypeAdapter(model).validate_python(data).model_dump(mode="json")

    def write(
        self,
        instructions: str,
        schema: dict[str, Any],
        result_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        key = replay_cache.cache_key([], instructions, schema, self.model)
        payload = replay_cache.load(key)
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
            )
        )
        data = unescape_json(json.loads(payload["output_text"]))
        if result_model is None:
            return data
        return TypeAdapter(result_model).validate_python(data).model_dump(mode="json")

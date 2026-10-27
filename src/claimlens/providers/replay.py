"""Replay provider: serves recorded responses from cache/ with no network or key."""

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from claimlens import cache as replay_cache
from claimlens.providers.meta import MODEL, prepare_image, unescape_json
from claimlens.schema import ReadingResult


class ReplayProvider:
    name = "replay"

    def __init__(self, model: str = MODEL):
        self.model = model
        self.calls: list = []

    def read_documents(
        self, images: list[Path], instructions: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        blobs = [prepare_image(p) for p in images]
        key = replay_cache.cache_key(blobs, instructions, schema, self.model)
        payload = replay_cache.load(key)
        data = unescape_json(json.loads(payload["output_text"]))
        return TypeAdapter(ReadingResult).validate_python(data).model_dump(mode="json")

    def write(self, instructions: str, schema: dict[str, Any]) -> dict[str, Any]:
        key = replay_cache.cache_key([], instructions, schema, self.model)
        payload = replay_cache.load(key)
        return unescape_json(json.loads(payload["output_text"]))

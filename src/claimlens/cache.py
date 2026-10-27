"""Replay cache: recorded raw model responses keyed by sha256 of the request."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class CacheMissError(LookupError):
    """Raised when no recorded response matches a replayed request."""


def cache_dir() -> Path:
    return Path(os.environ.get("CLAIMLENS_CACHE_DIR", "cache"))


def cache_key(
    image_blobs: list[bytes], instructions: str, schema: dict[str, Any], model: str
) -> str:
    """Hash of prepared image bytes + instructions + schema + model name."""
    digest = hashlib.sha256()
    for blob in image_blobs:
        digest.update(blob)
    digest.update(instructions.encode("utf-8"))
    digest.update(
        json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    digest.update(model.encode("utf-8"))
    return digest.hexdigest()


def cache_path(key: str) -> Path:
    return cache_dir() / f"{key}.json"


def store(key: str, payload: dict[str, Any]) -> Path:
    path = cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(key: str) -> dict[str, Any]:
    path = cache_path(key)
    if not path.exists():
        raise CacheMissError(
            f"No cached response for key {key} ({path}). "
            "Run once with the live provider to record it."
        )
    return json.loads(path.read_text(encoding="utf-8"))

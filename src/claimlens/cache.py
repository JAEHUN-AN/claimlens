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


def files_index_path(live: bool = False) -> Path:
    """Live runs remember file ids under live/ so committed cache stays fixed."""
    base = live_dir() if live else cache_dir()
    return base / "files_index.json"


def load_files_index(live: bool = False) -> dict[str, str]:
    """Maps prepared-image sha256 to the uploaded file id ({} when absent)."""
    path = files_index_path(live)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def store_file_id(blob_sha: str, file_id: str, live: bool = False) -> None:
    path = files_index_path(live)
    index = load_files_index(live)
    index[blob_sha] = file_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def drop_file_id(blob_sha: str, live: bool = False) -> None:
    index = load_files_index(live)
    if blob_sha in index:
        del index[blob_sha]
        files_index_path(live).write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )


def blob_sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def file_key_bytes(file_ids: list[str]) -> list[bytes]:
    """Cache-key input for file-referenced images (record and replay agree)."""
    return [f"file:{file_id}".encode() for file_id in file_ids]


def store(key: str, payload: dict[str, Any]) -> Path:
    path = cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def exists(key: str) -> bool:
    """True when a committed recording exists for the key."""
    return cache_path(key).exists()


def live_dir() -> Path:
    return cache_dir() / "live"


def live_path(key: str) -> Path:
    return live_dir() / f"{key}.json"


def store_live(key: str, payload: dict[str, Any]) -> Path:
    """Store a live-mode result beside (never over) committed recordings."""
    path = live_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_live(key: str) -> dict[str, Any]:
    path = live_path(key)
    if not path.exists():
        raise CacheMissError(f"No live result for key {key} ({path}).")
    return json.loads(path.read_text(encoding="utf-8"))


def load(key: str) -> dict[str, Any]:
    path = cache_path(key)
    if not path.exists():
        raise CacheMissError(
            f"No cached response for key {key} ({path}). "
            "Run once with the live provider to record it."
        )
    return json.loads(path.read_text(encoding="utf-8"))

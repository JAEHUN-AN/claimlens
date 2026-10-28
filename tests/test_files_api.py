"""Files API upload-once with base64 fallback (stub client, no network)."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from claimlens import cache as repo_cache
from claimlens.providers.meta import MetaProvider
from claimlens.providers.replay import ReplayProvider


class _StubFiles:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.uploads: list[bytes] = []

    def create(self, file: Any, purpose: str):
        assert purpose == "vision"
        if self.fail:
            raise RuntimeError("files api rejects images")
        self.uploads.append(file[1])
        return SimpleNamespace(id=f"file-{len(self.uploads)}")


class _StubResponses:
    def __init__(self, fail_on_file_ids: bool = False):
        self.fail_on_file_ids = fail_on_file_ids
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        parts = kwargs["input"][0]["content"][1:]
        if self.fail_on_file_ids and any("file_id" in p for p in parts):
            raise RuntimeError("file_id image parts rejected")
        return SimpleNamespace(
            output_text=json.dumps({"ok": True}),
            usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12),
        )


class _StubClient:
    def __init__(self, files_fail: bool = False, responses_fail_on_file_ids: bool = False):
        self.files = _StubFiles(fail=files_fail)
        self.responses = _StubResponses(fail_on_file_ids=responses_fail_on_file_ids)


class _TinyResult(BaseModel):
    ok: bool


def _image() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "samples"
        / "S2_seoul_worker_bronchitis"
        / "receipt_photo.jpg"
    )


def _provider(monkeypatch, tmp_path, **stub_kwargs) -> MetaProvider:
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path))
    provider = MetaProvider(api_key="test-key")
    provider._client = _StubClient(**stub_kwargs)
    return provider


def test_file_path_records_ids_and_replays(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path)
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert len(provider._client.files.uploads) == 1
    parts = provider._client.responses.calls[0]["input"][0]["content"][1:]
    assert parts == [{"type": "input_image", "file_id": "file-1"}]
    index = repo_cache.load_files_index()
    assert list(index.values()) == ["file-1"]
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["input_refs"] == [{"type": "file", "id": "file-1"}]
    replayed = ReplayProvider().read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert replayed == {"ok": True}


def test_upload_failure_falls_back_to_base64(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path, files_fail=True)
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert provider._client.files.uploads == []
    parts = provider._client.responses.calls[0]["input"][0]["content"][1:]
    assert len(parts) == 1 and parts[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert repo_cache.load_files_index() == {}
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["input_refs"][0]["type"] == "base64"
    from claimlens.providers.meta import prepare_image

    expected = repo_cache.cache_key(
        [prepare_image(_image())], "read", {"type": "object"}, provider.model
    )
    assert repo_cache.cache_path(expected).exists()


def test_file_id_rejection_retries_once_as_base64(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path, responses_fail_on_file_ids=True)
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert len(provider._client.responses.calls) == 2
    assert repo_cache.load_files_index() == {}
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["input_refs"][0]["type"] == "base64"


def test_upload_once_reuses_ids(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path)
    provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert len(provider._client.files.uploads) == 1

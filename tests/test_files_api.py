"""Files API upload-once with base64 fallback (stub client, no network)."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from claimlens import cache as repo_cache
from claimlens.providers.meta import MetaProvider
from claimlens.providers.replay import ReplayProvider


class _StatusError(Exception):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


class _StubFiles:
    def __init__(self, fail: bool = False, error: Exception | None = None):
        self.fail = fail
        self.error = error
        self.uploads: list[bytes] = []

    def create(self, file: Any, purpose: str):
        assert purpose == "user_data"
        if self.error is not None:
            raise self.error
        if self.fail:
            raise RuntimeError("files api rejects images")
        self.uploads.append(file[1])
        return SimpleNamespace(id=f"file-{len(self.uploads)}")


class _StubResponses:
    def __init__(
        self,
        fail_on_file_ids: bool = False,
        fail_file_parts: tuple[str, ...] = (),
        output: Any = None,
    ):
        self.fail_on_file_ids = fail_on_file_ids
        self.fail_file_parts = set(fail_file_parts)
        self.output = {"ok": True} if output is None else output
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        parts = kwargs["input"][0]["content"][1:]
        if self.fail_on_file_ids and any("file_id" in p for p in parts):
            raise RuntimeError("file_id image parts rejected")
        if any("file_id" in p and p.get("type") in self.fail_file_parts for p in parts):
            raise RuntimeError("input_image file_id parts rejected")
        return SimpleNamespace(
            output_text=json.dumps(self.output),
            usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12),
        )


class _StubClient:
    def __init__(
        self,
        files_fail: bool = False,
        files_error: Exception | None = None,
        responses_fail_on_file_ids: bool = False,
        fail_file_parts: tuple[str, ...] = (),
        output: Any = None,
    ):
        self.files = _StubFiles(fail=files_fail, error=files_error)
        self.responses = _StubResponses(
            fail_on_file_ids=responses_fail_on_file_ids,
            fail_file_parts=fail_file_parts,
            output=output,
        )


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


def _probe_provider(**stub_kwargs) -> MetaProvider:
    provider = MetaProvider(api_key="test-key")
    provider._client = _StubClient(output={"documents": []}, **stub_kwargs)
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
    assert payload["input_refs"] == [{"type": "file", "part": "input_image", "id": "file-1"}]
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


def test_file_id_rejection_tries_input_file_then_base64(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path, responses_fail_on_file_ids=True)
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert len(provider._client.responses.calls) == 3
    second = provider._client.responses.calls[1]["input"][0]["content"][1:]
    assert second == [{"type": "input_file", "file_id": "file-1"}]
    assert repo_cache.load_files_index() == {}
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["input_refs"][0]["type"] == "base64"


def test_upload_once_reuses_ids(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path)
    provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert len(provider._client.files.uploads) == 1


def test_probe_files_reports_file_path_and_stays_out_of_cache(tmp_path):
    from claimlens.probe import probe_files

    out = tmp_path / "probe"
    summary = probe_files(_image(), out, lambda: _probe_provider())
    assert summary["files_api"] == "works"
    assert summary["input"] == "file"
    assert summary["file_part"] == "input_image"
    assert summary["files_error"] is None
    assert summary["documents"] == 0
    assert summary["tokens"]["total_tokens"] == 12
    names = sorted(p.name for p in out.glob("*.json"))
    assert len(names) == 3
    assert "probe_result.json" in names and "files_index.json" in names
    assert os.environ.get("CLAIMLENS_CACHE_DIR") is None


def test_probe_files_reports_unavailable_on_upload_failure(tmp_path):
    from claimlens.probe import probe_files

    out = tmp_path / "probe"
    summary = probe_files(_image(), out, lambda: _probe_provider(files_fail=True))
    assert summary["files_api"] == "unavailable"
    assert summary["input"] == "base64"


def test_probe_files_rejects_missing_image(tmp_path):
    from claimlens.probe import probe_files

    with pytest.raises(ValueError, match="Not an image file"):
        probe_files(tmp_path / "nope.jpg", tmp_path / "probe", lambda: _probe_provider())


def test_upload_failure_records_status_and_message(monkeypatch, tmp_path):
    err = _StatusError(400, "purpose user_data does not accept images")
    provider = _provider(monkeypatch, tmp_path, files_error=err)
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert provider.last_files_error == {
        "stage": "upload",
        "status": 400,
        "message": "purpose user_data does not accept images",
    }


def test_file_id_rejection_records_each_read_error(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path, responses_fail_on_file_ids=True)
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert provider.last_files_error == {
        "stage": "read",
        "attempts": [
            {
                "part": "input_image",
                "status": None,
                "message": "file_id image parts rejected",
            },
            {
                "part": "input_file",
                "status": None,
                "message": "file_id image parts rejected",
            },
        ],
    }


def test_input_file_part_used_when_input_image_rejected(monkeypatch, tmp_path):
    provider = _provider(monkeypatch, tmp_path, fail_file_parts=("input_image",))
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert len(provider._client.responses.calls) == 2
    assert provider.last_files_error is None
    payload = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert payload["input_refs"] == [{"type": "file", "part": "input_file", "id": "file-1"}]


def test_live_provider_remembers_file_ids_under_live_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path))
    provider = MetaProvider(api_key="test-key", live=True)
    provider._client = _StubClient(output={"ok": True})
    out = provider.read_documents([_image()], "read", {"type": "object"}, _TinyResult)
    assert out == {"ok": True}
    assert not (tmp_path / "files_index.json").exists()
    assert list(tmp_path.glob("*.json")) == []
    assert (tmp_path / "live" / "files_index.json").exists()


def test_probe_files_records_failure_reason(tmp_path):
    from claimlens.probe import probe_files

    err = _StatusError(400, "purpose user_data does not accept images")
    out = tmp_path / "probe"
    summary = probe_files(_image(), out, lambda: _probe_provider(files_error=err))
    assert summary["files_api"] == "unavailable"
    assert summary["files_error"] == {
        "stage": "upload",
        "status": 400,
        "message": "purpose user_data does not accept images",
    }
    saved = json.loads((out / "probe_result.json").read_text(encoding="utf-8"))
    assert saved["files_error"]["status"] == 400

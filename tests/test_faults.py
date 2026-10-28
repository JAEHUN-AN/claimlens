"""Fault injection: every failure pins an outcome that is never a wrong number."""

import base64
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from claimlens import faults
from claimlens.engine import replay_reading
from claimlens.prompts import READING_INSTRUCTIONS
from claimlens.providers.meta import CallRecord, MetaProvider
from claimlens.reader import reading_schema

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def _status_error(code):
    request = SimpleNamespace(method="POST", url="https://api.meta.ai/v1/responses")
    response = SimpleNamespace(status_code=code, headers={}, request=request)
    return APIStatusError(f"{code} error", response=response, body=None)


def _timeout_error():
    return APITimeoutError(request=SimpleNamespace(method="POST"))


def _connection_error():
    return APIConnectionError(message="down", request=SimpleNamespace(method="POST"))


def _ok_response(payload):
    return SimpleNamespace(
        output_text=json.dumps(payload),
        usage=SimpleNamespace(input_tokens=5, output_tokens=1, total_tokens=6),
    )


class _ScriptedClient:
    """Fake responses client playing back results or raising errors."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.bodies = []
        self.responses = self

    def create(self, **kwargs):
        self.calls += 1
        self.bodies.append(kwargs)
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _provider(script, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    provider = MetaProvider(api_key="test-key", live=False)
    client = _ScriptedClient(script)
    provider._client = client
    provider._resolve_file_ids = lambda blobs: None
    return provider, client


def _photo():
    return SAMPLES / "S2_seoul_worker_bronchitis" / "receipt_photo.jpg"


def test_fault_spark_timeout(tmp_path, monkeypatch):
    provider, client = _provider([_timeout_error()], tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="Spark request failed"):
        provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert client.calls == 1
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_fault_429_recovers(tmp_path, monkeypatch):
    ok = _ok_response({"documents": []})
    provider, client = _provider([_status_error(429), _status_error(429), ok],
                                 tmp_path, monkeypatch)
    sleeps = []
    monkeypatch.setattr("claimlens.providers.meta._backoff_sleep", sleeps.append)
    result = provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert result == {"documents": []}
    assert client.calls == 3
    assert sleeps == [1.0, 2.0]


def test_fault_429_stops(tmp_path, monkeypatch):
    provider, client = _provider([_status_error(429)] * 3, tmp_path, monkeypatch)
    sleeps = []
    monkeypatch.setattr("claimlens.providers.meta._backoff_sleep", sleeps.append)
    with pytest.raises(RuntimeError, match="Spark request failed"):
        provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert client.calls == 3
    assert sleeps == [1.0, 2.0]


def test_fault_500_stops(tmp_path, monkeypatch):
    provider, client = _provider([_status_error(500)], tmp_path, monkeypatch)
    sleeps = []
    monkeypatch.setattr("claimlens.providers.meta._backoff_sleep", sleeps.append)
    with pytest.raises(RuntimeError, match="Spark request failed"):
        provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert client.calls == 1
    assert sleeps == []


def test_fault_connection_error_stops(tmp_path, monkeypatch):
    provider, client = _provider([_connection_error()], tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="Spark request failed"):
        provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert client.calls == 1


def _bad_output_provider(output_text, tmp_path, monkeypatch):
    response = _ok_response({})
    response.output_text = output_text
    provider, _ = _provider([response], tmp_path, monkeypatch)
    return provider


def test_fault_bad_json(tmp_path, monkeypatch):
    for broken in ('{"documents": oops', '{"documents": [{"doc_type": "rece'):
        provider = _bad_output_provider(broken, tmp_path, monkeypatch)
        with pytest.raises(RuntimeError, match="unusable output"):
            provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_fault_schema_violation(tmp_path, monkeypatch):
    provider = _bad_output_provider('{"documents": [{"doc_type": "receipt", "total_amount": "lots"}]}',
                                    tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="broke the schema"):
        provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_fault_empty_output(tmp_path, monkeypatch):
    provider = _bad_output_provider("", tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="unusable output"):
        provider.read_documents([_photo()], READING_INSTRUCTIONS, reading_schema())
    assert list((tmp_path / "cache").glob("*.json")) == []


def test_fault_files_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    provider = MetaProvider(api_key="test-key", live=False)
    client = _ScriptedClient([_ok_response({"documents": []})])
    client.files = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(
        _status_error(500)))
    provider._client = client
    images = [_photo(), SAMPLES / "S2_seoul_worker_bronchitis" / "medical_certificate_photo.jpg"]
    result = provider.read_documents(images, READING_INSTRUCTIONS, reading_schema())
    assert result == {"documents": []}
    assert provider.last_files_error is not None
    assert provider.last_files_error["status"] == 500
    sent = client.bodies[0]["input"][0]["content"]
    assert any(part.get("image_url", "").startswith("data:image/jpeg;base64,") for part in sent)


class _Stub:
    name = "stub"

    def __init__(self, readings):
        self._readings = list(readings)
        self.calls = []

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=0,
                                     total_tokens=100, cost_usd=None))
        if result_model is not None:
            return {}
        if len(self._readings) > 1:
            return copy.deepcopy(self._readings.pop(0))
        return copy.deepcopy(self._readings[0])

    def write(self, instructions, schema, result_model=None):
        self.calls.append(CallRecord(model="stub", input_tokens=50, output_tokens=0,
                                     total_tokens=50, cost_usd=None))
        return {"findings": []}


def _images(*names):
    out = []
    for sample, name in names:
        blob = (SAMPLES / sample / name).read_bytes()
        out.append({"name": name, "data": base64.b64encode(blob).decode("ascii")})
    return out


def _run(handler, body):
    raw = json.dumps(body).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json", "origin": ""}
    return handler.route_post("/api/run", raw, len(raw), headers, 8000)


def _person(sample_id):
    scenarios = json.loads((SAMPLES / "scenarios_inbound.json").read_text(encoding="utf-8"))
    return next(s for s in scenarios["scenarios"] if s["id"] == sample_id)["person"]


def test_fault_neo4j_engine(monkeypatch):
    from claimlens import serve

    reading = replay_reading("S2_seoul_worker_bronchitis", "photo")
    monkeypatch.setattr(serve, "live_provider", lambda: _Stub([reading]))
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    images = _images(("S2_seoul_worker_bronchitis", "receipt_photo.jpg"),
                     ("S2_seoul_worker_bronchitis", "medical_certificate_photo.jpg"))
    status, result = _run(serve, {"images": images, "person": _person("S2_seoul_worker_bronchitis")})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert "Neo4j" in result["result"]["title"]


def test_fault_pack_without_neo4j(monkeypatch):
    from claimlens import serve

    class _PackStub(_Stub):
        def write(self, instructions, schema, result_model=None):
            self.calls.append(CallRecord(model="stub", input_tokens=50, output_tokens=0,
                                         total_tokens=50, cost_usd=None))
            labels = [line[2:] for line in instructions.splitlines() if line.startswith("- ")]
            return {"findings": [], "labels": [{"ko": label, "en": label} for label in labels]}

    reading = replay_reading("S3_us_tourist_hip_fracture", "photo")
    monkeypatch.setattr(serve, "live_provider", lambda: _PackStub([reading]))
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    images = _images(("S3_us_tourist_hip_fracture", "receipt_photo.jpg"),
                     ("S3_us_tourist_hip_fracture", "medical_certificate_photo.jpg"))
    status, result = _run(serve, {"images": images, "person": _person("S3_us_tourist_hip_fracture")})
    assert status == 200
    assert result["result"]["badge"] == "claim_pack"
    assert result["matched_sample"] == "S3_us_tourist_hip_fracture"


def test_fault_serve_offline():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    harness = str(Path(__file__).with_name("fault_smoke.mjs")).removeprefix("\\\\?\\")
    page = str(ROOT / "docs" / "demo.html").removeprefix("\\\\?\\")
    proc = subprocess.run([node, harness, page], check=False, capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def test_fault_oversized_upload(monkeypatch):
    from claimlens import serve

    monkeypatch.setattr(serve, "live_provider", lambda: _Stub([{}]))
    # 10.2 MB decoded (over the limit) but under the 14 MB body cap.
    big = base64.b64encode(b"\xff\xd8\xff" + bytes(5_346_273)).decode("ascii")
    body = {"images": [{"name": "a.jpg", "data": big}, {"name": "b.jpg", "data": big}]}
    status, result = _run(serve, body)
    assert status == 400
    assert "10 MB" in result["error"]


def test_fault_non_image_upload(monkeypatch):
    from claimlens import serve

    monkeypatch.setattr(serve, "live_provider", lambda: _Stub([{}]))
    text = base64.b64encode(b"not an image at all" * 100).decode("ascii")
    body = {"images": [{"name": "note.txt", "data": text},
                       {"name": "receipt.jpg", "data": base64.b64encode(
                           (SAMPLES / "S2_seoul_worker_bronchitis" / "receipt_photo.jpg"
                            ).read_bytes()).decode("ascii")}]}
    status, result = _run(serve, body)
    assert status == 400
    assert "note.txt" in result["error"]


def test_fault_gate_single_failure(monkeypatch):
    from claimlens import serve

    class _Flaky(_Stub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            if result_model is None and cache_tag:
                raise RuntimeError("Spark request failed: timed out")
            return super().read_documents(images, instructions, schema, result_model,
                                          cache_tag=cache_tag)

    reading = replay_reading("S2_seoul_worker_bronchitis", "photo")
    monkeypatch.setattr(serve, "live_provider", lambda: _Flaky([reading]))
    images = _images(("S2_seoul_worker_bronchitis", "receipt_photo.jpg"),
                     ("S2_seoul_worker_bronchitis", "medical_certificate_photo.jpg"))
    status, result = _run(serve, {"images": images, "person": _person("S2_seoul_worker_bronchitis")})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert "alone cannot pass" in result["questions"][0]["question"]
    assert "run_id" not in result


def test_fault_gate_doc_count(monkeypatch):
    from claimlens import serve

    base = replay_reading("S2_seoul_worker_bronchitis", "photo")
    tripled = copy.deepcopy(base)
    tripled["documents"].append(copy.deepcopy(base["documents"][0]))

    class _CountSplit(_Stub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            if result_model is None and cache_tag:
                self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=0,
                                             total_tokens=100, cost_usd=None))
                return copy.deepcopy(tripled)
            return super().read_documents(images, instructions, schema, result_model,
                                          cache_tag=cache_tag)

    monkeypatch.setattr(serve, "live_provider", lambda: _CountSplit([base]))
    images = _images(("S2_seoul_worker_bronchitis", "receipt_photo.jpg"),
                     ("S2_seoul_worker_bronchitis", "medical_certificate_photo.jpg"))
    status, result = _run(serve, {"images": images, "person": _person("S2_seoul_worker_bronchitis")})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert result["questions"][0]["question"].startswith("documents:")


def test_fault_spark_timeout_serves_503(monkeypatch):
    from claimlens import serve

    class _Down(_Stub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            raise RuntimeError("Spark request failed: timed out")

    monkeypatch.setattr(serve, "live_provider", lambda: _Down([{}]))
    images = _images(("S2_seoul_worker_bronchitis", "receipt_photo.jpg"),
                     ("S2_seoul_worker_bronchitis", "medical_certificate_photo.jpg"))
    status, result = _run(serve, {"images": images, "person": _person("S2_seoul_worker_bronchitis")})
    assert status == 503
    assert "Both reads failed" in result["error"]


def test_every_fault_has_its_tests():
    module = sys.modules[__name__]
    for entry in faults.FAULTS:
        for node in entry["tests"]:
            name = node.split("::")[1]
            assert callable(getattr(module, name, None)), node


def test_readme_matches_generated_table():
    assert faults.render_table().rstrip("\n") in ROOT.joinpath("README.md").read_text(
        encoding="utf-8").replace("\r\n", "\n")

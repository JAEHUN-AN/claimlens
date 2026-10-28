"""Load check: plan-only default, byte-varying, percentile math, stub E2E."""

import base64
import copy
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import APIStatusError

from claimlens import load as load_mod
from claimlens.cli import main
from claimlens.engine import replay_reading
from claimlens.hard_eval import EVAL_MD_COSTS
from claimlens.providers.meta import CallRecord, MetaProvider

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "samples" / "live"


def test_load_plan_prints_and_stops(capsys, tmp_path):
    assert main(["load", "--output", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "5 concurrent live runs" in out
    assert "35 calls" in out
    assert "Stopped before any API call" in out
    assert list(tmp_path.iterdir()) == []


def test_load_plan_estimate_uses_committed_costs():
    text = load_mod.estimate_text(5)
    lo, hi = min(EVAL_MD_COSTS), max(EVAL_MD_COSTS)
    assert f"${35 * lo:.2f}" in text and f"${35 * hi:.2f}" in text


def test_vary_bytes_distinct_valid_jpeg(tmp_path):
    from claimlens.providers.meta import prepare_image

    blob = (LIVE / "S2_receipt_retake.jpg").read_bytes()
    variants = [load_mod.vary_bytes(blob, run) for run in range(5)]
    assert len(set(variants)) == 5
    assert all(v.startswith(b"\xff\xd8\xff") for v in variants)
    assert load_mod.vary_bytes(blob, 2) == variants[2]
    from PIL import Image

    with Image.open(io.BytesIO(variants[0])) as img:
        img.verify()
    prepared = set()
    for pos, variant in enumerate(variants):
        path = tmp_path / f"v{pos}.jpg"
        path.write_bytes(variant)
        prepared.add(prepare_image(path))
    assert len(prepared) == 5


def test_percentile_math():
    assert load_mod.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0
    assert load_mod.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 95) == pytest.approx(4.8)
    assert load_mod.percentile([2.5], 95) == 2.5


def test_summarize_math():
    records = [
        {"seconds": s, "cost_usd": 0.01, "retries_429": 0, "coherent": True}
        for s in (1.0, 2.0, 3.0, 4.0, 5.0)
    ]
    summary = load_mod.summarize(records)
    assert summary["p50_s"] == 3.0
    assert summary["p95_s"] == pytest.approx(4.8)
    assert summary["mean_cost_usd"] == pytest.approx(0.01)
    assert summary["total_cost_usd"] == pytest.approx(0.05)
    assert summary["all_coherent"] is True


def test_execute_refuses_past_max_cost(tmp_path):
    with pytest.raises(RuntimeError, match="--max-cost"):
        load_mod.execute(5, 0.01, tmp_path, LIVE)
    assert list(tmp_path.iterdir()) == []


class _Stub:
    name = "stub"

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=0,
                                     total_tokens=100, cost_usd=None))
        if result_model is not None:
            return {}
        return copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))

    def write(self, instructions, schema, result_model=None):
        self.calls.append(CallRecord(model="stub", input_tokens=50, output_tokens=0,
                                     total_tokens=50, cost_usd=None))
        return {"findings": []}

    def __init__(self):
        self.calls = []


def test_execute_stub_end_to_end(tmp_path, monkeypatch):
    from claimlens import serve

    monkeypatch.setattr(serve, "live_provider", lambda: _Stub())
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)

    def _direct(body):
        raw = json.dumps(body).encode("utf-8")
        headers = {"host": "127.0.0.1:8000", "content_type": "application/json",
                   "origin": ""}
        return serve.route_post("/api/run", raw, len(raw), headers, 8000)

    report = load_mod.execute(2, 2.00, tmp_path, LIVE, poster=_direct)
    assert report["runs"] == 2
    assert report["all_coherent"] is True
    assert all(r["status"] == 200 for r in report["results"])
    assert all(r["badge"] == "engine_unreachable" for r in report["results"])
    assert report["p50_s"] > 0
    files = list(tmp_path.glob("load_*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["runs"] == 2
    before = subprocess.run(["git", "-c", "safe.directory=C:/hack/claimlens",
                             "status", "--porcelain", "cache/"],
                            check=False, capture_output=True, text=True, cwd=ROOT).stdout
    assert before.strip() == ""


def test_execute_cli_refusal_is_exit_2(capsys, tmp_path):
    assert main(["load", "--execute", "--max-cost", "0.01",
                 "--output", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_serve_reports_cost_and_retries(monkeypatch):
    from claimlens import serve

    class _Priced(_Stub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=0,
                                         total_tokens=100, cost_usd=0.02))
            self.calls.append(CallRecord(model="stub", input_tokens=10, output_tokens=0,
                                         total_tokens=10, cost_usd=0.99, reused=True))
            if result_model is not None:
                return {}
            return copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))

    def _make():
        stub = _Priced()
        stub.retries_429 = 3
        return stub

    monkeypatch.setattr(serve, "live_provider", _make)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    images = []
    for name in ("receipt_photo.jpg", "medical_certificate_photo.jpg"):
        blob = (ROOT / "samples" / "S2_seoul_worker_bronchitis" / name).read_bytes()
        images.append({"name": name, "data": base64.b64encode(blob).decode("ascii")})
    from claimlens.engine import load_scenarios

    person = load_scenarios()[0]["S2_seoul_worker_bronchitis"]["person"]
    raw = json.dumps({"images": images, "person": person}).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json", "origin": ""}
    status, result = serve.route_post("/api/run", raw, len(raw), headers, 8000)
    assert status == 200
    assert result["cost_usd"] == pytest.approx(0.04)
    assert result["retries_429"] == 6


def test_provider_counts_429_retries(tmp_path, monkeypatch):
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("claimlens.providers.meta._backoff_sleep", lambda s: None)
    response = SimpleNamespace(
        output_text=json.dumps({"documents": []}),
        usage=SimpleNamespace(input_tokens=5, output_tokens=1, total_tokens=6),
    )
    request = SimpleNamespace(method="POST")
    error = APIStatusError("429", response=SimpleNamespace(status_code=429, headers={},
                                                           request=request), body=None)

    class _Client:
        def __init__(self):
            self.responses = self
            self.planned = [error, response]

        def create(self, **kwargs):
            action = self.planned.pop(0)
            if isinstance(action, Exception):
                raise action
            return action

    provider = MetaProvider(api_key="test-key", live=False)
    provider._client = _Client()
    provider._resolve_file_ids = lambda blobs: None
    photo = ROOT / "samples" / "S2_seoul_worker_bronchitis" / "receipt_photo.jpg"
    assert provider.read_documents([photo], READING_INSTRUCTIONS,
                                   reading_schema()) == {"documents": []}
    assert provider.retries_429 == 1

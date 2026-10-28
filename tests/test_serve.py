"""Live server endpoints with a stub provider (no sockets by default)."""

import base64
import copy
import http.client
import json
import socket
from pathlib import Path

import pytest

from claimlens import serve
from claimlens.engine import replay_reading
from claimlens.providers.meta import CallRecord


class StubProvider:
    name = "stub"
    model = "stub"

    def __init__(self, reused: bool = False):
        self.calls: list[CallRecord] = []
        self._reused = reused

    def _log(self, total: int):
        self.calls.append(
            CallRecord(model=self.model, input_tokens=total, output_tokens=0,
                       total_tokens=total, cost_usd=None, reused=self._reused)
        )

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        self._log(100)
        return copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))

    def write(self, instructions, schema, result_model=None):
        self._log(50)
        return {"findings": []}


@pytest.fixture()
def stubbed(monkeypatch):
    monkeypatch.setattr(serve, "live_provider", StubProvider)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    return serve


def _sample_images() -> list[dict[str, str]]:
    root = Path(__file__).resolve().parent.parent / "samples" / "S2_seoul_worker_bronchitis"
    out = []
    for name in ("receipt_photo.jpg", "medical_certificate_photo.jpg"):
        blob = (root / name).read_bytes()
        out.append({"name": name, "data": base64.b64encode(blob).decode("ascii")})
    return out


def _retake_images() -> list[dict[str, str]]:
    root = Path(__file__).resolve().parent.parent / "samples" / "live"
    out = []
    for name in ("S2_receipt_retake.jpg", "S2_medical_certificate_retake.jpg"):
        blob = (root / name).read_bytes()
        out.append({"name": name, "data": base64.b64encode(blob).decode("ascii")})
    return out


def _s2_person() -> dict:
    root = Path(__file__).resolve().parent.parent / "samples" / "scenarios_inbound.json"
    scenarios = json.loads(root.read_text(encoding="utf-8"))["scenarios"]
    return next(s for s in scenarios if s["id"] == "S2_seoul_worker_bronchitis")["person"]


PORT = 8000


def _headers(**overrides: str) -> dict[str, str]:
    headers = {"host": f"127.0.0.1:{PORT}", "content_type": "application/json", "origin": ""}
    headers.update(overrides)
    return headers


def _run(stubbed, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    raw = json.dumps(payload).encode("utf-8")
    return stubbed.route_post("/api/run", raw, len(raw), headers or _headers(), PORT)


def test_health(stubbed):
    status, body, media = stubbed.route_get("/api/health")
    assert (status, media) == (200, "application/json")
    assert json.loads(body.decode("utf-8")) == {"ok": True, "mode": "live"}


def test_static_demo_but_nothing_sensitive(stubbed):
    status, body, media = stubbed.route_get("/docs/demo.html")
    assert status == 200
    assert media == "text/html"
    assert b"ClaimLens" in body
    assert stubbed.route_get("/.env")[0] == 403
    assert stubbed.route_get("/cache/engine/x.json")[0] == 403
    assert stubbed.route_get("/docs/missing.html")[0] == 404


def test_run_live_end_to_end_with_stub(stubbed):
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert [s["key"] for s in result["steps"]] == [
        "reading", "checks", "double_read", "eligibility", "consistency", "decision",
    ]
    assert all(s["seconds"] >= 0 for s in result["steps"])
    assert result["steps"][0]["tokens"] == 200
    assert result["steps"][2]["detail"] == "agree"
    assert result["matched_sample"] == "S2_seoul_worker_bronchitis"
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["tokens_total"] == 250
    assert result["questions"] == []
    assert "run_id" not in result


def test_reused_recordings_say_so_with_zero_new_tokens(monkeypatch):
    monkeypatch.setattr(serve, "live_provider", lambda: StubProvider(reused=True))
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    status, result = _run(serve, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    by_key = {s["key"]: s for s in result["steps"]}
    assert by_key["reading"]["tokens"] == 0
    assert by_key["reading"]["meta"] == serve.REUSED_LABEL
    assert by_key["consistency"]["tokens"] == 0
    assert by_key["consistency"]["meta"] == serve.REUSED_LABEL
    assert result["tokens_total"] == 0


class _FailThenFixStub(StubProvider):
    """Both parallel base reads break identically; later re-reads are clean."""

    def __init__(self, reused: bool):
        super().__init__(reused=reused)
        self._reads = 0

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        self._reads += 1
        reading = super().read_documents(images, instructions, schema, result_model,
                                         cache_tag=cache_tag)
        if result_model is None and self._reads <= 2:
            reading["documents"][0]["kr_bill"]["cell_1"] = 0
        return reading


def test_reread_labels_honest_in_both_cases(monkeypatch):
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    monkeypatch.setattr(serve, "live_provider", lambda: _FailThenFixStub(reused=False))
    _, fresh = _run(serve, {"images": _sample_images(), "person": _s2_person()})
    checks = {s["key"]: s for s in fresh["steps"]}["checks"]
    assert checks["tokens"] == 200
    assert checks["meta"] == "deterministic + 200 tokens (live)"
    monkeypatch.setattr(serve, "live_provider", lambda: _FailThenFixStub(reused=True))
    _, reused = _run(serve, {"images": _sample_images(), "person": _s2_person()})
    checks = {s["key"]: s for s in reused["steps"]}["checks"]
    assert checks["tokens"] == 0
    assert checks["meta"] == f"deterministic + {serve.REUSED_LABEL}"


def test_run_live_engine_path_never_overwrites_recordings(stubbed, monkeypatch):
    from claimlens import engine

    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate", lambda inputs: {"decision": "PARTIAL", "amount": 22500})

    def _boom(*args, **kwargs):
        raise AssertionError("live run must not overwrite engine recordings")

    monkeypatch.setattr(engine, "store_result", _boom)
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert result["result"]["badge"] == "PARTIAL"
    assert result["result"]["title"] == "22,500 KRW"
    assert result["result"]["note"] == "live engine call, not cached"


def test_no_person_facts_pauses_with_questions(stubbed):
    status, result = _run(stubbed, {"images": _sample_images()})
    assert status == 200
    assert result["result"]["badge"] == "need_facts"
    assert [s["key"] for s in result["steps"]] == ["reading", "checks", "double_read"]
    assert len(result["questions"]) == 4
    assert all(set(q) == {"question", "why_needed"} for q in result["questions"])
    assert all(q["question"] and q["why_needed"] for q in result["questions"])
    assert result["run_id"]


def test_partial_person_asks_only_what_is_missing(stubbed):
    person = {"visa": "E-7", "korean_employer": True, "work_related": False}
    status, result = _run(stubbed, {"images": _sample_images(), "person": person})
    assert status == 200
    assert result["result"]["badge"] == "need_facts"
    assert len(result["questions"]) == 1
    assert "enter Korea" in result["questions"][0]["question"]


def test_continue_finishes_with_no_new_reading(stubbed, monkeypatch):
    stub = StubProvider()
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    _, paused = _run(stubbed, {"images": _sample_images()})
    reads = [c for c in stub.calls if c.total_tokens == 100]
    assert len(reads) == 2
    status, result = _run(
        stubbed, {"run_id": paused["run_id"], "person": _s2_person()}
    )
    assert status == 200
    assert [s["key"] for s in result["steps"]] == [
        "reading", "checks", "double_read", "eligibility", "consistency", "decision",
    ]
    assert result["result"]["badge"] == "engine_unreachable"
    assert "run_id" not in result
    assert len([c for c in stub.calls if c.total_tokens == 100]) == 2
    status, result = _run(stubbed, {"run_id": paused["run_id"], "person": _s2_person()})
    assert status == 400
    assert "drop the photos again" in result["error"]


def test_preset_scenario_reaches_engine_without_byte_match(stubbed, monkeypatch):
    from claimlens import engine

    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate", lambda inputs: {"decision": "PARTIAL", "amount": 22500})
    status, result = _run(stubbed, {
        "images": _retake_images(),
        "person": _s2_person(),
        "scenario": "S2_seoul_worker_bronchitis",
    })
    assert status == 200
    assert result["matched_sample"] is None
    assert result["scenario"] == "S2_seoul_worker_bronchitis"
    assert result["result"]["badge"] == "PARTIAL"
    assert result["result"]["title"] == "22,500 KRW"
    assert "preset-declared" in result["result"]["note"]


def test_continue_rejects_bad_run_id_person_and_scenario(stubbed):
    status, result = _run(stubbed, {"run_id": "nope", "person": _s2_person()})
    assert status == 400
    status, result = _run(stubbed, {"images": _sample_images(), "person": ["E-7"]})
    assert status == 400
    assert "person must be an object" in result["error"]
    status, result = _run(
        stubbed, {"images": _sample_images(), "person": _s2_person(), "scenario": "S9_nope"}
    )
    assert status == 400
    assert "Unknown scenario" in result["error"]


class _SplitStub(StubProvider):
    """Second read disagrees on the total; everything else identical."""

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        reading = super().read_documents(images, instructions, schema, result_model,
                                         cache_tag=cache_tag)
        if result_model is None and cache_tag:
            reading["documents"][0]["total_amount"] = 1.0
        return reading


class _UnorderableStub(StubProvider):
    """Second read loses the certificate."""

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        reading = super().read_documents(images, instructions, schema, result_model,
                                         cache_tag=cache_tag)
        if result_model is None and cache_tag:
            reading["documents"] = reading["documents"][:1]
        return reading


def test_gate_disagreement_stops_with_side_by_side_questions(stubbed, monkeypatch):
    monkeypatch.setattr(serve, "live_provider", lambda: _SplitStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert [s["key"] for s in result["steps"]] == ["reading", "checks", "double_read"]
    assert result["steps"][2]["detail"] == "1 field differ"
    assert result["result"]["badge"] == "needs_manual_check"
    assert len(result["questions"]) == 1
    question = result["questions"][0]
    assert set(question) == {"question", "why_needed"}
    assert "45,000" in question["question"] and "1" in question["question"]
    assert "run_id" not in result


def test_gate_unorderable_read_stops(stubbed, monkeypatch):
    monkeypatch.setattr(serve, "live_provider", lambda: _UnorderableStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert result["questions"][0]["question"].startswith("documents:")


def test_gate_diffs_pure():
    left = {"total_amount": 45000.0,
            "line_items": [{"amount": 18000.0}, {"amount": 9000.0}],
            "kr_bill": {"cell_1": 45000, "cell_6": 90000}}
    same = {"total_amount": 45000, "line_items": [{"amount": 18000}, {"amount": 9000}],
            "kr_bill": {"cell_1": 45000, "cell_6": 90000}}
    assert serve.gate_diffs(left, same) == []
    right = {"total_amount": None, "line_items": [{"amount": 18000.0}],
             "kr_bill": {"cell_1": 45000, "cell_6": 1}}
    diffs = serve.gate_diffs(left, right)
    assert [d[0] for d in diffs] == ["total", "line count", "KR cell 6"]
    assert diffs[0][1:] == ("45,000", "unreadable")
    questions = serve.gate_questions(diffs)
    assert len(questions) == 3
    assert all(set(q) == {"question", "why_needed"} for q in questions)


def test_run_rejects_non_images_and_wrong_counts(stubbed):
    bad = base64.b64encode(b"not an image at all....").decode("ascii")
    images = _sample_images()
    status, result = _run(stubbed, {"images": [{"name": "x.txt", "data": bad}, images[1]]})
    assert status == 400
    assert "images only" in result["error"]
    status, result = _run(stubbed, {"images": images[:1]})
    assert status == 400
    assert "exactly 2" in result["error"]


def test_run_rejects_oversized_uploads(stubbed):
    status, _ = stubbed.route_post("/api/run", b"{}", serve.MAX_BODY_BYTES + 1, _headers(), PORT)
    assert status == 413


def test_unknown_routes_404(stubbed):
    assert stubbed.route_post("/api/nope", b"{}", 2, _headers(), PORT)[0] == 404


def test_rejects_foreign_host(stubbed):
    status, result = _run(stubbed, {"images": []}, _headers(host="evil.example:8000"))
    assert status == 403
    assert result["error"] == "forbidden host"
    status, _ = _run(stubbed, {"images": []}, _headers(host=""))
    assert status == 403
    status, _ = _run(stubbed, {"images": []}, _headers(host="localhost:8000"))
    assert status == 400  # host ok; body invalid (proves the check passed)


def test_rejects_non_json_content_type(stubbed):
    status, result = _run(stubbed, {"images": []}, _headers(content_type="text/plain"))
    assert status == 415
    assert "application/json" in result["error"]
    status, _ = _run(stubbed, {"images": []}, _headers(content_type=""))
    assert status == 415


def test_rejects_cross_origin_only(stubbed):
    status, result = _run(
        stubbed, {"images": []}, _headers(origin="http://evil.example")
    )
    assert status == 403
    assert "cross-origin" in result["error"]
    status, _ = _run(
        stubbed, {"images": []}, _headers(origin="http://127.0.0.1:8000")
    )
    assert status == 400  # origin ok; body invalid (proves the check passed)


def _can_listen() -> bool:
    try:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        sock.close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _can_listen(), reason="sandbox blocks listen()")
def test_real_http_round_trip(stubbed):
    server = serve.start_background(0)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
        conn.request("GET", "/api/health")
        response = conn.getresponse()
        assert response.status == 200
        body = json.dumps({"images": _sample_images()}).encode("utf-8")
        conn.request("POST", "/api/run", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 200
        result = json.loads(response.read().decode("utf-8"))
        assert result["matched_sample"] == "S2_seoul_worker_bronchitis"
    finally:
        server.shutdown()
        server.server_close()

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

    def __init__(self):
        self.calls: list[CallRecord] = []

    def _log(self, total: int):
        self.calls.append(
            CallRecord(model=self.model, input_tokens=total, output_tokens=0,
                       total_tokens=total, cost_usd=None)
        )

    def read_documents(self, images, instructions, schema, result_model=None):
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


def _run(stubbed, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode("utf-8")
    return stubbed.route_post("/api/run", raw, len(raw))


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
    status, result = _run(stubbed, {"images": _sample_images()})
    assert status == 200
    assert [s["key"] for s in result["steps"]] == [
        "reading", "checks", "eligibility", "consistency", "decision",
    ]
    assert all(s["seconds"] >= 0 for s in result["steps"])
    assert result["steps"][0]["tokens"] == 100
    assert result["matched_sample"] == "S2_seoul_worker_bronchitis"
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["tokens_total"] == 150
    assert result["questions"] == []


def test_run_live_engine_path_never_overwrites_recordings(stubbed, monkeypatch):
    from claimlens import engine

    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate", lambda inputs: {"decision": "PARTIAL", "amount": 22500})

    def _boom(*args, **kwargs):
        raise AssertionError("live run must not overwrite engine recordings")

    monkeypatch.setattr(engine, "store_result", _boom)
    status, result = _run(stubbed, {"images": _sample_images()})
    assert status == 200
    assert result["result"]["badge"] == "PARTIAL"
    assert "not cached" in result["result"]["title"]


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
    status, _ = stubbed.route_post("/api/run", b"{}", serve.MAX_UPLOAD_BYTES + 2048)
    assert status == 413


def test_unknown_routes_404(stubbed):
    assert stubbed.route_post("/api/nope", b"{}", 2)[0] == 404


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

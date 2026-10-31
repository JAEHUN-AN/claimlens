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


def _travel_product() -> str:
    from claimlens.engine import product_catalog

    names = [n for n in product_catalog() if "해외여행" in n]
    assert len(names) == 1
    return names[0]


def _traveller_person(product: str | None = None) -> dict:
    person = {"visa": "none (Korean national)", "korean_employer": False,
              "work_related": False, "entry_date": "n/a",
              "alien_registration_date": "none", "korean_national": True}
    if product is not None:
        person["product"] = product
    return person


class _AbroadStub(StubProvider):
    """Unmatched bytes read as a Japanese clinic receipt + certificate."""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        from claimlens.rotation import RotationProbe

        if result_model is RotationProbe:
            self._log(10)
            return {"rotation": 0}
        self._log(100)
        return copy.deepcopy(replay_reading("A_niseko_wrist", "photo"))


def _continue(stubbed, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode("utf-8")
    return stubbed.route_post("/api/run", raw, len(raw), _headers(), PORT)


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


def test_static_get_rejects_unc_drive_and_nul(stubbed):
    """S1: backslash, colon and NUL in the path are rejected outright."""
    assert stubbed.route_get("/%5C%5Cevil%5Cshare")[0] == 400
    assert stubbed.route_get("/docs%5Cdemo.html")[0] == 400
    assert stubbed.route_get("/C:/Windows/x")[0] == 400
    assert stubbed.route_get("/docs/demo.html%00")[0] == 400
    assert stubbed.route_get("/docs/demo.html%00.png")[0] == 400


def test_get_checks_host(stubbed):
    """S1: GET enforces the same Host allow-list as POST."""
    good = {"host": f"127.0.0.1:{PORT}", "port": PORT}
    assert stubbed.route_get("/api/health", **good)[0] == 200
    assert stubbed.route_get("/docs/demo.html", **good)[0] == 200
    bad = {"host": "evil.example", "port": PORT}
    assert stubbed.route_get("/api/health", **bad)[0] == 403
    assert stubbed.route_get("/docs/demo.html", **bad)[0] == 403


class _Gate:
    """Semaphore stand-in that records entries."""

    def __init__(self):
        self.depth = 0
        self.max_depth = 0

    def __enter__(self):
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        return self

    def __exit__(self, *args):
        self.depth -= 1
        return False


def test_run_live_executes_inside_run_gate(stubbed, monkeypatch):
    """S2: live runs are concurrency-limited."""
    gate = _Gate()
    monkeypatch.setattr(stubbed, "_RUN_SEMAPHORE", gate)
    payload = {"images": _sample_images(), "person": _s2_person(),
               "scenario": "S2_seoul_worker_bronchitis"}
    status, _ = _run(stubbed, payload)
    assert status == 200
    assert gate.max_depth == 1
    assert gate.depth == 0


class _TagStub(StubProvider):
    """Both full reads fail checks; the re-read fixes them. Records tags."""

    def __init__(self):
        super().__init__()
        self.tags: list[str] = []

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.tags.append(cache_tag)
        reading = copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))
        if result_model is None or result_model.__name__ == "ReadingResult":
            reading["documents"][0]["kr_bill"]["cell_8"] = 999
            self._log(100)
            return reading
        if result_model.__name__ == "RotationProbe":
            self._log(10)
            return {"rotation": 0}
        self._log(50)
        bill = reading["documents"][0]["kr_bill"]
        return {k: v for k, v in bill.items() if k.startswith("cell_")}


def test_serve_rereads_use_per_read_tags(stubbed, monkeypatch):
    """C5: serve's two re-reads never share one recording."""
    stub = _TagStub()
    monkeypatch.setattr(stubbed, "live_provider", lambda: stub)
    payload = {"images": _sample_images(), "person": _s2_person(),
               "scenario": "S2_seoul_worker_bronchitis"}
    status, _ = _run(stubbed, payload)
    assert status == 200
    reread_tags = stub.tags[-2:]
    assert reread_tags == ["", ".read2"]


class _NoBillStub(StubProvider):
    """KR receipt without kr_bill but with passing totals."""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self._log(100)
        reading = copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))
        receipt = reading["documents"][0]
        receipt.pop("kr_bill", None)
        receipt["country"] = "KR"
        receipt["line_items"] = [
            {"description": "care", "category": "other",
             "amount": receipt["total_amount"]}
        ]
        return reading


def test_serve_kr_without_copay_stops_like_agent(stubbed, monkeypatch):
    """C3: a KR run with no copay rate is not adjudicated."""
    monkeypatch.setattr(stubbed, "live_provider", _NoBillStub)
    payload = {"images": _sample_images(), "person": _s2_person(),
               "scenario": "S2_seoul_worker_bronchitis"}
    status, result = _run(stubbed, payload)
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert any("cell" in q["question"] for q in result["questions"])


class _DroppedLinesStub(StubProvider):
    """S2 photo read that drops the item list; derivation rebuilds it."""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self._log(100)
        reading = copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))
        if result_model is None or result_model.__name__ == "ReadingResult":
            reading["documents"][0]["line_items"] = []
            return reading
        if result_model.__name__ == "RotationProbe":
            self._log(10)
            return {"rotation": 0}
        raise AssertionError("no re-read expected")


def test_serve_derived_kr_lines_show_source(stubbed, monkeypatch):
    """60a: dropped KR lines derive from the charge rows; the note shows it."""
    monkeypatch.setattr(stubbed, "live_provider", _DroppedLinesStub)
    payload = {"images": _sample_images(), "person": _s2_person(),
               "scenario": "S2_seoul_worker_bronchitis"}
    status, result = _run(stubbed, payload)
    assert status == 200
    checks = next(s for s in result["steps"] if s["key"] == "checks")
    assert "lines (derived from the charge rows)" in checks["detail"]


def test_run_gate_capacity_is_four():
    """S2: at most four live runs proceed; the fifth waits."""
    assert serve.MAX_CONCURRENT_RUNS == 4
    gate = serve._RUN_SEMAPHORE
    held = 0
    try:
        for _ in range(4):
            assert gate.acquire(blocking=False) is True
            held += 1
        assert gate.acquire(blocking=False) is False
    finally:
        for _ in range(held):
            gate.release()


def test_run_live_end_to_end_with_stub(stubbed):
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert [s["key"] for s in result["steps"]] == [
        "reading", "checks", "double_read", "eligibility", "consistency",
    ]
    assert all(s["seconds"] >= 0 for s in result["steps"])
    assert result["steps"][0]["tokens"] == 200
    assert result["steps"][2]["detail"] == "agree"
    assert result["matched_sample"] == "S2_seoul_worker_bronchitis"
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["tokens_total"] == 250
    assert len(result["questions"]) == 1
    assert "resend to retry" in result["questions"][0]["question"]
    assert result["run_id"]


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
    assert len(result["questions"]) == 6
    assert all(set(q) == {"question", "why_needed"} for q in result["questions"])
    assert all(q["question"] and q["why_needed"] for q in result["questions"])
    assert result["run_id"]


def test_partial_person_asks_only_what_is_missing(stubbed):
    person = {"visa": "E-7", "korean_employer": True, "work_related": False}
    status, result = _run(stubbed, {"images": _sample_images(), "person": person})
    assert status == 200
    assert result["result"]["badge"] == "need_facts"
    assert len(result["questions"]) == 3
    assert "enter Korea" in result["questions"][0]["question"]
    assert "Korean national" in result["questions"][2]["question"]


def test_person_facts_ask_registration_date(stubbed):
    """C7: the worker's foreign-resident registration date is asked."""
    person = {k: v for k, v in _s2_person().items() if k != "alien_registration_date"}
    status, result = _run(stubbed, {"images": _sample_images(), "person": person})
    assert status == 200
    assert result["result"]["badge"] == "need_facts"
    assert len(result["questions"]) == 1
    assert "regist" in result["questions"][0]["question"]
    assert result["run_id"]
    status, continued = _run(stubbed, {
        "run_id": result["run_id"],
        "person": {"alien_registration_date": "2026-03-20"},
    })
    assert status == 200
    assert continued["result"]["badge"] == "engine_unreachable"
    assert continued["run_id"] == result["run_id"]


def test_registration_none_counts_as_answered(stubbed):
    """C7: never-registered patients answer none and proceed."""
    person = dict(_s2_person())
    person["alien_registration_date"] = "none"
    status, result = _run(stubbed, {"images": _sample_images(), "person": person})
    assert status == 200
    assert "run_id" not in result


class _NoServiceDateStub(StubProvider):
    """S2 reading with the service date unreadable."""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self._log(100)
        reading = copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))
        reading["documents"][0]["service_date"] = None
        return reading


def test_service_date_falls_back_to_period_from(stubbed, monkeypatch):
    """C7: a missing service date uses the bill's treatment period."""
    monkeypatch.setattr(stubbed, "live_provider", _NoServiceDateStub)
    status, result = _run(stubbed, {"images": _sample_images(),
                                    "person": _s2_person()})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"


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
        "reading", "checks", "double_read", "eligibility", "consistency",
    ]
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["run_id"] == paused["run_id"]
    assert len([c for c in stub.calls if c.total_tokens == 100]) == 2
    status, result = _run(stubbed, {"run_id": paused["run_id"]})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["run_id"] == paused["run_id"]
    assert len([c for c in stub.calls if c.total_tokens == 100]) == 2


class _ProbeAwareStub(StubProvider):
    """Retake bytes are probed; the probe says upright, reads return S2."""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        from claimlens.rotation import RotationProbe

        if result_model is RotationProbe:
            self._log(10)
            return {"rotation": 0}
        return super().read_documents(images, instructions, schema, result_model,
                                      cache_tag)


def test_traveller_path_adjudicates_with_chosen_product(stubbed, monkeypatch):
    """H1: a Korean national treated abroad reaches the engine path."""
    from claimlens import engine

    monkeypatch.setattr(stubbed, "live_provider", _AbroadStub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    seen = {}
    def fake_adjudicate(inputs):
        seen.update(inputs)
        return {"decision": "PARTIAL", "amount": 100000}
    monkeypatch.setattr(engine, "live_adjudicate", fake_adjudicate)
    product = _travel_product()
    status, result = _run(stubbed, {"images": _retake_images(),
                                    "person": _traveller_person(product)})
    assert status == 200
    assert result["result"]["badge"] == "PARTIAL"
    assert seen["product"] == product
    assert seen["treated_abroad"] is True
    assert "chosen by user" in result["result"]["note"]
    assert result["scenario"] is None


def test_declared_scenario_never_supplies_policy(stubbed, monkeypatch):
    """H2: a declared scenario is reference-only; the user picks a product."""
    from claimlens import engine

    monkeypatch.setattr(stubbed, "live_provider", _ProbeAwareStub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    calls = []
    monkeypatch.setattr(engine, "live_adjudicate",
                        lambda inputs: calls.append(inputs) or {"decision": "X", "amount": 0})
    status, result = _run(stubbed, {
        "images": _retake_images(), "person": _s2_person(),
        "scenario": "S2_seoul_worker_bronchitis"})
    assert status == 200
    assert result["result"]["badge"] == "need_product"
    assert calls == []
    assert result["run_id"]
    product = _s2_product()
    status, result = _continue(stubbed, {"run_id": result["run_id"],
                                         "person": {"product": product}})
    assert status == 200
    assert result["result"]["badge"] == "X"
    assert calls[0]["product"] == product
    assert "shown for reference only" in result["result"]["note"]
    assert "run_id" not in result


def _s2_product() -> str:
    from claimlens.engine import product_catalog

    names = [n for n in product_catalog() if "해외여행" not in n]
    assert len(names) == 1
    return names[0]


def test_unknown_product_asks_with_catalog(stubbed, monkeypatch):
    """H1: an unknown product asks instead of pricing blind."""
    monkeypatch.setattr(stubbed, "live_provider", _AbroadStub)
    status, result = _run(stubbed, {"images": _retake_images(),
                                    "person": _traveller_person("No Such Product")})
    assert status == 200
    assert result["result"]["badge"] == "need_product"
    assert "Which insurance product" in result["questions"][0]["question"]
    assert "해외여행" in result["questions"][0]["why_needed"]
    assert result["run_id"]


def test_engine_down_pauses_with_retry_and_no_new_reads(stubbed, monkeypatch):
    """H1: engine down keeps the verified reading and retries on resend."""
    from claimlens import engine

    stub = _AbroadStub()
    monkeypatch.setattr(stubbed, "live_provider", lambda: stub)
    product = _travel_product()
    status, result = _run(stubbed, {"images": _retake_images(),
                                    "person": _traveller_person(product)})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert "resend to retry" in result["questions"][0]["question"]
    run_id = result["run_id"]
    reads = len(stub.calls)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate",
                        lambda inputs: {"decision": "PARTIAL", "amount": 100000})
    status, result = _continue(stubbed, {"run_id": run_id})
    assert status == 200
    assert result["result"]["badge"] == "PARTIAL"
    assert len(stub.calls) == reads  # no new reading call on retry
    assert [s["key"] for s in result["steps"]].count("decision") == 1


def test_dental_flags_for_reviewer_and_never_decides(stubbed, monkeypatch):
    """T6: dental treatment never reaches the engine, even with a product."""
    from claimlens import engine

    class _DentalStub(_AbroadStub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            from claimlens.rotation import RotationProbe

            if result_model is RotationProbe:
                self._log(10)
                return {"rotation": 0}
            self._log(100)
            reading = copy.deepcopy(replay_reading("A_niseko_wrist", "photo"))
            reading["documents"][1]["diagnoses"] = [{"code": "K04.7"}]
            return reading

    monkeypatch.setattr(stubbed, "live_provider", _DentalStub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate", lambda inputs: (_ for _ in ()).throw(
        AssertionError("engine must not decide dental")))
    status, result = _run(stubbed, {"images": _retake_images(),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "needs_review"
    assert "dental" in result["result"]["title"].lower()


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
    """Second read redistributes two line amounts; both reads verify clean."""

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        reading = super().read_documents(images, instructions, schema, result_model,
                                         cache_tag=cache_tag)
        if result_model is None and cache_tag:
            lines = reading["documents"][0]["line_items"]
            lines[0]["amount"] += 1000
            lines[1]["amount"] -= 1000
        return reading


class _TotalSplitStub(StubProvider):
    """Second read disagrees on the total alone (C2: caught at verify)."""

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


def test_gate_disagreement_pauses_with_side_by_side_choices(stubbed, monkeypatch):
    """H7: each differing field pauses with both values and its source."""
    monkeypatch.setattr(serve, "live_provider", lambda: _SplitStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert [s["key"] for s in result["steps"]] == ["reading", "checks", "double_read"]
    assert result["steps"][2]["detail"] == "2 fields differ"
    assert result["result"]["badge"] == "needs_manual_check"
    assert len(result["questions"]) == 2
    question = result["questions"][0]
    assert set(question) == {"question", "why_needed", "id", "options"}
    assert "18,000" in question["question"] and "19,000" in question["question"]
    assert question["id"] == "line 1 amount"
    assert [o["id"] for o in question["options"]] == ["first", "second"]
    assert all(o["source"] == "receipt line 1 amount" for o in question["options"])
    assert "19,000" in question["options"][1]["label"]
    assert result["run_id"]


def test_gate_resolution_continues_same_run(stubbed, monkeypatch):
    """H7: picked values are re-checked and the run continues."""
    monkeypatch.setattr(serve, "live_provider", lambda: _SplitStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    run_id = result["run_id"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"line 1 amount": "first", "line 2 amount": "first"},
    })
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["run_id"] == run_id
    resolve = next(s for s in result["steps"] if s["key"] == "resolve")
    assert resolve["meta"] == "person-confirmed"
    assert "line 1 amount" in resolve["detail"]
    assert result["answers"]["gate"] == {"line 1 amount": "first",
                                         "line 2 amount": "first"}


def test_gate_resolution_rechecks_and_repauses(stubbed, monkeypatch):
    """H7: picks that fail the sum check pause again under the same id."""
    monkeypatch.setattr(serve, "live_provider", lambda: _SplitStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    run_id = result["run_id"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"line 1 amount": "second", "line 2 amount": "first"},
    })
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert result["run_id"] == run_id
    assert "lines_sum" in result["result"]["title"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"line 1 amount": "second", "line 2 amount": "second"},
    })
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["run_id"] == run_id


class _MismatchStub(StubProvider):
    """S2 receipt stapled to an S3 certificate: rule blockers only."""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self._log(100)
        receipt = copy.deepcopy(
            replay_reading("S2_seoul_worker_bronchitis", "photo")["documents"][0])
        cert = copy.deepcopy(
            replay_reading("S3_us_tourist_hip_fracture", "photo")["documents"][1])
        return {"documents": [receipt, cert]}


def test_blockers_pause_with_picks_and_note_boxes(stubbed, monkeypatch):
    """H8: rule blockers pause with receipt/cert picks plus a note box."""
    monkeypatch.setattr(stubbed, "live_provider", _MismatchStub)
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert result["result"]["badge"] == "blocked"
    assert result["run_id"]
    kinds = {q["id"] for q in result["questions"]}
    assert kinds == {"blocker:patient_name", "blocker:visit_date", "blocker:visit_type"}
    for question in result["questions"]:
        assert [o["id"] for o in question["options"]] == ["receipt", "cert"]
        assert question["note"] is True
        assert "receipt (" in question["options"][0]["source"]


def test_blocker_resolution_continues_same_run(stubbed, monkeypatch):
    """H8: confirmed blockers unblock; provenance stays on the run."""
    monkeypatch.setattr(stubbed, "live_provider", _MismatchStub)
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    run_id = result["run_id"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {
            "blocker:patient_name": "receipt",
            "blocker:visit_date": "cert",
            "blocker:visit_type": "receipt",
        },
    })
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["run_id"] == run_id
    consistency = next(s for s in result["steps"] if s["key"] == "consistency")
    assert "person confirmed 3" in consistency["detail"]
    assert result["answers"]["blockers"]["patient_name"]["pick"] == "receipt"


def test_blocker_note_only_stays_blocked(stubbed, monkeypatch):
    """H8: a free-text note is recorded but resolves nothing by itself."""
    monkeypatch.setattr(stubbed, "live_provider", _MismatchStub)
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    run_id = result["run_id"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"blocker:patient_name": {"note": "ID checked at desk"}},
    })
    assert status == 200
    assert result["result"]["badge"] == "blocked"
    assert result["run_id"] == run_id
    assert "blocker:patient_name" in {q["id"] for q in result["questions"]}
    assert result["answers"]["notes"] == {"patient_name": "ID checked at desk"}


def _thb_receipt(total, lines, name="Jaeho PARK", dob="1990-01-01"):
    return {"doc_type": "receipt", "country": "TH", "currency": "THB",
            "total_amount": float(total), "service_date": "2026-09-18",
            "inpatient": False,
            "line_items": [{"description": label, "category": "other",
                            "amount": float(amount)}
                           for label, amount in lines],
            "pii": [{"kind": "name", "value": name},
                    {"kind": "dob", "value": dob}]}


def _thb_cert(code="A05.9", name="Jaeho PARK", dob="1990-01-01"):
    return {"doc_type": "medical_certificate",
            "diagnoses": [{"code": code}],
            "pii": [{"kind": "name", "value": name},
                    {"kind": "dob", "value": dob}],
            "diagnosed": "2026-09-18"}


class _PhotoStub(StubProvider):
    """One doc set per photo index; both reads identical unless overridden."""

    def __init__(self, photos, second=None):
        super().__init__()
        self.photos = photos
        self.second = second or {}

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        from claimlens.rotation import RotationProbe

        if result_model is RotationProbe:
            self._log(10)
            return {"rotation": 0}
        self._log(100)
        idx = int(images[0].stem.split("_")[1])
        script = self.second if cache_tag else self.photos
        docs = script.get(idx, self.photos[idx])
        return {"documents": copy.deepcopy(docs)}


def _multi_images(n):
    root = Path(__file__).resolve().parent.parent / "samples" / "live"
    blob = (root / "S2_receipt_retake.jpg").read_bytes()
    return [{"name": f"photo{i}.jpg",
             "data": base64.b64encode(blob).decode("ascii")} for i in range(n)]


def test_three_uploads_merge_receipts(stubbed, monkeypatch):
    """50: two receipts + certificate merge with per-photo provenance."""
    er = _thb_receipt(12550, [("Emergency fee", 2500.0), ("IV fluids", 1800.0),
                              ("Lab tests", 3200.0), ("Medication (ER)", 1450.0),
                              ("Observation (4 hrs)", 3600.0)])
    pharm = _thb_receipt(1660, [("Antibiotics", 890.0), ("Probiotics", 650.0),
                                ("ORS sachets", 120.0)])
    photos = {0: [er], 1: [pharm], 2: [_thb_cert()]}
    monkeypatch.setattr(stubbed, "live_provider", lambda: _PhotoStub(photos))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    merge = next(s for s in result["steps"] if s["key"] == "merge")
    assert "12,550" in merge["detail"] and "1,660" in merge["detail"]
    assert result["merge"]["merged_total"] == 14210.0
    assert result["merge"]["currency"] == "THB"
    assert [p["photo"] for p in result["merge"]["photos"]] == [1, 2, 3]


def test_card_slip_deduped_once(stubbed, monkeypatch):
    """50: a bill and its card slip with equal amounts count once."""
    bill = _thb_receipt(1333.85, [("Urgent care visit", 950.0),
                                  ("X-ray ankle", 620.0), ("Lab tests", 240.0),
                                  ("Medication", 95.5),
                                  ("Insurance adjustment", -571.65)])
    bill["country"], bill["currency"] = "US", "USD"
    slip = {"doc_type": "receipt", "country": "US", "currency": "USD",
            "total_amount": 1333.85, "service_date": "2026-09-26",
            "inpatient": False, "line_items": [],
            "pii": bill["pii"]}
    cert = _thb_cert("S93.4")
    photos = {0: [bill], 1: [slip], 2: [cert]}
    monkeypatch.setattr(stubbed, "live_provider", lambda: _PhotoStub(photos))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["merge"]["merged_total"] == 1333.85
    dropped = [p for p in result["merge"]["photos"] if p["status"] == "deduped"]
    assert len(dropped) == 1 and dropped[0]["photo"] == 2
    assert "same amount" in dropped[0]["note"]


def test_missing_certificate_asks(stubbed, monkeypatch):
    """50/T4: one receipt and no certificate asks for it (never 400)."""
    photos = {0: [_thb_receipt(16.5, [("Medicine", 16.5)])]}
    monkeypatch.setattr(stubbed, "live_provider", lambda: _PhotoStub(photos))
    status, result = _run(stubbed, {"images": _multi_images(1),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert "certificate" in result["questions"][0]["question"].lower()


def test_korean_multi_stop(stubbed, monkeypatch):
    """50: several Korean bills are separate visits; upload them apart."""
    bill = {"doc_type": "receipt", "country": "KR", "currency": "KRW",
            "total_amount": 45000.0, "service_date": "2026-08-10",
            "inpatient": False, "line_items": [], "kr_bill": {"cell_1": 1}}
    cert = {"doc_type": "medical_certificate", "diagnoses": [{"code": "J20.9"}]}
    photos = {0: [bill], 1: [dict(bill)], 2: [cert]}
    monkeypatch.setattr(stubbed, "live_provider", lambda: _PhotoStub(photos))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert "separately" in result["questions"][0]["question"]


def test_mixed_currency_stop(stubbed, monkeypatch):
    """50: receipts in different currencies are not merged blind."""
    thb = _thb_receipt(100, [("Care", 100.0)])
    vnd = _thb_receipt(200, [("Care", 200.0)])
    vnd["country"], vnd["currency"] = "VN", "VND"
    photos = {0: [thb], 1: [vnd], 2: [_thb_cert()]}
    monkeypatch.setattr(stubbed, "live_provider", lambda: _PhotoStub(photos))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert "mixed currenc" in result["questions"][0]["question"].lower()


def test_multi_gate_resolution_uses_photo_ids(stubbed, monkeypatch):
    """H7+50: per-photo diffs pause with photo ids and continue."""
    er = _thb_receipt(12550, [("Emergency fee", 2500.0), ("Rest", 10050.0)])
    er2 = _thb_receipt(12551, [("Emergency fee", 2500.0), ("Rest", 10051.0)])
    pharm = _thb_receipt(1660, [("Meds", 1660.0)])
    photos = {0: [er], 1: [pharm], 2: [_thb_cert()]}
    second = {0: [er2]}
    monkeypatch.setattr(stubbed, "live_provider",
                        lambda: _PhotoStub(photos, second))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    ids = [q["id"] for q in result["questions"]]
    assert ids == ["photo 1 total", "photo 1 line 2 amount"]
    assert result["questions"][0]["options"][0]["source"] == (
        "photo 1 receipt total_amount")
    run_id = result["run_id"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"photo 1 total": "first",
                        "photo 1 line 2 amount": "first"},
    })
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["merge"]["merged_total"] == 14210.0
    assert result["run_id"] == run_id


def _jpy_tax_photo(total, lines):
    receipt = {"doc_type": "receipt", "country": "JP", "currency": "JPY",
               "total_amount": float(total), "service_date": "2026-09-18",
               "inpatient": False,
               "line_items": [{"description": label, "category": "other",
                               "amount": float(amount)}
                              for label, amount in lines],
               "pii": [{"kind": "name", "value": "Jaeho PARK"},
                       {"kind": "dob", "value": "1990-01-01"}]}
    return receipt


class _AdjustStub(_PhotoStub):
    """Adjustment re-reads are scripted per photo; base reads pass through."""

    def __init__(self, photos, adjustments, second=None):
        super().__init__(photos, second)
        self.adjustments = adjustments

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        from claimlens.verify import AdjustmentReread

        if result_model is AdjustmentReread:
            self._log(10)
            idx = int(images[0].stem.split("_")[1])
            return copy.deepcopy(self.adjustments.get(
                idx, {"adjustment_lines": []}))
        return super().read_documents(images, instructions, schema, result_model,
                                      cache_tag=cache_tag)


def test_multi_receipt_with_tax_line_merges(stubbed, monkeypatch):
    """56/50: per-photo tax re-reads reconcile, then merge with provenance."""
    taxed = _jpy_tax_photo(12030, [("Consultation", 5000.0),
                                   ("Medicine", 6700.0)])
    plain = _jpy_tax_photo(5000, [("Follow-up", 5000.0)])
    photos = {0: [taxed], 1: [plain], 2: [_thb_cert()]}
    adjustments = {0: {"subtotal": 11700.0,
                       "adjustment_lines": [
                           {"label": "Consumption tax", "kind": "tax",
                            "amount": 330.0}]}}
    monkeypatch.setattr(stubbed, "live_provider",
                        lambda: _AdjustStub(photos, adjustments))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    checks = next(s for s in result["steps"] if s["key"] == "checks")
    assert "photo 1: tax 330" in checks["detail"]
    assert "photo 1 subtotal 11,700" in checks["detail"]
    assert "narrow re-read" in checks["detail"]
    assert result["merge"]["merged_total"] == 17030.0
    kept = [p for p in result["merge"]["photos"] if p["status"] == "kept"]
    assert "tax 330" in kept[0]["note"]
    assert "subtotal 11,700" in kept[0]["note"]


def test_two_image_tax_recovery_shows_in_checks(stubbed, monkeypatch):
    """56: the 2-image Checks row shows re-read adjustments with source."""
    from claimlens.verify import AdjustmentReread

    receipt = _jpy_tax_photo(12030, [("Consultation", 5000.0),
                                     ("Medicine", 6700.0)])
    cert = _thb_cert()

    class _TaxStub(StubProvider):
        def read_documents(self, images, instructions, schema,
                           result_model=None, cache_tag=""):
            from claimlens.rotation import RotationProbe

            if result_model is RotationProbe:
                self._log(10)
                return {"rotation": 0}
            self._log(100)
            if result_model is AdjustmentReread:
                return {"subtotal": 11700.0,
                        "adjustment_lines": [
                            {"label": "Consumption tax", "kind": "tax",
                             "amount": 330.0}]}
            return {"documents": [copy.deepcopy(receipt),
                                  copy.deepcopy(cert)]}

    monkeypatch.setattr(stubbed, "live_provider", _TaxStub)
    status, result = _run(stubbed, {
        "images": _retake_images(),
        "person": _traveller_person(_travel_product())})
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    checks = next(s for s in result["steps"] if s["key"] == "checks")
    assert "adjustments: tax 330, subtotal 11,700 (narrow re-read)" in checks[
        "detail"]


def test_multi_gate_merge_conflict_repauses(stubbed, monkeypatch):
    """H7+50: picks that pass per-photo checks but cannot merge re-pause."""
    thb = _thb_receipt(100, [("Care", 100.0)])
    usd = _thb_receipt(100, [("Care", 100.0)])
    usd["country"], usd["currency"] = "US", "USD"
    photos = {0: [thb], 1: [_thb_receipt(50, [("Meds", 50.0)])],
              2: [_thb_cert()]}
    monkeypatch.setattr(stubbed, "live_provider",
                        lambda: _PhotoStub(photos, {0: [usd]}))
    status, result = _run(stubbed, {"images": _multi_images(3),
                                    "person": _traveller_person(_travel_product())})
    assert status == 200
    assert [q["id"] for q in result["questions"]] == ["photo 1 currency",
                                                     "photo 1 country"]
    run_id = result["run_id"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"photo 1 currency": "second",
                        "photo 1 country": "second"},
    })
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert "cannot merge" in result["result"]["title"]
    assert result["run_id"] == run_id
    assert [q["id"] for q in result["questions"]] == ["photo 1 currency",
                                                     "photo 1 country"]
    status, result = _continue(stubbed, {
        "run_id": run_id,
        "resolutions": {"photo 1 currency": "first",
                        "photo 1 country": "first"},
    })
    assert status == 200
    assert result["result"]["badge"] == "engine_unreachable"
    assert result["merge"]["merged_total"] == 150.0
    assert result["run_id"] == run_id


def test_spark_blocker_stays_terminal(stubbed, monkeypatch):
    """H8: model blockers cannot be picked away; the run ends blocked."""

    class _SparkStub(StubProvider):
        def write(self, instructions, schema, result_model=None):
            self._log(50)
            return {"findings": [{"kind": "odd_code", "severity": "blocker",
                                  "reason": "The code looks unusual.",
                                  "quote_receipt": "45000", "quote_cert": "J20.9"}]}

    monkeypatch.setattr(stubbed, "live_provider", _SparkStub)
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert result["result"]["badge"] == "blocked"
    assert "run_id" not in result


def test_gate_resolution_rejects_unknown_and_missing(stubbed, monkeypatch):
    monkeypatch.setattr(serve, "live_provider", lambda: _SplitStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    run_id = result["run_id"]
    status, result = _continue(stubbed, {"run_id": run_id,
                                         "resolutions": {"line 9 amount": "first"}})
    assert status == 400
    assert "Unknown choices" in result["error"]
    status, result = _continue(stubbed, {"run_id": run_id,
                                         "resolutions": {"line 1 amount": "first"}})
    assert status == 400
    assert "Unresolved choices" in result["error"]
    status, result = _continue(stubbed, {"run_id": run_id,
                                         "resolutions": {"line 1 amount": "maybe",
                                                         "line 2 amount": "first"}})
    assert status == 400
    assert "must be 'first' or 'second'" in result["error"]


def test_total_disagreement_stops_at_checks(stubbed, monkeypatch):
    """C2: a total disagreeing with its own cells never reaches double_read."""
    monkeypatch.setattr(serve, "live_provider", lambda: _TotalSplitStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert [s["key"] for s in result["steps"]] == ["reading", "checks"]
    assert result["result"]["badge"] == "needs_manual_check"
    assert len(result["questions"]) == 1
    assert "printed_total_8" in result["questions"][0]["question"]
    assert "run_id" not in result


def test_gate_unorderable_read_stops(stubbed, monkeypatch):
    monkeypatch.setattr(serve, "live_provider", lambda: _UnorderableStub())
    status, result = _run(stubbed, {"images": _sample_images(), "person": _s2_person()})
    assert status == 200
    assert result["result"]["badge"] == "needs_manual_check"
    assert result["questions"][0]["question"].startswith("documents:")


def _reading_of(receipt, diagnoses=None):
    return {"documents": [receipt, {"doc_type": "medical_certificate",
                                    "diagnoses": [{"code": c} for c in
                                                  (diagnoses or ["J20.9"])]}]}


def test_gate_diffs_pure():
    left = {"total_amount": 45000.0,
            "line_items": [{"amount": 18000.0}, {"amount": 9000.0}],
            "kr_bill": {"cell_1": 45000, "cell_6": 90000}}
    same = {"total_amount": 45000, "line_items": [{"amount": 18000}, {"amount": 9000}],
            "kr_bill": {"cell_1": 45000, "cell_6": 90000}}
    assert serve.gate_diffs(_reading_of(left), _reading_of(same)) == []
    right = {"total_amount": None, "line_items": [{"amount": 18000.0}],
             "kr_bill": {"cell_1": 45000, "cell_6": 1}}
    diffs = serve.gate_diffs(_reading_of(left), _reading_of(right))
    assert [d[0] for d in diffs] == ["total", "line count", "KR cell 6"]
    assert diffs[0][1:] == ("45,000", "unreadable")
    questions = serve.gate_questions(diffs)
    assert len(questions) == 3
    assert all(set(q) == {"question", "why_needed", "id", "options"}
               for q in questions)


def test_gate_diffs_c1_identity_fields():
    """C1: currency, country, dates, stay, codes, and rows must agree too."""
    bill = {"cell_1": 45000, "cell_6": 90000,
            "charge_rows": [{"label": "a", "col_1": 1, "col_2": 2,
                             "col_3": 3, "col_4": 4}]}
    base = {"total_amount": 45000.0, "currency": "KRW", "country": "KR",
            "service_date": "2026-08-10", "inpatient": False,
            "line_items": [{"amount": 45000.0}], "kr_bill": bill}
    other_bill = {"cell_1": 45000, "cell_6": 90000,
                  "charge_rows": [{"label": "a", "col_1": 1, "col_2": 2,
                                   "col_3": 3, "col_4": 5}]}
    other = {"total_amount": 45000.0, "currency": "JPY", "country": "JP",
             "service_date": "2026-08-11", "inpatient": True,
             "line_items": [{"amount": 45000.0}], "kr_bill": other_bill}
    diffs = serve.gate_diffs(_reading_of(base), _reading_of(other, ["J20.8"]))
    labels = [d[0] for d in diffs]
    assert labels == ["currency", "country", "service date", "inpatient stay",
                      "diagnosis code 1", "charge row 1 col 4"]
    assert ("currency", "KRW", "JPY") in diffs
    assert serve.gate_diffs(_reading_of(base), _reading_of(dict(base))) == []


def test_run_rejects_non_images_and_wrong_counts(stubbed, monkeypatch):
    bad = base64.b64encode(b"not an image at all....").decode("ascii")
    images = _sample_images()
    status, result = _run(stubbed, {"images": [{"name": "x.txt", "data": bad}, images[1]]})
    assert status == 400
    assert "images only" in result["error"]
    status, result = _run(stubbed, {"images": []})
    assert status == 400
    assert "1 to 6" in result["error"]
    # 50: one upload is a multi run (receipt + certificate on one photo),
    # not a rejection: it reads and pauses for the missing person facts.
    monkeypatch.setattr(stubbed, "live_provider", _AbroadStub)
    status, result = _run(stubbed, {"images": images[:1]})
    assert status == 200
    assert result["result"]["badge"] == "need_facts"
    assert result["run_id"]


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


def test_gate_diffs_compare_adjustment_lines():
    # 56: two reads that differ only in a discount line must not agree.
    base = {"total_amount": 4037.5, "currency": "USD", "country": "US",
            "line_items": [{"amount": 4250.0}]}
    left = {**base, "adjustment_lines": [{"kind": "discount", "amount": -212.5}]}
    right = {**base, "adjustment_lines": [{"kind": "discount", "amount": -21.25}]}
    assert serve.gate_diffs(_reading_of(left), _reading_of(left)) == []
    diffs = serve.gate_diffs(_reading_of(left), _reading_of(right))
    assert [d[0] for d in diffs] == ["adjustment 1 amount"]
    assert [d[0] for d in serve.gate_diffs(_reading_of(left), _reading_of(base))] == [
        "adjustment line count"]

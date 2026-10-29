"""41f rotation probe: upright before reading, skip on sample match, never block."""

import base64
import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from claimlens import gate_eval, hard_eval
from claimlens.cache import cache_key
from claimlens.engine import replay_reading
from claimlens.eval import ground_truth, load_scenarios
from claimlens.hard_eval import BASE_EST, PROBE_EST, REREAD_EST
from claimlens.prompts import READING_INSTRUCTIONS
from claimlens.providers.meta import MODEL, CallRecord, prepare_image
from claimlens.providers.replay import ReplayProvider
from claimlens.reader import reading_schema, resolve_sample_images
from claimlens.rotation import (
    FAILED_NOTE,
    PROBE_LONG_SIDE,
    ROTATION_INSTRUCTIONS,
    ProbeError,
    RotationProbe,
    prepare_probe_copy,
    probe_rotation,
    rotation_schema,
    turned_note,
    upright_copy,
    upright_pages,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def _s2_images():
    return resolve_sample_images(SAMPLES / "S2_seoul_worker_bronchitis", "photo")


class _ProbeStub:
    """Scripts one rotation per probe; records what the probe sent."""

    name = "stub"

    def __init__(self, rotations):
        self._rotations = list(rotations)
        self.calls = []
        self.probe_sizes = []
        self.instructions = None
        self.schema = None

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=5,
                                     total_tokens=105, cost_usd=0.001))
        assert result_model is RotationProbe
        self.instructions = instructions
        self.schema = schema
        with Image.open(images[0]) as img:
            self.probe_sizes.append(img.size)
        return {"rotation": self._rotations.pop(0)}


def test_rotation_schema_is_strict_single_field():
    schema = rotation_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["rotation"]
    assert list(schema["properties"]) == ["rotation"]
    assert schema["properties"]["rotation"]["enum"] == [0, 90, 180, 270]


def test_probe_prompt_and_key_differ_from_reading(tmp_path):
    assert ROTATION_INSTRUCTIONS != READING_INSTRUCTIONS
    assert rotation_schema() != reading_schema()
    image = _s2_images()[0]
    read_blob = prepare_image(image)
    copy = tmp_path / "probe.jpg"
    probe_blob = prepare_probe_copy(image, copy)
    read_key = cache_key([read_blob], READING_INSTRUCTIONS, reading_schema(), MODEL)
    probe_key = cache_key([probe_blob], ROTATION_INSTRUCTIONS, rotation_schema(), MODEL)
    assert probe_key != read_key


def test_probe_copy_downscales_long_side(tmp_path):
    copy = tmp_path / "probe.jpg"
    prepare_probe_copy(_s2_images()[0], copy)
    with Image.open(copy) as img:
        assert max(img.size) <= PROBE_LONG_SIDE
        assert img.format == "JPEG"


def test_probe_rotation_asks_small_copy_with_own_key():
    stub = _ProbeStub([90])
    assert probe_rotation(_s2_images()[0], stub) == 90
    assert stub.instructions == ROTATION_INSTRUCTIONS
    assert stub.schema == rotation_schema()
    assert max(stub.probe_sizes[0]) <= PROBE_LONG_SIDE
    assert len(stub.calls) == 1


def test_probe_rotation_failure_modes():
    class _Boom:
        def read_documents(self, *args, **kwargs):
            raise RuntimeError("Spark request failed: timed out")

    with pytest.raises(ProbeError) as exc:
        probe_rotation(_s2_images()[0], _Boom())
    assert exc.value.missing is False

    class _BadValue:
        def read_documents(self, *args, **kwargs):
            return {"rotation": 45}

    with pytest.raises(ProbeError):
        probe_rotation(_s2_images()[0], _BadValue())

    with pytest.raises(ProbeError) as exc:
        probe_rotation(_s2_images()[0], ReplayProvider())
    assert exc.value.missing is True


def test_upright_copy_restores_turned_pages(tmp_path):
    receipt = _s2_images()[0]
    with Image.open(receipt) as img:
        plain = img.convert("RGB")
        size = img.size
    assert size[0] > size[1]  # the sample receipt is landscape
    cases = [
        (plain.transpose(Image.Transpose.ROTATE_270), 90),  # turned CW 90
        (plain.transpose(Image.Transpose.ROTATE_180), 180),  # upside down
        (plain.transpose(Image.Transpose.ROTATE_90), 270),  # turned CCW 90
    ]
    for pos, (turned, rotation) in enumerate(cases):
        src = tmp_path / f"turned_{pos}.jpg"
        turned.save(src, format="JPEG", quality=90)
        assert upright_copy(src, rotation, tmp_path / f"up_{pos}.jpg")
        with Image.open(tmp_path / f"up_{pos}.jpg") as fixed:
            assert fixed.size == size


def test_upright_pages_zero_keeps_originals(tmp_path):
    images = _s2_images()
    upright, notes = upright_pages(images, _ProbeStub([0, 0]), tmp_path)
    assert upright == images
    assert notes == []


def test_upright_pages_rotates_and_notes(tmp_path):
    images = _s2_images()
    with Image.open(images[0]) as img:
        size = img.size
    upright, notes = upright_pages(images, _ProbeStub([270, 0]), tmp_path)
    assert notes == [turned_note(270)]
    assert turned_note(90) == "page turned 90 upright"
    assert upright[1] == images[1]
    assert upright[0] != images[0]
    with Image.open(upright[0]) as fixed:
        assert fixed.size == (size[1], size[0])


def test_upright_pages_failure_reads_as_is(tmp_path):
    class _Boom:
        def read_documents(self, *args, **kwargs):
            raise RuntimeError("Spark request failed: 500")

    images = _s2_images()
    upright, notes = upright_pages(images, _Boom(), tmp_path)
    assert upright == images
    assert notes == [FAILED_NOTE]
    assert FAILED_NOTE == "rotation probe failed; read as is"


def _payload(images):
    return [{"name": p.name, "data": base64.b64encode(p.read_bytes()).decode("ascii")}
            for p in images]


def _sizes(images):
    out = []
    for path in images:
        with Image.open(path) as img:
            out.append(img.size)
    return out


def _s2_person():
    scenarios = json.loads((SAMPLES / "scenarios_inbound.json").read_text(
        encoding="utf-8"))["scenarios"]
    return next(s for s in scenarios if s["id"] == "S2_seoul_worker_bronchitis")["person"]


class _ServeStub:
    """Probe-aware serve double: scripted rotations, asserts upright reads."""

    name = "stub"
    model = "stub"

    def __init__(self, rotations, expect_sizes):
        self._rotations = list(rotations)
        self._expect_sizes = list(expect_sizes)
        self.calls = []
        self.probes = 0
        self.reads = 0

    def _log(self, total):
        self.calls.append(CallRecord(model=self.model, input_tokens=total,
                                     output_tokens=0, total_tokens=total,
                                     cost_usd=None))

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        if result_model is RotationProbe:
            self.probes += 1
            self._log(105)
            assert instructions == ROTATION_INSTRUCTIONS
            return {"rotation": self._rotations.pop(0)}
        self.reads += 1
        self._log(100)
        for pos, image in enumerate(images):  # both reads see upright pages
            with Image.open(image) as img:
                assert img.size == self._expect_sizes[pos]
        return copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))

    def write(self, instructions, schema, result_model=None):
        self._log(50)
        return {"findings": []}


def _turned_s2_copies(tmp_path):
    """S2 photos turned CCW 90 (hard rot90): the probe must say 270."""
    out = []
    for pos, src in enumerate(_s2_images()):
        with Image.open(src) as img:
            turned = img.convert("RGB").transpose(Image.Transpose.ROTATE_90)
        dest = tmp_path / f"turned_{pos}.jpg"
        turned.save(dest, format="JPEG", quality=90)
        out.append(dest)
    return out


def test_serve_matched_sample_skips_probe(monkeypatch):
    from claimlens import serve

    stub = _ServeStub([], _sizes(_s2_images()))
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    raw = json.dumps({"images": _payload(_s2_images()),
                      "person": _s2_person()}).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json",
               "origin": ""}
    status, result = serve.route_post("/api/run", raw, len(raw), headers, 8000)
    assert status == 200
    assert stub.probes == 0
    reading = next(s for s in result["steps"] if s["key"] == "reading")
    assert reading["detail"] == "2 documents read twice by Muse Spark"


def test_serve_turned_upload_reads_upright(tmp_path, monkeypatch):
    from claimlens import serve

    turned = _turned_s2_copies(tmp_path)
    stub = _ServeStub([270, 270], _sizes(_s2_images()))
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    raw = json.dumps({"images": _payload(turned), "person": _s2_person(),
                      "scenario": "S2_seoul_worker_bronchitis"}).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json",
               "origin": ""}
    status, result = serve.route_post("/api/run", raw, len(raw), headers, 8000)
    assert status == 200
    assert result["matched_sample"] is None
    assert stub.probes == 2
    assert stub.reads == 2  # both double-read sides saw upright pages
    reading = next(s for s in result["steps"] if s["key"] == "reading")
    assert "page turned 270 upright" in reading["detail"]
    assert result["result"]["badge"] == "engine_unreachable"


def test_serve_probe_failure_reads_as_is(tmp_path, monkeypatch):
    from claimlens import serve

    class _FailingProbe(_ServeStub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            if result_model is RotationProbe:
                self.probes += 1
                raise RuntimeError("Spark request failed: 500")
            return super().read_documents(images, instructions, schema,
                                          result_model, cache_tag)

    turned = _turned_s2_copies(tmp_path)
    stub = _FailingProbe([], _sizes(turned))
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    raw = json.dumps({"images": _payload(turned), "person": _s2_person(),
                      "scenario": "S2_seoul_worker_bronchitis"}).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json",
               "origin": ""}
    status, result = serve.route_post("/api/run", raw, len(raw), headers, 8000)
    assert status == 200
    assert stub.reads == 2  # the probe never blocks the read
    reading = next(s for s in result["steps"] if s["key"] == "reading")
    assert FAILED_NOTE in reading["detail"]


def _gate_case(images):
    truth = ground_truth(load_scenarios()["S2_seoul_worker_bronchitis"])
    return {"sample": "S2_seoul_worker_bronchitis", "transform": "rot90",
            "key": "S2_seoul_worker_bronchitis-rot90", "images": images,
            "truth": truth,
            "unreadable": {"total": False, "line_amounts": False, "kr_cells": []}}


class _GateProbeStub:
    """Gate double: scripted rotations, asserts upright base reads."""

    name = "stub"

    def __init__(self, script, rotations, expect_sizes):
        self._script = script
        self._rotations = list(rotations)
        self._expect_sizes = list(expect_sizes)
        self.calls = []
        self.probes = 0

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=0,
                                     total_tokens=100, cost_usd=0.01))
        if result_model is RotationProbe:
            self.probes += 1
            return {"rotation": self._rotations.pop(0)}
        if result_model is not None:
            return {}
        for pos, image in enumerate(images):
            with Image.open(image) as img:
                assert img.size == self._expect_sizes[pos]
        return copy.deepcopy(self._script.pop(0))


def test_gate_pair_probes_and_reads_upright(tmp_path):
    turned = _turned_s2_copies(tmp_path)
    sizes = _sizes(_s2_images())
    good = replay_reading("S2_seoul_worker_bronchitis", "photo")
    script = [copy.deepcopy(good), copy.deepcopy(good)]
    stubs = []

    def _factory():
        stub = _GateProbeStub(script, [270, 270], sizes)
        stubs.append(stub)
        return stub

    record = gate_eval.run_pair(_gate_case(turned), 1, _factory, probe_pages=True)
    assert record["agree"] is True
    assert record["stopped"] is False
    assert record["rotation"] == ["page turned 270 upright"]
    assert sum(s.probes for s in stubs) == 2


def test_gate_pair_probe_failure_reads_as_is(tmp_path):
    turned = _turned_s2_copies(tmp_path)
    turned_sizes = _sizes(turned)
    good = replay_reading("S2_seoul_worker_bronchitis", "photo")
    script = [copy.deepcopy(good), copy.deepcopy(good)]

    class _Failing(_GateProbeStub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            if result_model is RotationProbe:
                self.probes += 1
                raise RuntimeError("Spark request failed: 500")
            return super().read_documents(images, instructions, schema,
                                          result_model, cache_tag)

    record = gate_eval.run_pair(_gate_case(turned), 1,
                                lambda: _Failing(script, [], turned_sizes),
                                probe_pages=True)
    assert record["agree"] is True
    assert record["rotation"] == [FAILED_NOTE]


def test_gate_pair_default_skips_probe():
    good = replay_reading("S2_seoul_worker_bronchitis", "photo")
    script = [copy.deepcopy(good), copy.deepcopy(good)]
    sizes = _sizes(_s2_images())
    record = gate_eval.run_pair(_gate_case(_s2_images()), 1,
                                lambda: _GateProbeStub(script, [], sizes))
    assert record["rotation"] == []
    assert record["agree"] is True


def test_gate_estimate_includes_probes():
    text = gate_eval.estimate_text("hard", 24, 3, 2)
    assert "144 reads + up to 144 verify re-reads + 144 rotation probes" in text
    lo = 144 * BASE_EST + 144 * PROBE_EST
    assert f"${lo:.2f}" in text
    assert f"${lo + 144 * REREAD_EST:.2f}" in text
    plain = gate_eval.estimate_text("normal", 10, 3)
    assert "rotation probes" not in plain


def test_hard_run_once_probes_and_reads_upright(tmp_path, monkeypatch):
    from claimlens.hard_eval import cache_dir_scope

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    with cache_dir_scope(None):
        good = replay_reading("S2_seoul_worker_bronchitis", "photo")
        truth = ground_truth(load_scenarios()["S2_seoul_worker_bronchitis"])
    turned = _turned_s2_copies(tmp_path)
    stub = _GateProbeStub([copy.deepcopy(good)], [270, 270], _sizes(_s2_images()))
    record = hard_eval.run_once(
        "S2_seoul_worker_bronchitis", turned, truth,
        {"total": False, "line_amounts": False, "kr_cells": []},
        tmp_path / "cache", tmp_path / "live", True, lambda: stub,
        probe_pages=True,
    )
    assert record["rotation"] == ["page turned 270 upright"]
    assert stub.probes == 2
    assert record["reached"] == 0
    assert len(record["calls"]) == 3  # 2 probes + the base read


def test_hard_run_once_probe_failure_reads_as_is(tmp_path, monkeypatch):
    from claimlens.hard_eval import cache_dir_scope

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    with cache_dir_scope(None):
        good = replay_reading("S2_seoul_worker_bronchitis", "photo")
        truth = ground_truth(load_scenarios()["S2_seoul_worker_bronchitis"])
    turned = _turned_s2_copies(tmp_path)

    class _Failing(_GateProbeStub):
        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            if result_model is RotationProbe:
                self.probes += 1
                raise RuntimeError("Spark request failed: 500")
            return super().read_documents(images, instructions, schema,
                                          result_model, cache_tag)

    stub = _Failing([copy.deepcopy(good)], [], _sizes(turned))
    record = hard_eval.run_once(
        "S2_seoul_worker_bronchitis", turned, truth,
        {"total": False, "line_amounts": False, "kr_cells": []},
        tmp_path / "cache", tmp_path / "live", True, lambda: stub,
        probe_pages=True,
    )
    assert record["rotation"] == [FAILED_NOTE]
    assert record["checks_first"] == "pass"


def test_hard_run_once_default_skips_probe(tmp_path, monkeypatch):
    from claimlens.hard_eval import cache_dir_scope

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    with cache_dir_scope(None):
        good = replay_reading("S2_seoul_worker_bronchitis", "photo")
        truth = ground_truth(load_scenarios()["S2_seoul_worker_bronchitis"])
    stub = _GateProbeStub([copy.deepcopy(good)], [], _sizes(_s2_images()))
    record = hard_eval.run_once(
        "S2_seoul_worker_bronchitis", _s2_images(), truth,
        {"total": False, "line_amounts": False, "kr_cells": []},
        tmp_path / "cache", tmp_path / "live", True, lambda: stub,
    )
    assert record["rotation"] == []
    assert stub.probes == 0


def test_plan_and_estimate_include_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    plan = hard_eval.plan_hard(41, tmp_path / "hard", SAMPLES, 3,
                               ("A_niseko_wrist",), ("crop", "glare"))
    assert plan["probes_live"] == 2 * 3 * 2
    text = hard_eval.estimate_text(plan, "hard set x3")
    assert "rotation probes: 12 live" in text
    normal = hard_eval.plan_normal(SAMPLES, 3, ("A_niseko_wrist",))
    assert normal["probes_live"] == 0
    assert "rotation probes: 0 live" in hard_eval.estimate_text(normal, "normal x3")

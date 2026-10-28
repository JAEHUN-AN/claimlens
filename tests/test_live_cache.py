"""Live provider: reuse caches, never overwrite committed recordings."""

import base64
import json
import subprocess
from pathlib import Path

from claimlens.prompts import READING_INSTRUCTIONS
from claimlens.providers.meta import MetaProvider
from claimlens.reader import reading_schema, resolve_sample_images

ROOT = Path(__file__).resolve().parent.parent


class _NoNetwork:
    def __getattr__(self, name: str):
        raise AssertionError(f"live run touched the network ({name})")


def _offline_live() -> MetaProvider:
    provider = MetaProvider(api_key="test-key", live=True)
    provider._client = _NoNetwork()
    return provider


def _s2_images() -> list[Path]:
    return resolve_sample_images(ROOT / "samples" / "S2_seoul_worker_bronchitis", "photo")


def test_live_reuses_committed_reading_without_network():
    provider = _offline_live()
    reading = provider.read_documents(_s2_images(), READING_INSTRUCTIONS, reading_schema())
    assert [d["doc_type"] for d in reading["documents"]] == ["receipt", "medical_certificate"]
    assert provider.calls[0].total_tokens > 0


def test_live_reuses_committed_write_without_network():
    from claimlens.engine import build_inputs, load_result, replay_reading
    from claimlens.rationale import rationale_instructions, rationale_payload, rationale_schema

    provider = _offline_live()
    reading = replay_reading("S2_seoul_worker_bronchitis", "photo")
    inputs = build_inputs("S2_seoul_worker_bronchitis", "photo", reading)
    payload = rationale_payload(inputs, load_result("S2_seoul_worker_bronchitis", "photo", inputs))
    draft = provider.write(rationale_instructions(payload), rationale_schema(), None)
    assert draft["summary"].strip()


def test_live_miss_stores_under_live_dir_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path))

    class _Canned:
        files = _NoNetwork()

        def __init__(self):
            from types import SimpleNamespace

            self.responses = SimpleNamespace(
                create=lambda **kw: SimpleNamespace(
                    output_text=json.dumps({"ok": True}),
                    usage=SimpleNamespace(input_tokens=5, output_tokens=1, total_tokens=6),
                )
            )

    provider = MetaProvider(api_key="test-key", live=True)
    provider._client = _Canned()
    out = provider.write("novel instructions", {"type": "object"}, None)
    assert out == {"ok": True}
    assert list(tmp_path.glob("*.json")) == []
    stored = list((tmp_path / "live").glob("*.json"))
    assert len(stored) == 1


def test_sample_bytes_leave_git_diff_empty(monkeypatch):
    from claimlens import serve

    monkeypatch.setattr(serve, "live_provider", _offline_live)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    live_dir = ROOT / "cache" / "live"
    before = {p for p in live_dir.rglob("*")} if live_dir.exists() else set()
    images = []
    for path in _s2_images():
        images.append({"name": path.name, "data": base64.b64encode(path.read_bytes()).decode("ascii")})
    raw = json.dumps({"images": images}).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json", "origin": ""}
    status, result = serve.route_post("/api/run", raw, len(raw), headers, 8000)
    assert status == 200
    assert result["matched_sample"] == "S2_seoul_worker_bronchitis"
    after = {p for p in live_dir.rglob("*")} if live_dir.exists() else set()
    assert after == before
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "diff", "--exit-code", "--", "cache/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout

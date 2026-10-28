"""Local live server: `claimlens serve` (standard library only).

Serves the demo page and a JSON pipeline for real uploads: reading,
checks, re-read, eligibility, consistency, then the engine (when
Neo4j is reachable) or the Claim Pack. Bound to 127.0.0.1, 10 MB
max upload, images only. The API key stays in this process; the
browser only posts images and reads results.
"""

import base64
import binascii
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 14 * 1024 * 1024
REUSED_LABEL = "recording reused — no model call"

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def live_provider() -> Any:
    """Live Spark provider; reuses caches, never overwrites committed ones."""
    from dotenv import load_dotenv

    from claimlens.providers.meta import MetaProvider

    load_dotenv()
    return MetaProvider(live=True)


def neo4j_up() -> bool:
    try:
        from dotenv import load_dotenv
        from neo4j import GraphDatabase

        load_dotenv()
        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI"),
            auth=(os.environ.get("NEO4J_USER"), os.environ.get("NEO4J_PASSWORD")),
            connection_timeout=3,
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
    except Exception:  # noqa: BLE001 - connectivity probe: any failure means down
        return False
    return True


def _image_kind(blob: bytes) -> str | None:
    if blob.startswith(JPEG_MAGIC):
        return "jpg"
    if blob.startswith(PNG_MAGIC):
        return "png"
    return None


def match_sample(blobs: list[bytes]) -> str | None:
    """Sample id when every upload byte-matches that sample's photos."""
    from claimlens.engine import samples_dir
    from claimlens.reader import resolve_sample_images

    base = samples_dir()
    if not base.is_dir():
        return None
    wanted = sorted(hashlib.sha256(b).hexdigest() for b in blobs)
    for sample_dir in sorted(base.iterdir()):
        if not sample_dir.is_dir():
            continue
        try:
            images = resolve_sample_images(sample_dir, "photo")
        except FileNotFoundError:
            continue
        known = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in images)
        if known == wanted:
            return sample_dir.name
    return None


def order_docs(reading: dict[str, Any]) -> dict[str, Any]:
    """Receipt first, certificate second, by the model's own labels."""
    docs = reading.get("documents", [])
    receipt = next((d for d in docs if d.get("doc_type") == "receipt"), None)
    cert = next((d for d in docs if d.get("doc_type") == "medical_certificate"), None)
    if receipt is None or cert is None:
        raise ValueError("Could not tell the receipt from the certificate; upload one of each.")
    return {"documents": [receipt, cert]}


PERSON_FIELDS = ("visa", "korean_employer", "work_related", "entry_date")

FACT_QUESTIONS = {
    "visa": (
        "What visa does the patient hold?",
        "Special visas change when coverage starts (eligibility row 2).",
    ),
    "korean_employer": (
        "Does the patient work for a Korean employer?",
        "Workplace subscribers are covered from the first working day (row 1).",
    ),
    "work_related": (
        "Is this injury or illness work-related?",
        "Work injuries go to industrial-accident insurance first (row 7).",
    ),
    "entry_date": (
        "When did the patient enter Korea (YYYY-MM-DD)?",
        "Coverage starts from entry or registration (rows 2-4).",
    ),
}

_RUNS: dict[str, dict[str, Any]] = {}
_MAX_RUNS = 20


def missing_facts(person: dict[str, Any] | None) -> list[str]:
    """Panel fields with no answer yet. False is an answer; blank is not."""
    person = person or {}
    missing = []
    for key in PERSON_FIELDS:
        value = person.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def fact_questions(keys: list[str]) -> list[dict[str, str]]:
    """Missing facts as ask_user questions: same question/why_needed shape."""
    return [
        {"question": FACT_QUESTIONS[key][0], "why_needed": FACT_QUESTIONS[key][1]}
        for key in keys
    ]


def check_person(person: Any) -> dict[str, Any]:
    if person is None:
        return {}
    if not isinstance(person, dict):
        raise TypeError("person must be an object.")
    return person


def check_scenario(scenario: Any, scenarios: dict[str, dict[str, Any]]) -> str | None:
    if scenario is None or scenario == "":
        return None
    if not isinstance(scenario, str) or scenario not in scenarios:
        raise ValueError(f"Unknown scenario: {scenario!r}.")
    return scenario


def _step(steps: list[dict[str, Any]], key: str, label: str, detail: str,
          meta: str, seconds: float, tokens: int = 0) -> None:
    steps.append(
        {"key": key, "label": label, "detail": detail, "meta": meta,
         "seconds": round(seconds, 3), "tokens": tokens}
    )


def _step_usage(provider: Any, since: int) -> tuple[int, bool, bool]:
    """New tokens, whether any call was made, whether all were reused."""
    made = provider.calls[since:]
    fresh = [c for c in made if not getattr(c, "reused", False)]
    return sum(c.total_tokens for c in fresh), bool(made), bool(made) and not fresh


def _live_meta(provider: Any, since: int) -> tuple[str, int]:
    """Honest meta: only a real network call may say 'live'."""
    tokens, _, reused_only = _step_usage(provider, since)
    if reused_only:
        return REUSED_LABEL, 0
    return f"{tokens} tokens (live)", tokens


def run_live(
    images: list[dict[str, str]],
    person: dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Full pipeline on uploaded images. Raises ValueError on bad input.

    When person facts are missing the run pauses after the checks with
    ask_user questions instead of dead-ending; answering continues the
    same run (see run_continue) with no new reading call.
    """
    from claimlens.checks import check_kr_bill, check_kr_lines
    from claimlens.engine import load_scenarios
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema
    from claimlens.verify import verify_receipt

    if len(images) != 2:
        raise ValueError("Upload exactly 2 images: the receipt and the certificate.")
    blobs: list[bytes] = []
    for item in images:
        try:
            blob = base64.b64decode(item.get("data", ""), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{item.get('name', '?')}: not valid base64.") from None
        if _image_kind(blob) is None:
            raise ValueError(f"{item.get('name', '?')}: images only (JPEG or PNG).")
        blobs.append(blob)
    if sum(len(b) for b in blobs) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploads exceed the 10 MB limit.")

    person = check_person(person)
    scenarios, inbound = load_scenarios()
    declared = check_scenario(scenario, scenarios)

    steps: list[dict[str, Any]] = []
    tokens_total = 0
    provider = live_provider()
    with tempfile.TemporaryDirectory(prefix="claimlens-live-") as tmp:
        paths = []
        for item, blob in zip(images, blobs, strict=True):
            suffix = ".jpg" if _image_kind(blob) == "jpg" else ".png"
            path = Path(tmp) / f"upload_{len(paths)}{suffix}"
            path.write_bytes(blob)
            paths.append(path)
        started = time.monotonic()
        mark = len(provider.calls)
        reading = provider.read_documents(paths, READING_INSTRUCTIONS, reading_schema())
        meta, tokens = _live_meta(provider, mark)
        tokens_total += tokens
        _step(steps, "reading", "Reading", "2 documents read by Muse Spark",
              meta, time.monotonic() - started, tokens)
        reading = order_docs(reading)
        receipt = reading["documents"][0]

        started = time.monotonic()
        mark = len(provider.calls)
        bill = receipt.get("kr_bill")
        if bill:
            checks = [*check_kr_bill(bill), *check_kr_lines(receipt)]
            names = f"{sum(c.passed for c in checks)}/{len(checks)} pass"
            verified = verify_receipt(receipt, paths[0], provider)
            receipt = verified["receipt"]
            reading["documents"][0] = receipt
            detail = f"{names}; re-read: {verified['status']}"
        else:
            detail = "no bill checks for non-Korean receipts"
        tokens, made, _ = _step_usage(provider, mark)
        tokens_total += tokens
        if made:
            meta, _ = _live_meta(provider, mark)
            meta = f"deterministic + {meta}"
        else:
            meta = "deterministic"
        _step(steps, "checks", "Checks", detail, meta, time.monotonic() - started, tokens)

        matched = match_sample(blobs)
        run = {
            "reading": reading,
            "steps": steps,
            "tokens_total": tokens_total,
            "matched": matched,
            "scenario": declared,
            "person": person,
        }
        context = matched or declared
        if context and context not in inbound:
            return _finish_run(provider, run)
        if missing_facts(person):
            return _pause_run(run)
        return _finish_run(provider, run)


def _pause_run(run: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    """Park a run after the checks; the answer continues it (run_continue)."""
    missing = missing_facts(run["person"])
    if run_id is None:
        run_id = secrets.token_urlsafe(16)
    _RUNS[run_id] = run
    while len(_RUNS) > _MAX_RUNS:
        _RUNS.pop(next(iter(_RUNS)))
    plural = "s" if len(missing) != 1 else ""
    return {
        "steps": run["steps"],
        "result": {
            "badge": "need_facts",
            "title": f"Answer {len(missing)} question{plural} to continue.",
            "note": "",
        },
        "tokens_total": run["tokens_total"],
        "matched_sample": run["matched"],
        "scenario": run["scenario"],
        "questions": fact_questions(missing),
        "run_id": run_id,
    }


def _finish_run(provider: Any, run: dict[str, Any]) -> dict[str, Any]:
    """Eligibility, consistency, and decision on a run with full facts."""
    from claimlens.claimpack import build_pack
    from claimlens.consistency import deterministic_findings, spark_findings
    from claimlens.eligibility import check_eligibility
    from claimlens.engine import build_inputs, live_adjudicate, load_scenarios

    reading = run["reading"]
    steps = run["steps"]
    tokens_total = run["tokens_total"]
    matched = run["matched"]
    declared = run["scenario"]
    person = run["person"]
    receipt, cert = reading["documents"]
    _, inbound = load_scenarios()
    context = matched or declared
    started = time.monotonic()
    if context and context not in inbound:
        eligibility = {"outcome": "traveller_abroad", "rule": "engine_path",
                       "basis": "Korean traveller abroad — engine path."}
    else:
        eligibility = check_eligibility(person, receipt.get("service_date") or "")
    _step(steps, "eligibility", "Eligibility",
          f"{eligibility['outcome']} ({eligibility['rule']})",
          "deterministic", time.monotonic() - started)

    started = time.monotonic()
    mark = len(provider.calls)
    ruled = deterministic_findings(receipt, cert)
    sparked, dropped = spark_findings(receipt, cert, provider)
    meta, tokens = _live_meta(provider, mark)
    tokens_total += tokens
    blockers = [f for f in ruled + sparked if f["severity"] == "blocker"]
    _step(steps, "consistency", "Consistency",
          f"{len(blockers)} blockers, {len(ruled + sparked) - len(blockers)} notes"
          + (f"; {dropped} dropped quotes" if dropped else ""),
          meta, time.monotonic() - started, tokens)

    started = time.monotonic()
    note = ""
    if blockers:
        decision = {"badge": "blocked", "title": "Resolve the blocking questions first."}
        detail = f"{len(blockers)} blocking questions asked"
        meta = "stopped before decision"
    elif eligibility["outcome"] in ("nhi_member", "traveller_abroad") and context:
        if neo4j_up():
            inputs = build_inputs(context, "photo", reading)
            output = live_adjudicate(inputs)
            decision = {"badge": output["decision"], "title": f"{output['amount']:,} KRW"}
            detail = f"{output['decision']} {output['amount']:,} KRW"
            if matched:
                note = "live engine call, not cached"
            else:
                note = f"{context} context (preset-declared); live engine call, not cached"
            meta = note
        else:
            decision = {"badge": "engine_unreachable", "title": "Neo4j is down; no decision made."}
            detail = "engine skipped: Neo4j unreachable"
            meta = "deterministic"
    elif eligibility["outcome"] == "not_member_or_unknown" and matched:
        pack = build_pack(matched, "photo", provider)
        decision = {"badge": "claim_pack", "title": "Claim Pack built (sample-matched)."}
        detail = f"{len(pack['items'])} lines, total {pack['total_krw']:,} KRW"
        meta = "sample-matched pack"
    else:
        decision = {"badge": "needs_review", "title": "Human review: no decision path."}
        detail = eligibility["basis"]
        meta = "deterministic"
    decision["note"] = note
    _step(steps, "decision", "Decision", detail, meta, time.monotonic() - started)

    return {
        "steps": steps,
        "result": decision,
        "tokens_total": tokens_total,
        "matched_sample": matched,
        "scenario": declared,
        "questions": [
            {"question": f.get("question", ""), "why_needed": f.get("why_needed", "")}
            for f in blockers
        ],
    }


def run_continue(
    run_id: str,
    person: dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Answer a paused run's questions; finishes with no new reading call."""
    from claimlens.engine import load_scenarios

    if not isinstance(run_id, str) or run_id not in _RUNS:
        raise ValueError("Unknown or expired run; drop the photos again.")
    run = _RUNS[run_id]
    scenarios, inbound = load_scenarios()
    declared = check_scenario(scenario, scenarios)
    if declared:
        run["scenario"] = declared
    merged = dict(run["person"])
    for key, value in check_person(person).items():
        if value is None or (isinstance(value, str) and not value.strip()):
            merged.pop(key, None)
        else:
            merged[key] = value
    run["person"] = merged
    context = run["matched"] or run["scenario"]
    if not (context and context not in inbound) and missing_facts(merged):
        return _pause_run(run, run_id)
    del _RUNS[run_id]
    return _finish_run(live_provider(), run)


def route_get(path: str) -> tuple[int, bytes, str]:
    """Pure GET routing: status, body bytes, media type. No sockets."""
    if path == "/api/health":
        return 200, json.dumps({"ok": True, "mode": "live"}).encode("utf-8"), "application/json"
    target = unquote(path)
    if target in ("", "/"):
        target = "/index.html"
    root = repo_root()
    resolved = (root / target.lstrip("/")).resolve()
    allowed = resolved.is_relative_to(root) and (
        resolved.name == "index.html"
        or resolved.is_relative_to(root / "docs")
        or resolved.is_relative_to(root / "samples")
    )
    if not allowed or not resolved.is_file():
        code = 404 if allowed else 403
        return code, json.dumps({"error": "not found"}).encode("utf-8"), "application/json"
    media = "application/octet-stream"
    if resolved.suffix == ".html":
        media = "text/html"
    elif resolved.suffix == ".wav":
        media = "audio/wav"
    elif resolved.suffix in (".jpg", ".jpeg"):
        media = "image/jpeg"
    elif resolved.suffix == ".png":
        media = "image/png"
    return 200, resolved.read_bytes(), media


def route_post(
    path: str, raw: bytes, declared: int, headers: dict[str, str], port: int
) -> tuple[int, dict[str, Any]]:
    """Pure POST routing: status plus JSON payload. No sockets.

    Spend guard: only same-origin JSON posts from this machine reach
    the pipeline. The Host check also blocks DNS rebinding.
    """
    if path != "/api/run":
        return 404, {"error": "not found"}
    hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
    if headers.get("host", "").strip().lower() not in hosts:
        return 403, {"error": "forbidden host"}
    media = headers.get("content_type", "").split(";")[0].strip().lower()
    if media != "application/json":
        return 415, {"error": "Content-Type must be application/json."}
    origin = (headers.get("origin") or "").strip().lower()
    if origin and origin not in (f"http://{h}" for h in hosts):
        return 403, {"error": "cross-origin posts are forbidden"}
    if declared > MAX_BODY_BYTES:
        return 413, {"error": "Uploads exceed the 10 MB limit."}
    try:
        body = json.loads(raw.decode("utf-8"))
        if body.get("run_id"):
            result = run_continue(body["run_id"], body.get("person"), body.get("scenario"))
        else:
            result = run_live(body.get("images", []), body.get("person"), body.get("scenario"))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return 400, {"error": str(exc)}
    except RuntimeError as exc:
        return 503, {"error": str(exc)}
    return 200, result


class Handler(BaseHTTPRequestHandler):
    server_version = "ClaimLensLive/0.1"

    def log_message(self, *args: Any) -> None:
        pass

    def _send(self, status: int, body: bytes, media: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

    def do_GET(self) -> None:
        status, body, media = route_get(urlparse(self.path).path)
        if media == "application/json":
            self._send_json(status, json.loads(body.decode("utf-8")))
        else:
            self._send(status, body, media)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            declared = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        if path == "/api/run" and declared <= MAX_BODY_BYTES:
            raw = self.rfile.read(declared) if declared else b""
        else:
            raw = b""
        headers = {
            "host": self.headers.get("Host") or "",
            "content_type": self.headers.get("Content-Type") or "",
            "origin": self.headers.get("Origin") or "",
        }
        status, payload = route_post(path, raw, declared, headers, self.server.server_port)
        self._send_json(status, payload)


def serve_forever(port: int = 8000) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"ClaimLens live on http://127.0.0.1:{server.server_port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_background(port: int = 0) -> ThreadingHTTPServer:
    """Ephemeral server for tests; caller must shutdown() + server_close()."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

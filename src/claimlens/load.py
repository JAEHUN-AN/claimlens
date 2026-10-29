"""Light load check: N concurrent live runs against a local serve instance.

Default prints the plan only (calls and cost). --execute starts a real
127.0.0.1 server, POSTs N concurrent /api/run requests with per-run
byte-varied retake photos (so no run is a cache hit), and writes one
JSON data file for `claimlens headline`. No heavy load testing: this is
a local demo check of latency, cost, and clean 429 handling.
"""

import base64
import io
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from claimlens.hard_eval import EVAL_MD_COSTS

RUNS_DEFAULT = 5
# 2 rotation probes (byte-varied photos never match a sample) + 2 reads
# + 2 verify + consistency + verifier + rationale.
CALLS_PER_RUN_MAX = 9
PHOTOS = ("S2_receipt_retake.jpg", "S2_medical_certificate_retake.jpg")
SCENARIO = "S2_seoul_worker_bronchitis"


def estimate_text(runs: int) -> str:
    """Cost range from the committed per-call costs behind docs/eval.md."""
    calls = runs * CALLS_PER_RUN_MAX
    lo, hi = min(EVAL_MD_COSTS), max(EVAL_MD_COSTS)
    return (f"{runs} runs x up to {CALLS_PER_RUN_MAX} calls = {calls} calls; "
            f"estimate ${calls * lo:.2f}-${calls * hi:.2f} "
            f"(per-call ${lo:.4f}-${hi:.4f} from docs/eval.md).")


def plan_text(runs: int, max_cost: float) -> str:
    return "\n".join([
        "Load plan (no network calls made):",
        f"{runs} concurrent live runs; photos samples/live/{PHOTOS[0]} + {PHOTOS[1]},",
        "each run byte-varied with a corner marker block so nothing is a cache hit;",
        "S2 worker person preset; results to a new data/load_*.json file.",
        estimate_text(runs),
        f"Refuses to launch past --max-cost ${max_cost:.2f}.",
    ])


MARKER_SIZE = 24


def vary_bytes(blob: bytes, run: int) -> bytes:
    """Deterministic per-run bytes: a corner marker block, same reading.

    The block survives the provider's downscale + re-encode, so the
    prepared bytes (and cache keys) differ per run: no cache hits.
    """
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as img:
        frame = img.convert("RGB")
        gray = (25 + run * 40) % 256
        for x in range(MARKER_SIZE):
            for y in range(MARKER_SIZE):
                frame.putpixel((x, y), (gray, gray, gray))
        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=95)
        return buf.getvalue()


def percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile over ascending values."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * pct / 100.0
    low, frac = int(rank), rank - int(rank)
    return sorted_vals[low] * (1 - frac) + sorted_vals[low + 1] * frac


def _http_post(port: int, body: dict[str, Any], timeout: float) -> tuple[int, dict]:
    """POST one body; returns (status, payload). No record built here."""
    raw = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/run", data=raw, method="POST",
        headers={"Content-Type": "application/json",
                 "Host": f"127.0.0.1:{port}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except ValueError:
            return exc.code, {"error": "unparseable error body"}


def _record(status: int, payload: dict[str, Any], seconds: float) -> dict[str, Any]:
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    coherent = status in (200, 503) and (
        status != 200
        or (
            isinstance(result, dict)
            and bool(result.get("badge"))
            and isinstance(payload.get("tokens_total", 0), (int, float))
        )
    )
    return {
        "status": status,
        "seconds": round(seconds, 3),
        "badge": payload.get("result", {}).get("badge") if status == 200 else None,
        "tokens": payload.get("tokens_total", 0) if status == 200 else 0,
        "cost_usd": payload.get("cost_usd", 0.0) if status == 200 else 0.0,
        "retries_429": payload.get("retries_429", 0) if status == 200 else 0,
        "coherent": bool(coherent),
    }


def load_person() -> dict[str, Any]:
    from claimlens.engine import load_scenarios

    scenarios, _ = load_scenarios()
    return dict(scenarios[SCENARIO]["person"])


def build_bodies(samples_live: Path, runs: int) -> list[dict[str, Any]]:
    photos = [samples_live / name for name in PHOTOS]
    missing = [str(p) for p in photos if not p.exists()]
    if missing:
        raise FileNotFoundError(f"load photos missing: {', '.join(missing)}")
    person = load_person()
    bodies = []
    for run in range(runs):
        images = [
            {"name": photo.name,
             "data": base64.b64encode(vary_bytes(photo.read_bytes(), run)).decode("ascii")}
            for photo in photos
        ]
        bodies.append({"images": images, "person": dict(person), "scenario": SCENARIO})
    return bodies


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(r["seconds"] for r in records)
    costs = [r["cost_usd"] for r in records]
    return {
        "p50_s": round(percentile(latencies, 50), 2),
        "p95_s": round(percentile(latencies, 95), 2),
        "mean_cost_usd": round(sum(costs) / len(costs), 6) if costs else 0.0,
        "total_cost_usd": round(sum(costs), 6),
        "total_retries_429": sum(r["retries_429"] for r in records),
        "all_coherent": all(r["coherent"] for r in records),
    }


def _timed(poster: Any, body: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    status, payload = poster(body)
    return _record(status, payload, time.monotonic() - started)


def execute(runs: int, max_cost: float, out_dir: Path, samples_live: Path,
            timeout: float = 600.0, poster: Any = None) -> dict[str, Any]:
    """Run the load check; returns the record and writes one new JSON file.

    poster overrides the HTTP transport (tests call route_post directly);
    without it a real 127.0.0.1 server is started and stopped here.
    """
    from claimlens.serve import Handler

    calls = runs * CALLS_PER_RUN_MAX
    if calls * max(EVAL_MD_COSTS) > max_cost:
        raise RuntimeError(
            f"Load estimate exceeds --max-cost ${max_cost:.2f}; refusing to launch.")
    bodies = build_bodies(samples_live, runs)
    server = None
    thread = None
    if poster is None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def poster(body: dict[str, Any]) -> tuple[int, dict]:
            return _http_post(server.server_port, body, timeout)
    try:
        with ThreadPoolExecutor(max_workers=runs) as pool:
            records = list(pool.map(lambda body: _timed(poster, body), bodies))
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
    for pos, record in enumerate(records):
        record["run"] = pos
    report = {
        "tool": "load",
        "runs": runs,
        "photos": [f"samples/live/{name}" for name in PHOTOS],
        "scenario": SCENARIO,
        "results": records,
        **summarize(records),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"load_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["path"] = str(path)
    return report

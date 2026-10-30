"""Fault injection matrix: every failure the suite pins, in one table.

Each entry names a fault, where it is injected, the expected outcome,
and the covering tests. No fault may ever surface as a wrong number:
provider faults raise or fall back, serve faults answer 4xx/5xx or stop
for a person, and the double-read gate stops unless both reads agree.

tests/test_faults.py asserts every entry has its tests; the README
table below is rendered from this data (never typed by hand); item 46
reuses the registry for its Measured block.
"""

FAULTS: tuple[dict[str, object], ...] = (
    {
        "id": "spark_timeout",
        "area": "provider",
        "fault": "Spark call times out",
        "expected": "RuntimeError; serve answers 503 with the error, no result",
        "tests": ("tests/test_faults.py::test_fault_spark_timeout",),
    },
    {
        "id": "http_429_recover",
        "area": "provider",
        "fault": "HTTP 429, then success",
        "expected": "retries with 1s/2s backoff, returns the reading",
        "tests": ("tests/test_faults.py::test_fault_429_recovers",),
    },
    {
        "id": "http_429_stop",
        "area": "provider",
        "fault": "HTTP 429 three times",
        "expected": "stops after 3 attempts, RuntimeError",
        "tests": ("tests/test_faults.py::test_fault_429_stops",),
    },
    {
        "id": "http_500",
        "area": "provider",
        "fault": "HTTP 500",
        "expected": "no retry, RuntimeError on the first failure",
        "tests": ("tests/test_faults.py::test_fault_500_stops",),
    },
    {
        "id": "bad_json",
        "area": "provider",
        "fault": "malformed or truncated JSON output",
        "expected": "RuntimeError, nothing stored or returned",
        "tests": ("tests/test_faults.py::test_fault_bad_json",),
    },
    {
        "id": "schema_violation",
        "area": "provider",
        "fault": "JSON breaks the strict schema",
        "expected": "RuntimeError, nothing stored or returned",
        "tests": ("tests/test_faults.py::test_fault_schema_violation",),
    },
    {
        "id": "empty_output",
        "area": "provider",
        "fault": "empty model output",
        "expected": "RuntimeError, nothing stored or returned",
        "tests": ("tests/test_faults.py::test_fault_empty_output",),
    },
    {
        "id": "files_fallback",
        "area": "provider",
        "fault": "Files API upload fails",
        "expected": "base64 fallback, files_error recorded, reading returned",
        "tests": ("tests/test_faults.py::test_fault_files_fallback",),
    },
    {
        "id": "neo4j_engine",
        "area": "engine",
        "fault": "Neo4j unreachable, member claim",
        "expected": "engine_unreachable badge stating the reason",
        "tests": ("tests/test_faults.py::test_fault_neo4j_engine",),
    },
    {
        "id": "neo4j_pack",
        "area": "engine",
        "fault": "Neo4j unreachable, visitor claim",
        "expected": "Claim Pack still built, no engine call",
        "tests": ("tests/test_faults.py::test_fault_pack_without_neo4j",),
    },
    {
        "id": "serve_offline",
        "area": "serve",
        "fault": "network down in claimlens serve",
        "expected": "page shows the error, never a stale result",
        "tests": ("tests/test_faults.py::test_fault_serve_offline",),
    },
    {
        "id": "oversized_upload",
        "area": "serve",
        "fault": "upload over the 10 MB limit",
        "expected": "400 naming the limit, nothing read",
        "tests": ("tests/test_faults.py::test_fault_oversized_upload",),
    },
    {
        "id": "non_image_upload",
        "area": "serve",
        "fault": "non-image upload",
        "expected": "400 naming the file, nothing read",
        "tests": ("tests/test_faults.py::test_fault_non_image_upload",),
    },
    {
        "id": "gate_single_failure",
        "area": "gate",
        "fault": "one of two reads fails or times out",
        "expected": "needs_manual_check; the single read never passes alone",
        "tests": ("tests/test_faults.py::test_fault_gate_single_failure",),
    },
    {
        "id": "gate_doc_count",
        "area": "gate",
        "fault": "reads disagree on document count",
        "expected": "needs_manual_check with a documents question",
        "tests": ("tests/test_faults.py::test_fault_gate_doc_count",),
    },
)


def render_table() -> str:
    """README section body generated from the registry (counts included)."""
    lines = [
        "## What happens when something fails",
        "",
        (f"{len(FAULTS)} fault cases, each pinned by a test with stubbed "
         "providers and requests — no case ever returns a wrong number."),
        "",
        "| fault | expected | test |",
        "|---|---|---|",
    ]
    for entry in FAULTS:
        tests = ", ".join(f"`{t.split('::')[1]}`" for t in entry["tests"])  # type: ignore[union-attr]
        lines.append(f"| {entry['fault']} | {entry['expected']} | {tests} |")
    return "\n".join(lines) + "\n"

"""MCP client test: speaks JSON-RPC to the server, lists and calls tools."""

import io
import json
from typing import Any

from claimlens.mcp import serve


def run_client(messages: list[dict[str, Any]], monkeypatch) -> list[dict[str, Any]]:
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
    stdout = io.StringIO()
    serve(stdin, stdout)
    return [
        json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()
    ]


def test_mcp_initialize_and_list_tools(monkeypatch):
    responses = run_client(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        monkeypatch,
    )
    assert [r.get("id") for r in responses] == [1, 2]  # no reply to notifications
    assert responses[0]["result"]["serverInfo"]["name"] == "claimlens"
    assert "tools" in responses[0]["result"]["capabilities"]
    names = [t["name"] for t in responses[1]["result"]["tools"]]
    assert names == [
        "read_documents",
        "run_checks",
        "decide_eligibility",
        "convert_codes",
        "adjudicate",
        "build_claim_pack",
    ]
    for tool in responses[1]["result"]["tools"]:
        assert "sample_id" in tool["inputSchema"]["properties"]


def call(monkeypatch, name: str, args: dict[str, Any]) -> dict[str, Any]:
    (response,) = run_client(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        ],
        monkeypatch,
    )
    assert response["id"] == 1
    assert response["result"]["isError"] is False
    return json.loads(response["result"]["content"][0]["text"])


def assert_provenance(result: dict[str, Any]) -> None:
    records = result["provenance"]
    assert len(records) > 0
    for record in records:
        assert record["label"] and record["source"] is not None
        assert "value" in record


def test_mcp_read_documents(monkeypatch):
    result = call(monkeypatch, "read_documents", {"sample_id": "S2_seoul_worker_bronchitis"})
    assert result["total"] == 45000
    assert result["diagnoses"] == ["J20.9"]
    assert_provenance(result)


def test_mcp_run_checks(monkeypatch):
    result = call(monkeypatch, "run_checks", {"sample_id": "S2_seoul_worker_bronchitis"})
    assert result["all_passed"] is True
    assert len(result["checks"]) == 11
    assert_provenance(result)


def test_mcp_decide_eligibility(monkeypatch):
    result = call(
        monkeypatch, "decide_eligibility", {"sample_id": "S2_seoul_worker_bronchitis"}
    )
    assert result["outcome"] == "nhi_member"
    assert_provenance(result)


def test_mcp_convert_codes(monkeypatch):
    result = call(monkeypatch, "convert_codes", {"sample_id": "S2_seoul_worker_bronchitis"})
    assert result["who"] == "J20.9"
    assert_provenance(result)


def test_mcp_adjudicate(monkeypatch):
    result = call(monkeypatch, "adjudicate", {"sample_id": "S2_seoul_worker_bronchitis"})
    assert result["decision"] == "PARTIAL"
    assert result["amount_krw"] == 22500
    assert_provenance(result)


def test_mcp_build_claim_pack(monkeypatch):
    result = call(
        monkeypatch, "build_claim_pack", {"sample_id": "S3_us_tourist_hip_fracture"}
    )
    assert result["total_krw"] == 15000000
    assert result["items"] == 12
    assert_provenance(result)


def test_mcp_unknown_tool_and_bad_arguments(monkeypatch):
    responses = run_client(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {"sample_id": "S2"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "read_documents", "arguments": {}},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "no_such_method"},
        ],
        monkeypatch,
    )
    assert [r["error"]["code"] for r in responses] == [-32602, -32602, -32601]


def test_mcp_unknown_sample_is_tool_error(monkeypatch):
    (response,) = run_client(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "read_documents", "arguments": {"sample_id": "nope"}},
            }
        ],
        monkeypatch,
    )
    assert response["result"]["isError"] is True

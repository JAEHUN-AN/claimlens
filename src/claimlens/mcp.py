"""MCP server over stdio: JSON-RPC without extra dependencies.

The six tools wrap the same deterministic engine functions the agent
uses. Every result carries provenance records (label/value/source) so
a calling agent can cite where each number came from. Replay mode
works through CLAIMLENS_PROVIDER=replay like the rest of the CLI.
"""

import json
from typing import Any, TextIO

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "claimlens"
SERVER_VERSION = "0.1.0"


def _sample_schema(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "sample_id": {
            "type": "string",
            "description": "Sample folder name, e.g. S2_seoul_worker_bronchitis.",
        },
        "variant": {
            "type": "string",
            "description": "Image variant.",
            "default": "photo",
        },
    }
    if extra:
        properties.update(extra)
    return {
        "type": "object",
        "properties": properties,
        "required": ["sample_id"],
        "additionalProperties": False,
    }


TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "read_documents",
        "description": "Read the receipt and certificate of one sample.",
        "inputSchema": _sample_schema(),
    },
    {
        "name": "run_checks",
        "description": "Run the receipt arithmetic checks on one sample.",
        "inputSchema": _sample_schema(),
    },
    {
        "name": "decide_eligibility",
        "description": "Decide insurance eligibility for one sample.",
        "inputSchema": _sample_schema(),
    },
    {
        "name": "convert_codes",
        "description": "Convert the certificate diagnosis KCD to WHO and ICD-10-CM.",
        "inputSchema": _sample_schema(
            {"facts": {"type": "object", "description": "Narrowing facts."}}
        ),
    },
    {
        "name": "adjudicate",
        "description": "Send the claim to the pinned adjudication engine.",
        "inputSchema": _sample_schema(),
    },
    {
        "name": "build_claim_pack",
        "description": "Build the English Claim Pack (visitors without a policy only).",
        "inputSchema": _sample_schema(),
    },
]


def _state(sample_id: str, variant: str) -> Any:
    from claimlens.agent import AgentState, tool_read_documents

    state = AgentState(sample_id=sample_id, variant=variant)
    tool_read_documents(state)
    return state


def _prov(label: str, value: Any, source: str) -> dict[str, Any]:
    return {"label": label, "value": value, "source": source}


def handle_read_documents(args: dict[str, Any]) -> dict[str, Any]:
    state = _state(str(args["sample_id"]), str(args.get("variant") or "photo"))
    receipt = state.reading["documents"][0]
    diags = state.reading["documents"][1].get("diagnoses", [])
    total = receipt.get("total_amount")
    summary = {
        "documents": [d.get("doc_type") for d in state.reading["documents"]],
        "currency": receipt.get("currency"),
        "total": total,
        "diagnoses": [d.get("code") for d in diags],
        "service_date": receipt.get("service_date"),
    }
    provenance = [_prov("Receipt total", total, f"receipt total_amount {total}")]
    for i, diag in enumerate(diags):
        code = diag.get("code")
        provenance.append(
            _prov(
                "Certificate diagnosis code",
                code,
                f"certificate diagnoses[{i}].code {code}",
            )
        )
    return {**summary, "provenance": provenance}


def handle_run_checks(args: dict[str, Any]) -> dict[str, Any]:
    from claimlens.agent import tool_run_checks

    state = _state(str(args["sample_id"]), str(args.get("variant") or "photo"))
    result = tool_run_checks(state)
    result["provenance"] = [
        _prov(
            f"Check {c['name']}",
            c["passed"],
            f"receipt arithmetic check {c['name']}",
        )
        for c in result.get("checks", [])
    ]
    return result


def handle_decide_eligibility(args: dict[str, Any]) -> dict[str, Any]:
    from claimlens.agent import tool_decide_eligibility

    state = _state(str(args["sample_id"]), str(args.get("variant") or "photo"))
    result = tool_decide_eligibility(state)
    result["provenance"] = [
        _prov(
            "Eligibility outcome",
            result.get("outcome"),
            f"eligibility rule {result.get('rule')}",
        ),
        _prov("Eligibility basis", result.get("basis"), "eligibility table row"),
    ]
    return result


def handle_convert_codes(args: dict[str, Any]) -> dict[str, Any]:
    from claimlens.agent import tool_convert_codes

    state = _state(str(args["sample_id"]), str(args.get("variant") or "photo"))
    result = tool_convert_codes(state, dict(args.get("facts") or {}))
    if "error" in result:
        return result
    cm = result.get("cm") or {}
    result["provenance"] = [
        _prov("KCD code", result.get("kcd"), "certificate code"),
        _prov(
            "WHO ICD-10 code",
            result.get("who"),
            "KCD-9 truncation to 4 characters",
        ),
        _prov(
            "ICD-10-CM candidate",
            cm.get("chosen"),
            "FY2027 defaults plus narrowing facts",
        ),
    ]
    return result


def handle_adjudicate(args: dict[str, Any]) -> dict[str, Any]:
    from claimlens.agent import tool_adjudicate
    from claimlens.engine import ENGINE_LABEL

    state = _state(str(args["sample_id"]), str(args.get("variant") or "photo"))
    result = tool_adjudicate(state)
    if "error" in result:
        return result
    amount = result.get("amount_krw")
    result["provenance"] = [
        _prov("Payable amount", amount, f"engine output amount {amount}"),
        _prov("Engine", ENGINE_LABEL, "pinned engine tag"),
    ]
    return result


def handle_build_claim_pack(args: dict[str, Any]) -> dict[str, Any]:
    from claimlens.agent import tool_build_claim_pack
    from claimlens.reader import get_provider

    state = _state(str(args["sample_id"]), str(args.get("variant") or "photo"))
    result = tool_build_claim_pack(state, get_provider())
    if "error" in result:
        return result
    total = result.get("total_krw")
    result["provenance"] = [
        _prov("Bill total", total, f"pack total_krw {total}"),
        _prov("Pack lines", result.get("items"), "itemized bill row count"),
    ]
    return result


HANDLERS = {
    "read_documents": handle_read_documents,
    "run_checks": handle_run_checks,
    "decide_eligibility": handle_decide_eligibility,
    "convert_codes": handle_convert_codes,
    "adjudicate": handle_adjudicate,
    "build_claim_pack": handle_build_claim_pack,
}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    msg_id = msg.get("id")
    method = msg.get("method", "")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOL_DEFS},
        }
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(msg_id, -32602, f"Unknown tool {name!r}.")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict) or "sample_id" not in arguments:
            return _error(msg_id, -32602, "Tool calls need a sample_id argument.")
        try:
            result = handler(arguments)
        except (LookupError, KeyError, ValueError, OSError) as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result)}],
                "isError": "error" in result,
            },
        }
    return _error(msg_id, -32601, f"Unknown method {method!r}.")


def serve(rfile: TextIO, wfile: TextIO) -> None:
    """Newline-delimited JSON-RPC loop (the MCP stdio transport)."""
    for line in rfile:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            wfile.write(json.dumps(_error(None, -32700, "Parse error.")) + "\n")
            wfile.flush()
            continue
        if not isinstance(msg, dict):
            wfile.write(
                json.dumps(_error(None, -32600, "Invalid request.")) + "\n"
            )
            wfile.flush()
            continue
        response = handle_message(msg)
        if response is not None:
            wfile.write(json.dumps(response) + "\n")
            wfile.flush()


def main() -> None:
    import sys

    serve(sys.stdin, sys.stdout)

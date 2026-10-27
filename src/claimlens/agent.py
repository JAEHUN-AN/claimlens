"""Clarifying agent: a tool-calling loop that asks instead of guessing.

The model picks the next tool each step; deterministic tools stay the only
source of numbers. When a value the engine or code conversion needs is
missing, the model must call ask_user — never guess it.
"""

import copy
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claimlens import cache as replay_cache
from claimlens.checks import all_passed, check_kr_bill, check_kr_lines
from claimlens.providers.meta import MODEL, cost_usd
from claimlens.schema import strict_schema_of

MAX_STEPS = 12
TRACE_DIR = "cache/agent"

SYSTEM = """You process one insurance claim with tools, one tool call per step.
Rules:
- Read each tool result before choosing the next tool.
- Never invent numbers, codes, or dates. Every number must come from a tool result.
- Ask only when a tool reports a value missing (a missing list, or an error
  telling you to ask): copay cells, copay rate, fracture side, enrolment date.
  A questions list that defaults already resolved is not missing — never ask
  to refine a conversion the tools already completed. Do not guess.
- Call convert_codes with no arguments first; only ask about side or
  open/closed when its result lists them missing.
- Cells shown as "hidden" cannot be recovered by re-reading; ask the user.
- Only Korean bills (kr_bill true) have copay cells; other receipts never do.
- When the claim is decided or the pack is built, stop calling tools and write
  a short final summary with the decision and amount.
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "read_documents",
        "description": "Read the receipt and certificate. Hidden cells show as hidden.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "run_checks",
        "description": "Run the receipt arithmetic checks on the current reading.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "reread_cells",
        "description": "Re-read named cells from the receipt image. Hidden cells are refused.",
        "parameters": {
            "type": "object",
            "properties": {"cells": {"type": "array", "items": {"type": "string"}}},
            "required": ["cells"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "decide_eligibility",
        "description": "Decide insurance eligibility from the person facts and service date.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "convert_codes",
        "description": "Convert the certificate diagnosis KCD to WHO and ICD-10-CM.",
        "parameters": {
            "type": "object",
            "properties": {
                "laterality": {"type": "string"},
                "open_closed": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "adjudicate",
        "description": "Send the claim to the adjudication engine via its replay cache.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "build_claim_pack",
        "description": "Build the English Claim Pack (visitors without a policy only).",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "ask_user",
        "description": "Ask the user for a missing value. Values given as cell_N=NNNN are recorded.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "why_needed": {"type": "string"},
            },
            "required": ["question", "why_needed"],
            "additionalProperties": False,
        },
    },
]

TASK = "Process the claim for sample {sample} ({variant} images)."


@dataclass
class AgentState:
    sample_id: str
    variant: str
    reading: dict[str, Any] | None = None
    hidden_cells: set[str] = field(default_factory=set)
    hidden_policy: set[str] = field(default_factory=set)
    hide_side: bool = False
    answers: dict[str, Any] = field(default_factory=dict)
    eligibility: dict[str, Any] | None = None
    codes: dict[str, Any] | None = None
    envelope: dict[str, Any] | None = None
    pack: dict[str, Any] | None = None


def parse_user_amounts(text: str) -> dict[str, int]:
    """Cell values from an answer: cell_1=45000 (commas allowed)."""
    found = {}
    for key, raw in re.findall(r"cell_(\d+)\s*=\s*([\d,]+)", text):
        found[f"cell_{key}"] = int(raw.replace(",", ""))
    return found


def parse_user_date(text: str) -> str | None:
    """First YYYY-MM-DD date in an answer, if any."""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else None


def parse_user_side(text: str) -> str | None:
    """Fracture side in an answer: right or left."""
    match = re.search(r"\b(right|left)\b", text.lower())
    return match.group(1) if match else None


def _bill(state: AgentState) -> dict[str, Any]:
    return (state.reading or {}).get("documents", [{}])[0].get("kr_bill") or {}


def tool_read_documents(state: AgentState) -> dict[str, Any]:
    from claimlens.engine import replay_reading

    reading = copy.deepcopy(replay_reading(state.sample_id, state.variant))
    bill = reading["documents"][0].get("kr_bill") or {}
    for key in state.hidden_cells:
        if key in bill:
            bill[key] = None
    if state.hide_side:
        for diag in reading["documents"][1].get("diagnoses", []):
            label = diag.get("label") or ""
            diag["label"] = re.sub(r"\b(right|left)\b", "", label, flags=re.IGNORECASE)
            diag["label"] = re.sub(r"\s+", " ", diag["label"]).strip()
    state.reading = reading
    receipt = reading["documents"][0]
    cells = {
        k: ("hidden" if k in state.hidden_cells else v)
        for k, v in bill.items()
        if k.startswith("cell_")
    }
    summary: dict[str, Any] = {
        "documents": [d.get("doc_type") for d in reading["documents"]],
        "currency": receipt.get("currency"),
        "total": receipt.get("total_amount"),
        "kr_bill": bool(bill),
        "institution": bill.get("institution_type"),
        "inpatient": receipt.get("inpatient"),
        "diagnoses": [d.get("code") for d in reading["documents"][1].get("diagnoses", [])],
        "service_date": receipt.get("service_date"),
    }
    if bill:
        summary["kr_cells"] = cells
    return summary


def tool_run_checks(state: AgentState) -> dict[str, Any]:
    if state.reading is None:
        return {"error": "no reading yet; call read_documents first."}
    receipt = state.reading["documents"][0]
    bill = receipt.get("kr_bill") or {}
    checks = [*check_kr_bill(bill), *check_kr_lines(receipt)]
    return {
        "all_passed": all_passed(checks),
        "checks": [{"name": c.name, "passed": c.passed} for c in checks],
    }


def tool_reread_cells(state: AgentState, cells: list[str], provider: Any) -> dict[str, Any]:
    from claimlens.reader import resolve_sample_images
    from claimlens.verify import build_reread_instructions, build_reread_model, merge_reread

    if state.reading is None:
        return {"error": "no reading yet; call read_documents first."}
    hidden = [c for c in cells if c in state.hidden_cells]
    if hidden:
        return {"error": f"{hidden} are hidden and cannot be re-read; ask the user."}
    receipt = state.reading["documents"][0]
    model = build_reread_model(cells)
    schema = strict_schema_of(model)
    image = resolve_sample_images(
        Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / state.sample_id,
        state.variant,
    )[0]
    try:
        reread = provider.read_documents(
            [image], build_reread_instructions(cells, receipt), schema, result_model=model
        )
    except LookupError as exc:
        return {"error": f"re-read not available offline: {exc}"}
    merged, corrected = merge_reread(receipt, reread)
    state.reading["documents"][0] = merged
    return {"corrected": corrected}


def tool_decide_eligibility(state: AgentState) -> dict[str, Any]:
    from claimlens.eligibility import check_eligibility
    from claimlens.engine import load_scenarios

    if state.reading is None:
        return {"error": "no reading yet; call read_documents first."}
    scenarios, _ = load_scenarios()
    service = state.reading["documents"][0].get("service_date") or ""
    result = check_eligibility(scenarios[state.sample_id]["person"], service)
    state.eligibility = result
    return result


def tool_convert_codes(state: AgentState, facts: dict[str, Any]) -> dict[str, Any]:
    from claimlens.codes import convert_diagnosis

    if state.reading is None:
        return {"error": "no reading yet; call read_documents first."}
    receipt = state.reading["documents"][0]
    diags = state.reading["documents"][1].get("diagnoses", [])
    if not diags or not diags[0].get("code"):
        return {"error": "no diagnosis code on the certificate."}
    merged = dict(facts or {})
    if state.answers.get("laterality"):
        merged.setdefault("laterality", state.answers["laterality"])
    if "laterality" not in merged:
        side = parse_user_side(diags[0].get("label") or "")
        if side:
            merged["laterality"] = side
    result = convert_diagnosis(diags[0]["code"], receipt.get("service_date"), merged)
    if result.get("who") == "S72.1" and "laterality" not in merged:
        result["cm"]["chosen"] = None
        result["missing"] = ["fracture side (left or right)"]
    state.codes = result
    return result


def tool_adjudicate(state: AgentState) -> dict[str, Any]:
    from claimlens.engine import build_inputs, copay_rate_from_bill, load_result

    if state.reading is None:
        return {"error": "no reading yet; call read_documents first."}
    receipt = state.reading["documents"][0]
    bill = receipt.get("kr_bill")
    if receipt.get("country") == "KR" and copay_rate_from_bill(bill) is None:
        return {
            "error": "cannot adjudicate without copay_rate (receipt cells 1 and 2); "
            "ask the user.",
            "missing": ["copay_rate (receipt cells 1 and 2)"],
        }
    try:
        inputs = build_inputs(state.sample_id, state.variant, state.reading)
    except (ValueError, KeyError) as exc:
        return {"error": str(exc), "missing": ["claim total"]}
    if "enrolled_on" in state.hidden_policy:
        inputs["enrolled_on"] = state.answers.get("enrolled_on")
    if not inputs.get("enrolled_on"):
        return {
            "error": "cannot adjudicate without the policy enrolment date "
            "(YYYY-MM-DD); ask the user.",
            "missing": ["policy enrolment date (YYYY-MM-DD)"],
        }
    try:
        output = load_result(state.sample_id, state.variant, inputs)
    except LookupError as exc:
        return {"error": str(exc)}
    state.envelope = {"inputs": inputs, "output": output}
    return {"decision": output["decision"], "amount_krw": output["amount"]}


def tool_build_claim_pack(state: AgentState, provider: Any) -> dict[str, Any]:
    from claimlens.claimpack import build_pack
    from claimlens.engine import load_scenarios

    if state.reading is None:
        return {"error": "no reading yet; call read_documents first."}
    _, inbound = load_scenarios()
    if state.sample_id not in inbound:
        return {"error": "traveller cases go through adjudication, not the pack."}
    try:
        pack = build_pack(state.sample_id, state.variant, provider)
    except ValueError as exc:
        return {"error": str(exc)}
    state.pack = pack
    return {
        "built": True,
        "items": len(pack["items"]),
        "total_krw": pack["total_krw"],
        "policy_line": pack["policy_line"],
    }


def tool_ask_user(
    state: AgentState, question: str, why_needed: str, answer_fn: Callable[[str, str], str]
) -> dict[str, Any]:
    answer = answer_fn(question, why_needed)
    recorded: dict[str, Any] = {}
    if state.reading is not None:
        bill = state.reading["documents"][0].get("kr_bill") or {}
        for key, value in parse_user_amounts(answer).items():
            if key in state.hidden_cells:
                bill[key] = value
                recorded[key] = value
        if recorded and set(recorded) >= {
            k for k in state.hidden_cells if k in bill
        }:
            receipt = state.reading["documents"][0]
            second = [*check_kr_bill(bill), *check_kr_lines(receipt)]
            if not all_passed(second):
                for key in recorded:
                    bill[key] = None
                failing = [c.name for c in second if not c.passed]
                return {
                    "answer": answer,
                    "recorded": {},
                    "error": f"those values contradict the receipt (failing: "
                    f"{', '.join(failing)}); nothing was recorded; ask again.",
                    "contradiction": True,
                }
    given_date = parse_user_date(answer)
    if given_date and "enrolled_on" in state.hidden_policy:
        state.answers["enrolled_on"] = given_date
        recorded["enrolled_on"] = given_date
    given_side = parse_user_side(answer)
    if given_side and (state.hide_side or "laterality" not in state.answers):
        state.answers["laterality"] = given_side
        recorded["laterality"] = given_side
    return {"answer": answer, "recorded": recorded}


def run_tool(
    state: AgentState,
    name: str,
    args: dict[str, Any],
    provider: Any,
    answer_fn: Callable[[str, str], str],
) -> dict[str, Any]:
    """Execute one tool; unknown tools and crashes become error results."""
    try:
        if name == "read_documents":
            return tool_read_documents(state)
        if name == "run_checks":
            return tool_run_checks(state)
        if name == "reread_cells":
            return tool_reread_cells(state, args.get("cells", []), provider)
        if name == "decide_eligibility":
            return tool_decide_eligibility(state)
        if name == "convert_codes":
            return tool_convert_codes(
                state, {k: v for k, v in args.items() if v is not None}
            )
        if name == "adjudicate":
            return tool_adjudicate(state)
        if name == "build_claim_pack":
            return tool_build_claim_pack(state, provider)
        if name == "ask_user":
            return tool_ask_user(state, args["question"], args["why_needed"], answer_fn)
        return {"error": f"unknown tool {name}."}
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"tool {name} failed: {exc}"}


def _model_key(history: list[dict[str, Any]], namespace: str = "") -> str:
    instructions = json.dumps(history, ensure_ascii=False, sort_keys=True)
    if namespace:
        instructions = f"[{namespace}]\n{instructions}"
    return replay_cache.cache_key([], instructions, {"tools": TOOLS}, MODEL)


def model_turn(
    history: list[dict[str, Any]], live: bool, namespace: str = ""
) -> dict[str, Any]:
    """One model step: live call recorded, or the recording replayed."""
    key = _model_key(history, namespace)
    if not live:
        return replay_cache.load(key)
    import dotenv
    from openai import OpenAI

    from claimlens.providers.meta import BASE_URL

    dotenv.load_dotenv()
    api_key = os.environ.get("META_API_KEY")
    if not api_key:
        raise RuntimeError("META_API_KEY is not set; cannot run the agent live.")
    client = OpenAI(base_url=BASE_URL, api_key=api_key)
    response = client.responses.create(
        model=MODEL, input=history, tools=TOOLS, tool_choice="auto", reasoning={"effort": "low"}
    )
    usage = response.usage
    in_tokens = getattr(usage, "input_tokens", 0) or 0
    out_tokens = getattr(usage, "output_tokens", 0) or 0
    total = getattr(usage, "total_tokens", in_tokens + out_tokens) or 0
    calls, texts = [], []
    for item in response.output:
        if getattr(item, "type", "") == "function_call":
            calls.append(
                {"name": item.name, "arguments": item.arguments, "call_id": item.call_id}
            )
        elif getattr(item, "type", "") == "message":
            for part in item.content or []:
                if getattr(part, "type", "") == "output_text":
                    texts.append(part.text)
    payload = {
        "model": MODEL,
        "calls": calls,
        "text": "\n".join(texts),
        "usage": {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": total,
            "cost_usd": cost_usd(in_tokens, out_tokens),
        },
    }
    replay_cache.store(key, payload)
    return payload


def run_agent(
    sample_id: str,
    variant: str,
    answer_fn: Callable[[str, str], str],
    live: bool,
    hidden_cells: set[str] | None = None,
    hidden_policy: set[str] | None = None,
    hide_side: bool = False,
    max_steps: int = MAX_STEPS,
    namespace: str = "",
) -> dict[str, Any]:
    """Run the loop; returns the trace, outcome, and model usage."""
    from claimlens.providers.replay import ReplayProvider

    state = AgentState(
        sample_id=sample_id,
        variant=variant,
        hidden_cells=set(hidden_cells or ()),
        hidden_policy=set(hidden_policy or ()),
        hide_side=hide_side,
    )
    provider = ReplayProvider()
    history: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": SYSTEM + TASK.format(sample=sample_id, variant=variant),
                }
            ],
        }
    ]
    trace: list[dict[str, Any]] = []
    usages: list[dict[str, Any]] = []
    for step in range(1, max_steps + 1):
        turn = model_turn(history, live, namespace)
        usages.append(turn["usage"])
        if not turn["calls"]:
            trace.append({"n": step, "kind": "final", "text": turn["text"]})
            break
        call = turn["calls"][0]
        args = json.loads(call["arguments"] or "{}")
        result = run_tool(state, call["name"], args, provider, answer_fn)
        entry: dict[str, Any] = {"n": step, "kind": "tool", "tool": call["name"], "args": args}
        if call["name"] == "ask_user":
            entry["kind"] = "question"
            entry["question"] = args.get("question", "")
            entry["why_needed"] = args.get("why_needed", "")
            entry["answer"] = result.get("answer", "")
        entry["result"] = result
        trace.append(entry)
        history.append(
            {
                "type": "function_call",
                "call_id": call["call_id"],
                "name": call["name"],
                "arguments": call["arguments"],
            }
        )
        history.append(
            {
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": json.dumps(result, ensure_ascii=False),
            }
        )
    else:
        trace.append({"n": max_steps + 1, "kind": "stopped", "reason": "step cap reached"})
    outcome: dict[str, Any] = {}
    if state.envelope:
        outcome = {
            "decision": state.envelope["output"]["decision"],
            "amount_krw": state.envelope["output"]["amount"],
        }
    elif state.pack:
        outcome = {"pack_built": True, "total_krw": state.pack["total_krw"]}
    return {"scenario": sample_id, "trace": trace, "outcome": outcome, "usages": usages}


def trace_path(name: str) -> Path:
    return Path(TRACE_DIR) / f"{name}.json"


def save_trace(name: str, result: dict[str, Any]) -> Path:
    path = trace_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_trace(name: str) -> dict[str, Any]:
    return json.loads(trace_path(name).read_text(encoding="utf-8"))

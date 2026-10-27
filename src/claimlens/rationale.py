"""English rationale cards rephrasing engine output (backlog 6).

The model only rephrases engine text. Amounts, step names, and clause IDs are
copied by code, and a check rejects any number or clause ID the engine did
not emit.
"""

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

_NUMBER_RE = re.compile(r"\d[\d,]*(\.\d+)?")


class RationaleStep(BaseModel):
    step: str = Field(description="Engine step name, copied exactly.")
    text: str = Field(description="One English line rephrasing the step.")


class RationaleClause(BaseModel):
    id: str = Field(description="Engine clause node id, copied exactly.")
    text: str = Field(description="One English line rephrasing the clause.")


class Rationale(BaseModel):
    summary: str = Field(description="Two or three English sentences overall.")
    steps: list[RationaleStep] = Field(description="One line per engine step.")
    clauses: list[RationaleClause] = Field(description="Cited clauses only.")


def rationale_schema() -> dict[str, Any]:
    return strict_schema_of(Rationale)


def rationale_payload(engine_inputs: dict[str, Any], engine_output: dict[str, Any]) -> dict[str, Any]:
    """Curated engine facts for the prompt; volatile fields left out."""
    steps = [
        {"step": s.get("step", ""), "summary": s.get("summary", ""), "detail": s.get("detail", {})}
        for s in engine_output.get("steps", [])
    ]
    evidence = [
        {
            "id": e.get("node_uid", ""),
            "title": e.get("article_title", ""),
            "quote": e.get("quote", ""),
            "role": e.get("role", ""),
        }
        for e in engine_output.get("evidence", [])
    ]
    return {
        "decision": engine_output.get("decision", ""),
        "amount_krw": engine_output.get("amount", 0),
        "claimed_krw": engine_inputs.get("claimed_amount_krw", 0),
        "reason": engine_output.get("reason", ""),
        "steps": steps,
        "evidence": evidence,
        "guardrails": engine_output.get("guardrails", []),
    }


RATIONALE_PREAMBLE = """You explain an insurance claim decision in English for the claimant.
Rephrase ONLY the engine output below. Copy every step name and clause id
exactly as given. Write numerals ONLY when the exact number appears in the
engine output; never compute, round differently, or invent amounts, dates,
counts, or clause ids. Plain words for anything else. No medical advice."""


def rationale_instructions(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return f"{RATIONALE_PREAMBLE}\nEngine output:\n{body}"


def _normalize_number(raw: str) -> str:
    cleaned = raw.replace(",", "").lstrip("0")
    return cleaned or "0"


def engine_numbers(payload: dict[str, Any]) -> set[str]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(text)}


def draft_numbers(draft: dict[str, Any]) -> set[str]:
    parts = [draft.get("summary", "")]
    parts += [s.get("text", "") for s in draft.get("steps", [])]
    parts += [c.get("text", "") for c in draft.get("clauses", [])]
    found: set[str] = set()
    for part in parts:
        found.update(_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(part))
    return found


def check_rationale(draft: dict[str, Any], payload: dict[str, Any]) -> None:
    """Reject any step name, clause id, or number the engine did not emit."""
    want_steps = {s["step"] for s in payload["steps"]}
    got_steps = {s["step"] for s in draft.get("steps", [])}
    if not got_steps <= want_steps:
        raise ValueError(f"Unknown step names: {sorted(got_steps - want_steps)}.")
    want_ids = {e["id"] for e in payload["evidence"]}
    got_ids = {c["id"] for c in draft.get("clauses", [])}
    if not got_ids <= want_ids:
        raise ValueError(f"Unknown clause ids: {sorted(got_ids - want_ids)}.")
    allowed = engine_numbers(payload)
    unknown = sorted(n for n in draft_numbers(draft) if n not in allowed)
    if unknown:
        raise ValueError(f"Numbers not in engine output: {unknown}.")


def build_rationale(sample_id: str, variant: str, provider: Any) -> dict[str, Any]:
    """Draft (model), check (code), then assemble the card with engine facts."""
    from claimlens.engine import build_inputs, load_result, replay_reading

    reading = replay_reading(sample_id, variant)
    inputs = build_inputs(sample_id, variant, reading)
    output = load_result(sample_id, variant, inputs)
    payload = rationale_payload(inputs, output)
    draft = provider.write(rationale_instructions(payload), rationale_schema(), Rationale)
    check_rationale(draft, payload)
    titles = {e["id"]: e["title"] for e in payload["evidence"]}
    return {
        "sample": sample_id,
        "variant": variant,
        "decision": output["decision"],
        "amount_krw": output["amount"],
        "summary": draft["summary"],
        "steps": [{"step": s["step"], "text": s["text"]} for s in draft["steps"]],
        "clauses": [
            {"id": c["id"], "title": titles.get(c["id"], ""), "text": c["text"]}
            for c in draft["clauses"]
        ],
        "guardrails": payload["guardrails"],
        "provider": provider.name,
        "model": provider.model,
        "calls": [vars(c) for c in provider.calls],
    }


def format_card(card: dict[str, Any]) -> str:
    lines = [
        f"# Claim decision: {card['sample']}",
        "",
        f"Decision: **{card['decision']}**",
        f"Amount: **{card['amount_krw']:,} KRW** (copied from the engine output)",
        "",
        card["summary"],
        "",
        "## Steps",
        "",
    ]
    for item in card["steps"]:
        lines.append(f"- {item['text']}")
    lines += ["", "## Cited clauses", ""]
    for item in card["clauses"]:
        lines.append(f"- `{item['id']}` ({item['title']}): {item['text']}")
    if card["guardrails"]:
        lines += ["", "Guardrails: " + ", ".join(card["guardrails"])]
    return "\n".join(lines) + "\n"


def rationale_provider_default() -> Any:
    load_dotenv()
    if os.environ.get("CLAIMLENS_PROVIDER", "meta").lower() == "replay":
        from claimlens.providers.replay import ReplayProvider

        return ReplayProvider()
    from claimlens.providers.meta import MetaProvider

    return MetaProvider()

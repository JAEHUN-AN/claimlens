"""Agent scorecard: 8 scripted cases, asking when it must and only then."""

import json
import re
from collections.abc import Callable
from typing import Any

NUMBER_RE = re.compile(r"\d{4}-\d{2}-\d{2}|(?<![A-Za-z_0-9])\d[\d,]*(\.\d+)?")

CASES: list[dict[str, Any]] = [
    {
        "id": "ask-hidden-copay",
        "sample": "S2_seoul_worker_bronchitis",
        "hidden_cells": {"cell_1", "cell_2"},
        "answers": ["cell_1=45000, cell_2=45000"],
        "must_ask": True,
        "expect": {"decision": "PARTIAL", "amount_krw": 22500},
    },
    {
        "id": "noask-s2-complete",
        "sample": "S2_seoul_worker_bronchitis",
        "answers": [],
        "must_ask": False,
        "expect": {"decision": "PARTIAL", "amount_krw": 22500},
    },
    {
        "id": "ask-enrolment",
        "sample": "A_niseko_wrist",
        "hidden_policy": {"enrolled_on"},
        "answers": [
            {"match": "wrist", "text": "The left wrist; a closed fracture."},
            {"match": "enrol", "text": "The policy started on 2026-07-01."},
        ],
        "must_ask": True,
        "expect": {"decision": "PAID", "amount_krw": 2216050},
    },
    {
        "id": "noask-a-complete",
        "sample": "A_niseko_wrist",
        "answers": [],
        "must_ask": False,
        "expect": {"decision": "PAID", "amount_krw": 2216050},
    },
    {
        "id": "ask-side",
        "sample": "S3_us_tourist_hip_fracture",
        "hide_side": True,
        "answers": ["The right femur; a closed fracture."],
        "must_ask": True,
        "expect": {"cm_chosen": "S72.141A"},
    },
    {
        "id": "noask-s3-complete",
        "sample": "S3_us_tourist_hip_fracture",
        "answers": [],
        "must_ask": False,
        "expect": {"cm_chosen": "S72.141A"},
    },
    {
        "id": "confirm-voice-date",
        "voice_clip": "W_factory_fall_ko",
        "must_ask": True,
        "expect": {"confirmations": ["incident_date", "visa"]},
    },
    {
        "id": "reject-contradiction",
        "sample": "S2_seoul_worker_bronchitis",
        "hidden_cells": {"cell_1", "cell_2"},
        "answers": ["cell_1=50000, cell_2=45000", "cell_1=45000, cell_2=45000"],
        "must_ask": True,
        "expect": {"decision": "PARTIAL", "amount_krw": 22500, "questions": 2},
    },
]


def scripted(answers: list[str | dict[str, str]]) -> Callable[[str, str], str]:
    """Answers in order; a {"match": ..., "text": ...} entry matches any order."""
    asked: list[str] = []
    used: set[int] = set()

    def answer(question: str, why_needed: str) -> str:
        asked.append(question)
        lowered = question.lower()
        for n, entry in enumerate(answers):
            if n in used or not isinstance(entry, dict):
                continue
            if entry["match"].lower() in lowered:
                used.add(n)
                return entry["text"]
        plain = [a for n, a in enumerate(answers) if n not in used and isinstance(a, str)]
        if plain:
            used.add(answers.index(plain[0]))
            return plain[0]
        raise AssertionError(f"Unexpected question: {question} ({why_needed})")

    return answer


def number_tokens(text: str) -> list[str]:
    return [t.replace(",", "") for t in NUMBER_RE.findall(text)]


def invented_numbers(trace: list[dict[str, Any]]) -> list[str]:
    """Numbers in model prose (final, questions) missing from every tool result."""
    corpus = []
    prose = []
    for entry in trace:
        if entry["kind"] == "tool":
            corpus.append(json.dumps(entry["result"], ensure_ascii=False))
        elif entry["kind"] == "question":
            corpus.append(entry["answer"])
            prose.append(entry["question"])
            prose.append(entry.get("why_needed", ""))
        elif entry["kind"] == "final":
            prose.append(entry.get("text", ""))
    joined = " ".join(corpus)
    invented = []
    for text in prose:
        for token in number_tokens(text):
            if token and token not in joined and token not in invented:
                invented.append(token)
    return invented


def run_case(case: dict[str, Any], live: bool) -> dict[str, Any]:
    from claimlens.agent import run_agent

    if "voice_clip" in case:
        from claimlens.providers.replay import ReplayProvider
        from claimlens.voice import intake

        result = intake(case["voice_clip"], live=False, provider=ReplayProvider())
        fields = [c["field"] for c in result["confirmations"]]
        asked = fields == case["expect"]["confirmations"]
        return {
            "case": case["id"],
            "must_ask": True,
            "asked": asked,
            "asked_when_needed": asked,
            "no_needless": True,
            "no_invented": True,
            "steps": 0,
            "cost": 0.0,
            "notes": f"confirm: {','.join(fields)}",
        }
    result = run_agent(
        case["sample"],
        "photo",
        scripted(case["answers"]),
        live=live,
        hidden_cells=set(case.get("hidden_cells") or ()),
        hidden_policy=set(case.get("hidden_policy") or ()),
        hide_side=bool(case.get("hide_side", False)),
        namespace=case["id"],
    )
    trace = result["trace"]
    questions = [e for e in trace if e["kind"] == "question"]
    asked = len(questions) > 0
    invented = invented_numbers(trace)
    cost = sum(u.get("cost_usd", 0) or 0 for u in result.get("usages", []))
    notes = ""
    expect = case.get("expect", {})
    if "decision" in expect:
        outcome = result.get("outcome", {})
        ok = outcome.get("decision") == expect["decision"] and outcome.get(
            "amount_krw"
        ) == expect["amount_krw"]
        notes = f"{outcome.get('decision')} {outcome.get('amount_krw')}"
        if not ok:
            notes += " (EXPECTED " + f"{expect['decision']} {expect['amount_krw']})"
    if "cm_chosen" in expect:
        converts = [e for e in trace if e.get("tool") == "convert_codes"]
        chosen = converts[-1]["result"].get("cm", {}).get("chosen") if converts else None
        notes = f"CM {chosen}"
        if chosen != expect["cm_chosen"]:
            notes += f" (EXPECTED {expect['cm_chosen']})"
    if "questions" in expect and len(questions) != expect["questions"]:
        notes += f" (EXPECTED {expect['questions']} questions)"
    return {
        "case": case["id"],
        "must_ask": case["must_ask"],
        "asked": asked,
        "asked_when_needed": (not case["must_ask"]) or asked,
        "no_needless": (not asked) if not case["must_ask"] else True,
        "no_invented": not invented,
        "steps": len(trace),
        "cost": round(cost, 6),
        "notes": notes.strip(),
    }


def eval_all(live: bool = False) -> list[dict[str, Any]]:
    return [run_case(case, live) for case in CASES]


def format_markdown(rows: list[dict[str, Any]]) -> str:
    header = (
        "| case | must_ask | asked | asked_when_needed | no_needless "
        "| no_invented | steps | cost | notes |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|"
    def tick(value: bool) -> str:
        return "yes" if value else "NO"

    lines = [header, sep]
    for r in rows:
        cost = f"${r['cost']:.4f}"
        lines.append(
            f"| {r['case']} | {tick(r['must_ask'])} | {tick(r['asked'])} "
            f"| {tick(r['asked_when_needed'])} | {tick(r['no_needless'])} "
            f"| {tick(r['no_invented'])} | {r['steps']} | {cost} | {r['notes']} |"
        )
    return "\n".join(lines) + "\n"

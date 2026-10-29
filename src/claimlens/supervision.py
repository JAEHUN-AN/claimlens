"""Verification the agent cannot skip, plus escalation and sign-off.

Pattern inspired by Meta's legal-agent-workshop (VERIFICATION.md and
ESCALATION_RULES.md — own implementation, no copied code): checks run
inside the terminal tools at fixed points, so the model loop cannot
skip them; a second Spark pass confirms model statements against
their quotes; refusals escalate to a person with a handoff; nothing
ships without reviewer sign-off.
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

REFUSAL_LIMIT = 3
REVISION_STEPS = 4

VERIFY_PREAMBLE = """You check quoted evidence for insurance paperwork. Below is a \
list of claims, each with one statement and the quoted text that should \
support it. For each claim in order, answer whether the quote supports \
the statement. Judge support only: the quote contains the statement's \
content, or it does not. Answer true only when the support is explicit."""


class ClaimVerdict(BaseModel):
    supported: bool = Field(description="True when the quote supports the statement.")


class ClaimVerdictSet(BaseModel):
    verdicts: list[ClaimVerdict] = Field(description="One verdict per claim, in order.")


def verdicts_schema() -> dict[str, Any]:
    return strict_schema_of(ClaimVerdictSet)


def verify_claims(claims: list[dict[str, str]], provider: Any) -> dict[str, Any]:
    """One Spark call per claim set; unsupported statements are dropped.

    Code still owns every number: the model only judges whether each
    quote supports its statement. Empty input makes no call.
    """
    if not claims:
        return {"verdicts": [], "dropped": 0}
    instructions = (
        f"{VERIFY_PREAMBLE}\nClaims:\n{json.dumps(claims, ensure_ascii=False, sort_keys=True)}"
    )
    draft = provider.write(instructions, verdicts_schema(), ClaimVerdictSet)
    verdicts = [bool(v.get("supported")) for v in draft.get("verdicts", [])]
    if len(verdicts) != len(claims):
        raise ValueError(
            f"Verifier returned {len(verdicts)} verdicts for {len(claims)} claims."
        )
    kept = [c for c, ok in zip(claims, verdicts, strict=True) if ok]
    return {"verdicts": verdicts, "kept": kept, "dropped": len(claims) - len(kept)}


def verify_receipt_gate(state: Any) -> dict[str, Any]:
    """Receipt checks passed, or were verified by a re-read."""
    from claimlens.checks import all_passed, check_kr_bill, check_kr_lines

    receipt = (state.reading or {}).get("documents", [{}])[0]
    bill = receipt.get("kr_bill")
    if not bill:
        # Recorded agent turns are keyed on this feedback; keep it stable.
        return {"passed": True, "feedback": "no bill checks for non-Korean receipts."}
    checks = [*check_kr_bill(bill), *check_kr_lines(receipt)]
    if all_passed(checks):
        if getattr(state, "reread_verified", False):
            return {"passed": True, "feedback": "checks pass after a verified re-read."}
        return {"passed": True, "feedback": "receipt checks pass."}
    failing = [c.name for c in checks if not c.passed]
    return {
        "passed": False,
        "feedback": f"receipt checks failing ({', '.join(failing)}); "
        "re-read the failed cells or ask the user.",
    }


def verify_no_blockers(state: Any) -> dict[str, Any]:
    """No consistency blocker open (deterministic layer; no model call)."""
    from claimlens.consistency import deterministic_findings

    docs = (state.reading or {}).get("documents", [])
    if len(docs) < 2:
        return {"passed": True, "feedback": "single document; nothing to compare."}
    findings = deterministic_findings(docs[0], docs[1])
    blockers = [f for f in findings if f["severity"] == "blocker"]
    if not blockers:
        return {"passed": True, "feedback": "no consistency blockers."}
    kinds = ", ".join(sorted({f["kind"] for f in blockers}))
    first = blockers[0]
    return {
        "passed": False,
        "feedback": f"consistency blockers open ({kinds}); resolve them first.",
        "question": first.get("question", ""),
        "why_needed": first.get("why_needed", ""),
    }


def guard_terminal_tool(state: Any, tool: str) -> dict[str, Any] | None:
    """Refusal for adjudicate/build_claim_pack, or None to proceed."""
    if state.reading is None:
        return None
    gate = verify_receipt_gate(state)
    if not gate["passed"]:
        return {
            "refused": True,
            "rule": "receipt_checks",
            "feedback": gate["feedback"],
            "error": f"refused by verification ({tool}): {gate['feedback']}",
        }
    blockers = verify_no_blockers(state)
    if not blockers["passed"]:
        return {
            "refused": True,
            "rule": "no_open_blockers",
            "feedback": blockers["feedback"],
            "question": blockers.get("question", ""),
            "why_needed": blockers.get("why_needed", ""),
            "error": f"refused by verification ({tool}): {blockers['feedback']}",
        }
    return None


def build_handoff(tool: str, refusal: dict[str, Any], state: Any) -> dict[str, Any]:
    """What the person sees: blocked item, rule, what was read, one question."""
    reading = state.reading or {}
    docs = reading.get("documents", [])
    receipt = docs[0] if docs else {}
    if refusal.get("rule") == "no_open_blockers":
        question = refusal.get("question") or "Resolve the consistency blockers."
        why = refusal.get("why_needed") or ""
    else:
        question = "The receipt checks fail. Provide the corrected cells or confirm the documents."
        why = refusal.get("feedback", "")
    return {
        "blocked_item": tool,
        "rule_fired": refusal.get("rule", ""),
        "what_was_read": {
            "documents": [d.get("doc_type") for d in docs],
            "total": receipt.get("total_amount"),
            "currency": receipt.get("currency"),
        },
        "question": question,
        "why_needed": why,
    }


class Supervisor:
    """Counts refusals, opens handoffs, resumes, and takes sign-off.

    A run that stops for a person makes no model calls until someone
    acts: resume() refuses without an answer or new documents before
    touching the model, and approve() ends the run directly.
    """

    def __init__(self) -> None:
        self.refusals = 0
        self.checkpoint: dict[str, Any] | None = None
        self.handoff: dict[str, Any] | None = None
        self.revision_used = False
        self.signed: str | None = None

    def observe(self, tool: str, result: dict[str, Any], state: Any) -> dict[str, Any] | None:
        """Feed one tool result; returns a handoff when the run must stop."""
        if not isinstance(result, dict) or not result.get("refused"):
            self.refusals = 0
            return None
        if result.get("rule") == "no_open_blockers":
            self.handoff = build_handoff(tool, result, state)
            return self.handoff
        self.refusals += 1
        if self.refusals >= REFUSAL_LIMIT:
            self.handoff = build_handoff(tool, result, state)
            return self.handoff
        return None

    def resume(self, answer: str | None = None, new_documents: bool = False) -> dict[str, Any]:
        """Continue the stopped run; refuses with no model call otherwise."""
        if self.checkpoint is None:
            raise ValueError("Nothing to resume: the run never stopped for a person.")
        if not answer and not new_documents:
            raise ValueError("Resume needs an answer or new documents; no model call made.")
        self.handoff = None
        self.refusals = 0
        checkpoint, self.checkpoint = self.checkpoint, None
        return _continue(checkpoint, self, answer=answer)

    def signoff(self, approve: bool, notes: str = "") -> dict[str, Any]:
        """Reviewer decision; return sends notes back for one revision."""
        if self.checkpoint is None:
            raise ValueError("Nothing to sign off: no finished run is waiting.")
        if approve:
            self.checkpoint = None
            self.signed = "approved"
            return {"status": "done", "signed": "approved"}
        if self.revision_used:
            raise ValueError("Only one revision is allowed.")
        if not notes:
            raise ValueError("Returning without notes helps nobody; say what to fix.")
        self.revision_used = True
        checkpoint, self.checkpoint = self.checkpoint, None
        result = _continue(checkpoint, self, answer=notes, steps_budget=REVISION_STEPS)
        result["status"] = "revised"
        return result


def replay_trace_guards(trace_name: str, hidden_cells: set[str] | None = None) -> list[dict[str, Any]]:
    """Re-execute a recorded trace's tools, capturing each guard verdict.

    Deterministic replay (no model): answers come from the recorded
    questions. Only terminal tools carry guard verdicts.
    """
    from claimlens.agent import AgentState, load_trace, run_tool
    from claimlens.providers.replay import ReplayProvider

    recorded = load_trace(trace_name)
    state = AgentState(
        sample_id=recorded["scenario"], variant="photo", hidden_cells=set(hidden_cells or ())
    )
    provider = ReplayProvider()
    answers = [e.get("answer", "") for e in recorded["trace"] if e.get("kind") == "question"]
    verdicts: list[dict[str, Any]] = []
    for entry in recorded["trace"]:
        tool = entry.get("tool", "")
        if entry.get("kind") == "question":
            tool = "ask_user"
        if tool not in ("read_documents", "run_checks", "reread_cells",
                        "decide_eligibility", "convert_codes", "adjudicate",
                        "build_claim_pack", "ask_user"):
            continue
        args = dict(entry.get("args", {}))
        if tool == "ask_user":
            args = {"question": entry.get("question", ""), "why_needed": entry.get("why_needed", "")}
        answer = answers.pop(0) if tool == "ask_user" and answers else ""
        result = run_tool(state, tool, args, provider, lambda q, w, a=answer: a)
        if tool in ("adjudicate", "build_claim_pack"):
            refused = bool(result.get("refused"))
            verdicts.append(
                {
                    "step": entry.get("n"),
                    "tool": tool,
                    "verdict": "refuse" if refused else "pass",
                    "rule": result.get("rule", ""),
                    "feedback": result.get("feedback", result.get("error", "")),
                }
            )
    return verdicts


def build_walkthrough() -> dict[str, Any]:
    """Scripted verification walkthrough (deterministic, no model).

    Refusal, fix, handoff, resumed checks, and approval are real tool
    outputs; only the reviewer's return notes are scripted input.
    """
    from claimlens.agent import (
        AgentState,
        tool_adjudicate,
        tool_ask_user,
        tool_read_documents,
        tool_run_checks,
    )
    from claimlens.engine import replay_reading

    bill = replay_reading("S2_seoul_worker_bronchitis", "photo")["documents"][0]["kr_bill"]
    answer = f"cell_1={bill['cell_1']}, cell_2={bill['cell_2']}"
    state = AgentState(
        sample_id="S2_seoul_worker_bronchitis", variant="photo",
        hidden_cells={"cell_1", "cell_2"},
    )
    tool_read_documents(state)
    refused = tool_adjudicate(state)
    asked = tool_ask_user(state, "Which cells?", "To pass the checks.", lambda q, w: answer)
    fixed = tool_adjudicate(state)
    supervisor = Supervisor()
    handoff = None
    for _ in range(REFUSAL_LIMIT):
        handoff = supervisor.observe("adjudicate", refused, state)
    rerun = tool_run_checks(state)
    passed = sum(1 for c in rerun["checks"] if c["passed"])
    total = len(rerun["checks"])
    supervisor.checkpoint = {"walkthrough": True}
    signed = supervisor.signoff(approve=True)
    return {
        "refusal": {
            "tool": "adjudicate",
            "rule": refused["rule"],
            "feedback": refused["feedback"],
        },
        "fix": {
            "recorded": asked["recorded"],
            "decision": fixed["decision"],
            "amount_krw": fixed["amount_krw"],
        },
        "handoff": handoff,
        "resume": {"answer": answer, "checks": f"{passed}/{total} pass"},
        "signoff": {
            "returned_notes": "Confirm the checks pass before paying.",
            "revision": f"re-ran checks: {passed}/{total} pass",
            "signed": signed["signed"],
        },
    }


def _outcome(state: Any) -> dict[str, Any]:
    if state.envelope:
        return {
            "decision": state.envelope["output"]["decision"],
            "amount_krw": state.envelope["output"]["amount"],
        }
    if state.pack:
        return {"pack_built": True, "total_krw": state.pack["total_krw"]}
    return {}


def _steps(
    state: Any,
    history: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    usages: list[dict[str, Any]],
    ctx: dict[str, Any],
    start: int,
    max_steps: int,
    supervisor: "Supervisor",
) -> dict[str, Any]:
    """The supervised loop; same primitives and history format as run_agent."""
    from claimlens.agent import model_turn, run_tool

    for step in range(start, max_steps + 1):
        turn = model_turn(history, ctx["live"], ctx["namespace"])
        usages.append(turn["usage"])
        if not turn["calls"]:
            trace.append({"n": step, "kind": "final", "text": turn["text"]})
            break
        call = turn["calls"][0]
        args = json.loads(call["arguments"] or "{}")
        result = run_tool(state, call["name"], args, ctx["provider"], ctx["answer_fn"])
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
        handoff = supervisor.observe(call["name"], result, state)
        if handoff is not None:
            trace.append({"n": step, "kind": "escalated", "handoff": handoff})
            supervisor.checkpoint = {**ctx, "state": state, "history": history,
                                     "trace": trace, "usages": usages, "next_step": step + 1}
            return {"status": "escalated", "handoff": handoff}
    else:
        trace.append({"n": max_steps + 1, "kind": "stopped", "reason": "step cap reached"})
    return {"status": "finished"}


def run_supervised(
    sample_id: str,
    variant: str,
    answer_fn: Any,
    live: bool,
    hidden_cells: set[str] | None = None,
    hidden_policy: set[str] | None = None,
    hide_side: bool = False,
    max_steps: int | None = None,
    namespace: str = "",
    supervisor: "Supervisor | None" = None,
) -> dict[str, Any]:
    """run_agent with verification, escalation, and sign-off support."""
    from claimlens.agent import MAX_STEPS, SYSTEM, TASK, AgentState
    from claimlens.providers.replay import ReplayProvider

    max_steps = MAX_STEPS if max_steps is None else max_steps
    supervisor = supervisor or Supervisor()
    state = AgentState(
        sample_id=sample_id,
        variant=variant,
        hidden_cells=set(hidden_cells or ()),
        hidden_policy=set(hidden_policy or ()),
        hide_side=hide_side,
    )
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
    ctx = {
        "sample_id": sample_id,
        "variant": variant,
        "live": live,
        "namespace": namespace,
        "max_steps": max_steps,
        "answer_fn": answer_fn,
        "provider": ReplayProvider(),
        "supervisor": supervisor,
    }
    ending = _steps(state, history, trace, usages, ctx, 1, max_steps, supervisor)
    if ending["status"] == "finished":
        supervisor.checkpoint = {**ctx, "state": state, "history": history,
                                 "trace": trace, "usages": usages, "next_step": len(trace) + 1}
    return {
        "scenario": sample_id,
        "trace": trace,
        "outcome": _outcome(state),
        "usages": usages,
        **ending,
    }


def _continue(checkpoint: dict[str, Any], supervisor: "Supervisor",
              answer: str | None = None, max_steps: int | None = None,
              steps_budget: int | None = None) -> dict[str, Any]:
    history = list(checkpoint["history"])
    if answer:
        history.append(
            {"role": "user", "content": [{"type": "input_text", "text": answer}]}
        )
    start = checkpoint["next_step"]
    if steps_budget is not None:
        limit = start + steps_budget - 1
    else:
        limit = max_steps if max_steps is not None else checkpoint["max_steps"]
    ending = _steps(
        checkpoint["state"], history, checkpoint["trace"], checkpoint["usages"],
        checkpoint, start, limit, supervisor,
    )
    if ending["status"] == "finished":
        supervisor.checkpoint = {**checkpoint, "history": history,
                                 "next_step": len(checkpoint["trace"]) + 1}
    return {
        "scenario": checkpoint["sample_id"],
        "trace": checkpoint["trace"],
        "outcome": _outcome(checkpoint["state"]),
        "usages": checkpoint["usages"],
        **ending,
    }

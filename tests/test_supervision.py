"""Verification layer: guards, escalation/resume, sign-off, claims check."""

from typing import Any

import pytest

from claimlens import agent
from claimlens.agent import (
    AgentState,
    run_tool,
    tool_adjudicate,
    tool_ask_user,
    tool_read_documents,
)
from claimlens.providers.replay import ReplayProvider
from claimlens.supervision import (
    Supervisor,
    build_handoff,
    guard_terminal_tool,
    replay_trace_guards,
    run_supervised,
    verify_claims,
    verify_no_blockers,
    verify_receipt_gate,
)

S2 = "S2_seoul_worker_bronchitis"


def _hidden_state() -> AgentState:
    state = AgentState(sample_id=S2, variant="photo", hidden_cells={"cell_1", "cell_2"})
    tool_read_documents(state)
    return state


def _complete_state() -> AgentState:
    state = AgentState(sample_id=S2, variant="photo")
    tool_read_documents(state)
    return state


def test_guards_pass_a_complete_claim():
    state = _complete_state()
    assert verify_receipt_gate(state)["passed"] is True
    assert verify_no_blockers(state)["passed"] is True
    assert guard_terminal_tool(state, "adjudicate") is None
    result = tool_adjudicate(state)
    assert result["decision"] == "PARTIAL"


def test_refusal_then_fix_on_the_same_state():
    from claimlens.engine import replay_reading

    bill = replay_reading(S2, "photo")["documents"][0]["kr_bill"]
    answer = f"cell_1={bill['cell_1']}, cell_2={bill['cell_2']}"
    state = _hidden_state()
    refused = tool_adjudicate(state)
    assert refused["refused"] is True
    assert refused["rule"] == "receipt_checks"
    asked = tool_ask_user(state, "Which cells?", "To pass the checks.", lambda q, w: answer)
    assert asked["recorded"] == {"cell_1": bill["cell_1"], "cell_2": bill["cell_2"]}
    fixed = tool_adjudicate(state)
    assert fixed["decision"] == "PARTIAL"
    assert fixed["amount_krw"] == 22500


def test_blocker_refusal_carries_its_question():
    from claimlens.consistency import bundle_reading

    docs = bundle_reading("S2r-S3c")
    state = _complete_state()
    state.reading["documents"][1] = docs["cert"]
    gate = verify_no_blockers(state)
    assert gate["passed"] is False
    refused = guard_terminal_tool(state, "adjudicate")
    assert refused["rule"] == "no_open_blockers"
    assert "Which patient" in refused["question"]


def test_replay_trace_guards_pass_the_demo_trace():
    verdicts = replay_trace_guards("s2_hidden_copay", hidden_cells={"cell_1", "cell_2"})
    assert len(verdicts) == 1
    assert verdicts[0]["tool"] == "adjudicate"
    assert verdicts[0]["verdict"] == "pass"


def _scripted(turns: list[dict[str, Any]]):
    calls: list[int] = []

    def fake(history: list[dict[str, Any]], live: bool, namespace: str) -> dict[str, Any]:
        calls.append(len(history))
        if turns:
            turn = turns.pop(0)
        else:
            turn = {"calls": [], "text": "done"}
        return {"calls": turn.get("calls", []), "text": turn.get("text", ""), "usage": {}}

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def _call(name: str, arguments: str = "{}", call_id: str = "c1") -> dict[str, Any]:
    return {"call_id": call_id, "name": name, "arguments": arguments}


def test_three_refusals_escalate_with_a_handoff(monkeypatch):
    stub = _scripted(
        [
            {"calls": [_call("read_documents", "{}", "c1")]},
            {"calls": [_call("run_checks", "{}", "c2")]},
            {"calls": [_call("adjudicate", "{}", "c3")]},
            {"calls": [_call("adjudicate", "{}", "c4")]},
            {"calls": [_call("adjudicate", "{}", "c5")]},
            {"calls": [_call("adjudicate", "{}", "c6")]},
        ]
    )
    monkeypatch.setattr(agent, "model_turn", stub)
    supervisor = Supervisor()
    result = run_supervised(
        S2, "photo", lambda q, w: "", False,
        hidden_cells={"cell_1", "cell_2"}, supervisor=supervisor,
    )
    assert result["status"] == "escalated"
    assert len(stub.calls) == 5
    assert result["trace"][-1]["kind"] == "escalated"
    handoff = result["handoff"]
    assert handoff["blocked_item"] == "adjudicate"
    assert handoff["rule_fired"] == "receipt_checks"
    assert handoff["what_was_read"]["documents"] == ["receipt", "medical_certificate"]
    assert handoff["question"]


def test_resume_needs_an_answer_and_makes_no_call_waiting(monkeypatch):
    stub = _scripted([{"calls": [_call("adjudicate", "{}", "c1")]}])
    monkeypatch.setattr(agent, "model_turn", stub)
    supervisor = Supervisor()
    state = _hidden_state()
    for _ in range(3):
        handoff = supervisor.observe("adjudicate", tool_adjudicate(state), state)
    assert handoff is not None
    supervisor.checkpoint = {"state": state, "history": [], "trace": [],
                             "usages": [], "next_step": 2, "max_steps": 12}
    with pytest.raises(ValueError, match="needs an answer"):
        supervisor.resume()
    assert stub.calls == []


def test_resume_with_answer_continues_to_a_decision(monkeypatch):
    from claimlens.engine import replay_reading

    bill = replay_reading(S2, "photo")["documents"][0]["kr_bill"]
    stub = _scripted(
        [
            {"calls": [_call("read_documents", "{}", "c1")]},
            {"calls": [_call("run_checks", "{}", "c2")]},
            {"calls": [_call("adjudicate", "{}", "c3")]},
            {"calls": [_call("adjudicate", "{}", "c4")]},
            {"calls": [_call("adjudicate", "{}", "c5")]},
            {"calls": [_call("ask_user", '{"question": "cells?", "why_needed": "checks"}', "c6")]},
            {"calls": [_call("adjudicate", "{}", "c7")]},
            {"calls": [], "text": "finished"},
        ]
    )
    monkeypatch.setattr(agent, "model_turn", stub)
    supervisor = Supervisor()
    answers = iter([f"cell_1={bill['cell_1']}, cell_2={bill['cell_2']}"])
    result = run_supervised(
        S2, "photo", lambda q, w: next(answers), False,
        hidden_cells={"cell_1", "cell_2"}, supervisor=supervisor,
    )
    assert result["status"] == "escalated"
    resumed = supervisor.resume(answer="the corrected cells arrived")
    assert resumed["outcome"] == {"decision": "PARTIAL", "amount_krw": 22500}


def test_signoff_approve_ends_with_no_model_call(monkeypatch):
    stub = _scripted(
        [
            {"calls": [_call("read_documents", "{}", "c1")]},
            {"calls": [], "text": "all done"},
        ]
    )
    monkeypatch.setattr(agent, "model_turn", stub)
    supervisor = Supervisor()
    result = run_supervised(S2, "photo", lambda q, w: "", False, supervisor=supervisor)
    assert result["status"] == "finished"
    before = len(stub.calls)
    signed = supervisor.signoff(approve=True)
    assert signed == {"status": "done", "signed": "approved"}
    assert len(stub.calls) == before


def test_signoff_return_revises_once_then_stops(monkeypatch):
    stub = _scripted(
        [
            {"calls": [_call("read_documents", "{}", "c1")]},
            {"calls": [], "text": "first try"},
            {"calls": [_call("run_checks", "{}", "c2")]},
            {"calls": [], "text": "revised"},
        ]
    )
    monkeypatch.setattr(agent, "model_turn", stub)
    supervisor = Supervisor()
    run_supervised(S2, "photo", lambda q, w: "", False, supervisor=supervisor)
    revised = supervisor.signoff(approve=False, notes="confirm the checks first")
    assert revised["status"] == "revised"
    assert revised["trace"][-1]["kind"] == "final"
    signed = supervisor.signoff(approve=True)
    assert signed == {"status": "done", "signed": "approved"}


def test_signoff_return_twice_is_refused(monkeypatch):
    stub = _scripted(
        [
            {"calls": [_call("read_documents", "{}", "c1")]},
            {"calls": [], "text": "first try"},
            {"calls": [], "text": "revised"},
        ]
    )
    monkeypatch.setattr(agent, "model_turn", stub)
    supervisor = Supervisor()
    run_supervised(S2, "photo", lambda q, w: "", False, supervisor=supervisor)
    supervisor.checkpoint = dict(supervisor.checkpoint or {})
    supervisor.signoff(approve=False, notes="once")
    supervisor.checkpoint = {"state": _complete_state(), "history": [], "trace": [],
                             "usages": [], "next_step": 2, "max_steps": 12}
    with pytest.raises(ValueError, match="Only one revision"):
        supervisor.signoff(approve=False, notes="twice")


class _VerifyStub:
    name = "stub"
    model = "stub"

    def __init__(self, verdicts: list[bool]):
        self.verdicts = verdicts
        self.calls: list[Any] = []

    def write(self, instructions: str, schema: dict[str, Any], result_model: Any = None):
        self.calls.append(instructions)
        assert "quoted evidence" in instructions
        return {"verdicts": [{"supported": v} for v in self.verdicts]}


def test_verify_claims_drops_unsupported_and_skips_empty():
    stub = _VerifyStub([True, False])
    out = verify_claims(
        [
            {"statement": "paid 22,500", "quote": "total 22,500"},
            {"statement": "paid 99", "quote": "total 22,500"},
        ],
        stub,
    )
    assert out["dropped"] == 1
    assert out["kept"] == [{"statement": "paid 22,500", "quote": "total 22,500"}]
    assert verify_claims([], stub) == {"verdicts": [], "dropped": 0}
    assert len(stub.calls) == 1


def test_verify_claims_rejects_short_verdicts():
    stub = _VerifyStub([True])
    with pytest.raises(ValueError, match="1 verdicts for 2 claims"):
        verify_claims(
            [
                {"statement": "a", "quote": "a"},
                {"statement": "b", "quote": "b"},
            ],
            stub,
        )


def test_handoff_names_blocked_item_rule_reads_and_question():
    from claimlens.consistency import bundle_reading

    docs = bundle_reading("S2r-S3c")
    state = _complete_state()
    state.reading["documents"][1] = docs["cert"]
    refused = guard_terminal_tool(state, "build_claim_pack")
    handoff = build_handoff("build_claim_pack", refused, state)
    assert handoff["blocked_item"] == "build_claim_pack"
    assert handoff["rule_fired"] == "no_open_blockers"
    assert handoff["what_was_read"]["documents"] == ["receipt", "medical_certificate"]
    assert "Which patient" in handoff["question"]


def test_run_tool_threads_answer_fn():
    state = _hidden_state()
    result = run_tool(
        state, "ask_user", {"question": "q", "why_needed": "w"},
        ReplayProvider(), lambda q, w: "cell_1=1, cell_2=2",
    )
    assert "answer" in result

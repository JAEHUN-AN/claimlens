"""Clarifying agent tests: the recorded dialogue replays offline."""

from claimlens.agent import (
    AgentState,
    load_trace,
    parse_user_amounts,
    run_agent,
    tool_adjudicate,
    tool_read_documents,
    tool_reread_cells,
)


def scripted_answer(question, why_needed):
    assert "cell_1" in question or "copay" in question.lower()
    assert why_needed
    return "cell_1=45000, cell_2=45000"


def test_agent_replays_hidden_copay_dialogue():
    recorded = load_trace("s2_hidden_copay")
    result = run_agent(
        "S2_seoul_worker_bronchitis",
        "photo",
        scripted_answer,
        live=False,
        hidden_cells={"cell_1", "cell_2"},
        namespace="ask-hidden-copay",
    )
    assert result["outcome"] == {"decision": "PARTIAL", "amount_krw": 22500}
    replayed_tools = [e.get("tool", e["kind"]) for e in result["trace"]]
    recorded_tools = [e.get("tool", e["kind"]) for e in recorded["trace"]]
    assert replayed_tools == recorded_tools
    questions = [e for e in result["trace"] if e["kind"] == "question"]
    assert len(questions) == 1
    assert "cell_1" in questions[0]["question"]
    assert questions[0]["answer"] == "cell_1=45000, cell_2=45000"


def test_agent_step_cap_stops():
    result = run_agent(
        "S2_seoul_worker_bronchitis",
        "photo",
        scripted_answer,
        live=False,
        hidden_cells={"cell_1", "cell_2"},
        max_steps=1,
        namespace="ask-hidden-copay",
    )
    assert result["trace"][-1]["kind"] == "stopped"
    assert result["outcome"] == {}


def test_parse_user_amounts():
    assert parse_user_amounts("cell_1=45,000, cell_2=45000") == {
        "cell_1": 45000,
        "cell_2": 45000,
    }
    assert parse_user_amounts("I don't know") == {}


def test_reread_hidden_cells_refused():
    state = AgentState(sample_id="S2_seoul_worker_bronchitis", variant="photo")
    tool_read_documents(state)
    state.hidden_cells = {"cell_1"}
    result = tool_reread_cells(state, ["cell_1"], provider=None)
    assert "ask the user" in result["error"]


def test_adjudicate_missing_copay():
    state = AgentState(
        sample_id="S2_seoul_worker_bronchitis",
        variant="photo",
        hidden_cells={"cell_1", "cell_2"},
    )
    tool_read_documents(state)
    result = tool_adjudicate(state)
    assert result["refused"] is True
    assert result["rule"] == "receipt_checks"
    assert "failing" in result["feedback"]

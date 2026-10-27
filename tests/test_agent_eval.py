"""Agent scorecard tests: all eight cases replay green."""

from claimlens.agent_eval import CASES, eval_all, format_markdown


def test_scorecard_replays_all_green(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    rows = eval_all(live=False)
    assert [r["case"] for r in rows] == [c["id"] for c in CASES]
    for row in rows:
        assert row["asked_when_needed"], row["case"]
        assert row["no_needless"], row["case"]
        assert row["no_invented"], row["case"]
        assert "EXPECTED" not in row["notes"], row["case"]
    assert sum(r["steps"] for r in rows) > 0


def test_scorecard_format():
    text = format_markdown(eval_all(live=False))
    assert "| ask-hidden-copay | yes | yes |" in text
    assert "| reject-contradiction | yes | yes |" in text


def test_agent_eval_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.cli import main

    target = tmp_path / "agent-eval.md"
    assert main(["agent-eval", "--output", str(target)]) == 0
    body = target.read_text(encoding="utf-8")
    assert "# ClaimLens agent scorecard" in body
    assert "noask-s3-complete" in body

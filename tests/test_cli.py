"""CLI output tests: console-safe printing."""

import io
import sys

from claimlens.cli import _emit


class Cp949Stdout(io.StringIO):
    encoding = "cp949"

    def write(self, text):
        text.encode("cp949")
        return super().write(text)


def test_emit_prints_normally(capsys):
    _emit("hello", end="")
    assert capsys.readouterr().out == "hello"


def test_emit_survives_cp949_console(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdout", Cp949Stdout())
    _emit("em—dash", end="")  # U+2014 is not in cp949
    captured = capsys.readouterr()
    assert "cannot show" in captured.err


def test_remeasure_plan_bundles_every_plan(capsys):
    """56: one screen carries all gate sets plus trips-check and a total."""
    from claimlens.cli import main

    assert main(["remeasure-plan"]) == 0
    out = capsys.readouterr().out
    for name in ("normal:", "hard:", "unseen:", "trips:"):
        assert name in out
    assert "GATE TOTAL live calls:" in out
    assert "Trips serve-path scenario check" in out
    assert "TOTAL live calls across 6 trips" in out
    assert "GRAND TOTAL (gate + trips-check):" in out
    assert "gate-eval --set both --execute --max-cost" in out
    assert "gate-eval --set unseen --execute --max-cost" in out
    assert "gate-eval --set trips --execute --max-cost" in out
    assert "trips-check --execute --max-cost" in out
    assert "Stopped before any API call." in out


def test_remeasure_plan_matches_single_set_plans(capsys):
    """56: bundled per-set lines equal the standalone plan outputs."""
    from claimlens.cli import main

    assert main(["gate-eval", "--set", "both"]) == 0
    both = capsys.readouterr().out
    assert main(["gate-eval", "--set", "unseen"]) == 0
    unseen = capsys.readouterr().out
    assert main(["gate-eval", "--set", "trips"]) == 0
    trips = capsys.readouterr().out
    assert main(["remeasure-plan"]) == 0
    bundle = capsys.readouterr().out
    for line in both.splitlines() + unseen.splitlines() + trips.splitlines():
        if line.startswith(("normal:", "hard:", "unseen:", "trips:")):
            assert line in bundle

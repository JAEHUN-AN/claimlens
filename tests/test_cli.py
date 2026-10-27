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

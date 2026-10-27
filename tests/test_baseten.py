"""Spark Open translation tests: parsing plus replay comparison row."""

import pytest

from claimlens.providers.baseten import MODEL, _table_of, translate_labels_open


def test_table_rejects_bad_arguments():
    with pytest.raises(ValueError, match="JSON"):
        _table_of("not json", ["a"])
    with pytest.raises(ValueError, match="b"):
        _table_of('{"labels": [{"ko": "a", "en": "A"}]}', ["a", "b"])


def test_open_translation_replays_twelve_labels(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.engine import replay_reading

    reading = replay_reading("S3_us_tourist_hip_fracture", "photo")
    labels = [r["label"] for r in reading["documents"][0]["kr_bill"]["charge_rows"]]
    out = translate_labels_open(labels)
    assert len(out["table"]) == 12
    assert out["usage"]["total_tokens"] > 0


def test_open_comparison_row_from_replay(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.eval import open_translation_row

    row = open_translation_row()
    assert row["open"] == MODEL == "meta-models/muse-spark-open-1026"
    assert row["hosted"] == "muse-spark-1.3"
    assert row["labels"] == 12
    matched, total = row["identical"].split("/")
    assert total == "12" and 0 <= int(matched) <= 12


def test_eval_output_contains_open_section(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.cli import main

    target = tmp_path / "eval.md"
    assert main(["eval", "--output", str(target)]) == 0
    body = target.read_text(encoding="utf-8")
    assert "## Pack translation: hosted Spark vs Spark Open" in body
    assert "meta-models/muse-spark-open-1026" in body

"""Spark Open tests: translation plus document reading comparison."""

import inspect
from pathlib import Path

import pytest

from claimlens.providers.baseten import (
    MODEL,
    BasetenProvider,
    _table_of,
    reading_tool_schema,
    translate_labels_open,
)


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


def test_reading_tool_schema_forces_submit_reading():
    from claimlens.reader import reading_schema

    schema = reading_schema()
    key_schema = reading_tool_schema(schema)
    assert key_schema["tools"][0]["function"]["name"] == "submit_reading"
    assert key_schema["tools"][0]["function"]["parameters"] == schema


def test_provider_matches_meta_signature():
    from claimlens.providers.meta import MetaProvider

    assert list(inspect.signature(BasetenProvider.read_documents).parameters) == list(
        inspect.signature(MetaProvider.read_documents).parameters
    )


def test_open_reading_replays(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.providers.replay import ReplayProvider
    from claimlens.reader import reading_schema, resolve_sample_images

    images = resolve_sample_images(Path("samples/A_niseko_wrist"), "photo")
    result = ReplayProvider(model=MODEL).read_documents(
        images, READING_INSTRUCTIONS, reading_tool_schema(reading_schema())
    )
    assert result["documents"][0]["total_amount"] == 235000.0


def test_verify_loop_runs_on_open_reading(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.engine import replay_reading
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.providers.replay import ReplayProvider
    from claimlens.reader import reading_schema, resolve_sample_images
    from claimlens.verify import verify_receipt

    images = resolve_sample_images(Path("samples/S2_seoul_worker_bronchitis"), "photo")
    receipt = ReplayProvider(model=MODEL).read_documents(
        images, READING_INSTRUCTIONS, reading_tool_schema(reading_schema())
    )["documents"][0]
    fixed_lines = replay_reading("S2_seoul_worker_bronchitis", "photo")["documents"][0][
        "line_items"
    ]

    class StubProvider:
        def read_documents(self, images, instructions, schema, result_model=None):
            return {"line_items": fixed_lines}

    result = verify_receipt(receipt, images[0], StubProvider())
    assert result["status"] == "verified"
    assert result["corrected"] == ["line_items"]

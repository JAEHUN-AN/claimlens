"""Meta tiles: each fact pinned against its committed source."""

import json
import os

from claimlens import meta_tiles
from claimlens.demo import REPO_ROOT, export_demo
from claimlens.voice import CONFIRM_FIELDS

ROOT = REPO_ROOT


def _tiles():
    return {tile["key"]: tile for tile in meta_tiles.tiles(ROOT)}


def test_tile_order_and_steps():
    tiles = meta_tiles.tiles(ROOT)
    assert [t["key"] for t in tiles] == ["code", "spark", "files", "sam", "voice", "open"]
    assert tiles[0]["tool"] == "Muse Code"
    assert all(t["step"]["en"] and t["step"]["ko"] for t in tiles)


def test_code_fact_counts_logged_sessions():
    log = (ROOT / "docs" / "meta-tooling-log.md").read_text(encoding="utf-8")
    sessions = sum(1 for line in log.splitlines() if line.startswith("## "))
    assert _tiles()["code"]["fact"] == {"en": f"{sessions} logged sessions",
                                        "ko": f"기록된 작업 {sessions}건"}


def test_spark_fact_matches_recomputed_summaries():
    from claimlens import hard_eval

    data = json.loads((ROOT / "data" / "hard_eval_20261028.json").read_text(
        encoding="utf-8"))
    scored = agreed = agree_n = 0
    for entry in data["sets"].values():
        cases = entry["cases"]
        summary = hard_eval.summarize(cases, len(cases[0]["runs"]))
        for acc in summary["accuracy"].values():
            scored += acc["n"]
        for agr in summary["agree"].values():
            agreed += agr["agree"]
            agree_n += agr["n"]
    pct = round(agreed * 100 / agree_n)
    cases = sum(len(entry["cases"]) for entry in data["sets"].values())
    hard = len(data["sets"]["hard"]["cases"])
    assert _tiles()["spark"]["fact"] == {
        "en": (f"{scored} fields read ×3 ({cases} cases, hard {hard}/24), "
               f"{pct}% run-to-run agreement"),
        "ko": (f"{scored}개 필드 ×3회 판독 ({cases}건, hard {hard}/24), "
               f"실행 간 일치율 {pct}%"),}


def test_files_fact_matches_probe():
    probe = json.loads((ROOT / "data" / "files_probe.json").read_text(encoding="utf-8"))
    fact = _tiles()["files"]["fact"]
    assert fact["en"] == (f"one read by file id as {probe['file_part']}, "
                          f"{probe['tokens']['total_tokens']:,} tokens")


def test_sam_fact_matches_masks_on_disk():
    masked = sorted((ROOT / "docs" / "masking").glob("*_after.png"))
    assert _tiles()["sam"]["fact"] == {"en": f"{len(masked)} masked copies",
                                       "ko": f"{len(masked)}건 마스킹본"}


def test_voice_fact_matches_confirm_fields():
    assert _tiles()["voice"]["fact"] == {
        "en": f"{len(CONFIRM_FIELDS)} fact types need confirmation",
        "ko": f"{len(CONFIRM_FIELDS)}종 사실 확인 필요",}


def test_open_fact_matches_replay_eval():
    from claimlens.eval import eval_all

    prev = os.environ.get("CLAIMLENS_PROVIDER")
    os.environ["CLAIMLENS_PROVIDER"] = "replay"
    try:
        rows = eval_all()
    finally:
        if prev is None:
            os.environ.pop("CLAIMLENS_PROVIDER", None)
        else:
            os.environ["CLAIMLENS_PROVIDER"] = prev
    matched = total = 0
    for row in rows:
        opened = row.get("open")
        if row.get("variant") != "photo" or not opened:
            continue
        for field in ("total", "lines", "checks"):
            total += 1
            matched += row.get(field) == opened.get(field)
    assert _tiles()["open"]["fact"] == {
        "en": f"{matched}/{total} fields match hosted",
        "ko": f"{total}개 중 {matched}개 일치",}


def test_missing_data_means_step_only(tmp_path):
    tiles = {tile["key"]: tile for tile in meta_tiles.tiles(tmp_path)}
    assert tiles["code"]["fact"] is None
    assert tiles["spark"]["fact"] is None
    assert tiles["files"]["fact"] is None
    assert tiles["sam"]["fact"] is None
    assert tiles["voice"]["fact"] is not None


def test_model_table_has_files_row_and_facts():
    table = meta_tiles.render_model_table(ROOT)
    rows = table.strip().splitlines()
    assert rows[0] == "| Step | Model | How | Measured |"
    assert len(rows) == 15
    assert any("Send documents by file id" in row and "4,023 tokens" in row
               for row in rows)
    assert sum("267 fields read" in row for row in rows) == 1
    assert sum("11/15 fields match hosted" in row for row in rows) == 1
    assert sum("(33 cases, hard 23/24)" in row for row in rows) == 1


def test_readme_table_matches_rendered():
    text = (ROOT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index("| Step | Model |")
    end = text.index("| Mask seals and signatures |")
    end = text.index("\n", end) + 1
    assert text[start:end] == meta_tiles.render_model_table(ROOT)


def test_readme_attribution_and_samples_row():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Muse Code wrote the code from the backlog." in text
    assert "Co-Authored-By: Claude" in text
    assert "prepared before the hackathon" in text


def test_demo_carries_meta_tools(tmp_path):
    text = export_demo(tmp_path / "demo.html").read_text(encoding="utf-8")
    assert '"tool": "Muse Code"' in text
    assert '"tool": "Spark Open on Baseten"' in text
    assert "Built with Meta" in text
    assert "metaToolsHtml" in text

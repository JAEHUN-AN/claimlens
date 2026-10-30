"""Storyboard v4: totals, captions, cards, measured shot (dry-run level)."""

import json
import sys

from claimlens import headline, meta_tiles
from claimlens.demo import REPO_ROOT

ROOT = REPO_ROOT
sys.path.insert(0, str(ROOT / "tools" / "video"))

import video_lib as V
import video_shots


def _main():
    return json.loads((ROOT / "tools" / "video" / "storyboard-main.json").read_text(
        encoding="utf-8"))


def _vertical():
    return json.loads((ROOT / "tools" / "video" / "storyboard-vertical.json").read_text(
        encoding="utf-8"))


def test_main_totals_180_and_closes():
    board = _main()
    assert sum(s["duration"] for s in board["segments"]) == 180
    assert board["segments"][-1]["id"] == "closing"
    assert any(s.get("rush") for s in board["segments"])


def test_vertical_final_cut_45_and_links():
    board = _vertical()
    assert V.effective_total(board) == 45
    assert board["segments"][-1]["id"] == "vlink"


def test_captions_within_limits():
    for seg in _main()["segments"]:
        assert seg["caption"] and len(seg["caption"]) <= 190, seg["id"]
    for seg in _vertical()["segments"]:
        assert seg["caption"] and len(seg["caption"]) <= 44, seg["id"]


def test_why_segment_after_thesis():
    ids = [s["id"] for s in _main()["segments"]]
    assert ids.index("why") == ids.index("thesis") + 1
    why = next(s for s in _main()["segments"] if s["id"] == "why")
    assert why["page"] == "card:why"
    assert "koui" not in ids and "tooling" not in ids


def test_eval_caption_comes_from_headline():
    eval_seg = next(s for s in _main()["segments"] if s["id"] == "eval")
    assert eval_seg["caption"] == headline.eval_caption(ROOT)
    assert eval_seg["page"] == "measured"


def test_honest_wording_pins():
    """53-H6/H9/H14: propose/confirm framing, replay scope, (est.)."""
    segs = {s["id"]: s["caption"] for s in _main()["segments"]}
    assert "the engine proposes payment in full" in segs["sceneA"]
    assert "a reviewer confirms" in segs["sceneA"]
    assert "paid in full under the travel policy" not in segs["sceneA"]
    assert "each replayed once" in segs["score"]
    assert "(est.)" in segs["why"]
    for caption in segs.values():
        assert len(caption) <= 190


def test_why_card_content():
    text = (ROOT / "tools" / "video" / "cards" / "cards.html").read_text(
        encoding="utf-8")
    assert 'id="why"' in text
    for needle in ("hospital data systems", "₩251.2 billion", "2.01 million",
                   "Theme: Build for Your World.",
                   "Paperwork check — not medical or legal advice."):
        assert needle in text
    assert "₩251.2 billion unclaimed in Korea in 2022 (est.)" in text
    vhook = text.split('id="vhook"')[1].split("</section>")[0]
    assert "National Assembly office, 2023-09-06" in vhook


def test_meta_card_matches_tiles():
    text = (ROOT / "tools" / "video" / "cards" / "cards.html").read_text(
        encoding="utf-8")
    assert "<b>MCP</b>" not in text
    for tile in meta_tiles.tiles(ROOT):
        assert f"<b>{tile['tool']}</b>" in text
        assert tile["step"]["en"] in text
        if tile["fact"]:
            assert tile["fact"]["en"] in text


def test_measured_shot_has_gate_line(tmp_path):
    paths = video_shots.build_shots(ROOT, tmp_path)
    text = paths["measured"].read_text(encoding="utf-8")
    assert 'class="gate-line"' in text
    assert "47 wrong amounts" in text
    assert "Fields scored" in text


def test_dry_run_validation_passes(tmp_path):
    for name, cap in (("storyboard-main.json", 190),
                      ("storyboard-vertical.json", 44)):
        board = json.loads((ROOT / "tools" / "video" / name).read_text(
            encoding="utf-8"))
        texts = V.page_texts_for(ROOT, tmp_path / name, {
            "cards": ROOT / "tools" / "video" / "cards" / "cards.html",
            "phone": ROOT / "tools" / "video" / "phone.html"})
        texts["live"] = texts["demo"]
        for cid in V.CARD_IDS:
            texts[f"card:{cid}"] = texts["cards"]
        assert V.validate(ROOT, board, texts, cap) == []
        assert V.check_assets(ROOT, board, texts) == []

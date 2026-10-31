"""Storyboard v5: totals, keyword captions + narrations, cards, measured shot."""

import json
import sys

from claimlens import meta_tiles
from claimlens.demo import REPO_ROOT

ROOT = REPO_ROOT
sys.path.insert(0, str(ROOT / "tools" / "video"))

import captions
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


def test_gate_caption_comes_from_headline():
    # The eval scene lives under id "gate": headline.apply_storyboard
    # still owns id "eval" while src is frozen for 63.
    gate = next(s for s in _main()["segments"] if s["id"] == "gate")
    nums = captions.numbers(ROOT)
    assert gate["caption"] == (
        f"Wrong amounts: {nums['old']} (old single read)"
        f" → {nums['live']} (live gate)")
    assert gate["page"] == "measured"
    # Spoken form is short and built from the same data (captions.gate_narration).
    assert gate["narration"] == captions.gate_narration(ROOT, nums)
    assert gate["narration"].startswith(
        f"Wrong amounts: {nums['old']} with a single read, {nums['live']} with the live gate.")


def test_honest_wording_pins():
    """53-H6/H9/H14: propose/confirm framing, replay scope, (est.)."""
    segs = {s["id"]: s.get("narration", "") for s in _main()["segments"]}
    assert "the engine proposes payment in full" in segs["sceneA"]
    assert "a reviewer confirms" in segs["sceneA"]
    assert "paid in full under the travel policy" not in segs["sceneA"]
    assert "replayed once" in segs["score"]
    assert "An estimated" in segs["why"]
    for seg in _main()["segments"]:
        assert len(seg["caption"]) <= 190


def test_v5_captions_match_owner_draft():
    nums = captions.numbers(ROOT)
    segs = {s["id"]: s["caption"] for s in _main()["segments"]}
    assert segs["thesis"] == "AI reads. Code counts. People decide."
    assert segs["why"] == "₩251.2B unclaimed (2022, est.) · 2.01M foreign patients (2025)"
    assert segs["before_after"] == (
        f"By hand: 30+ min (est.) → ClaimLens: ~{nums['n']} s (measured)")
    assert segs["s2flow"] == "Every cell read → re-added in code"
    assert segs["prov"] == "Every number shows its source"
    assert segs["agent"] == "Something missing? It asks — never guesses"
    assert segs["score"] == f"Agent scorecard {nums['a']}/{nums['b']}"
    assert segs["s3"] == "No policy → no decision, a claim pack"
    assert segs["voice"] == "Spoken dates: confirmed, not trusted"
    assert segs["live"] == "LIVE · new photos · real Muse Spark call"
    assert segs["mismatch"] == "Documents disagree → a question"
    assert segs["verify"] == "Checks the agent can't skip"
    assert segs["phone"] == "Same proof on your phone"
    assert segs["tools"] == "6 Meta tools, each measured"
    assert segs["builtvs"] == "Built here · engine pre-existing, pinned"
    assert segs["sceneA"] == "The other way: a Korean skier in Japan"
    assert segs["closing"] == (
        "Try it: jaehun-an.github.io/claimlens · github.com/JAEHUN-AN/claimlens")


def test_v5_narrations_carry_old_captions():
    segs = {s["id"]: s for s in _main()["segments"]}
    assert segs["thesis"]["narration"] == "AI reads, reasons and asks; code counts."
    assert segs["why"]["narration"].startswith(
        "I work on hospital data systems in Korea.")
    assert "replayed once" in segs["score"]["narration"]
    assert "the engine proposes payment in full" in segs["sceneA"]["narration"]
    for ch in ("ch1", "ch2", "ch3", "ch4", "ch5", "ch6"):
        assert "narration" not in segs[ch]
    assert segs["before_after"]["narration"] == captions.before_after_narration(
        captions.numbers(ROOT))


def test_before_after_scene_after_why():
    segs = _main()["segments"]
    ids = [s["id"] for s in segs]
    assert ids.index("before_after") == ids.index("why") + 1
    scene = next(s for s in segs if s["id"] == "before_after")
    assert scene["page"] == "card:before_after"
    assert scene["duration"] == 5
    by_id = {s["id"]: s for s in segs}
    assert by_id["tools"]["duration"] == 8
    assert by_id["phone"]["duration"] == 9  # the phone scene needs 9 s of actions
    assert by_id["verify"]["duration"] == 14  # 11 s overran on 10-31
    assert sum(s["duration"] for s in segs) == 180
    assert segs[-1]["id"] == "closing"


def test_vertical_split_keeps_captions():
    for seg in _vertical()["segments"]:
        if seg["id"] != "vlive":
            assert seg["narration"] == seg["caption"]
    vhook = next(s for s in _vertical()["segments"] if s["id"] == "vhook")
    assert vhook["caption"] == "Hospital bills don't translate themselves."


def test_vertical_live_narration_carries_the_sourced_stat():
    # vhook is too short to speak the stat, so vlive says it; the vhook card shows the source.
    vlive = next(s for s in _vertical()["segments"] if s["id"] == "vlive")
    cards = (ROOT / "tools" / "video" / "cards" / "cards.html").read_text(encoding="utf-8")
    assert "₩251.2 billion unclaimed in Korea in 2022 (est.)" in cards
    assert vlive["narration"].startswith(
        "In Korea, an estimated ₩251.2 billion went unclaimed in 2022.")
    assert vlive["narration"].endswith("a real wait, sped up.")


def test_captions_match_fresh_refresh():
    assert captions.check(ROOT) == []


def test_eval_shot_shows_trips_line(tmp_path):
    paths = video_shots.build_shots(ROOT, tmp_path)
    text = paths["measured"].read_text(encoding="utf-8")
    assert "Real trips through live upload" in text


def test_committed_main_captions_fit_two_lines():
    board = _main()
    width = board["viewport"]["width"]
    for seg in board["segments"]:
        lines, overflow = V.caption_lines(seg["caption"], 23, width)
        assert lines <= 2, seg["id"]
        assert overflow == [], seg["id"]


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


def test_live_scenes_answer_product_pause_then_wait_amount():
    """H2: retakes are unmatched, so the live run pauses for a product.

    The recorder picks the S2 product, continues, and only then waits
    for the decided amount — otherwise the video would show a stall.
    """
    from claimlens.engine import load_scenarios, product_catalog

    scenarios, _ = load_scenarios()
    s2_product = scenarios["S2_seoul_worker_bronchitis"]["policy"]["product"]
    assert s2_product in product_catalog()
    for board, seg_id in ((_main(), "live"), (_vertical(), "vlive")):
        seg = next(s for s in board["segments"] if s["id"] == seg_id)
        acts = seg["actions"]
        drop_at = next(i for i, a in enumerate(acts)
                       if a["op"] == "dropfiles")
        tail = [(a["op"], a.get("selector"))
                for a in acts[drop_at + 1:drop_at + 5]]
        assert tail == [("wait_for", "#flow-view .flow-result"),
                        ("select", "#person-product"),
                        ("click", "#flow-questions button"),
                        ("wait_for", "#flow-result .amount")], seg_id
        sel = next(a for a in acts if a["op"] == "select")
        assert sel["selector"] == "#person-product"
        assert sel["value"] == s2_product, seg_id


def test_dry_run_validation_passes(tmp_path):
    for name, cap, font, lines in (("storyboard-main.json", 190, 23, 2),
                                   ("storyboard-vertical.json", 44, 34, None)):
        board = json.loads((ROOT / "tools" / "video" / name).read_text(
            encoding="utf-8"))
        texts = V.page_texts_for(ROOT, tmp_path / name, {
            "cards": ROOT / "tools" / "video" / "cards" / "cards.html",
            "phone": ROOT / "tools" / "video" / "phone.html"})
        texts["live"] = texts["demo"]
        for cid in V.CARD_IDS:
            texts[f"card:{cid}"] = texts["cards"]
        assert V.validate(ROOT, board, texts, cap, font_px=font,
                          max_lines=lines) == []
        assert V.check_assets(ROOT, board, texts) == []

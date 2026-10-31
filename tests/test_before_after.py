"""Before/after illustration (61): verbatim wording, labels, placements."""

import json
import re

from claimlens import before_after, headline
from claimlens.demo import REPO_ROOT, export_demo

ROOT = REPO_ROOT


def _text_nodes(svg: str) -> str:
    return " ".join(re.findall(r">([^<>]+)<", svg))


def test_owner_wording_is_verbatim_both_languages():
    for lang, sentence in before_after.OWNER_SENTENCE.items():
        words = _text_nodes(before_after.svg("22.97", lang))
        assert sentence in " ".join(words.split())


def test_required_labels_are_visible():
    labels = {"en": ("illustration", "builder's estimate"),
              "ko": ("설명 그림", "만든 사람의 경험상 추정")}
    for lang, (tag, estimate) in labels.items():
        words = _text_nodes(before_after.svg("22.97", lang))
        assert tag in words
        assert estimate in words
    assert "30+" in _text_nodes(before_after.svg("22.97", "en"))
    assert "30분" in _text_nodes(before_after.svg("22.97", "ko"))


def test_claimlens_side_uses_measured_n():
    en = _text_nodes(before_after.svg("22.97", "en"))
    assert "about 22.97 s" in en
    assert "(measured)" in en
    assert "약 22.97초" in _text_nodes(before_after.svg("22.97", "ko"))


def test_no_new_numbers_in_artwork():
    # Geometry coordinates carry digits; visible text must not, except N + 30.
    for lang in ("en", "ko"):
        words = _text_nodes(before_after.svg("22.97", lang))
        assert set(re.findall(r"\d+", words)) <= {"22", "97", "30"}


def test_five_step_labels_per_language():
    en = _text_nodes(before_after.svg("22.97", "en"))
    for label in ("certificate", "codes", "currency", "items", "form"):
        assert label in en
    ko = _text_nodes(before_after.svg("22.97", "ko"))
    for label in ("진단서", "코드", "통화", "항목", "양식"):
        assert label in ko


def test_readme_links_figure_below_why():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert (ROOT / "docs" / "before_after.svg").exists()
    assert text.index("Theme: Build for Your World.") < text.index(
        "docs/before_after.svg") < text.index("<!-- measured:start -->")


def test_demo_payload_carries_both_figures(tmp_path, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    dst = export_demo(tmp_path / "demo.html")
    text = dst.read_text(encoding="utf-8")
    payload = json.loads(
        re.search(r'<script id="demo-data"[^>]*>(.*?)</script>', text,
                  re.DOTALL).group(1))
    figures = payload["flow"]["before_after"]
    assert "about 22.97 s" in figures["en"]
    assert "(measured)" in figures["en"]
    assert "약 22.97초" in figures["ko"]
    assert "beforeAfterHtml()" in text


def test_standalone_file_keeps_xmlns_inline_drops_it():
    assert 'xmlns="http://www.w3.org/2000/svg"' in before_after.svg("22.97", "en")
    inline = before_after.svg("22.97", "en", standalone=False)
    assert "http://" not in inline
    assert (ROOT / "docs" / "before_after.svg").read_text(
        encoding="utf-8").startswith("<svg ")


def test_video_card_carries_figure_with_measured_n():
    text = (ROOT / "tools" / "video" / "cards" / "cards.html").read_text(
        encoding="utf-8")
    assert 'id="before_after"' in text
    card = text.split('id="before_after"')[1].split("</section>")[0]
    assert f"about {headline.after_n(ROOT)} s" in card
    assert "(measured)" in card
    assert "builder's estimate" in card

"""Real-browser check for the UI language switch (Edge via Playwright).

Clicks the topbar switcher like the owner did, opens all six scenes,
and asserts the whole chrome (not just topbar and tabs) shows the
picked language with exactly one view visible.
"""

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEMO = Path(__file__).resolve().parent.parent / "docs" / "demo.html"

SCENES = [
    "A_niseko_wrist",
    "S2_seoul_worker_bronchitis",
    "S3_us_tourist_hip_fracture",
    "agent_s2_hidden_copay",
    "voice_factory_fall",
    "mismatch_s2r_s3c",
]

FLOW_EXAMPLES = SCENES[:5]

TITLES = {
    "ko": {
        "A_niseko_wrist": "장면 A — 일본에서 치료받은 한국 여행자",
        "S2_seoul_worker_bronchitis": "장면 S2 — 서울에서 치료받은 가입 근로자",
        "S3_us_tourist_hip_fracture": "장면 S3 — 서울에서 치료받은 미가입 방문자",
        "agent_s2_hidden_copay": "장면 Agent — 본인부담 칸이 숨겨진 S2",
        "voice_factory_fall": "장면 Voice — 공장 추락 (음성 접수)",
        "mismatch_s2r_s3c": "장면 Mismatch — S2 영수증과 S3 진단서",
    },
}

H3 = {
    "ko": {
        "A_niseko_wrist": ["읽기", "자격", "엔진 카드", "단계", "인용 조항"],
        "S2_seoul_worker_bronchitis": [
            "읽기",
            "자격",
            "엔진 카드",
            "단계",
            "인용 조항",
            "본인부담금 확인 (ClaimLens가 판독본에서 계산)",
        ],
        "S3_us_tourist_hip_fracture": ["읽기", "검증 후 재판독", "자격", "Claim Pack"],
        "agent_s2_hidden_copay": ["에이전트 타임라인", "검증", "스크립트 시연"],
        "voice_factory_fall": ["음성 접수"],
        "mismatch_s2r_s3c": ["문서 간 대조 결과"],
    },
}

FLOW = {
    "ko": {
        "tagline": "AI는 읽고 추론하고 묻고, 코드는 계산한다.",
        "strip": ["Muse Spark가 읽고 추론", "코드가 계산", "사람이 결정"],
        "h2": "청구 처리",
        "drop": "직접 문서를 올려보고 싶으세요? 실시간 업로드에는 API 키가 필요합니다 — 위 예시로 체험해 보세요.",
        "play": "재생",
        "s2_steps": ["읽기", "검증", "자격", "판정"],
        "voice_first": "받아쓰기 (en)",
    },
}

EN_CHROME = [
    "Process a claim",
    "AI reads, reasons and asks; code counts.",
    "Want to try your own document?",
    "Scene S2 — insured worker treated in Seoul",
    "See the full example",
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            launched = p.chromium.launch(channel="msedge", headless=True)
        except PlaywrightError as exc:
            pytest.fail(f"Edge (msedge channel) did not launch: {exc}")
        yield launched
        launched.close()


@pytest.mark.parametrize("lang", ["ko"])
def test_language_switch_in_browser(browser, lang):
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(DEMO.as_uri())
    # English default: EN/한국어 switcher only, English chrome.
    assert page.locator("#langswitch button").all_inner_texts() == ["EN", "한국어"]
    assert page.locator("#flow-view h2").inner_text() == "Process a claim"
    page.locator(f'#langswitch button[data-lang="{lang}"]').click()

    # One flow card and six scenes: re-render replaces, never appends.
    assert page.locator("#flow-view").count() == 1
    assert page.locator("section.scene").count() == 6

    # Flow card chrome is translated.
    flow = FLOW[lang]
    assert page.locator("#flow-view .tagline").inner_text() == flow["tagline"]
    assert page.locator("#flow-view .strip3 li").all_inner_texts() == flow["strip"]
    assert page.locator("#flow-view h2").inner_text() == flow["h2"]
    assert page.locator("#flow-drop").inner_text() == flow["drop"]
    assert page.locator("#flow-play").inner_text() == flow["play"]
    picks = page.locator("#flow-view .fpick").all_inner_texts()
    assert picks == [TITLES[lang][s] for s in FLOW_EXAMPLES]

    # Scene tabs carry the translated titles.
    tabs = page.locator("#scenes button").all_inner_texts()
    assert tabs[1:] == [TITLES[lang][s] for s in SCENES]

    # Step names translate once an example is picked.
    page.evaluate("pickFlow('S2_seoul_worker_bronchitis')")
    steps = page.locator("#flow-steps .fstep strong").all_inner_texts()
    assert steps == flow["s2_steps"]
    page.evaluate("pickFlow('voice_factory_fall')")
    first = page.locator("#flow-steps .fstep strong").first.inner_text()
    assert first == flow["voice_first"]

    # Each scene body: translated title and headers, exactly one view visible.
    for scene in SCENES:
        page.locator("#scenes button", has_text=TITLES[lang][scene]).click()
        section = page.locator(f"section#{scene}")
        assert section.locator("h2").inner_text() == TITLES[lang][scene]
        assert section.locator("h3").all_inner_texts() == H3[lang][scene]
        assert page.locator("#flow-view").is_visible() is False
        visible = sum(
            page.locator(f"section#{s}").is_visible() for s in SCENES
        )
        assert visible == 1

    # No English chrome string survives outside document contents.
    chrome = page.evaluate(
        """() => [
          document.getElementById('topnote').textContent,
          ...[...document.querySelectorAll('#flow-view h2, #flow-view .tagline')],
          ...[...document.querySelectorAll('section.scene h2, section.scene h3')],
        ].map(e => typeof e === 'string' ? e : e.textContent).join('\\n')"""
    )
    for en in EN_CHROME:
        assert en not in chrome, f"stale English chrome: {en}"

    # Back to the flow view: only the flow card shows.
    page.locator("#scenes button").first.click()
    assert page.locator("#flow-view").is_visible() is True
    assert sum(page.locator(f"section#{s}").is_visible() for s in SCENES) == 0

    assert errors == []
    page.close()

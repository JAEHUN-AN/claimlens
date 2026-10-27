"""Real-browser check for the UI language switch (Edge via Playwright).

Clicks the topbar switcher like the owner did, opens all five scenes,
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
]

TITLES = {
    "ko": {
        "A_niseko_wrist": "장면 A — 일본에서 치료받은 한국 여행자",
        "S2_seoul_worker_bronchitis": "장면 S2 — 서울에서 치료받은 가입 근로자",
        "S3_us_tourist_hip_fracture": "장면 S3 — 서울에서 치료받은 미가입 방문자",
        "agent_s2_hidden_copay": "장면 Agent — 본인부담 칸이 숨겨진 S2",
        "voice_factory_fall": "장면 Voice — 공장 추락 (음성 접수)",
    },
    "vi": {
        "A_niseko_wrist": "Cảnh A — du khách Hàn Quốc điều trị tại Nhật Bản",
        "S2_seoul_worker_bronchitis": "Cảnh S2 — người lao động có bảo hiểm điều trị tại Seoul",
        "S3_us_tourist_hip_fracture": "Cảnh S3 — du khách không bảo hiểm điều trị tại Seoul",
        "agent_s2_hidden_copay": "Cảnh Agent — S2 với ô đồng chi trả bị ẩn",
        "voice_factory_fall": "Cảnh Voice — ngã tại nhà máy (tiếp nhận bằng giọng nói)",
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
        "S3_us_tourist_hip_fracture": ["읽기", "자격", "Claim Pack"],
        "agent_s2_hidden_copay": ["에이전트 타임라인"],
        "voice_factory_fall": ["음성 접수"],
    },
    "vi": {
        "A_niseko_wrist": ["Đọc", "Điều kiện", "Thẻ engine", "Các bước", "Điều khoản trích dẫn"],
        "S2_seoul_worker_bronchitis": [
            "Đọc",
            "Điều kiện",
            "Thẻ engine",
            "Các bước",
            "Điều khoản trích dẫn",
            "Kiểm tra khấu trừ (ClaimLens tính từ bản đọc)",
        ],
        "S3_us_tourist_hip_fracture": ["Đọc", "Điều kiện", "Claim Pack"],
        "agent_s2_hidden_copay": ["Dòng thời gian agent"],
        "voice_factory_fall": ["Tiếp nhận bằng giọng nói"],
    },
}

FLOW = {
    "ko": {
        "tagline": "국경을 넘나드는 의료 서류 — 양방향으로",
        "strip": ["읽기", "검증", "판정 또는 Claim Pack 작성"],
        "h2": "청구 처리",
        "drop": "문서 사진을 여기에 놓으세요 — 또는 위에서 예시를 고르세요.",
        "play": "재생",
        "s2_steps": ["읽기", "검증", "자격", "판정"],
        "voice_first": "받아쓰기 (en)",
    },
    "vi": {
        "tagline": "Giấy tờ y tế vượt biên giới — theo cả hai chiều",
        "strip": ["Đọc", "Xác minh", "Quyết định hoặc lập Claim Pack"],
        "h2": "Xử lý bồi thường",
        "drop": "Thả ảnh tài liệu vào đây — hoặc chọn một ví dụ ở trên.",
        "play": "Chạy",
        "s2_steps": ["Đọc", "Kiểm tra", "Điều kiện", "Quyết định"],
        "voice_first": "Chép lời (en)",
    },
}

EN_CHROME = [
    "Process a claim",
    "Medical paperwork that crosses borders",
    "Drop a document photo",
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


@pytest.mark.parametrize("lang", ["ko", "vi"])
def test_language_switch_in_browser(browser, lang):
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(DEMO.as_uri())
    page.locator(f'#langswitch button[data-lang="{lang}"]').click()

    # One flow card and five scenes: re-render replaces, never appends.
    assert page.locator("#flow-view").count() == 1
    assert page.locator("section.scene").count() == 5

    # Flow card chrome is translated.
    flow = FLOW[lang]
    assert page.locator("#flow-view .tagline").inner_text() == flow["tagline"]
    assert page.locator("#flow-view .strip3 li").all_inner_texts() == flow["strip"]
    assert page.locator("#flow-view h2").inner_text() == flow["h2"]
    assert page.locator("#flow-drop").inner_text() == flow["drop"]
    assert page.locator("#flow-play").inner_text() == flow["play"]
    picks = page.locator("#flow-view .fpick").all_inner_texts()
    assert picks == [TITLES[lang][s] for s in SCENES]

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

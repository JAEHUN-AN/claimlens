"""Real-browser checks (Edge via Playwright): the UI language switch and
the live person-facts flow against a stubbed live server.
"""

import copy
import socket
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from claimlens import engine, serve
from claimlens.engine import replay_reading
from claimlens.providers.meta import CallRecord

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


def test_scope_footer_and_proposed_labels_in_browser(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(DEMO.as_uri())
    seen_labeled: set[str] = set()
    for lang in ("en", "ko"):
        page.locator(f'#langswitch button[data-lang="{lang}"]').click()
        buttons = page.locator("#scenes button")
        assert buttons.count() == 7
        for pos in range(buttons.count()):
            buttons.nth(pos).click()
            scopes = page.locator(".scope:visible")
            assert scopes.count() >= 1
            for idx in range(scopes.count()):
                assert scopes.nth(idx).inner_text() == SCOPE_TEXT[lang]
            badges = page.locator(".badge:visible")
            for idx in range(badges.count()):
                badge = badges.nth(idx)
                if badge.inner_text() in DECISION_BADGES:
                    text = badge.evaluate(
                        "b => (b.nextElementSibling && "
                        "b.nextElementSibling.classList.contains('proposed')) ? "
                        "b.nextElementSibling.textContent : ''"
                    )
                    assert text == PROPOSED_TEXT[lang]
                    seen_labeled.add(badge.inner_text())
    assert {"PAID", "PARTIAL"} <= seen_labeled
    assert errors == []
    page.close()


def test_phone_layout_in_browser(browser):
    context = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(DEMO.as_uri())
    assert page.locator('meta[name="viewport"]').count() == 1
    assert page.locator("#flow-view").is_visible() is True
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    page.locator("#scenes button", has_text="Scene S2").click()
    assert page.locator("section#S2_seoul_worker_bronchitis").is_visible() is True
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    assert errors == []
    page.close()
    context.close()


class _LiveStub:
    """Stub provider that counts readings; reads the S2 replay recording."""

    name = "stub"
    model = "stub"

    def __init__(self):
        self.calls: list[CallRecord] = []
        self.reads = 0

    def _log(self, total: int):
        self.calls.append(
            CallRecord(model=self.model, input_tokens=total, output_tokens=0,
                       total_tokens=total, cost_usd=None)
        )

    def read_documents(self, images, instructions, schema, result_model=None, cache_tag=""):
        from claimlens.rotation import RotationProbe

        if result_model is RotationProbe:
            self._log(10)  # retake drops are probed; the probe is not a read
            return {"rotation": 0}
        self.reads += 1
        self._log(100)
        return copy.deepcopy(replay_reading("S2_seoul_worker_bronchitis", "photo"))

    def write(self, instructions, schema, result_model=None):
        self._log(50)
        return {"findings": []}


DROP_RETAKES = """async () => {
  const spec = [
    ['/samples/live/S2_receipt_retake.jpg', 'receipt.jpg'],
    ['/samples/live/S2_medical_certificate_retake.jpg', 'cert.jpg'],
  ];
  const dt = new DataTransfer();
  for (const [url, name] of spec) {
    const buf = await (await fetch(url)).arrayBuffer();
    dt.items.add(new File([buf], name, {type: 'image/jpeg'}));
  }
  document.getElementById('flow-drop').dispatchEvent(
    new DragEvent('drop', {dataTransfer: dt, bubbles: true}));
}"""

S2_PRESET = '#person-presets button[data-preset="S2_seoul_worker_bronchitis"]'

SCOPE_TEXT = {
    "en": "Paperwork check — not medical or legal advice. A person makes every decision.",
    "ko": "서류 점검 도구입니다. 의료·법률 조언이 아니며, 최종 결정은 사람이 합니다.",
}
PROPOSED_TEXT = {
    "en": "Proposed — for a reviewer",
    "ko": "제안 — 검토자 확인 필요",
}
DECISION_BADGES = ("PAID", "PARTIAL", "DENIED", "HUMAN_REVIEW")


def _can_listen() -> bool:
    try:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        sock.close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _can_listen(), reason="sandbox blocks listen()")
def test_live_preset_run_reaches_partial_in_browser(browser, monkeypatch):
    stub = _LiveStub()
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate",
                        lambda inputs: {"decision": "PARTIAL", "amount": 22500})
    server = serve.start_background(0)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{server.server_port}/docs/demo.html")
        page.locator("#person-presets").wait_for(timeout=15000)
        page.locator(S2_PRESET).click()
        assert page.locator("#person-visa").input_value() == "E-7"
        page.evaluate(DROP_RETAKES)
        # H2: unmatched photos pause for the user's product choice first.
        page.locator("#flow-questions li").first.wait_for(timeout=60000)
        assert page.locator("#flow-result .badge").inner_text() == "need_product"
        assert stub.reads == 2
        page.locator("#person-product").select_option(_s2_product())
        page.locator("#flow-questions button").click()
        page.locator("#flow-result .amount").wait_for(timeout=60000)
        assert page.locator("#flow-result .badge").inner_text() == "PARTIAL"
        assert page.locator("#flow-result .amount").inner_text() == "22,500 KRW"
        assert stub.reads == 2
        assert errors == []
        page.close()
    finally:
        server.shutdown()
        server.server_close()


def _s2_product() -> str:
    scenarios, _ = engine.load_scenarios()
    return scenarios["S2_seoul_worker_bronchitis"]["policy"]["product"]


@pytest.mark.skipif(not _can_listen(), reason="sandbox blocks listen()")
def test_live_questions_continue_in_browser(browser, monkeypatch):
    stub = _LiveStub()
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate",
                        lambda inputs: {"decision": "PARTIAL", "amount": 22500})
    server = serve.start_background(0)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{server.server_port}/docs/demo.html")
        page.locator("#person-presets").wait_for(timeout=15000)
        page.evaluate(DROP_RETAKES)
        page.locator("#flow-questions li").first.wait_for(timeout=60000)
        assert page.locator("#flow-questions li").count() == len(serve.PERSON_FIELDS)  # visa, employer, work, entry, registration
        assert page.locator("#flow-result .badge").inner_text() == "need_facts"
        assert page.locator("#flow-result .amount").count() == 0
        assert stub.reads == 2
        page.locator(S2_PRESET).click()
        page.locator("#person-product").select_option(_s2_product())
        page.locator("#flow-questions button").click()
        page.locator("#flow-result .amount").wait_for(timeout=60000)
        assert page.locator("#flow-result .badge").inner_text() == "PARTIAL"
        assert page.locator("#flow-result .amount").inner_text() == "22,500 KRW"
        assert stub.reads == 2
        assert errors == []
        page.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _can_listen(), reason="sandbox blocks listen()")
def test_live_file_picker_upload_in_browser(browser, monkeypatch):
    """H9: the file picker uploads photos; drag-and-drop still works."""
    stub = _LiveStub()
    monkeypatch.setattr(serve, "live_provider", lambda: stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: True)
    monkeypatch.setattr(engine, "live_adjudicate",
                        lambda inputs: {"decision": "PARTIAL", "amount": 22500})
    server = serve.start_background(0)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{server.server_port}/docs/demo.html")
        page.locator("#person-presets").wait_for(timeout=15000)
        picker = page.locator("#flow-pick")
        assert picker.get_attribute("type") == "file"
        assert picker.get_attribute("accept") == "image/*"
        page.locator(S2_PRESET).click()
        live = Path(__file__).resolve().parent.parent / "samples" / "live"
        picker.set_input_files([live / "S2_receipt_retake.jpg",
                                live / "S2_medical_certificate_retake.jpg"])
        page.locator("#flow-questions li").first.wait_for(timeout=60000)
        assert page.locator("#flow-result .badge").inner_text() == "need_product"
        assert stub.reads == 2
        page.locator("#person-product").select_option(_s2_product())
        page.locator("#flow-questions button").click()
        page.locator("#flow-result .amount").wait_for(timeout=60000)
        assert page.locator("#flow-result .badge").inner_text() == "PARTIAL"
        assert page.locator("#flow-result .amount").inner_text() == "22,500 KRW"
        assert stub.reads == 2
        assert errors == []
        page.close()
    finally:
        server.shutdown()
        server.server_close()

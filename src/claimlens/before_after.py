"""Before/after illustration (61): hand effort vs measured ClaimLens time.

One SVG, no brand marks. The left side is the owner's labelled estimate
(verbatim wording from the backlog); the right side is the measured load
p50. No new numbers: N comes from the load data via headline.after_n,
and the only other figure in the artwork is the approved "30+ minutes".
"""

OWNER_SENTENCE = {
    "en": ("Doing this by hand \u2014 translating the certificate, converting "
           "the codes and currency, itemising the bill and filling the "
           "insurer's form \u2014 takes 30+ minutes per claim "
           "(builder's estimate)."),
    "ko": ("사람이 직접 하면 \u2014 진단서 번역, 코드·통화 변환, 영수증 항목 정리, "
           "보험사 양식 작성 \u2014 한 건에 30분 이상 "
           "걸립니다(만든 사람의 경험상 추정)."),
}

STEP_LABELS = {
    "en": ("certificate", "codes", "currency", "items", "form"),
    "ko": ("진단서", "코드", "통화", "항목", "양식"),
}

_CAPTION_LINES = {
    "en": ("Doing this by hand — translating the certificate,",
           "converting the codes and currency, itemising the bill",
           "and filling the insurer's form — takes 30+ minutes",
           "per claim (builder's estimate)."),
    "ko": ("사람이 직접 하면 — 진단서 번역, 코드·통화 변환,",
           "영수증 항목 정리, 보험사 양식 작성 — 한 건에",
           "30분 이상 걸립니다(만든 사람의 경험상 추정)."),
}

for _lang, _lines in _CAPTION_LINES.items():
    assert " ".join(_lines) == OWNER_SENTENCE[_lang], _lang

INK = "#1a1a1a"
DIM = "#65676b"
ACCENT = "#0064e0"
EDGE = "#d9dee4"


def _steps(lang: str) -> str:
    """Five manual-step glyphs with short labels."""
    labels = STEP_LABELS[lang]
    cells = []
    for pos, label in enumerate(labels):
        cx = 59 + pos * 70
        top = 100
        if pos == 0:  # translated certificate: document with lines
            glyph = (
                f'<rect x="{cx - 17}" y="{top}" width="34" height="42" rx="2" '
                f'fill="#fff" stroke="{INK}" stroke-width="1.6"/>'
                f'<path d="M{cx - 17} {top + 12}h34 M{cx - 17} {top + 21}h34 '
                f'M{cx - 17} {top + 30}h22" stroke="{DIM}" stroke-width="1.4"/>'
            )
        elif pos == 1:  # converted codes
            glyph = (
                f'<text x="{cx}" y="{top + 32}" text-anchor="middle" '
                f'font-size="22" font-family="monospace" fill="{INK}">'
                "&lt;/&gt;</text>"
            )
        elif pos == 2:  # converted currency: won under a circular arrow
            glyph = (
                f'<text x="{cx}" y="{top + 30}" text-anchor="middle" '
                f'font-size="24" fill="{INK}">\u20a9</text>'
                f'<path d="M{cx - 20} {top + 34}a20 20 0 0 1 36 -11" '
                f'fill="none" stroke="{DIM}" stroke-width="1.8"/>'
                f'<path d="M{cx + 19} {top + 17}l-1 9 -8 -4z" fill="{DIM}"/>'
            )
        elif pos == 3:  # itemised bill: bulleted list
            rows = "".join(
                f'<circle cx="{cx - 14}" cy="{top + 8 + i * 11}" r="2" '
                f'fill="{INK}"/>'
                f'<path d="M{cx - 8} {top + 8 + i * 11}h22" stroke="{DIM}" '
                'stroke-width="1.6"/>'
                for i in range(3)
            )
            glyph = rows
        else:  # insurer form: sheet with checkboxes
            glyph = (
                f'<rect x="{cx - 15}" y="{top}" width="30" height="42" rx="2" '
                f'fill="#fff" stroke="{INK}" stroke-width="1.6"/>'
                f'<rect x="{cx - 10}" y="{top + 7}" width="7" height="7" '
                f'fill="none" stroke="{DIM}" stroke-width="1.4"/>'
                f'<path d="M{cx} {top + 10}h10" stroke="{DIM}" '
                'stroke-width="1.4"/>'
                f'<rect x="{cx - 10}" y="{top + 20}" width="7" height="7" '
                f'fill="none" stroke="{DIM}" stroke-width="1.4"/>'
                f'<path d="M{cx} {top + 23}h10" stroke="{DIM}" '
                'stroke-width="1.4"/>'
            )
        cells.append(
            f"<g>{glyph}"
            f'<text x="{cx}" y="{top + 60}" text-anchor="middle" '
            f'font-size="11" fill="{DIM}">{label}</text></g>'
        )
    return "".join(cells)


def svg(n: str, lang: str = "en", standalone: bool = True) -> str:
    """The before/after figure; n is the measured seconds, lang en/ko.

    Inline copies (demo, video card) drop the xmlns namespace: HTML does
    not need it, and the video asset check forbids http references.
    """
    if lang == "ko":
        left_head = "직접 하면: 한 건에 30분 이상"
        right_big = f"약 {n}초"
        right_sub = "(측정값)"
        left_sub = "(만든 사람의 경험상 추정)"
        tag = "설명 그림"
        aria = (f"설명 그림: 사람이 직접 하면 한 건에 30분 이상"
                f"(만든 사람의 경험상 추정), ClaimLens는 약 {n}초(측정값)")
    else:
        lang = "en"
        left_head = "By hand: 30+ minutes per claim"
        right_big = f"about {n} s"
        right_sub = "(measured)"
        left_sub = "(builder's estimate)"
        tag = "illustration"
        aria = (f"Illustration: by hand, 30+ minutes per claim "
                "(builder's estimate); ClaimLens, about "
                f"{n} seconds (measured)")
    caption = "".join(
        f'<text x="24" y="{200 + i * 22}" font-size="12.5" fill="{INK}">'
        f"{line}</text>"
        for i, line in enumerate(_CAPTION_LINES[lang])
    )
    ns = 'xmlns="http://www.w3.org/2000/svg" ' if standalone else ""
    return (
        f'<svg {ns}viewBox="0 0 660 370" '
        f'width="660" height="370" role="img" aria-label="{aria}">'
        f'<rect x="8" y="8" width="392" height="354" rx="10" fill="#f7f8fa" '
        f'stroke="{EDGE}"/>'
        f'<rect x="412" y="8" width="240" height="354" rx="10" fill="#eef4fd" '
        f'stroke="{EDGE}"/>'
        f'<text x="24" y="34" font-size="11" letter-spacing="2" fill="{DIM}">'
        f"{tag}</text>"
        f'<text x="24" y="62" font-size="18" font-weight="bold" fill="{INK}">'
        f"{left_head}</text>"
        f'<text x="24" y="84" font-size="13" fill="{DIM}">'
        f"{left_sub}</text>"
        f"{_steps(lang)}{caption}"
        f'<text x="532" y="62" text-anchor="middle" font-size="18" '
        f'font-weight="bold" fill="{INK}">ClaimLens:</text>'
        f'<text x="532" y="102" text-anchor="middle" font-size="30" '
        f'font-weight="bold" fill="{ACCENT}">{right_big}</text>'
        f'<text x="532" y="126" text-anchor="middle" font-size="13" '
        f'fill="{DIM}">{right_sub}</text>'
        f'<rect x="497" y="150" width="70" height="130" rx="12" fill="#fff" '
        f'stroke="{INK}" stroke-width="2"/>'
        f'<path d="M524 292h16" stroke="{DIM}" stroke-width="2"/>'
        f'<circle cx="556" cy="262" r="24" fill="{ACCENT}"/>'
        '<path d="M545 262l8 8 14 -16" fill="none" stroke="#fff" '
        'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
    )

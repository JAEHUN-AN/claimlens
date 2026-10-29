#!/usr/bin/env python3
"""Render the held-out unseen set from samples/unseen/truth.json.

Usage:
    uv run python tools/unseen/render.py [--out DIR] [--seed N] [--cases U1,..]

Draws receipt + certificate per case as clean.png, then a mild phone-photo
variant as photo.jpg (perspective + light + JPEG, same kind of effect as
hard_images, its own strength and seeds). Deterministic: same seed renders
byte-identical files. Stdlib + Pillow only; fonts come from the machine
(see samples/unseen/README.md) and are never stored in the repo.
"""

import argparse
import hashlib
import json
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[2]
TRUTH = ROOT / "samples" / "unseen" / "truth.json"
W, H = 1240, 1754
MARGIN = 90
INK = (25, 25, 30)
GRAY = (110, 110, 120)
LIGHT = (232, 232, 236)
RED = (178, 34, 34)

FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
# Logical base -> (regular, bold). ttc entries carry an index.
FONTS = {
    "malgun": (("malgun.ttf", None), ("malgunbd.ttf", None)),
    "kopub": (("KoPubBatangMedium.ttf", None), ("KoPubBatangBold.ttf", None)),
    "yugothic": (("YuGothR.ttc", 0), ("YuGothB.ttc", 0)),
    "calibri": (("calibri.ttf", None), ("calibrib.ttf", None)),
    "simsun": (("simsun.ttc", 0), ("simsun.ttc", 0)),
    "georgia": (("georgia.ttf", None), ("georgiab.ttf", None)),
    "arial": (("arial.ttf", None), ("arialbd.ttf", None)),
    "consola": (("consola.ttf", None), ("consola.ttf", None)),
    "thai": (("LEELAWAD.TTF", None), ("LEELAWDB.TTF", None)),
    "cambria": (("cambria.ttc", 0), ("cambriab.ttf", None)),
}


def font(base: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name, idx = FONTS[base][1 if bold else 0]
    path = FONTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Font {name} missing in {FONTS_DIR}.")
    kw = {} if idx is None else {"index": idx}
    return ImageFont.truetype(str(path), size, **kw)


def text(d: ImageDraw.ImageDraw, xy, s: str, fnt, fill=INK, anchor="la",
         stroke: int = 0) -> None:
    d.text(xy, s, font=fnt, fill=fill, anchor=anchor, stroke_width=stroke,
           stroke_fill=fill)


def rule(d: ImageDraw.ImageDraw, x: int, y: int, w: int, dashed=False) -> int:
    if dashed:
        for x0 in range(x, x + w, 14):
            d.line([(x0, y), (min(x0 + 8, x + w), y)], fill=GRAY, width=2)
    else:
        d.line([(x, y), (x + w, y)], fill=GRAY, width=2)
    return y + 14


def _tokens(s: str) -> list[str]:
    out: list[str] = []
    for word in s.split(" "):
        if any(ord(c) > 0x2E7F for c in word):
            out.extend(list(word))
        else:
            out.append(word)
    return out


def para(d: ImageDraw.ImageDraw, x: int, y: int, maxw: int, s: str, fnt,
         fill=INK, lh: int = 44) -> int:
    line = ""
    for tok in _tokens(s):
        both_cjk = (
            bool(line)
            and ord(line[-1]) > 0x2E7F
            and ord(tok[:1]) > 0x2E7F
        )
        trial = f"{line}{'' if both_cjk else ' '}{tok}" if line else tok
        if d.textlength(trial, font=fnt) <= maxw:
            line = trial
        else:
            text(d, (x, y), line, fnt, fill)
            y += lh
            line = tok
    if line:
        text(d, (x, y), line, fnt, fill)
        y += lh
    return y + 6


def table(d: ImageDraw.ImageDraw, x: int, y: int, widths: list[int],
          rows: list[list[str]], fnt, bold, aligns: list[str],
          header_fill=(242, 242, 245), rh: int = 52) -> int:
    total = sum(widths)
    for ri, row in enumerate(rows):
        if ri == 0:
            d.rectangle([x, y, x + total, y + rh], fill=header_fill)
        f = bold if ri == 0 else fnt
        cx = x
        for ci, (cell, wdt) in enumerate(zip(row, widths)):
            ax = {"l": "la", "c": "ma", "r": "ra"}[aligns[ci]]
            px = {"l": cx + 12, "c": cx + wdt // 2, "r": cx + wdt - 12}[aligns[ci]]
            text(d, (px, y + 10), cell, f, anchor=ax)
            cx += wdt
        y += rh
        d.line([(x, y), (x + total, y)], fill=GRAY, width=2)
    d.line([(x, y - len(rows) * rh), (x, y)], fill=GRAY, width=2)
    d.line([(x + total, y - len(rows) * rh), (x + total, y)], fill=GRAY, width=2)
    cx = x
    for wdt in widths[:-1]:
        cx += wdt
        d.line([(cx, y - len(rows) * rh), (cx, y)], fill=GRAY, width=1)
    return y + 18


def leader(d: ImageDraw.ImageDraw, x: int, y: int, w: int, left: str,
           right: str, fnt, bold) -> int:
    text(d, (x, y), left, fnt)
    rw = d.textlength(right, font=bold)
    text(d, (x + w - rw, y), right, bold, anchor="la")
    dots = "." * max(2, int((w - d.textlength(left, font=fnt) - rw - 40) / 9))
    text(d, (x + d.textlength(left, font=fnt) + 16, y), dots, fnt, fill=GRAY)
    return y + 52


def watermark(img: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    fnt = font("arial", 120, bold=True)
    ld.text((img.width // 2, img.height // 2), "SYNTHETIC SAMPLE", font=fnt,
            fill=(178, 34, 34, 36), anchor="mm")
    layer = layer.rotate(30, resample=Image.BICUBIC,
                         center=(img.width // 2, img.height // 2))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def stamp_circle(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, s: str,
                 fnt) -> None:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RED, width=4)
    text(d, (cx, cy - 18), s, fnt, fill=RED, anchor="ma")


def money(amount: float, decimals: int = 0) -> str:
    return f"{amount:,.{decimals}f}" if decimals else f"{amount:,.0f}"


def base_image() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), "white")
    return img, ImageDraw.Draw(img)


def receipt_u1(case: dict, data: dict) -> Image.Image:
    """Gridless clinic bill: plain lines, dot leaders, boxed total."""
    img, d = base_image()
    fnt, bold = font("malgun", 30), font("malgun", 30, bold=True)
    title = font("malgun", 52, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital_ko"], title, anchor="ma")
    y += 70
    text(d, (x + w // 2, y), data["hospital"], fnt, anchor="ma")
    y += 44
    text(d, (x + w // 2, y), "진료비 영수증  RECEIPT", bold, anchor="ma")
    y = rule(d, x, y + 44, w) + 10
    pat = case["patient"]
    for label, value in [
        ("영수증번호", data["receipt_no"]),
        ("진료일", f"{data['issue_date']}  ({data['visit']})"),
        ("환자", f"{pat['name']}  ·  DOB {pat['dob']}"),
        ("", f"Passport {pat['passport']}  ·  ID {pat['patient_id']}"),
    ]:
        text(d, (x, y), label, bold)
        text(d, (x + 220, y), value, fnt)
        y += 50
    y = rule(d, x, y + 8, w, dashed=True) + 10
    for item in data["items"]:
        left = f"{item['label']}  {item['label_en']}"
        y = leader(d, x, y, w, left, f"{money(item['amount'])}원", fnt, bold)
    y += 6
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    d.line([(x, y + 8), (x + w, y + 8)], fill=INK, width=3)
    y += 20
    text(d, (x, y), "합계  Total", font("malgun", 38, bold=True))
    total = f"{money(data['total'])}원"
    text(d, (x + w, y), total, font("malgun", 38, bold=True), anchor="ra")
    y += 70
    y = rule(d, x, y, w) + 10
    text(d, (x, y), f"카드결제 일시불  ·  {data['address']}",
         font("malgun", 24), fill=GRAY)
    stamp_circle(d, x + w - 90, y + 150, 75, "수납필",
                 font("malgun", 34, bold=True))
    return watermark(img)


def receipt_u2(case: dict, data: dict) -> Image.Image:
    """Inpatient bill: quantity x unit grid, amount last."""
    img, d = base_image()
    fnt, bold = font("kopub", 28), font("kopub", 28, bold=True)
    title = font("kopub", 48, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), f"{data['hospital_ko']} {data['hospital']}",
         title, anchor="ma")
    y += 66
    text(d, (x + w // 2, y), "입원 진료비 계산서  INPATIENT BILL", bold, anchor="ma")
    y += 60
    pat = case["patient"]
    rows = [
        ["구분", "내용"],
        ["환자", f"{pat['name']}  ·  DOB {pat['dob']}"],
        ["여권 / 등록번호", f"{pat['passport']}  /  {pat['patient_id']}"],
        ["입원기간", (f"{data['service_date']} ~ {data['discharge_date']}  "
                      f"·  병실 {data['ward']}")],
        ["계산서번호", data["receipt_no"]],
    ]
    y = table(d, x, y, [300, w - 300], rows, fnt, bold, ["l", "l"], rh=50)
    head = ["항목 Item", "수량", "단가 (원)", "금액 (원)"]
    grows = [head]
    for item in data["items"]:
        grows.append([f"{item['label']} {item['label_en']}",
                      str(item["qty"]), money(item["unit"]),
                      money(item["amount"])])
    grows.append(["합계 Total", "", "", f"{money(data['total'])}원"])
    y = table(d, x, y, [w - 480, 120, 180, 180], grows, fnt, bold,
              ["l", "c", "r", "r"])
    y = rule(d, x, y, w) + 10
    text(d, (x, y), f"{data['address']}  ·  카드결제", font("kopub", 24),
         fill=GRAY)
    return watermark(img)


def receipt_u3(case: dict, data: dict) -> Image.Image:
    """Narrow register-slip receipt with a consumption-tax block."""
    img, d = base_image()
    fnt, bold = font("yugothic", 30), font("yugothic", 30, bold=True)
    x, w = MARGIN + 130, W - 2 * (MARGIN + 130)
    y = 90
    text(d, (x + w // 2, y), data["hospital_ja"], font("yugothic", 44, bold=True),
         anchor="ma")
    y += 60
    text(d, (x + w // 2, y), data["hospital"], fnt, anchor="ma")
    y += 44
    text(d, (x + w // 2, y), "領収書  RECEIPT", bold, anchor="ma")
    y = rule(d, x, y + 44, w, dashed=True) + 10
    pat = case["patient"]
    for left, right in [
        ("No.", data["receipt_no"]),
        ("Date", f"{data['issue_date']}  {data['department']}"),
        ("Patient", f"{pat['name']}"),
        ("DOB / Passport", f"{pat['dob']} / {pat['passport']}"),
        ("ID", pat["patient_id"]),
    ]:
        text(d, (x, y), left, fnt, fill=GRAY)
        text(d, (x + w, y), right, fnt, anchor="ra")
        y += 46
    y = rule(d, x, y + 8, w, dashed=True) + 10
    for item in data["items"][:5]:
        y = leader(d, x, y, w, f"{item['label']} {item['label_en']}",
                   money(item["amount"]), fnt, fnt)
    y = rule(d, x, y + 8, w, dashed=True) + 10
    tax = data["items"][5]
    for left, right, bf in [
        ("小計 Subtotal", money(data["subtotal"]), fnt),
        ("うち消費税対象 Taxable", money(data["taxable"]), fnt),
        (f"{tax['label']} {tax['label_en']}", money(tax["amount"]), bold),
    ]:
        y = leader(d, x, y, w, left, right, fnt, bf)
    y += 4
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    y += 18
    text(d, (x, y), "合計 Total", font("yugothic", 40, bold=True))
    text(d, (x + w, y), f"¥{money(data['total'])}",
         font("yugothic", 40, bold=True), anchor="ra")
    y += 58
    text(d, (x + w, y), f"JPY {money(data['total'])}", fnt, anchor="ra")
    y = rule(d, x, y + 52, w, dashed=True) + 10
    text(d, (x + w // 2, y), "ありがとうございました  Thank you", fnt, anchor="ma")
    y += 46
    text(d, (x + w // 2, y), data["address"], font("yugothic", 22),
         fill=GRAY, anchor="ma")
    return watermark(img)


def receipt_u4(case: dict, data: dict) -> Image.Image:
    """US bill, description first with qty, nonzero adjustment row."""
    img, d = base_image()
    fnt, bold = font("calibri", 30), font("calibri", 30, bold=True)
    mono = font("consola", 29)
    title = font("calibri", 46, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x, y), data["hospital"], title)
    text(d, (x + w, y + 6), "ITEMIZED BILL", font("calibri", 34, bold=True),
         anchor="ra")
    y += 58
    text(d, (x, y), data["address"], fnt, fill=GRAY)
    text(d, (x + w, y), f"Statement {data['statement_date']}", fnt, anchor="ra")
    y = rule(d, x, y + 50, w) + 10
    pat = case["patient"]
    for left, right in [
        ("Patient", f"{pat['name']}  ·  DOB {pat['dob']}"),
        ("Account", f"{data['account']}  ·  {pat['patient_id']}"),
        ("Service", f"{data['service_date']}"),
        ("", data["visit"]),
        ("Previous balance", f"${money(data['previous_balance'], 2)}"),
    ]:
        text(d, (x, y), left, bold)
        text(d, (x + 330, y), right, fnt)
        y += 48
    y += 4
    rows = [["Description", "Qty", "Amount"]]
    for item in data["items"][:5]:
        rows.append([item["label"], str(item["qty"]),
                     money(item["amount"], 2)])
    y = table(d, x, y, [w - 360, 120, 240], rows, fnt, bold, ["l", "c", "r"])
    adj = data["items"][5]
    for left, right, bf in [
        ("Charges subtotal", f"${money(data['subtotal'], 2)}", fnt),
        (adj["label"], money(adj["amount"], 2), bold),
    ]:
        text(d, (x + w - 560, y), left, bf)
        text(d, (x + w - 12, y), right, mono, anchor="ra")
        y += 50
    d.line([(x + w - 560, y), (x + w, y)], fill=INK, width=3)
    y += 14
    text(d, (x + w - 560, y), "AMOUNT DUE", font("calibri", 36, bold=True))
    text(d, (x + w - 12, y), f"${money(data['total'], 2)}",
         font("consola", 34), anchor="ra")
    y = rule(d, x, y + 62, w) + 10
    text(d, (x, y), "Questions? Call Patient Billing. USD only; wire instructions "
                    "on request.", font("calibri", 24), fill=GRAY)
    return watermark(img)


def receipt_u5(case: dict, data: dict) -> Image.Image:
    """Chinese receipt: red masthead, project/amount grid, FX memo."""
    img, d = base_image()
    fnt = font("simsun", 30)
    bold = font("simsun", 30, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital_cn"], font("simsun", 48, bold=True),
         fill=RED, anchor="ma", stroke=1)
    y += 64
    text(d, (x + w // 2, y), data["hospital"], fnt, anchor="ma")
    y += 46
    text(d, (x + w // 2, y), "医疗收费发票  MEDICAL RECEIPT",
         font("simsun", 32, bold=True), anchor="ma", stroke=1)
    y += 62
    pat = case["patient"]
    rows = [
        ["项目", "内容"],
        ["发票号", data["invoice_no"]],
        ["日期", f"{data['issue_date']}  ·  {data['department']}"],
        ["患者", f"{pat['name']}  ·  DOB {pat['dob']}"],
        ["护照 / 病案号", f"{pat['passport']}  /  {pat['patient_id']}"],
    ]
    y = table(d, x, y, [300, w - 300], rows, fnt, bold, ["l", "l"], rh=50)
    grows = [["收费项目 Item", "金额 Amount (¥)"]]
    for item in data["items"]:
        grows.append([f"{item['label']} {item['label_en']}",
                      money(item["amount"], 2)])
    y = table(d, x, y, [w - 320, 320], grows, fnt, bold, ["l", "r"])
    text(d, (x, y), "合计 Total", font("simsun", 38, bold=True), stroke=1)
    text(d, (x + w, y), f"¥{money(data['total'], 2)} (CNY)",
         font("simsun", 38, bold=True), anchor="ra", stroke=1)
    y += 62
    text(d, (x + w, y), data["fx_note"], font("simsun", 24), fill=GRAY,
         anchor="ra")
    y = rule(d, x, y + 52, w) + 10
    text(d, (x, y), data["address"], font("simsun", 24), fill=GRAY)
    d.rounded_rectangle([x + w - 260, y + 40, x + w, y + 130], radius=12,
                        outline=RED, width=4)
    text(d, (x + w - 130, y + 62), "收费专用章", font("simsun", 34, bold=True),
         fill=RED, anchor="ma", stroke=1)
    return watermark(img)


def receipt_u6(case: dict, data: dict) -> Image.Image:
    """Compact urgent-care receipt: two columns, balance due."""
    img, d = base_image()
    fnt, bold = font("georgia", 30), font("georgia", 30, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital"], font("georgia", 40, bold=True),
         anchor="ma")
    y += 58
    text(d, (x + w // 2, y), data["address"], font("georgia", 24), fill=GRAY,
         anchor="ma")
    y += 44
    text(d, (x + w // 2, y), "URGENT CARE RECEIPT", bold, anchor="ma")
    y = rule(d, x, y + 44, w) + 10
    pat = case["patient"]
    for left, right in [
        ("Receipt", data["receipt_no"]),
        ("Service", f"{data['service_date']}  ·  {data['visit']}"),
        ("Patient", f"{pat['name']}  ·  DOB {pat['dob']}"),
        ("Passport / ID", f"{pat['passport']}  /  {pat['patient_id']}"),
    ]:
        text(d, (x, y), left, bold)
        text(d, (x + 300, y), right, fnt)
        y += 48
    y += 6
    rows = [["Description", "Amount"]]
    for item in data["items"]:
        rows.append([item["label"], f"${money(item['amount'], 2)}"])
    y = table(d, x, y, [w - 300, 300], rows, fnt, bold, ["l", "r"])
    text(d, (x, y), "BALANCE DUE", font("georgia", 36, bold=True))
    text(d, (x + w - 12, y), f"${money(data['total'], 2)}",
         font("georgia", 36, bold=True), anchor="ra")
    y = rule(d, x, y + 62, w) + 10
    text(d, (x, y), "Pay at the front desk or online. Thank you.",
         font("georgia", 24), fill=GRAY)
    return watermark(img)


def cert_simple(case: dict, data: dict) -> Image.Image:
    """Plain certificate: patient strip, diagnosis lines, prose blocks."""
    img, d = base_image()
    fnt = font("arial", 29)
    bold = font("arial", 29, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital"], fnt, fill=GRAY, anchor="ma")
    y += 46
    title = data["title"]
    title_fnt = font("arial", 42, bold=True)
    text(d, (x + w // 2, y), title, title_fnt, anchor="ma")
    y += 58
    if data.get("title_local"):
        base = {"U1": "malgun", "U2": "kopub", "U3": "yugothic",
                "T3": "yugothic"}.get(case["id"][:2], "arial")
        text(d, (x + w // 2, y), data["title_local"],
             font(base, 34, bold=True), anchor="ma")
        y += 46
    y = rule(d, x, y + 16, w) + 10
    pat = case["patient"]
    rows = [
        ["Field", "Detail"],
        ["Patient name", pat["name"]],
        ["Date of birth", pat["dob"]],
        ["Passport No.", pat["passport"]],
        ["Patient ID", pat["patient_id"]],
        ["Date of visit", data["date_of_visit"]],
    ]
    y = table(d, x, y, [330, w - 330], rows, fnt, bold, ["l", "l"])
    for pos, diag in enumerate(data["diagnoses"], 1):
        text(d, (x, y), f"{pos}. {diag['label']}", bold)
        text(d, (x + w, y), f"{diag['code']} ({diag['system']})", fnt,
             anchor="ra")
        y += 50
    y = rule(d, x, y + 8, w, dashed=True) + 10
    for head, key in [("History", "history"), ("Treatment", "treatment"),
                      ("Outcome", "outcome")]:
        text(d, (x, y), head, bold)
        y = para(d, x + 280, y, w - 280, data[key], fnt) + 4
    y = rule(d, x, y + 8, w) + 10
    text(d, (x, y), f"Date of issue: {data['issue_date']}", fnt)
    y += 46
    text(d, (x, y), f"{data['doctor']}  ·  License {data['license']}", fnt)
    return watermark(img)


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def cert_letter(case: dict, data: dict) -> Image.Image:
    """Letter-style certificate: prose paragraphs, codes embedded in text."""
    img, d = base_image()
    fnt = font("georgia", 30)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x, y), data["hospital"], font("georgia", 34, bold=True))
    text(d, (x + w, y), data["issue_date"], fnt, anchor="ra")
    y = rule(d, x, y + 52, w) + 10
    text(d, (x, y), "To Whom It May Concern,", fnt)
    y += 62
    pat = case["patient"]
    year, mon, day = pat["dob"].split("-")
    dob_words = f"{MONTHS[int(mon) - 1]} {int(day)}, {year}"
    title = pat.get("title", "")
    diags = "; ".join(f"{g['label']} ({g['system']} code {g['code']})"
                      for g in data["diagnoses"])
    y = para(d, x, y, w, f"{title} {pat['name']} (date of birth {dob_words}; "
                        f"passport {pat['passport']}; patient ID "
                        f"{pat['patient_id']}) was treated at {data['hospital']} "
                        f"on {data['date_of_visit']}.", fnt)
    y = para(d, x, y, w, f"The diagnosis was {diags}.", fnt)
    y = para(d, x, y, w, f"{data['treatment']} {data['outcome']}", fnt)
    y += 10
    text(d, (x, y), "Sincerely,", fnt)
    y += 62
    text(d, (x, y), data["doctor"], font("georgia", 32, bold=True))
    y += 48
    text(d, (x, y), f"License No. {data['license']}", fnt, fill=GRAY)
    return watermark(img)


RECEIPTS = {
    "u1_gridless": receipt_u1,
    "u2_qty_grid": receipt_u2,
    "u3_slip": receipt_u3,
    "u4_desc_first": receipt_u4,
    "u5_fapiao": receipt_u5,
    "u6_compact": receipt_u6,
}
CERTS = {"cert_simple": cert_simple, "cert_letter": cert_letter}


def receipt_t1_er(case: dict, data: dict) -> Image.Image:
    """Thai ER bill: EN-first rows, baht total."""
    img, d = base_image()
    fnt, bold = font("thai", 30), font("thai", 30, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital"], font("thai", 44, bold=True),
         anchor="ma")
    y += 60
    text(d, (x + w // 2, y), data["hospital_th"], fnt, anchor="ma")
    y += 46
    text(d, (x + w // 2, y), "EMERGENCY RECEIPT  ใบเสร็จรับเงิน", bold,
         anchor="ma")
    y = rule(d, x, y + 44, w) + 10
    pat = case["patient"]
    rows = [
        ["Field", "Detail"],
        ["Receipt No.", data["receipt_no"]],
        ["Date", f"{data['issue_date']}  ·  {data['department']}"],
        ["Patient", f"{pat['name']}  ·  DOB {pat['dob']}"],
        ["Passport / ID", f"{pat['passport']}  /  {pat['patient_id']}"],
    ]
    y = table(d, x, y, [330, w - 330], rows, fnt, bold, ["l", "l"])
    grows = [["Description", "Amount"]]
    for item in data["items"]:
        grows.append([item["label"], money(item["amount"], 2)])
    y = table(d, x, y, [w - 300, 300], grows, fnt, bold, ["l", "r"])
    text(d, (x, y), "TOTAL", font("thai", 38, bold=True))
    text(d, (x + w, y), f"฿{money(data['total'], 2)} (THB)",
         font("thai", 38, bold=True), anchor="ra")
    y = rule(d, x, y + 62, w) + 10
    text(d, (x, y), data["address"], font("thai", 24), fill=GRAY)
    return watermark(img)


def receipt_t1_pharm(case: dict, data: dict) -> Image.Image:
    """Thai pharmacy slip: narrow, centred, dashed rules."""
    img, d = base_image()
    fnt, bold = font("thai", 30), font("thai", 30, bold=True)
    x, w = MARGIN + 130, W - 2 * (MARGIN + 130)
    y = 90
    text(d, (x + w // 2, y), data["hospital"], font("thai", 40, bold=True),
         anchor="ma")
    y += 56
    text(d, (x + w // 2, y), "PHARMACY RECEIPT  ใบเสร็จรับเงิน", bold,
         anchor="ma")
    y = rule(d, x, y + 44, w, dashed=True) + 10
    pat = case["patient"]
    text(d, (x + w // 2, y), f"{data['receipt_no']}  ·  {data['issue_date']}",
         fnt, anchor="ma")
    y += 44
    text(d, (x + w // 2, y), pat["name"], fnt, anchor="ma")
    y = rule(d, x, y + 44, w, dashed=True) + 10
    for item in data["items"]:
        y = leader(d, x, y, w, item["label"], money(item["amount"], 2), fnt,
                   fnt)
    y += 4
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    y += 18
    text(d, (x, y), "TOTAL", font("thai", 38, bold=True))
    text(d, (x + w, y), f"฿{money(data['total'], 2)}",
         font("thai", 38, bold=True), anchor="ra")
    y = rule(d, x, y + 62, w, dashed=True) + 10
    text(d, (x + w // 2, y), data["address"], font("thai", 22), fill=GRAY,
         anchor="ma")
    return watermark(img)


def fmt_vnd(a: float) -> str:
    """Vietnamese thousands: dots, no decimals (1.250.000)."""
    return f"{int(a):,}".replace(",", ".")


def fmt_eur(a: float) -> str:
    """French decimals: comma for the point (12,50)."""
    return f"{a:.2f}".replace(".", ",")


def receipt_t2_vnd(case: dict, data: dict) -> Image.Image:
    """Vietnamese clinic receipt: dots separate thousands."""
    img, d = base_image()
    fnt, bold = font("calibri", 30), font("calibri", 30, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital_vi"], font("calibri", 44, bold=True),
         anchor="ma")
    y += 60
    text(d, (x + w // 2, y), data["hospital"], fnt, anchor="ma")
    y += 44
    text(d, (x + w // 2, y), "HÓA ĐƠN  RECEIPT", bold, anchor="ma")
    y = rule(d, x, y + 44, w) + 10
    pat = case["patient"]
    for left, right in [
        ("Số / No.", data["receipt_no"]),
        ("Ngày / Date", data["issue_date"]),
        ("Bệnh nhân / Patient", f"{pat['name']}  ·  DOB {pat['dob']}"),
        ("Passport / ID", f"{pat['passport']}  /  {pat['patient_id']}"),
    ]:
        text(d, (x, y), left, bold)
        text(d, (x + 430, y), right, fnt)
        y += 48
    y = rule(d, x, y + 8, w, dashed=True) + 10

    for item in data["items"]:
        y = leader(d, x, y, w, f"{item['label']}  {item['label_en']}",
                   fmt_vnd(item["amount"]), fnt, bold)
    y += 6
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    y += 18
    text(d, (x, y), "TỔNG CỘNG  Total", font("calibri", 38, bold=True))
    text(d, (x + w, y), f"{fmt_vnd(data['total'])} ₫ (VND)",
         font("calibri", 38, bold=True), anchor="ra")
    y = rule(d, x, y + 66, w) + 10
    text(d, (x, y), data["address"], font("calibri", 24), fill=GRAY)
    return watermark(img)


def receipt_t3_clinic(case: dict, data: dict) -> Image.Image:
    """Full-page Japanese clinic bill with a consumption-tax block."""
    img, d = base_image()
    fnt, bold = font("yugothic", 30), font("yugothic", 30, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), f"{data['hospital_ja']}  {data['hospital']}",
         font("yugothic", 38, bold=True), anchor="ma")
    y += 58
    text(d, (x + w // 2, y), "領収書  RECEIPT", bold, anchor="ma")
    y = rule(d, x, y + 44, w) + 10
    pat = case["patient"]
    rows = [
        ["項目", "内容"],
        ["No.", data["receipt_no"]],
        ["Date", f"{data['issue_date']}  ·  {data['department']}"],
        ["Patient", f"{pat['name']}  ·  DOB {pat['dob']}"],
        ["Passport / ID", f"{pat['passport']}  /  {pat['patient_id']}"],
    ]
    y = table(d, x, y, [300, w - 300], rows, fnt, bold, ["l", "l"], rh=50)
    for item in data["items"][:4]:
        y = leader(d, x, y, w, f"{item['label']} {item['label_en']}",
                   money(item["amount"]), fnt, fnt)
    y = rule(d, x, y + 8, w, dashed=True) + 10
    tax = data["items"][4]
    for left, right, bf in [
        ("小計 Subtotal", money(data["subtotal"]), fnt),
        ("うち消費税対象 Taxable", money(data["taxable"]), fnt),
        (f"{tax['label']} {tax['label_en']}", money(tax["amount"]), bold),
    ]:
        y = leader(d, x, y, w, left, right, fnt, bf)
    y += 4
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    y += 18
    text(d, (x, y), "合計 Total", font("yugothic", 40, bold=True))
    text(d, (x + w, y), f"¥{money(data['total'])}",
         font("yugothic", 40, bold=True), anchor="ra")
    y += 58
    text(d, (x + w, y), f"JPY {money(data['total'])} (fully self-paid)", fnt,
         anchor="ra")
    y = rule(d, x, y + 52, w) + 10
    text(d, (x, y), data["address"], font("yugothic", 24), fill=GRAY)
    return watermark(img)


def receipt_t4_pharm(case: dict, data: dict) -> Image.Image:
    """French pharmacy ticket: decimal commas, no certificate exists."""
    img, d = base_image()
    fnt, bold = font("arial", 30), font("arial", 30, bold=True)
    mono = font("consola", 29)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital"], font("arial", 42, bold=True),
         anchor="ma")
    y += 60
    text(d, (x + w // 2, y), "TICKET DE CAISSE", bold, anchor="ma")
    y = rule(d, x, y + 44, w, dashed=True) + 10

    pat = case["patient"]
    text(d, (x, y), f"{data['receipt_no']}  ·  {data['issue_date']}", fnt)
    y += 46
    text(d, (x, y), f"{pat['name']}  ·  ID {pat['patient_id']}", fnt)
    y = rule(d, x, y + 44, w, dashed=True) + 10
    for item in data["items"]:
        text(d, (x, y), item["label"], fnt)
        text(d, (x + w, y), f"{fmt_eur(item['amount'])} €", mono, anchor="ra")
        y += 52
    y += 4
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    y += 18
    text(d, (x, y), "Total", font("arial", 38, bold=True))
    text(d, (x + w, y), f"{fmt_eur(data['total'])} € (EUR)",
         font("arial", 38, bold=True), anchor="ra")
    y = rule(d, x, y + 62, w, dashed=True) + 10
    text(d, (x + w // 2, y), "Merci de votre visite", fnt, anchor="ma")
    y += 44
    text(d, (x + w // 2, y), data["address"], font("arial", 22), fill=GRAY,
         anchor="ma")
    return watermark(img)


def receipt_t5_bill(case: dict, data: dict) -> Image.Image:
    """US bill with an insurance adjustment and patient responsibility."""
    img, d = base_image()
    fnt, bold = font("calibri", 30), font("calibri", 30, bold=True)
    mono = font("consola", 29)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x, y), data["hospital"], font("calibri", 42, bold=True))
    text(d, (x + w, y + 4), "STATEMENT", font("calibri", 32, bold=True),
         anchor="ra")
    y += 56
    text(d, (x, y), data["address"], fnt, fill=GRAY)
    text(d, (x + w, y), f"Statement {data['statement_date']}", fnt, anchor="ra")
    y = rule(d, x, y + 50, w) + 10
    pat = case["patient"]
    for left, right in [
        ("Patient", f"{pat['name']}  ·  DOB {pat['dob']}"),
        ("Account", f"{data['account']}  ·  {pat['patient_id']}"),
        ("Service", f"{data['service_date']}  ·  {data['visit']}"),
    ]:
        text(d, (x, y), left, bold)
        text(d, (x + 300, y), right, fnt)
        y += 48
    y += 6
    rows = [["Description", "Amount"]]
    for item in data["items"][:4]:
        rows.append([item["label"], money(item["amount"], 2)])
    y = table(d, x, y, [w - 280, 280], rows, fnt, bold, ["l", "r"])
    adj = data["items"][4]
    for left, right, bf in [
        ("Charges subtotal", f"${money(data['subtotal'], 2)}", fnt),
        (adj["label"], money(adj["amount"], 2), bold),
    ]:
        text(d, (x + w - 600, y), left, bf)
        text(d, (x + w - 12, y), right, mono, anchor="ra")
        y += 50
    d.line([(x + w - 600, y), (x + w, y)], fill=INK, width=3)
    y += 14
    text(d, (x + w - 600, y), "PATIENT RESPONSIBILITY",
         font("calibri", 32, bold=True))
    text(d, (x + w - 12, y), f"${money(data['total'], 2)}", font("consola", 32),
         anchor="ra")
    y = rule(d, x, y + 60, w) + 10
    text(d, (x, y), "Insurance billed separately. Pay online or at the desk.",
         font("calibri", 24), fill=GRAY)
    return watermark(img)


def receipt_t5_cardpay(case: dict, data: dict) -> Image.Image:
    """Card payment slip: one amount, no line items."""
    img, d = base_image()
    fnt, bold = font("consola", 30), font("consola", 30, bold=True)
    x, w = MARGIN + 180, W - 2 * (MARGIN + 180)
    y = 130
    text(d, (x + w // 2, y), data["hospital"], font("arial", 30, bold=True),
         anchor="ma")
    y += 52
    text(d, (x + w // 2, y), "CARD SALE", bold, anchor="ma")
    y = rule(d, x, y + 44, w, dashed=True) + 10
    for left, right in [
        ("Card", data["card"]),
        ("Auth", data["auth"]),
        ("Date", data["date"]),
    ]:
        text(d, (x, y), left, fnt, fill=GRAY)
        text(d, (x + w, y), right, fnt, anchor="ra")
        y += 48
    y += 6
    d.line([(x, y), (x + w, y)], fill=INK, width=3)
    y += 18
    text(d, (x, y), "AMOUNT", font("consola", 38, bold=True))
    text(d, (x + w, y), f"${money(data['total'], 2)}",
         font("consola", 38, bold=True), anchor="ra")
    y = rule(d, x, y + 62, w, dashed=True) + 10
    text(d, (x + w // 2, y), "APPROVED - Thank you", fnt, anchor="ma")
    return watermark(img)


def receipt_t6_dental(case: dict, data: dict) -> Image.Image:
    """Dental receipt with procedure codes."""
    img, d = base_image()
    fnt, bold = font("cambria", 30), font("cambria", 30, bold=True)
    x, w = MARGIN, W - 2 * MARGIN
    y = 90
    text(d, (x + w // 2, y), data["hospital"], font("cambria", 42, bold=True),
         anchor="ma")
    y += 60
    text(d, (x + w // 2, y), "DENTAL RECEIPT", bold, anchor="ma")
    y = rule(d, x, y + 44, w) + 10
    pat = case["patient"]
    for left, right in [
        ("Receipt", data["receipt_no"]),
        ("Service", f"{data['issue_date']}  ·  {data['visit']}"),
        ("Patient", f"{pat['name']}  ·  DOB {pat['dob']}"),
        ("Passport / ID", f"{pat['passport']}  /  {pat['patient_id']}"),
    ]:
        text(d, (x, y), left, bold)
        text(d, (x + 300, y), right, fnt)
        y += 48
    y += 6
    rows = [["Code", "Description", "Amount"]]
    for item in data["items"]:
        rows.append([item.get("code", ""), item["label"],
                     money(item["amount"], 2)])
    y = table(d, x, y, [180, w - 460, 280], rows, fnt, bold, ["l", "l", "r"])
    text(d, (x, y), "TOTAL DUE", font("cambria", 36, bold=True))
    text(d, (x + w - 12, y), f"${money(data['total'], 2)}",
         font("cambria", 36, bold=True), anchor="ra")
    y = rule(d, x, y + 62, w) + 10
    text(d, (x, y), data["address"], font("cambria", 24), fill=GRAY)
    return watermark(img)


TEMPLATES = {
    **RECEIPTS,
    **CERTS,
    "t1_er": receipt_t1_er,
    "t1_pharm": receipt_t1_pharm,
    "t2_vnd": receipt_t2_vnd,
    "t3_clinic": receipt_t3_clinic,
    "t4_pharm": receipt_t4_pharm,
    "t5_bill": receipt_t5_bill,
    "t5_cardpay": receipt_t5_cardpay,
    "t6_dental": receipt_t6_dental,
}


def phone_photo(img: Image.Image, seed: str) -> Image.Image:
    """Mild phone-photo effect: slight perspective, light falloff, JPEG grain."""
    rng = random.Random(hashlib.sha256(seed.encode("utf-8")).hexdigest())
    wdt, hgt = img.size

    def jit() -> float:
        return rng.uniform(-0.012, 0.012)

    quad = []
    for cx, cy in [(0, 0), (0, hgt), (wdt, hgt), (wdt, 0)]:
        quad.extend([cx + jit() * wdt, cy + jit() * hgt])
    photo = img.transform((wdt, hgt), Image.QUAD, quad, resample=Image.BICUBIC)
    photo = ImageEnhance.Brightness(photo).enhance(rng.uniform(0.93, 1.0))
    photo = ImageEnhance.Contrast(photo).enhance(rng.uniform(0.97, 1.03))
    return photo


def render_case(case: dict, out_dir: Path, seed: int) -> list[Path]:
    case_dir = out_dir / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for doc in case["documents"]:
        clean = TEMPLATES[doc["template"]](case, doc["data"])
        name = doc.get("file") or doc["doc_type"]
        png = case_dir / f"{name}_clean.png"
        clean.save(png)
        paths.append(png)
        photo = phone_photo(clean, f"{seed}:{case['id']}:{name}")
        jpg = case_dir / f"{name}_photo.jpg"
        photo.save(jpg, quality=90)
        paths.append(jpg)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the unseen eval set.")
    parser.add_argument("--out", default=str(ROOT / "samples" / "unseen"))
    parser.add_argument("--truth", default=str(TRUTH))
    parser.add_argument("--seed", type=int, default=49)
    parser.add_argument("--cases", default=None,
                        help="Comma-separated case ids; default all.")
    args = parser.parse_args(argv)
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    wanted = None
    if args.cases:
        wanted = {s.strip() for s in args.cases.split(",")}
    out_dir = Path(args.out)
    count = 0
    files = 0
    for case in truth.get("scenarios", truth.get("cases", [])):
        if wanted and case["id"] not in wanted:
            continue
        files += len(render_case(case, out_dir, args.seed))
        count += 1
    print(f"rendered {count} cases, {files} images to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


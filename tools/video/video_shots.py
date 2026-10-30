"""Doc shot pages for the demo-video recorders (README/eval/masking/...).

Renders small local HTML pages from repo Markdown so the video can show
them without leaving the local server. Pure file work, no browser.
"""

import html
import re
from pathlib import Path

SHOTS = ("readme", "agent-eval", "masking", "eval", "tooling", "measured")

SHOT_CSS = (
    "body{font:16px/1.5 system-ui,sans-serif;color:#111;max-width:1120px;"
    "margin:0 auto;padding:1.2rem;background:#fff}"
    "table{border-collapse:collapse;margin:.6rem 0}"
    "th,td{border:1px solid #999;padding:.25rem .5rem;text-align:left;font-size:14px}"
    "h1{font-size:1.3rem}h2{font-size:1.1rem}.src{color:#555;font-size:13px}"
    "img{max-width:100%}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem}"
    "figure{margin:.4rem 0}figcaption{font-size:13px;color:#333}#shot-end{height:1px}"
)


def _inline(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def _blocks(lines: list[str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
            i += 1
            continue
        if line.startswith("# "):
            out.append(f"<h2>{_inline(line[2:])}</h2>")
            i += 1
            continue
        if line.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            rows = [r for r in rows if not all(re.fullmatch(r":?-{1,}:?", c or "-") for c in r)]
            head, body = rows[0], rows[1:]
            out.append(
                "<table><tr>"
                + "".join(f"<th>{_inline(c)}</th>" for c in head)
                + "</tr>"
                + "".join(
                    "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body
                )
                + "</table>"
            )
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(c)}</li>" for c in items) + "</ul>")
            continue
        out.append(f"<p>{_inline(line.strip())}</p>")
        i += 1
    return "\n".join(out)


def _drop_title(lines: list[str]) -> list[str]:
    out = list(lines)
    for i, line in enumerate(out):
        if not line.strip():
            continue
        if line.startswith("# "):
            del out[i]
        break
    return out


def _page(title: str, note: str, body: str) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>'
        f"<title>{title}</title><style>{SHOT_CSS}</style></head><body>"
        f"<h1>{title}</h1><p class=\"src\">{note}</p>"
        f'<main id="shot">{body}</main><p id="shot-end"></p></body></html>'
    )


def _write(shots_dir: Path, name: str, title: str, note: str, body: str) -> Path:
    path = shots_dir / f"shot_{name}.html"
    path.write_text(_page(title, note, body), encoding="utf-8")
    return path


def _eval_table(root: Path) -> str:
    lines = (root / "docs" / "eval.md").read_text(encoding="utf-8").split("\n")
    head = next(line for line in lines if line.startswith("| sample |"))
    cols = [c.strip() for c in head.strip().strip("|").split("|")]
    keep = ["sample", "total", "lines", "checks", "open_total", "open_lines", "open_checks"]
    idx = [cols.index(k) for k in keep]
    rows = []
    for line in lines[lines.index(head) + 1 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(cols) or set("".join(cells)) <= set("|-: "):
            continue
        if cells[cols.index("variant")] != "photo":
            continue
        rows.append([cells[i] for i in idx])
    return (
        "<table><tr>"
        + "".join(f"<th>{_inline(c)}</th>" for c in keep)
        + "</tr>"
        + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
        + "</table>"
    )


def build_shots(root: Path, shots_dir: Path) -> dict[str, Path]:
    """Render local doc shot pages from repo files. Pure file work, no browser."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    readme = (root / "README.md").read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(readme) if line.startswith("## Built vs"))
    stop = next(
        (i for i in range(start + 1, len(readme)) if readme[i].startswith("## ")),
        len(readme),
    )
    paths["readme"] = _write(
        shots_dir, "readme", "Built vs pre-existing", "Source: README.md",
        _blocks(readme[start + 1 : stop]),
    )
    agent = (root / "docs" / "agent-eval.md").read_text(encoding="utf-8").split("\n")
    paths["agent-eval"] = _write(
        shots_dir, "agent-eval", "Agent scorecard", "Source: docs/agent-eval.md",
        _blocks(_drop_title(agent)),
    )
    paths["eval"] = _write(
        shots_dir, "eval", "Reading accuracy, photo rows",
        "Hosted vs open, values verbatim. Full table: docs/eval.md", _eval_table(root),
    )
    pairs = [
        ("S2 receipt", "/samples/S2_seoul_worker_bronchitis/receipt_photo.jpg", "/docs/masking/S2_receipt_after.png"),
        ("S3 certificate", "/samples/S3_us_tourist_hip_fracture/medical_certificate_photo.jpg", "/docs/masking/S3_cert_after.png"),
    ]
    body = '<div class="pair">' + "".join(
        f'<figure><img src="{before}"/><figcaption>{label} — before (photo)</figcaption></figure>'
        f'<figure><img src="{after}"/><figcaption>{label} — after (masked)</figcaption></figure>'
        for label, before, after in pairs
    )
    paths["masking"] = _write(
        shots_dir, "masking", "Masking before / after", "Seals and signatures masked on a copy",
        body + "</div>",
    )
    log = (root / "docs" / "meta-tooling-log.md").read_text(encoding="utf-8").split("\n")
    paths["tooling"] = _write(
        shots_dir, "tooling", "Tooling log", "Source: docs/meta-tooling-log.md",
        _blocks(_drop_title(log)),
    )
    paths["measured"] = _write(
        shots_dir, "measured", "Measured", "Source: data/*.json via claimlens headline",
        _measured_block(root),
    )
    return paths


def _measured_block(root: Path) -> str:
    from claimlens import headline

    items = []
    for entry in headline.lines(root):
        mark = " class=\"gate-line\"" if "double-read gate" in entry["en"] else ""
        items.append(f"<li{mark}>{_inline(entry['en'])}</li>")
    foot = headline.scope_footnote(root)
    if foot is not None:
        items.append(f"<li>{_inline(foot['en'])}</li>")
    return "<ul>" + "".join(items) + "</ul>"

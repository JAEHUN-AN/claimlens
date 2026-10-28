"""Measured block: repo-data lines for README and the demo first screen.

Every line comes from a committed data file (or the fault registry);
lines without data are omitted. `claimlens headline` prints the block
and regenerates README + demo (+ the video eval caption) in one go.
"""

import json
import re
from pathlib import Path
from typing import Any

AFTER_NLESS = "Bill photo → checked claim, every number traceable."
AFTER_N = "Bill photo → checked claim in about {n} s, every number traceable."
AFTER_RE = re.compile(
    r"Bill photo → checked claim(?: in about (\d+) s)?, every number traceable\.")
MEASURED_START = "<!-- measured:start -->"
MEASURED_END = "<!-- measured:end -->"


def _newest(root: Path, pattern: str) -> Path | None:
    files = sorted((root / "data").glob(pattern))
    return files[-1] if files else None


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hard_sets(root: Path) -> dict[str, dict[str, int]] | None:
    """Single-read wrongs + simulated gate pairs, recomputed from cases."""
    from claimlens import hard_eval

    path = _newest(root, "hard_eval_*.json")
    if path is None:
        return None
    out = {}
    for name, entry in _read(path)["sets"].items():
        cases = entry["cases"]
        repeat = len(cases[0]["runs"]) if cases else 0
        summary = hard_eval.summarize(cases, repeat)
        gate = hard_eval.simulate_gate(cases)
        out[name] = {"repeat": repeat, "reached": summary["reached"],
                     "leaks": gate["leaks"], "stops": gate["stops"],
                     "pairs": gate["pairs"]}
    return out


def gate_line(root: Path) -> dict[str, str] | None:
    """Single read vs double-read gate; live numbers drop 'simulated'."""
    hard = _hard_sets(root)
    gate_path = _newest(root, "gate_live_*.json")
    live = _read(gate_path)["sets"].get("hard") if gate_path else None
    if hard is None and live is None:
        return None
    if live is not None and hard is not None:
        ref = hard["hard"]
        normal = _read(gate_path)["sets"].get("normal")
        en_normal = ko_normal = ""
        if normal is not None:
            en_normal = (f"; clean documents: {normal['leaks']} left, "
                         f"{normal['stops']}/{normal['pairs']} stopped")
            ko_normal = (f"; 깨끗한 서류: {normal['leaks']}건 유출, "
                         f"{normal['pairs']}쌍 중 {normal['stops']}쌍 중단")
        return {
            "en": (f"Hard documents ×{ref['repeat']} runs: {ref['reached']} wrong "
                   f"numbers left single read, {live['leaks']} with the double-read "
                   f"gate ({live['stops']}/{live['pairs']} pairs stopped, live gate)"
                   f"{en_normal}"),
            "ko": (f"어려운 서류 ×{ref['repeat']}회: 단일 판독 {ref['reached']}건 유출, "
                   f"이중 판독 관문 {live['leaks']}건"
                   f"({live['pairs']}쌍 중 {live['stops']}쌍 중단, 실시간 관문)"
                   f"{ko_normal}"),
        }
    if live is not None:
        rep = _read(gate_path)["repeat"]
        return {
            "en": (f"Live double-read gate: {live['leaks']} wrong numbers left over "
                   f"{live['pairs']} pairs ({live['stops']} stopped, ×{rep} runs)"),
            "ko": (f"실시간 이중 판독 관문: {live['pairs']}쌍 중 {live['leaks']}건 유출"
                   f"({live['stops']}쌍 중단, ×{rep}회)"),
        }
    ref = hard["hard"]
    return {
        "en": (f"Hard documents ×{ref['repeat']} runs: {ref['reached']} wrong numbers "
               f"left single read, {ref['leaks']} with the double-read gate "
               f"({ref['stops']}/{ref['pairs']} pairs stopped, simulated from "
               "recorded runs)"),
        "ko": (f"어려운 서류 ×{ref['repeat']}회: 단일 판독 {ref['reached']}건 유출, "
               f"이중 판독 관문 {ref['leaks']}건"
               f"({ref['pairs']}쌍 중 {ref['stops']}쌍 중단, 기록된 실행에서 시뮬레이션)"),
    }


def agent_line(root: Path) -> dict[str, str] | None:
    path = root / "data" / "agent_eval.json"
    if not path.exists():
        return None
    rows = _read(path)["rows"]
    passed = sum(1 for r in rows
                 if r["asked_when_needed"] and r["no_needless"] and r["no_invented"])
    return {
        "en": (f"Agent scorecard: {passed}/{len(rows)} (asks when it must, "
               "never invents a number)"),
        "ko": (f"에이전트 점수표: {len(rows)}개 중 {passed}개 통과"
               "(물을 때 묻고, 숫자를 지어내지 않음)"),
    }


def fault_line() -> dict[str, str]:
    from claimlens import faults

    count = len(faults.FAULTS)
    return {
        "en": f"{count} fault cases injected, no wrong number",
        "ko": f"장애 {count}건 주입, 틀린 숫자 0건",
    }


def load_line(root: Path) -> dict[str, str] | None:
    path = _newest(root, "load_*.json")
    if path is None:
        return None
    data = _read(path)
    p50 = f"{data['p50_s']:g}"
    p95 = f"{data['p95_s']:g}"
    cost = f"${data['mean_cost_usd']:.4f}"
    return {
        "en": (f"Per claim: p50 {p50} s, p95 {p95} s, {cost} "
               f"({data['runs']} concurrent live runs)"),
        "ko": (f"청구 1건당 p50 {p50}초, p95 {p95}초, {cost}"
               f"(동시 실시간 {data['runs']}회)"),
    }


def lines(root: Path) -> list[dict[str, str]]:
    """Measured lines in order; only lines with data appear."""
    out = []
    for entry in (gate_line(root), agent_line(root), fault_line(), load_line(root)):
        if entry is not None:
            out.append(entry)
    return out


def after_n(root: Path) -> str | None:
    """N for the After line: load p50, else None (N-less sentence stays)."""
    path = _newest(root, "load_*.json")
    if path is None:
        return None
    return f"{_read(path)['p50_s']:g}"


def render_readme_block(entries: list[dict[str, str]]) -> str:
    body = "\n".join(f"- {entry['en']}" for entry in entries)
    return f"{MEASURED_START}\n**Measured:**\n{body}\n{MEASURED_END}\n"


def apply_readme(readme: Path, root: Path) -> bool:
    """Rewrite the After sentence + Measured block; True when changed."""
    text = readme.read_text(encoding="utf-8")
    n = after_n(root)
    after = AFTER_N.format(n=n) if n else AFTER_NLESS
    updated = AFTER_RE.sub(after, text)
    block = render_readme_block(lines(root))
    if MEASURED_START in updated:
        pattern = re.compile(f"{re.escape(MEASURED_START)}.*?"
                             f"{re.escape(MEASURED_END)}\n?", re.DOTALL)
        updated = pattern.sub(block, updated)
    else:
        anchor = "Theme: Build for Your World.\n"
        updated = updated.replace(anchor, anchor + "\n" + block, 1)
    if updated != text:
        readme.write_text(updated, encoding="utf-8")
        return True
    return False


def eval_caption(root: Path) -> str:
    """Storyboard eval caption, built from the same gate numbers."""
    hard = _hard_sets(root)
    gate_path = _newest(root, "gate_live_*.json")
    live = _read(gate_path)["sets"].get("hard") if gate_path else None
    if hard is None and live is None:
        return "Hard documents, read three times: measured, not claimed."
    if hard is not None:
        ref = hard["hard"]
        leaks = live["leaks"] if live else ref["leaks"]
        tag = "live gate" if live else "simulated gate"
        return (f"Single read let {ref['reached']} wrong numbers leave; the "
                f"double-read gate leaves {leaks} ({tag}).")
    return (f"Live double-read gate: {live['leaks']} wrong numbers left over "
            f"{live['pairs']} pairs.")


def apply_storyboard(root: Path) -> bool:
    """Refresh the video eval caption; True when changed."""
    path = root / "tools" / "video" / "storyboard-main.json"
    board = json.loads(path.read_text(encoding="utf-8"))
    caption = eval_caption(root)
    for seg in board["segments"]:
        if seg["id"] == "eval" and seg["caption"] != caption:
            seg["caption"] = caption
            path.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            return True
    return False


def apply_model_table(readme: Path, root: Path) -> bool:
    """Rewrite the model table with the Measured column; True when changed."""
    from claimlens import meta_tiles

    raw = readme.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("| Step | Model |"))
    end = next(i for i, line in enumerate(lines)
               if "| Mask seals and signatures |" in line)
    table = meta_tiles.render_model_table(root)
    ending = "\r\n" if "\r\n" in raw else "\n"
    updated = lines[:start] + [row + ending for row in table.splitlines()] + lines[end + 1:]
    if updated == lines:
        return False
    readme.write_text("".join(updated), encoding="utf-8")
    return True


def apply_cards(root: Path) -> bool:
    """Rewrite the video Meta card tiles from the tile facts; True when changed."""
    import html as html_mod

    from claimlens import meta_tiles

    path = root / "tools" / "video" / "cards" / "cards.html"
    text = path.read_text(encoding="utf-8")
    tiles = []
    for tile in meta_tiles.tiles(root):
        step = html_mod.escape(tile["step"]["en"])
        fact = tile["fact"]
        extra = f"<span>{html_mod.escape(fact['en'])}</span>" if fact else ""
        tiles.append(f"<div class=\"tile\"><b>{tile['tool']}</b><span>{step}</span>"
                     f"{extra}</div>")
    section = ("<section class=\"card\" id=\"meta\">\n"
               "<p class=\"kicker\">Built with Meta tools</p>\n"
               "<div class=\"tiles\">\n" + "\n".join(tiles) + "\n</div>\n</section>")
    pattern = re.compile(r"<section class=\"card\" id=\"meta\">.*?</section>",
                         re.DOTALL)
    updated = pattern.sub(section, text, count=1)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def regen(root: Path) -> dict[str, bool]:
    """One command rebuilds README, demo, and the video eval caption + Meta card."""
    from claimlens.demo import export_demo

    changed = {
        "readme": apply_readme(root / "README.md", root),
        "model_table": apply_model_table(root / "README.md", root),
        "storyboard": apply_storyboard(root),
        "cards": apply_cards(root),
    }
    before = (root / "docs" / "demo.html").read_text(encoding="utf-8")
    export_demo(root / "docs" / "demo.html", root=root)
    after = (root / "docs" / "demo.html").read_text(encoding="utf-8")
    changed["demo"] = before != after
    return changed

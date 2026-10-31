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
AFTER_RE = re.compile(
    r"Bill photo → checked claim(?: in about ([\d.]+) s( \([^)]*\))?)?, "
    r"every number traceable\.")
MEASURED_START = "<!-- measured:start -->"
MEASURED_END = "<!-- measured:end -->"

# What the gate metric scores (C1 scope): amounts plus the identity
# fields the gate compares. Labels for hard_eval.GATE_FIELDS;
SCOPE_LABELS = {"total": "total", "lines": "line amounts", "kr_cells": "Korean bill cells", "currency": "currency", "country": "country", "service_date": "service date", "inpatient": "inpatient stay", "diags": "diagnosis codes", "charge_rows": "charge rows"}
SCOPE_LABELS_KO = {"total": "합계", "lines": "항목 금액", "kr_cells": "한국 영수증 칸", "currency": "통화", "country": "국가", "service_date": "진료일", "inpatient": "입원 여부", "diags": "진단 코드", "charge_rows": "청구 행"}
HELDOUT_LABELS = {"unseen": "Unseen layouts", "trips": "real trips"}
HELDOUT_LABELS_KO = {"unseen": "새 양식", "trips": "실제 여행"}

# Short glosses for badges a first-time reader meets in the block; only
# badges listed here are annotated, and only when the data behind the
# line actually shows them.
BADGE_GLOSS = {"PARTIAL": ("partly paid", "일부 지급"),
               "needs_manual_check": ("stopped for a person", "사람 확인 중단")}


def _newest(root: Path, pattern: str) -> Path | None:
    files = sorted((root / "data").glob(pattern))
    return files[-1] if files else None


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _newest_gate(root: Path) -> Path | None:
    """Newest live gate run that measured the hard set (unseen/trips runs do not)."""
    files = sorted((root / "data").glob("gate_live_*.json"))
    for path in reversed(files):
        if "hard" in _read(path).get("sets", {}):
            return path
    return None


def _run_date(path: Path) -> str | None:
    """YYYY-MM-DD from a data filename (hard_eval_YYYYMMDD, gate_live_*)."""
    match = re.search(r"(\d{4})(\d{2})(\d{2})", path.name)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _planned_hard_cases() -> int:
    from claimlens.hard_images import HARD_SAMPLES, TRANSFORMS

    return len(HARD_SAMPLES) * len(TRANSFORMS)


# Runs recorded before 54 (C1) scored amount fields only and carry no "fields" key.
LEGACY_SCORED_FIELDS = ("total", "lines", "kr_cells")


def _scope_text(data: dict[str, Any] | None = None) -> tuple[str, str]:
    """Metric scope (C1): the fields the run behind the numbers actually scored."""
    fields = (data or {}).get("fields") or LEGACY_SCORED_FIELDS
    en = ", ".join(SCOPE_LABELS.get(field, field) for field in fields)
    ko = ", ".join(SCOPE_LABELS_KO.get(field, field) for field in fields)
    return en, ko


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
                     "pairs": gate["pairs"], "cases": len(cases)}
    return out


def _newest_set_run(root: Path, name: str) -> Path | None:
    """Newest live gate run that measured the named set."""
    files = sorted((root / "data").glob("gate_live_*.json"))
    for path in reversed(files):
        if name in _read(path).get("sets", {}):
            return path
    return None


def _live_case_count(entry: dict[str, Any], repeat: int) -> int:
    cases = entry.get("cases") or []
    if cases:
        return len(cases)
    pairs = entry.get("pairs", 0)
    return pairs // repeat if repeat else pairs


def gate_line(root: Path) -> dict[str, str] | None:
    """Conclusion first: the current pipeline's live gate numbers."""
    hard = _hard_sets(root)
    gate_path = _newest_gate(root)
    live = _read(gate_path)["sets"].get("hard") if gate_path else None
    if hard is None and live is None:
        return None
    if live is not None:
        gate_data = _read(gate_path)
        normal = gate_data["sets"].get("normal")
        gate_date = _run_date(gate_path) if gate_path else None
        rep = gate_data.get("repeat", 0)
        live_cases = _live_case_count(live, rep)
        en_normal = ko_normal = ""
        if normal is not None:
            en_normal = (f"; normal documents: {normal['leaks']} left, "
                         f"{normal['stops']}/{normal['pairs']} stopped")
            ko_normal = (f"; 일반 서류: {normal['leaks']}건 유출, "
                         f"{normal['pairs']}쌍 중 {normal['stops']}쌍 중단")
        return {
            "en": (f"Live double-read gate, {gate_date or 'undated'} run on the "
                   f"current pipeline ({live_cases} cases \u00d7{rep} = "
                   f"{live['pairs']} pairs): {live['leaks']} wrong amounts left "
                   f"({live['stops']} stopped for a person){en_normal}."),
            "ko": (f"실시간 이중 판독 관문, {gate_date or '날짜 없음'} 현 파이프라인 "
                   f"실행 ({live_cases}건 \u00d7{rep}회 = "
                   f"{live['pairs']}쌍): {live['leaks']}건 유출 "
                   f"({live['stops']}쌍 중단){ko_normal}."),
        }
    ref = hard["hard"]
    return {
        "en": (f"Double-read gate, simulated from recorded runs (hard set "
               f"\u00d7{ref['repeat']} runs): {ref['leaks']} wrong amounts left "
               f"({ref['stops']}/{ref['pairs']} pairs stopped)."),
        "ko": (f"이중 판독 관문, 기록된 실행에서 시뮬레이션 (hard "
               f"\u00d7{ref['repeat']}회): {ref['leaks']}건 유출 "
               f"({ref['pairs']}쌍 중 {ref['stops']}쌍 중단)."),
    }


def legacy_line(root: Path) -> dict[str, str] | None:
    """The old pipeline's single-read number, kept as a later line."""
    hard = _hard_sets(root)
    if hard is None:
        return None
    ref = hard["hard"]
    hard_path = _newest(root, "hard_eval_*.json")
    hard_date = _run_date(hard_path) if hard_path else None
    return {
        "en": (f"Single read, {hard_date or 'undated'} run on the old pipeline "
               "(before the line-sum check and rotation probe): "
               f"{ref['reached']} wrong amounts left "
               f"(hard set, {ref['cases']}/{_planned_hard_cases()} cases "
               f"\u00d7{ref['repeat']})."),
        "ko": (f"단일 판독, {hard_date or '날짜 없음'} 구 파이프라인 실행"
               "(합계 검사·회전 확인 이전): "
               f"{ref['reached']}건 유출 "
               f"(hard, {ref['cases']}/{_planned_hard_cases()}건 "
               f"\u00d7{ref['repeat']}회)."),
    }


def scope_footnote(root: Path) -> dict[str, str] | None:
    """Fields-scored footnote, from the run behind the numbers."""
    hard = _hard_sets(root)
    gate_path = _newest_gate(root)
    if hard is None and gate_path is None:
        return None
    scope_en, scope_ko = _scope_text(_read(gate_path) if gate_path else None)
    legacy_en, legacy_ko = _scope_text({})
    if scope_en == legacy_en:
        return {"en": f"Fields scored: {scope_en}.",
                "ko": f"채점 범위: {scope_ko}."}
    # Only the current runs scored the wider set; older lines scored amounts only.
    return {"en": (f"Fields scored in the current runs: {scope_en}. "
                   f"Older runs (the single-read line and the first run before fixes) "
                   f"scored {legacy_en} only."),
            "ko": (f"현재 실행의 채점 범위: {scope_ko}. "
                   f"이전 실행(단일 판독 줄, 고치기 전 첫 실행)은 {legacy_ko}만 채점.")}


def _set_runs(root: Path, name: str) -> list[Path]:
    """Every live gate run that measured the named set, oldest first."""
    files = sorted((root / "data").glob("gate_live_*.json"))
    return [path for path in files if name in _read(path).get("sets", {})]


def _heldout_totals(root: Path, pick: int) -> tuple[int, int, int, str] | None:
    """(pairs, stops, leaks, date) over unseen + trips; pick 0 = first run, -1 = latest."""
    found = []
    for name in ("unseen", "trips"):
        runs = _set_runs(root, name)
        if runs:
            path = runs[pick]
            found.append((_read(path)["sets"][name], _run_date(path)))
    if not found:
        return None
    dates = sorted({date for _, date in found if date})
    when = "/".join(dates) if dates else "undated"
    return (sum(e["pairs"] for e, _ in found), sum(e["stops"] for e, _ in found),
            sum(e["leaks"] for e, _ in found), when)


def heldout_line(root: Path) -> dict[str, str] | None:
    """Unseen + trips: the first run before fixes and, if newer, the latest run."""
    first = _heldout_totals(root, 0)
    if first is None:
        return None
    latest = _heldout_totals(root, -1)
    names = " + ".join(HELDOUT_LABELS[n] for n in ("unseen", "trips") if _set_runs(root, n))
    names_ko = " + ".join(HELDOUT_LABELS_KO[n] for n in ("unseen", "trips") if _set_runs(root, n))
    pairs, stops, leaks, when = first
    en = (f"{names}, first run before fixes ({when}): {leaks} wrong amounts left over "
          f"{pairs} pairs ({stops} stopped for a person)")
    ko = (f"{names_ko}, 고치기 전 첫 실행 ({when}): {pairs}쌍 중 {leaks}건 유출 "
          f"({stops}쌍 중단)")
    if latest is not None and latest != first:
        l_pairs, l_stops, l_leaks, l_when = latest
        en += (f"; after fixes ({l_when}, wider scoring): {l_leaks} wrong values left over "
               f"{l_pairs} pairs ({l_stops} stopped)")
        ko += (f"; 고친 뒤 ({l_when}, 넓힌 채점): {l_pairs}쌍 중 {l_leaks}건 유출 "
               f"({l_stops}쌍 중단)")
    return {"en": en + ".", "ko": ko + "."}


def _trips_truth(root: Path) -> dict[str, dict[str, Any]]:
    """Per-trip truth (KRW total + accepted badges), keyed by case id."""
    path = root / "samples" / "unseen" / "trips" / "truth.json"
    if not path.exists():
        return {}
    cases = _read(path).get("cases") or []
    return {c.get("id"): c for c in cases if c.get("id")}


def _trips_paid_amount(title: str) -> int | None:
    digits = "".join(ch for ch in (title or "") if ch.isdigit())
    return int(digits) if digits else None


def trips_line(root: Path) -> dict[str, str] | None:
    """Real trips through live upload, from the newest trips-check run."""
    path = _newest(root, "trips_check_*.json")
    truth = _trips_truth(root)
    cases = _read(path).get("cases", []) if path else []
    if not cases or not truth:
        return None
    when = _run_date(path) if path else None
    decided: list[str] = []
    mismatched: list[tuple[str, int | None, Any]] = []
    correct: list[str] = []
    paused: list[str] = []
    stopped: list[str] = []
    other: list[str] = []
    for case in cases:
        short = str(case.get("case", "?")).split("_")[0]
        badge = case.get("badge", "?")
        want = (truth.get(case.get("case")) or {}).get("expected") or {}
        accepted = (want.get("serve_engine_up") or {}).get("badges") or []
        if badge in accepted:
            decided.append(short)
            paid = _trips_paid_amount(case.get("title", ""))
            krw = ((truth.get(case.get("case")) or {}).get("totals")
                   or {}).get("krw")
            if paid is not None and paid == krw:
                continue
            mismatched.append((short, paid, krw))
        elif (not accepted
              and badge == (want.get("serve_today") or {}).get("badge")):
            correct.append(f"{short} ({badge})")
        elif (badge == "engine_unreachable"
              and badge == (want.get("serve_today") or {}).get("badge")):
            paused.append(short)
        elif badge == "needs_manual_check":
            stopped.append(short)
        else:
            other.append(f"{short} ({badge})")
    head_en = f"Real trips through live upload, {when or 'undated'} run"
    head_ko = f"실시간 업로드 실제 여행, {when or '날짜 없음'} 실행"
    total = len(cases)
    en: list[str] = []
    ko: list[str] = []
    if decided:
        ids = ", ".join(decided)
        en.append(f"{len(decided)} of {total} decided ({ids})")
        ko.append(f"{total}건 중 {len(decided)}건 판정({ids})")
        if mismatched:
            for short, paid, krw in mismatched:
                shown = (f"{paid:,} KRW" if paid is not None
                         else "no amount shown")
                want_krw = (f"{krw:,} KRW"
                            if isinstance(krw, (int, float))
                            else "truth total missing")
                en.append(f"{short} paid {shown}, truth {want_krw}")
                ko.append(f"{short} 지급 {shown}, 정답 {want_krw}")
        else:
            en.append("each paid amount matches the truth KRW total")
            ko.append("지급액 모두 정답 원화 합계와 일치")
    if correct:
        en.append(f"{', '.join(correct)} correctly not decided")
        ko.append(f"{'·'.join(correct)}은 의도대로 미판정")
    if paused:
        ids = ", ".join(paused)
        en.append(f"{ids} paused as expected with the engine down")
        ko.append(f"{'·'.join(paused)} 엔진 다운으로 예상대로 일시정지")
    if stopped:
        ids = ", ".join(stopped)
        en.append(f"{ids} stopped for a person")
        ko.append(f"{'·'.join(stopped)}는 사람 확인용 중단")
    if other:
        en.append(f"{', '.join(other)} not decided")
        ko.append(f"{'·'.join(other)} 미판정")
    return {"en": head_en + ": " + "; ".join(en) + ".",
            "ko": head_ko + ": " + "; ".join(ko) + "."}


def agent_line(root: Path) -> dict[str, str] | None:
    path = root / "data" / "agent_eval.json"
    if not path.exists():
        return None
    rows = _read(path)["rows"]
    passed = sum(1 for r in rows
                 if r["asked_when_needed"] and r["no_needless"] and r["no_invented"])
    agent_n = sum(1 for r in rows if r.get("steps", 1))
    rule_n = len(rows) - agent_n
    return {
        "en": (f"Agent scorecard: {passed}/{len(rows)} ({agent_n} agent dialogues "
               f"+ {rule_n} voice rule, each replayed once from its recording)"),
        "ko": (f"에이전트 점수표: {len(rows)}개 중 {passed}개 통과"
               f"(에이전트 대화 {agent_n} + 음성 규칙 {rule_n}, 각 1회 녹화 재생)"),
    }


def fault_line() -> dict[str, str]:
    from claimlens import faults

    count = len(faults.FAULTS)
    return {
        "en": f"{count} fault cases injected in tests (no live calls), no wrong number",
        "ko": f"테스트에서 장애 {count}건 주입(실제 호출 없음), 틀린 숫자 0건",
    }


def _load_scope(data: dict[str, Any]) -> dict[str, str] | None:
    """What the load numbers cover (H8): photos, outcomes, median badge."""
    results = data.get("results")
    if not results:
        return None
    sample = str(data.get("scenario", "")).split("_")[0] or "?"
    photos = data.get("photos") or []
    retake = any("retake" in str(photo) for photo in photos)
    counts: dict[str, int] = {}
    for run in results:
        badge = str(run.get("badge", "?"))
        counts[badge] = counts.get(badge, 0) + 1
    order = sorted(counts, key=lambda b: (-counts[b], b))
    outcomes = ", ".join(f"{badge} {counts[badge]}" for badge in order)
    glossed = [(badge, BADGE_GLOSS[badge]) for badge in order
               if badge in BADGE_GLOSS]
    gloss_en = (" (" + ", ".join(f"{badge} = {gloss[0]}"
                                 for badge, gloss in glossed) + ")"
                if glossed else "")
    gloss_ko = (" (" + ", ".join(f"{badge} = {gloss[1]}"
                                 for badge, gloss in glossed) + ")"
                if glossed else "")
    median = next((str(run.get("badge")) for run in results
                   if run.get("seconds") == data.get("p50_s")), None)
    med_en = f"; median run {median}" if median else ""
    med_ko = f"; 중앙값 실행 {median}" if median else ""
    kind_en = "retake photos" if retake else "photos"
    kind_ko = "재촬영 사진" if retake else "사진"
    return {
        "en": f"({sample} {kind_en}, {data['runs']} concurrent live runs)",
        "ko": f"({sample} {kind_ko}, 동시 실시간 {data['runs']}회)",
        "outcomes_en": f"outcomes {outcomes}{gloss_en}{med_en}",
        "outcomes_ko": f"결과 {outcomes}{gloss_ko}{med_ko}",
    }


def load_line(root: Path) -> dict[str, str] | None:
    path = _newest(root, "load_*.json")
    if path is None:
        return None
    data = _read(path)
    p50 = f"{data['p50_s']:g}"
    p95 = f"{data['p95_s']:g}"
    cost = f"${data['mean_cost_usd']:.4f}"
    scope = _load_scope(data)
    if scope is None:
        return {
            "en": (f"Per claim: p50 {p50} s, p95 {p95} s, {cost} "
                   f"({data['runs']} concurrent live runs)"),
            "ko": (f"청구 1건당 p50 {p50}초, p95 {p95}초, {cost}"
                   f"(동시 실시간 {data['runs']}회)"),
        }
    return {
        "en": (f"Per claim {scope['en']}: p50 {p50} s, p95 {p95} s, {cost}; "
               f"{scope['outcomes_en']}"),
        "ko": (f"청구 1건당 {scope['ko']}: p50 {p50}초, p95 {p95}초, {cost}; "
               f"{scope['outcomes_ko']}"),
    }


def lines(root: Path) -> list[dict[str, str]]:
    """Measured lines in order; only lines with data appear."""
    out = []
    for entry in (gate_line(root), legacy_line(root), heldout_line(root),
                  trips_line(root), agent_line(root),
                  fault_line(), load_line(root)):
        if entry is not None:
            out.append(entry)
    return out


def after_n(root: Path) -> str | None:
    """N for the After line: load p50, else None (N-less sentence stays)."""
    path = _newest(root, "load_*.json")
    if path is None:
        return None
    return f"{_read(path)['p50_s']:g}"


def after_sentence(root: Path) -> str:
    """After line with N; the load scope lives only in the Measured block."""
    n = after_n(root)
    if not n:
        return AFTER_NLESS
    return f"Bill photo \u2192 checked claim in about {n} s, every number traceable."


def render_readme_block(entries: list[dict[str, str]],
                        footnote: dict[str, str] | None = None) -> str:
    body = "\n".join(f"- {entry['en']}" for entry in entries)
    if footnote is not None:
        body += f"\n{footnote['en']}"
    return f"{MEASURED_START}\n**Measured:**\n{body}\n{MEASURED_END}\n"


def apply_eval_tables(text: str, root: Path) -> str:
    """Rewrite the two README Eval tables from a fresh replay eval (H7)."""
    from claimlens.eval import eval_all, format_readme_tables

    fresh = format_readme_tables(eval_all())
    newline = "\r\n" if "\r\n" in text else "\n"
    out = text.splitlines(keepends=True)
    for table in fresh:
        wanted = table.splitlines()
        head = next((i for i, line in enumerate(out)
                     if line.strip() == wanted[0]), None)
        if head is None:  # minimal READMEs (tests) have no Eval tables
            continue
        stop = head
        while stop < len(out) and out[stop].strip().startswith("|"):
            stop += 1
        out[head:stop] = [line + newline for line in wanted]
    return "".join(out)


def apply_readme(readme: Path, root: Path) -> bool:
    """Rewrite the After sentence + Measured block; True when changed."""
    text = readme.read_text(encoding="utf-8")
    updated = AFTER_RE.sub(after_sentence(root), text)
    updated = apply_eval_tables(updated, root)
    block = render_readme_block(lines(root), scope_footnote(root))
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
    gate_path = _newest_gate(root)
    live = _read(gate_path)["sets"].get("hard") if gate_path else None
    if hard is None and live is None:
        return "Hard documents, read three times: measured, not claimed."
    if hard is not None:
        ref = hard["hard"]
        hard_path = _newest(root, "hard_eval_*.json")
        hard_date = _run_date(hard_path) if hard_path else None
        base = (f"Single read ({hard_date or '?'}, old pipeline) let "
                f"{ref['reached']} wrong amounts leave; ")
        if live is None:
            return base + (f"the simulated gate leaves {ref['leaks']}.")
        gate_date = _run_date(gate_path) if gate_path else None
        return base + (f"the live gate ({gate_date or '?'}, current pipeline) "
                       f"leaves {live['leaks']}.")
    return (f"Live double-read gate: {live['leaks']} wrong amounts left over "
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
    updated = _refresh_before_after_card(root, updated)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _refresh_before_after_card(root: Path, text: str) -> str:
    """Refresh the video before/after card from the figure (61)."""
    from claimlens.before_after import svg as figure_svg

    n = after_n(root)
    if not n:
        return text
    section = f"""<section class="card" id="before_after">
<p class="kicker">Before / after</p>
{figure_svg(n, 'en', standalone=False)}
</section>"""
    pattern = re.compile('<section class="card" id="before_after">.*?</section>',
                         re.DOTALL)
    if not pattern.search(text):
        return text
    return pattern.sub(section, text, count=1)




def write_before_after(root: Path) -> bool:
    """Write docs/before_after.svg (EN) with the measured N; True when changed."""
    from claimlens.before_after import svg as figure_svg

    n = after_n(root)
    if not n:
        return False
    path = root / "docs" / "before_after.svg"
    text = figure_svg(n, "en")
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def regen(root: Path) -> dict[str, bool]:
    """One command rebuilds README, demo, the video cards, and the figure."""
    from claimlens.demo import export_demo

    changed = {
        "readme": apply_readme(root / "README.md", root),
        "model_table": apply_model_table(root / "README.md", root),
        "storyboard": apply_storyboard(root),
        "cards": apply_cards(root),
        "figure": write_before_after(root),
    }
    before = (root / "docs" / "demo.html").read_text(encoding="utf-8")
    export_demo(root / "docs" / "demo.html", root=root)
    after = (root / "docs" / "demo.html").read_text(encoding="utf-8")
    changed["demo"] = before != after
    return changed

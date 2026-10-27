"""KCD to WHO ICD-10 to ICD-10-CM conversion (SPEC 5.5). Deterministic rules.

Rule-based conversion only, not an official mapping. Full WHO-terminal
validation needs the WHO 2019 terminal list (not shipped); the two cases SPEC
names explicitly (I84, K35) are handled below.
"""

import re
from typing import Any

DISCLAIMER = "Rule-based code conversion, not an official mapping."

FRACTURE_FAMILIES = {
    "S02",
    "S12",
    "S22",
    "S32",
    "S42",
    "S52",
    "S62",
    "S72",
    "S82",
    "S92",
    "T02",
    "T08",
    "T10",
    "T12",
}

KNOWN_PITFALLS = {
    "S72.120": {
        "kcd_means": "intertrochanteric fracture, closed",
        "cm_prefix": "S72.12x",
        "cm_means": "lesser trochanter fracture",
    },
    "S32.030": {
        "kcd_means": "L2 fracture, closed",
        "cm_prefix": "S32.030",
        "cm_means": "L3 wedge compression fracture",
    },
    "S32.020": {
        "kcd_means": "L1 fracture, closed",
        "cm_prefix": "S32.020",
        "cm_means": "L2 wedge compression fracture",
    },
}

_CODE_RE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9]{1,3})?$")


def normalize_kcd(code: str) -> str:
    """Uppercase and dot form: S72120 becomes S72.120. Raises on garbage."""
    text = code.strip().upper()
    if "." not in text and re.fullmatch(r"[A-Z][0-9]{3,5}", text):
        text = text[:3] + "." + text[3:]
    if not _CODE_RE.match(text):
        raise ValueError(f"Not a KCD-shaped code: {code!r}.")
    return text


def kcd_edition(service_date: str | None) -> str:
    """KCD-9 from 2026-01-01 on; before that KCD-8 (lift table not shipped)."""
    if service_date is None:
        return "KCD-9 (assumed)"
    try:
        year, month, day = (int(p) for p in service_date.strip().split("-"))
        dated = year * 10000 + month * 100 + day
    except (ValueError, TypeError, AttributeError):
        return "KCD-9 (assumed)"
    return "KCD-9" if dated >= 20260101 else "KCD-8"


def is_han_u_code(code: str) -> bool:
    """Korean-medicine U codes share numbers with WHO emergency codes."""
    text = normalize_kcd(code)
    if not text.startswith("U"):
        return False
    major = int(text[1:3])
    return (20 <= major <= 33) or (50 <= major <= 79) or (95 <= major <= 98)


def fracture_attribute(code: str) -> str | None:
    """Closed/open from the 6th digit of KCD-9 fracture codes (0/1)."""
    text = normalize_kcd(code)
    bare = text.replace(".", "")
    if len(bare) != 6 or bare[:3] not in FRACTURE_FAMILIES:
        return None
    if bare.endswith("0"):
        return "closed"
    if bare.endswith("1"):
        return "open"
    return None


def who_from_kcd(code: str) -> tuple[str, list[str]]:
    """Truncate to the WHO 4-character code; returns (code, notes)."""
    text = normalize_kcd(code)
    head, dot, tail = text.partition(".")
    who = f"{head}.{tail[0]}" if dot and tail else head
    notes: list[str] = []
    if who.startswith("I84"):
        # Hemorrhoids moved chapters but the subdivisions do not correspond,
        # so only the bare category crosses over.
        dropped = who[3:]
        who = "K64"
        notes.append("I84 moved to K64 in WHO.")
        if dropped:
            notes.append("subdivision must be re-coded from the certificate")
    if who == "K35" or who.startswith("K35."):
        suffix = who[4:] if who.startswith("K35.") else ""
        if suffix not in ("2", "3", "8"):
            notes.append("K35 is terminal in WHO 2019 only as K35.2/.3/.8.")
    return who, notes


def pitfall_warning(code: str) -> dict[str, str] | None:
    """Warn when a prefix match into CM would give a different condition."""
    text = normalize_kcd(code)
    hit = KNOWN_PITFALLS.get(text)
    if hit is None:
        return None
    return {
        "kcd": text,
        "kcd_means": hit["kcd_means"],
        "cm_prefix": hit["cm_prefix"],
        "cm_means": hit["cm_means"],
        "warning": (
            f"Do not match {text} ({hit['kcd_means']}) to ICD-10-CM by prefix: "
            f"{hit['cm_prefix']} means {hit['cm_means']}."
        ),
    }


def cm_candidates(who: str, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    """CM candidates with FY2027 defaults; S72.1 family has shipped rules."""
    facts = facts or {}
    out: dict[str, Any] = {
        "candidates": [],
        "chosen": None,
        "questions": [],
        "disclaimer": DISCLAIMER,
    }
    if who != "S72.1":
        out["note"] = f"No CM narrowing rule shipped for {who}."
        return out
    laterality = (facts.get("laterality") or "").lower()
    open_closed = (facts.get("open_closed") or facts.get("fracture") or "").lower()
    if open_closed not in ("open", "closed"):
        open_closed = "closed"
    displaced = facts.get("displaced", True) is not False
    encounter = (facts.get("encounter") or "initial").lower()
    sixth = {"right": "1", "left": "2"}.get(laterality, "3")
    if not displaced:
        sixth = {"1": "4", "2": "5", "3": "6"}[sixth]
    if encounter.startswith("subsequent"):
        seventh = "D"
    elif open_closed == "open":
        seventh = "B"
    else:
        seventh = "A"
    chosen = f"S72.14{sixth}{seventh}"
    out["candidates"] = [chosen]
    out["chosen"] = chosen
    if laterality not in ("right", "left"):
        out["questions"].append("Which side (right/left)? Unspecified codes to ...3.")
    if facts.get("displaced") is None:
        out["questions"].append("Displaced or nondisplaced? Defaults to displaced.")
    if open_closed == "open" and encounter.startswith("initial"):
        out["questions"].append("Open fracture: Gustilo type? B covers I/II, C covers III.")
    return out


def convert_diagnosis(
    kcd_code: str,
    service_date: str | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full pipeline: KCD to WHO plus attribute, CM, and pitfall warning."""
    text = normalize_kcd(kcd_code)
    result: dict[str, Any] = {
        "kcd": text,
        "edition": kcd_edition(service_date),
        "disclaimer": DISCLAIMER,
    }
    if is_han_u_code(text):
        result.update({"unconvertible": True, "who": None, "attribute": None})
        result["note"] = "U code: cannot convert to an international code."
        result["cm"] = None
        result["pitfall"] = None
        return result
    who, notes = who_from_kcd(text)
    result.update(
        {
            "unconvertible": False,
            "who": who,
            "attribute": fracture_attribute(text),
            "notes": notes,
        }
    )
    merged_facts = dict(facts or {})
    if result["attribute"] and "open_closed" not in merged_facts:
        merged_facts["open_closed"] = result["attribute"]
    result["cm"] = cm_candidates(who, merged_facts)
    result["pitfall"] = pitfall_warning(text)
    return result

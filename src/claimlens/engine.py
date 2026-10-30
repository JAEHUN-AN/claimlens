"""Adjudication through the pinned pre-existing engine (SPEC 3.3).

Only callers that already passed eligibility reach the engine: Korean
travellers treated abroad, or inbound cases with `nhi_member`. Readings come
from the pinned replay cache so engine inputs are deterministic.
"""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ENGINE_LABEL = "clausegraph@claimlens-base-20261026 (pre-existing open-source engine, pinned)"

CATEGORY_KO = {
    "consultation": "진찰",
    "emergency_fee": "응급실 진료",
    "imaging": "영상 검사",
    "lab": "검체 검사",
    "procedure": "처치",
    "surgery": "수술",
    "medication": "약제",
    "vaccination": "예방접종",
    "device_purchase": "진료재료의 구입",
    "health_checkup": "건강검진",
    "room": "병실",
    "admin_fee": "증명료",
    "other": "기타",
}


def samples_dir() -> Path:
    return Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples"))


def engine_cache_path(sample_id: str, variant: str) -> Path:
    root = Path(os.environ.get("CLAIMLENS_ENGINE_CACHE_DIR", "cache/engine"))
    return root / f"{sample_id}_{variant}.json"


def load_scenarios() -> tuple[dict[str, dict[str, Any]], set[str]]:
    """All scenarios plus the ids that came from the inbound file."""
    found: dict[str, dict[str, Any]] = {}
    inbound: set[str] = set()
    base = samples_dir()
    for name in ("scenarios.json", "scenarios_inbound.json"):
        path = base / name
        if not path.exists():
            continue
        for sc in json.loads(path.read_text(encoding="utf-8")).get("scenarios", []):
            found[sc["id"]] = sc
            if name == "scenarios_inbound.json":
                inbound.add(sc["id"])
    return found, inbound


def fx_rates() -> dict[str, float]:
    data = json.loads((samples_dir() / "fx_demo.json").read_text(encoding="utf-8"))
    return {k: float(v) for k, v in data["rates"].items()}


def to_krw(amount: float, currency: str) -> int:
    if currency == "KRW":
        return round(amount)
    rates = fx_rates()
    if currency not in rates:
        raise ValueError(f"No demo FX rate for {currency}; refusing to invent one.")
    return round(amount * rates[currency])


def build_narrative(line_items: list[dict[str, Any]]) -> str:
    """One short paragraph from the closed category table (SPEC 3.1)."""
    seen: list[str] = []
    for item in line_items:
        label = CATEGORY_KO.get(item.get("category", "other"), "기타")
        if label not in seen:
            seen.append(label)
    return ", ".join(seen)


def copay_rate_from_bill(bill: dict[str, Any] | None) -> float | None:
    """Copay rate is 1 divided by (1 + 2); None when it cannot be formed."""
    if not bill:
        return None
    c1, c2 = bill.get("cell_1"), bill.get("cell_2")
    if not isinstance(c1, int) or not isinstance(c2, int):
        return None
    if c1 <= 0 or c2 < 0 or c1 + c2 <= 0:
        return None
    return c1 / (c1 + c2)


def replay_reading(sample_id: str, variant: str) -> dict[str, Any]:
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.providers.replay import ReplayProvider
    from claimlens.reader import reading_schema, resolve_sample_images

    images = resolve_sample_images(samples_dir() / sample_id, variant)
    provider = ReplayProvider()
    return provider.read_documents(images, READING_INSTRUCTIONS, reading_schema())


def product_catalog() -> dict[str, dict[str, Any]]:
    """H2: insurable products by name, with the demo terms for each.

    Built from the scenario policies (first occurrence wins). The engine
    prices a live claim against the product the USER chose, never against
    a declared scenario's policy; the demo terms are shown on screen.
    """
    scenarios, _ = load_scenarios()
    catalog: dict[str, dict[str, Any]] = {}
    for sample_id in sorted(scenarios):
        policy = scenarios[sample_id].get("policy") or {}
        name = policy.get("product", "")
        if name and name not in catalog:
            catalog[name] = {
                "enrolled_on": policy.get("enrolled_on", ""),
                "sum_insured_krw": policy.get("sum_insured_krw"),
                "paid_so_far_krw": policy.get("paid_so_far_krw", 0),
            }
    return catalog


def _inputs_for_policy(claim_id: str, product: str, policy: dict[str, Any],
                       reading: dict[str, Any]) -> dict[str, Any]:
    """Structured engine arguments (SPEC 3.3) for one reading."""
    docs = reading["documents"]
    receipt, cert = docs[0], docs[1]
    bill = receipt.get("kr_bill")
    total = receipt.get("total_amount")
    if total is None:
        raise ValueError(f"{claim_id}: receipt has no total; cannot adjudicate.")
    codes = tuple(d["code"] for d in cert.get("diagnoses", []) if d.get("code"))
    rate = copay_rate_from_bill(bill)
    return {
        "claim_id": claim_id,
        "product": product,
        "enrolled_on": policy.get("enrolled_on", ""),
        "narrative": build_narrative(receipt.get("line_items", [])),
        "diagnosis_codes": list(codes),
        "claimed_amount_krw": to_krw(float(total), receipt.get("currency", "")),
        "treated_abroad": receipt.get("country", "") != "KR",
        "sum_insured": policy.get("sum_insured_krw"),
        "paid_this_year": int(policy.get("paid_so_far_krw", 0)),
        "institution": bill.get("institution_type") if bill else None,
        "copay_rate": rate,
    }


def build_inputs(sample_id: str, variant: str, reading: dict[str, Any]) -> dict[str, Any]:
    """Structured engine arguments (SPEC 3.3) for one scenario reading."""
    scenarios, _ = load_scenarios()
    policy = scenarios[sample_id].get("policy") or {}
    return _inputs_for_policy(f"{sample_id}-{variant}", policy.get("product", ""),
                              policy, reading)


def build_inputs_for_product(product: str, claim_id: str,
                             reading: dict[str, Any]) -> dict[str, Any]:
    """H2: engine arguments against the user's chosen product (demo terms)."""
    catalog = product_catalog()
    if product not in catalog:
        raise ValueError(f"Unknown product {product!r}; choose one of "
                         f"{sorted(catalog)}.")
    return _inputs_for_policy(claim_id, product, catalog[product], reading)


@contextmanager
def engine_working_dir():
    """Run the engine from its data root; the engine reads data/ relatively."""
    load_dotenv()
    root = os.environ.get("CLAUSEGRAPH_DATA_ROOT", "")
    if not root:
        raise RuntimeError("CLAUSEGRAPH_DATA_ROOT is not set; cannot run the engine.")
    previous = os.getcwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(previous)


def live_adjudicate(inputs: dict[str, Any]) -> dict[str, Any]:
    """Call extract_claim + adjudicate once. Needs Neo4j and the data root."""
    from datetime import date

    from clausegraph.access import Principal
    from clausegraph.agents.extract import (
        extract_claim,
        parse_copay_rate,
        parse_institution,
    )
    from clausegraph.agents.models import ClaimHistory
    from clausegraph.agents.orchestrator import adjudicate
    from neo4j import GraphDatabase

    load_dotenv()
    year, month, day = (int(p) for p in inputs["enrolled_on"].split("-"))
    institution = inputs["institution"]
    institution = parse_institution(institution) if institution else None
    rate = inputs["copay_rate"]
    rate = parse_copay_rate(rate) if rate is not None else None
    with engine_working_dir():
        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI"),
            auth=(os.environ.get("NEO4J_USER"), os.environ.get("NEO4J_PASSWORD")),
        )
        try:
            claim = extract_claim(
                inputs["claim_id"],
                inputs["product"],
                date(year, month, day),
                inputs["narrative"],
                history=ClaimHistory(paid_this_year=inputs["paid_this_year"]),
                diagnosis_codes=tuple(inputs["diagnosis_codes"]),
                claimed_amount=inputs["claimed_amount_krw"],
                sum_insured=inputs["sum_insured"],
                treated_abroad=inputs["treated_abroad"],
                institution=institution,
                copay_rate=rate,
            )
            principal = Principal(name="claimlens", products=frozenset({inputs["product"]}))
            result = adjudicate(driver, claim, principal=principal)
        finally:
            driver.close()
    return result.model_dump(mode="json")


def store_result(sample_id: str, variant: str, inputs: dict[str, Any], output: dict[str, Any]) -> Path:
    path = engine_cache_path(sample_id, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine": ENGINE_LABEL,
        "inputs": inputs,
        "output": output,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_result(sample_id: str, variant: str, inputs: dict[str, Any]) -> dict[str, Any]:
    path = engine_cache_path(sample_id, variant)
    if not path.exists():
        raise LookupError(f"No recorded engine output at {path}; run live once to record it.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("inputs") != inputs:
        raise LookupError(
            f"Engine inputs for {sample_id} {variant} changed since recording; "
            "re-record live instead of reusing a stale decision."
        )
    return payload["output"]


def adjudicate_sample(sample_id: str, variant: str = "photo") -> dict[str, Any]:
    """Eligibility gate, then the engine (live) or its recording (replay)."""
    from claimlens.eligibility import check_eligibility, service_date_of

    scenarios, inbound = load_scenarios()
    reading = replay_reading(sample_id, variant)
    inputs = build_inputs(sample_id, variant, reading)
    envelope: dict[str, Any] = {
        "sample": sample_id,
        "variant": variant,
        "engine": ENGINE_LABEL,
        "inputs": inputs,
    }
    if sample_id in inbound:
        service_date = service_date_of(reading["documents"][0])
        eligibility = check_eligibility(scenarios[sample_id]["person"], service_date)
        envelope["eligibility"] = eligibility
        if eligibility["outcome"] != "nhi_member":
            envelope["sent"] = False
            envelope["output"] = None
            return envelope
    envelope["sent"] = True
    load_dotenv()
    if os.environ.get("CLAIMLENS_PROVIDER", "meta").lower() == "replay":
        envelope["provider"] = "replay"
        envelope["output"] = load_result(sample_id, variant, inputs)
        return envelope
    envelope["provider"] = "engine-live"
    envelope["output"] = live_adjudicate(inputs)
    store_result(sample_id, variant, inputs, envelope["output"])
    return envelope

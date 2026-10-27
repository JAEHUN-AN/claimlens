"""Provenance tests: every payload number reference resolves to a record."""

from claimlens.demo import agent_scene_payload, scene_payload


def collect_refs(node, found):
    if isinstance(node, dict):
        if "prov" in node and "v" in node:
            found.add(node["prov"])
        for value in node.values():
            collect_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            collect_refs(value, found)


def check_scene(payload):
    records = payload.get("provenance") or {}
    assert records
    refs: set[str] = set()
    collect_refs({k: v for k, v in payload.items() if k != "provenance"}, refs)
    assert refs
    missing = refs - set(records)
    assert not missing, f"missing records: {missing}"
    for rid, record in records.items():
        assert record["kind"] in ("reading", "check", "clausegraph", "rule", "user"), rid
        for op in record.get("operands") or []:
            assert op in records, f"operand {op} of {rid}"


def test_s2_numbers_have_provenance(tmp_path):
    payload = scene_payload("S2_seoul_worker_bronchitis", "S2", tmp_path / "demo.html")
    check_scene(payload)
    records = payload["provenance"]
    assert records["s2-amount"]["kind"] == "clausegraph"
    for term in ("s2-ded0", "s2-ded1", "s2-ded2", "s2-ded-ours", "s2-c1", "s2-c2", "s2-copay"):
        assert term in records["s2-amount"]["operands"]
    assert records["s2-copay"]["formula"] == "① ÷ (① + ②)"


def test_s3_numbers_have_provenance(tmp_path):
    payload = scene_payload("S3_us_tourist_hip_fracture", "S3", tmp_path / "demo.html")
    check_scene(payload)
    records = payload["provenance"]
    assert records["s3-pack-total"]["kind"] == "reading"
    assert records["s3-line-0"]["formula"].count("+") == 3
    assert records["s3-kcd"]["kind"] == "reading"
    assert records["s3-who"]["kind"] == "rule"


def test_agent_numbers_have_provenance(tmp_path):
    payload = agent_scene_payload(tmp_path / "demo.html")
    check_scene(payload)
    records = payload["provenance"]
    kinds = {r["kind"] for r in records.values()}
    assert {"reading", "check", "clausegraph", "user"} <= kinds

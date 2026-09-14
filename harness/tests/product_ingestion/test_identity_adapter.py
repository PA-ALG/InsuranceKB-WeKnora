from __future__ import annotations

import importlib
import json
from copy import deepcopy

import pytest


def fixture_response():
    evidence = [
        {
            "evidence_ref": "class",
            "locator_ref": "loc_" + "a" * 64,
            "entity_ref": "product",
            "purpose": "classification",
            "field_key": None,
        },
        {
            "evidence_ref": "name",
            "locator_ref": "loc_" + "a" * 64,
            "entity_ref": "product",
            "purpose": "name",
            "field_key": None,
        },
        {
            "evidence_ref": "version",
            "locator_ref": "loc_" + "a" * 64,
            "entity_ref": "product",
            "purpose": "version",
            "field_key": None,
        },
    ]
    response = {
        "contract": "g3-batch-resolution-semantic-references.local.v1",
        "materials": [
            {
                "material_id": "terms",
                "material_role": "terms",
                "material_role_evidence_refs": [],
                "evidence": evidence,
                "entities": [
                    {
                        "entity_ref": "product",
                        "issuer": None,
                        "name": "平安测试医疗保险",
                        "product_code": None,
                        "version_label": "2026",
                        "filing_or_registration": {
                            "kind": "filing_number",
                            "value": "平安〔2025〕168号",
                        },
                        "identity_confidence": "1.000000",
                        "identity_evidence_refs": ["class", "name", "version"],
                        "labels": [
                            {
                                "taxonomy_label": "medical_insurance",
                                "confidence": "1.000000",
                                "evidence_refs": ["class"],
                            }
                        ],
                        "primary_label": "medical_insurance",
                        "valid_from": None,
                        "valid_through": None,
                    }
                ],
            }
        ],
    }
    context = {
        "materials": [
            {
                "material_id": "terms",
                "blocks": [
                    {
                        "block_ref": "first",
                        "page_number": 1,
                        "text": "平安测试医疗保险2026\n平安〔2025〕168号",
                        "evidence_locator_refs": [
                            {"locator_ref": "loc_" + "a" * 64, "quote": "平安测试医疗保险2026"},
                            {"locator_ref": "loc_" + "b" * 64, "quote": "平安〔2025〕168号"},
                        ],
                    }
                ],
            }
        ]
    }
    return response, context


def adapter():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.identity_adapter")
    except ModuleNotFoundError:
        pytest.fail("deterministic identity evidence adapter missing")


def test_redundant_classification_and_misdirected_filing_keep_original():
    obj, context = fixture_response()
    raw = json.dumps(obj, ensure_ascii=False).encode()
    before = deepcopy(obj)
    result = adapter().adapt_identity_response(raw, context)
    derived = json.loads(result.semantic_raw)
    assert obj == before
    entity = derived["materials"][0]["entities"][0]
    assert "class" not in entity["identity_evidence_refs"]
    assert derived["materials"][0]["evidence"][:2] != []
    assert entity["issuer"] is None
    assert (
        entity["filing_or_registration"]
        == before["materials"][0]["entities"][0]["filing_or_registration"]
    )
    assert any(
        e["locator_ref"] == "loc_" + "b" * 64 and e["purpose"] == "version"
        for e in derived["materials"][0]["evidence"]
    )
    assert result.audit["changes"]


def test_absent_filing_cannot_be_invented_or_treated_as_product_code():
    obj, context = fixture_response()
    context["materials"][0]["blocks"][0]["evidence_locator_refs"].pop()
    with pytest.raises(ValueError, match="lacks offered source evidence"):
        adapter().adapt_identity_response(json.dumps(obj).encode(), context)


def test_auxiliary_offered_page_can_support_filing_without_new_source():
    obj, context = fixture_response()
    block = context["materials"][0]["blocks"][0]
    filing = block["evidence_locator_refs"].pop()
    context["materials"][0]["blocks"].append(
        {
            "block_ref": "later",
            "page_number": 2,
            "text": filing["quote"],
            "evidence_locator_refs": [filing],
        }
    )
    result = adapter().adapt_identity_response(json.dumps(obj).encode(), context)
    assert any(c.get("locator_ref") == filing["locator_ref"] for c in result.audit["changes"])


def test_repeated_exact_filing_uses_stable_offered_locator_and_keeps_all_original_evidence():
    obj, context = fixture_response()
    block = context["materials"][0]["blocks"][0]
    block["evidence_locator_refs"].append(
        {"locator_ref": "loc_" + "c" * 64, "quote": "平安〔2025〕168号"}
    )
    raw = json.dumps(obj).encode()
    result = adapter().adapt_identity_response(raw, context)
    derived = json.loads(result.semantic_raw)
    original = {e["evidence_ref"]: e for e in obj["materials"][0]["evidence"]}
    actual = {e["evidence_ref"]: e for e in derived["materials"][0]["evidence"]}
    assert all(actual[key] == value for key, value in original.items())
    links = [
        c for c in result.audit["changes"] if c["reason"] == "ASSERTED_VALUE_OFFERED_EVIDENCE_LINK"
    ]
    assert links[0]["locator_ref"] == "loc_" + "b" * 64
    assert adapter().adapt_identity_response(raw, context) == result


def test_foreign_locator_rejected_before_adaptation():
    obj, context = fixture_response()
    obj["materials"][0]["evidence"][0]["locator_ref"] = "loc_" + "f" * 64
    with pytest.raises(ValueError, match="outside offered"):
        adapter().adapt_identity_response(json.dumps(obj).encode(), context)


@pytest.mark.parametrize("already_linked", [False, True])
def test_product_code_occurrence_cannot_support_same_number_as_filing(already_linked):
    obj, context = fixture_response()
    entity = obj["materials"][0]["entities"][0]
    entity["product_code"] = "5011"
    entity["filing_or_registration"]["value"] = "5011"
    context["materials"][0]["blocks"][0]["evidence_locator_refs"][1]["quote"] = "产品代码：5011"
    if already_linked:
        obj["materials"][0]["evidence"].append(
            {
                "evidence_ref": "bad-filing",
                "locator_ref": "loc_" + "b" * 64,
                "entity_ref": "product",
                "purpose": "version",
                "field_key": None,
            }
        )
        entity["identity_evidence_refs"] = sorted([*entity["identity_evidence_refs"], "bad-filing"])
    with pytest.raises(ValueError, match="filing evidence type"):
        adapter().adapt_identity_response(json.dumps(obj).encode(), context)


@pytest.mark.parametrize(
    "quote, accepted",
    [
        ("产品代码5011，备案编号9999", False),
        ("产品代码5011，备案编号50112", False),
        ("产品代码5011，备案编号5011", True),
    ],
)
def test_same_number_requires_its_own_explicit_filing_occurrence(quote, accepted):
    obj, context = fixture_response()
    entity = obj["materials"][0]["entities"][0]
    entity["product_code"] = "5011"
    entity["filing_or_registration"]["value"] = "5011"
    context["materials"][0]["blocks"][0]["evidence_locator_refs"][1]["quote"] = quote
    if not accepted:
        with pytest.raises(ValueError, match="filing evidence type"):
            adapter().adapt_identity_response(json.dumps(obj).encode(), context)
    else:
        result = adapter().adapt_identity_response(json.dumps(obj).encode(), context)
        assert (
            json.loads(result.semantic_raw)["materials"][0]["entities"][0][
                "filing_or_registration"
            ]["value"]
            == "5011"
        )

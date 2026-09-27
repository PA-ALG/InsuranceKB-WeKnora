"""Deterministic, audited identity-reference adaptation; never mutate model raw."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import _normalized
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3SemanticReferenceResponseV1,
)

from .identity import validate_identity_offered_response


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _filing_support(value: str, kind: str, quote: str, product_code: str | None) -> bool:
    """A code occurrence is not evidence of the separately typed filing anchor."""
    observed, text = _normalized(value), _normalized(quote)
    label = r"(?:备案|报备)" if kind == "filing_number" else r"(?:登记|注册)"
    if re.search(
        label + r"(?:编号|号码|号)?[:：]?" + re.escape(observed) + r"(?![0-9A-Za-z])", text
    ):
        return True
    if (product_code is not None and observed == _normalized(product_code)) or re.search(
        r"(?:产品|险种)(?:代码|编码)[:：]?" + re.escape(observed), text
    ):
        return False
    # Complete observed Chinese filing references carry their own type-bearing
    # issuer/year/number syntax even when their native locator is the bare line.
    return (
        kind == "filing_number"
        and re.fullmatch(
            r"[\u3400-\u9fffA-Za-z（）()·]{2,80}[〔\[]\d{4}[〕\]][^\r\n]{0,80}\d+号",
            observed,
        )
        is not None
    )


@dataclass(frozen=True)
class IdentityAdaptation:
    semantic_raw: bytes
    audit: dict[str, Any]


def adapt_identity_response(raw: bytes, context: dict[str, Any]) -> IdentityAdaptation:
    """Repair reference relationships only using this call's offered locators.

    Locator coordinates remain opaque here. Their offered order is the renderer's
    stable source order; the original native projector verifies coordinates later.
    Unsupported asserted values fail closed, rather than inventing or erasing them.
    """
    validate_identity_offered_response(raw, context)
    response = G3SemanticReferenceResponseV1.model_validate_json(raw).model_dump(mode="json")
    offered: dict[str, list[tuple[int, int, int, dict[str, Any]]]] = {}
    for material in context["materials"]:
        locators = []
        for block_index, block in enumerate(material["blocks"]):
            for ordinal, row in enumerate(block["evidence_locator_refs"]):
                locators.append((block["page_number"], block_index, ordinal, row))
        offered[material["material_id"]] = sorted(locators, key=lambda row: row[:3])
    changes: list[dict[str, Any]] = []
    for material in response["materials"]:
        by_ref = {row["evidence_ref"]: row for row in material["evidence"]}
        locators = offered[material["material_id"]]
        quotes = {row[3]["locator_ref"]: row[3]["quote"] for row in locators}
        for entity in material["entities"]:
            selected = entity["identity_evidence_refs"]
            canonical_refs = sorted(set(selected))
            if selected != canonical_refs:
                changes.append(
                    {
                        "material_id": material["material_id"],
                        "entity_ref": entity["entity_ref"],
                        "reason": "IDENTITY_REFERENCE_SET_NORMALIZED",
                        "original_evidence_refs": selected,
                        "evidence_refs": canonical_refs,
                    }
                )
                selected = canonical_refs
            if any(ref not in by_ref for ref in selected):
                raise ValueError("dangling semantic evidence ref")
            removed = [
                ref
                for ref in selected
                if by_ref[ref]["purpose"] in {"classification", "material_role", "field"}
            ]
            selected = [ref for ref in selected if ref not in removed]
            if removed:
                changes.append(
                    {
                        "material_id": material["material_id"],
                        "entity_ref": entity["entity_ref"],
                        "reason": "REDUNDANT_NON_IDENTITY_REFERENCE",
                        "evidence_refs": removed,
                    }
                )
            if any(by_ref[ref]["entity_ref"] != entity["entity_ref"] for ref in selected):
                raise ValueError("wrong-purpose identity evidence")
            values = [
                ("name", entity["name"], None),
                ("issuer", entity["issuer"], None),
                ("product_code", entity["product_code"], None),
                ("version", entity["version_label"], None),
            ]
            if entity["filing_or_registration"] is not None:
                values.append(
                    (
                        "version",
                        entity["filing_or_registration"]["value"],
                        entity["filing_or_registration"]["kind"],
                    )
                )
            for purpose, value, filing_kind in values:
                if value is None or any(
                    by_ref[ref]["purpose"] == purpose
                    and _normalized(value) in _normalized(quotes[by_ref[ref]["locator_ref"]])
                    and (
                        filing_kind is None
                        or _filing_support(
                            value,
                            filing_kind,
                            quotes[by_ref[ref]["locator_ref"]],
                            entity["product_code"],
                        )
                    )
                    for ref in selected
                ):
                    continue
                matches = [
                    row
                    for page, _, _, row in locators
                    if (page == 1 or purpose in {"issuer", "product_code", "version"})
                    and _normalized(value) in _normalized(row["quote"])
                ]
                if not matches:
                    raise ValueError("identity asserted value lacks offered source evidence")
                if filing_kind is not None:
                    matches = [
                        row
                        for row in matches
                        if _filing_support(value, filing_kind, row["quote"], entity["product_code"])
                    ]
                    if not matches:
                        raise ValueError("identity filing evidence type is unsupported")
                locator = matches[0]["locator_ref"]
                ref = (
                    "adapt_"
                    + hashlib.sha256(
                        _bytes([material["material_id"], entity["entity_ref"], purpose, locator])
                    ).hexdigest()
                )
                evidence = {
                    "evidence_ref": ref,
                    "locator_ref": locator,
                    "entity_ref": entity["entity_ref"],
                    "purpose": purpose,
                    "field_key": None,
                }
                if ref in by_ref and by_ref[ref] != evidence:
                    raise ValueError("identity derived evidence collision")
                if ref not in by_ref:
                    material["evidence"].append(evidence)
                    by_ref[ref] = evidence
                if ref not in selected:
                    selected.append(ref)
                changes.append(
                    {
                        "material_id": material["material_id"],
                        "entity_ref": entity["entity_ref"],
                        "reason": "ASSERTED_VALUE_OFFERED_EVIDENCE_LINK",
                        "purpose": purpose,
                        "value": value,
                        "evidence_ref": ref,
                        "locator_ref": locator,
                    }
                )
            entity["identity_evidence_refs"] = sorted(selected)
        material["evidence"] = sorted(material["evidence"], key=lambda row: row["evidence_ref"])
    semantic_raw = _bytes(response)
    validate_identity_offered_response(semantic_raw, context)
    return IdentityAdaptation(
        semantic_raw=semantic_raw,
        audit={
            "contract": "product-identity-adaptation.830.v1",
            "original_semantic_sha256": hashlib.sha256(raw).hexdigest(),
            "context_sha256": hashlib.sha256(_bytes(context)).hexdigest(),
            "adapted_semantic_sha256": hashlib.sha256(semantic_raw).hexdigest(),
            "changes": changes,
        },
    )

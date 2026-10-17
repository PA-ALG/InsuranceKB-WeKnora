"""S3d-2 acceptance: a candidate bundle carries its product page (Spec §3.3).

Protected file: written by Claude. With a page, the bundle adds one entity member and one
presentation_profile member beside the claims: contract payloads, the platform digest, no
evidence references, space scope. A page for another product or pack, or a slug used twice
across kinds, stops the build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import jsonschema  # type: ignore[import-untyped]
import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.canonical import member_digest
from insurance_harness.compilers.schema_fields.claims import candidate_bundle
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.compilers.schema_fields.page import ProductPage
from insurance_harness.contracts import Entity, PresentationProfile
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

REPO = Path(__file__).resolve().parents[3]
SHA = "ab" * 32


def schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((REPO / "contracts" / name).read_text(encoding="utf-8"))
    return loaded


class Page:
    def __init__(self, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = "保险条款.pdf", SHA, page, text


SOURCE = SegmentedSource([Page(1, "1.4 等待期\n自本合同生效之日起90日内为等待期。\n")])
SOURCES = {"保险条款.pdf": SourceRevision(knowledge_id="k-1", parse_attempt=2)}


def field(key: str, state: Literal["present", "unknown"], ids: list[str]) -> FieldResult:
    return FieldResult(
        field_key=key,
        state=state,
        value="90日" if state == "present" else None,
        evidence=SOURCE.evidence(ids),
        segment_ids=ids,
    )


def output(entity_id: str = "1828", fields: list[FieldResult] | None = None) -> CompileOutput:
    return CompileOutput(
        pack_id="pack_demo",
        entity_id=entity_id,
        model="deepseek-flash",
        cards_version="harness-test-cards",
        fields=fields
        if fields is not None
        else [
            field("waiting_period", "present", ["D1P1S1"]),
            field("cooling_off_period", "unknown", []),
        ],
    )


def page(entity_id: str = "1828", pack_id: str = "pack_demo") -> ProductPage:
    entity = Entity(
        entity_id=entity_id,
        entity_type="insurance_product",
        names=["演示重大疾病保险"],
        identifiers={"product_code": entity_id},
        classification_labels=["demo_class"],
        owner_module="harness/schema_fields",
    )
    profile = PresentationProfile.model_validate(
        {
            "profile_id": "profile_demo",
            "profile_version": "1.0.0",
            "profile_sha256": "cd" * 32,
            "schema_pack_id": pack_id,
            "classification_labels": ["demo_class"],
            "sections": [
                {
                    "section_key": "contract",
                    "display_name": "投保与合同",
                    "fields": [{"field_key": "waiting_period", "short_title": "等待期"}],
                }
            ],
        }
    )
    return ProductPage(entity=entity, profile=profile)


def build(compiled: CompileOutput, product: ProductPage) -> dict[str, Any]:
    bundle = candidate_bundle(
        compiled, SOURCE, SOURCES, compiler_identity="harness/schema_fields@test", page=product
    )
    dumped: dict[str, Any] = bundle.model_dump(mode="json")
    return dumped


def test_a_page_adds_one_entity_and_one_profile_member_beside_the_claims() -> None:
    product = page()
    bundle = build(output(), product)
    jsonschema.validate(bundle, schema("candidate_bundle.schema.json"))
    by_slug = {m["logical_slug"]: m for m in bundle["members"]}
    assert set(by_slug) == {
        "entity/1828",
        "presentation/profile_demo",
        "1828/waiting_period",
        "1828/cooling_off_period",
    }
    entity, profile = by_slug["entity/1828"], by_slug["presentation/profile_demo"]
    assert entity["kind"] == "entity"
    assert entity["payload"] == product.entity.model_dump(mode="json")
    assert profile["kind"] == "presentation_profile"
    assert profile["payload"] == product.profile.model_dump(mode="json")
    for member in (entity, profile):
        assert member["evidence_refs"] == [] and member["access_scope"] == "space"
        assert member["member_digest"] == member_digest(member["payload"])
    jsonschema.validate(entity["payload"], schema("entity.schema.json"))
    jsonschema.validate(profile["payload"], schema("presentation_profile.schema.json"))
    claims = [by_slug["1828/waiting_period"], by_slug["1828/cooling_off_period"]]
    assert all(member["kind"] == "claim" for member in claims)


@pytest.mark.parametrize(
    "wrong", [page(entity_id="9999"), page(pack_id="pack_other")], ids=["product", "pack"]
)
def test_a_page_for_another_product_or_pack_is_refused(wrong: ProductPage) -> None:
    with pytest.raises(BundleError) as error:
        build(output(), wrong)
    assert error.value.reason == "PAGE_MISMATCH"


def test_a_slug_is_used_once_across_member_kinds() -> None:
    """Entity "entity" with a field "entity" would publish two members as entity/entity."""
    compiled = output("entity", [field("entity", "unknown", [])])
    with pytest.raises(BundleError) as error:
        build(compiled, page(entity_id="entity"))
    assert error.value.reason == "DUPLICATE_LOGICAL_KEY"

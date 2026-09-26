"""Capability-scoped relation proposals and server-owned identity binding."""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import Field, model_validator

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import definition_sha256_830_g3
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import ConceptDefinition
from insurance_harness.knowledge_compiler.product_concept_relation import (
    ProductConceptRelation,
    relation_stable_key,
)
from insurance_harness.product_ingestion.native_admission_contract import (
    NativeAdmissionResponseV2,
    NativePage,
    _Frozen,
)

RELATION_CAPABILITY: Final = "product-concept-relation.830.v1"
PREDICATE_MEANING = (
    "The subject product's benefit is reduced by advance payment under the linked "
    "insurance category, only under the source-supported conditions and exceptions. "
    "The object is a concept/category, not a newly identified concrete product."
)


class RelationProposal(_Frozen):
    predicate: Literal["benefit_reduced_by_advance_payment"]
    object_ref: str = Field(min_length=1)


class NativeRelationPage(NativePage):
    relation: RelationProposal | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, value: Any) -> Any:
        if isinstance(value, dict) and "relation" in value and value["relation"] is None:
            raise ValueError("native relation proposal cannot be null")
        return value


class NativeRelationResponse(NativeAdmissionResponseV2):
    pages: tuple[NativeRelationPage, ...]


def admission_response(value: Any, context: dict[str, Any]) -> NativeAdmissionResponseV2:
    capability = context.get("relation_capability")
    if capability is None:
        return NativeAdmissionResponseV2.model_validate(value)
    if capability != RELATION_CAPABILITY:
        raise ValueError("native relation capability invalid")
    response = NativeRelationResponse.model_validate(value)
    if (
        any(row.relation is not None for row in response.pages)
        and context.get("isolation_enabled") is not True
    ):
        raise ValueError("native relation requires complete dependency selection domain")
    return response


def enable_relation_context(context: dict[str, Any], capability: str | None) -> None:
    if capability is None:
        return
    if capability != RELATION_CAPABILITY or context.get("dependency_policy") is None:
        raise ValueError("native relation capability invalid")
    context["relation_capability"] = capability
    context["response_schema"] = NativeRelationResponse.model_json_schema()
    context["relation_contract"] = {
        "predicate": "benefit_reduced_by_advance_payment",
        "meaning": PREDICATE_MEANING,
        "subject": "current entity and version; server bound",
        "object_ref": "supplied definition member_ref or offered existing concept_id only",
        "stable_key": "$relation",
        "provenance": "All relation content must be SOURCE_SUPPORTED",
    }


def bind_relation_page(
    row: NativePage,
    *,
    space_id: str,
    entity_id: str,
    definitions_by_ref: dict[str, ConceptDefinition],
) -> dict[str, Any]:
    proposal = row.relation if isinstance(row, NativeRelationPage) else None
    if proposal is None:
        if row.stable_key == "$relation":
            raise ValueError("native relation placeholder requires proposal")
        return {}
    target = definitions_by_ref.get(proposal.object_ref)
    if (
        row.stable_key != "$relation"
        or row.concept_refs != (proposal.object_ref,)
        or target is None
        or target.space_id != space_id
    ):
        raise ValueError("native relation target/identity invalid")
    relation = ProductConceptRelation(
        contract=RELATION_CAPABILITY,
        subject_type="PRODUCT",
        object_type="CONCEPT",
        predicate=proposal.predicate,
        object_concept_id=target.concept_id,
        object_definition_sha256=definition_sha256_830_g3(target),
    )
    return {
        "business_relation": relation,
        "stable_key": relation_stable_key(space_id, entity_id, relation),
    }

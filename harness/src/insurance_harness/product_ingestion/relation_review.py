"""Versioned independent review contract for formal product-concept relations."""

from typing import Any

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput, free_page_id
from insurance_harness.product_ingestion.discovery import DEPENDENCY_DISCOVERY_REVIEW_PROMPT
from insurance_harness.product_ingestion.native_relation_admission import (
    PREDICATE_MEANING,
    RELATION_CAPABILITY,
)

RELATION_REVIEW_VERSION = "product-discovery-review-context.830.v9"
RELATION_REVIEW_PURPOSE = "g3-relation-discovery-review"
RELATION_REVIEW_PROMPT = (
    DEPENDENCY_DISCOVERY_REVIEW_PROMPT
    + b"""
Additionally verify every typed business_relation against original source evidence.
The fixed predicate benefit_reduced_by_advance_payment means:
"""
    + PREDICATE_MEANING.encode()
    + b"""
Check the product subject/version, object concept and exact definition revision, relation
direction, trigger, recipients, reductions, conditions and exceptions. A typed payload
and native candidate description are not proof of truth. Reject unsupported relation
claims; use NEEDS_HUMAN for uncertainty. All relation content must be SOURCE_SUPPORTED.
Do not turn an unnamed insurance category into an identified concrete product. The
full final-output hash binds this relation, its dependencies and the source selections.
The supplied dependency_selection must prove the explicit relation capability and a
complete dependency domain. This review does not authorize publication by itself.
"""
)


def relation_review_view(
    output: CompileOutput, member_views: list[dict[str, Any]], selection: dict[str, Any] | None
) -> dict[str, Any]:
    if (
        selection is None
        or selection.get("admission_context", {}).get("relation_capability") != RELATION_CAPABILITY
        or selection["admission_context"].get("isolation_enabled") is not True
    ):
        raise ValueError("relation review requires verified capability and dependency selection")
    relations = {
        free_page_id(p): p.business_relation
        for p in output.pages
        if p.business_relation is not None
    }
    for view in member_views:
        relation = relations.get(view["member_id"])
        if relation is not None:
            view["business_relation"] = relation.model_dump(mode="json")
    return {"relation_predicates": {"benefit_reduced_by_advance_payment": PREDICATE_MEANING}}

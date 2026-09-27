"""Adapt trusted review views to the compiler's single qualification policy."""

from __future__ import annotations

from typing import Any

from insurance_harness.knowledge_compiler.concept_compile_830_g2 import ValueScore
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import KnowledgeContentProvenance
from insurance_harness.knowledge_compiler.knowledge_quality import (
    QUALITY_POLICY,
    KnowledgeQualification,
    QualityContent,
    qualify_knowledge,
)

QUALITY_REVIEW_PURPOSE = "g3-provenance-quality-review"


def quality_review_prompt() -> bytes:
    # Relation review already contains provenance and dependency review rules.
    from insurance_harness.product_ingestion.relation_review import RELATION_REVIEW_PROMPT

    return (
        RELATION_REVIEW_PROMPT
        + b"""
Applicable quality policy: provenance-applicable-score.830.v1. Keep all six raw
score dimensions and their original maxima. For a fully MODEL_GENERATED member
with no evidence, evidence_quality must remain zero; assess its quality against
the applicable 80 points, accepting at 64 and requiring review at 48. For source
supported, mixed or legacy evidence-bearing content, maxima remain 100 with
80/60 thresholds. Do not invent evidence points or inflate the other dimensions.
Scores do not override REJECT/NEEDS_HUMAN or deficient product facts, conditions,
provenance, dependencies or dispositions. A generic generated explanation must
be explicitly labeled; an unsupported product-specific claim is not acceptable.
Only apply relation checks when a typed relation exists, and dependency checks
when dependency_selection is present. Bind the supplied policy and batch request
identity. Compare actual effective field content where provided; a field label
or unknown field does not prove that the candidate's meaning is already covered.
"""
    )


def review_qualifications(
    context: dict[str, Any],
    scores: dict[str, ValueScore],
) -> dict[str, KnowledgeQualification]:
    policy = context.get("quality_policy")
    if policy is None:
        return {
            key: qualify_knowledge(None, QualityContent("", 0, None), score)
            for key, score in scores.items()
        }
    if policy != QUALITY_POLICY:
        raise ValueError("UNKNOWN_KNOWLEDGE_QUALITY_POLICY")
    rows = context["candidate_members"]
    members = {row["member_id"]: row for row in rows}
    if len(members) != len(rows) or set(members) != set(scores):
        raise ValueError("quality review score coverage mismatch")
    return {
        key: qualify_knowledge(
            policy,
            QualityContent(
                member["rendered_content"],
                len(member["evidence"]),
                KnowledgeContentProvenance.model_validate(member["content_provenance"])
                if member.get("content_provenance") is not None
                else None,
            ),
            scores[key],
        )
        for key, member in members.items()
    }

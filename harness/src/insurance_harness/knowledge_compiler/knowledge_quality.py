"""One provenance-aware qualification rule; scores never confer publication authority.

The caller supplies validated content, not a model's claimed provenance category.
Historical requests retain their exact six-dimensional score interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .concept_compile_830_g2 import ValueScore
from .concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FreeWikiPage,
    KnowledgeContentProvenance,
    free_page_content,
)

QualityPolicy = Literal["provenance-applicable-score.830.v1"]
QUALITY_POLICY: QualityPolicy = "provenance-applicable-score.830.v1"


@dataclass(frozen=True, slots=True)
class QualityContent:
    rendered_content: str
    evidence_count: int
    provenance: KnowledgeContentProvenance | None


@dataclass(frozen=True, slots=True)
class KnowledgeQualification:
    raw_total: int
    applicable_max: int
    band: Literal["REJECTED", "PENDING", "ACCEPTED"]


def qualify_knowledge(
    policy: QualityPolicy | None,
    content: QualityContent,
    score: ValueScore,
) -> KnowledgeQualification:
    """Validate applicable dimensions and classify using integer ratios."""
    if policy not in (None, QUALITY_POLICY):
        raise ValueError("UNKNOWN_KNOWLEDGE_QUALITY_POLICY")
    score = ValueScore.model_validate(score)
    maximum = 100
    if policy is not None:
        provenance = content.provenance
        if content.evidence_count < 0:
            raise ValueError("QUALITY_SOURCE_INVALID")
        if provenance is None:
            if not content.evidence_count:
                raise ValueError("QUALITY_PROVENANCE_REQUIRED")
        else:
            provenance = KnowledgeContentProvenance.model_validate(provenance)
            if "".join(row.text for row in provenance.segments) != content.rendered_content:
                raise ValueError("QUALITY_PROVENANCE_COVERAGE_MISMATCH")
            used: set[int] = set()
            for row in provenance.segments:
                indexes = row.evidence_indexes
                if (
                    tuple(sorted(set(indexes))) != indexes
                    or any(index < 0 or index >= content.evidence_count for index in indexes)
                    or bool(indexes) != (row.origin == "SOURCE_SUPPORTED")
                ):
                    raise ValueError("QUALITY_PROVENANCE_SOURCE_MISMATCH")
                used.update(indexes)
            if used != set(range(content.evidence_count)):
                raise ValueError("QUALITY_UNUSED_EVIDENCE")
            if not content.evidence_count:
                if score.evidence_quality != 0:
                    raise ValueError("generated-only member evidence score must be zero")
                maximum = 80
    total = score.total
    band: Literal["REJECTED", "PENDING", "ACCEPTED"] = "ACCEPTED"
    if total * 100 < maximum * 60:
        band = "REJECTED"
    elif total * 100 < maximum * 80:
        band = "PENDING"
    return KnowledgeQualification(total, maximum, band)


def qualify_member(
    policy: QualityPolicy | None,
    member: ConceptDefinition | FreeWikiPage,
    score: ValueScore,
) -> KnowledgeQualification:
    """Domain adapter revalidates copied instances before computing qualification."""
    if isinstance(member, ConceptDefinition):
        member = ConceptDefinition.model_validate(member)
        rendered = member.body
    else:
        member = FreeWikiPage.model_validate(member)
        rendered = free_page_content(member)
    return qualify_knowledge(
        policy,
        QualityContent(rendered, len(member.evidence), member.content_provenance),
        score,
    )

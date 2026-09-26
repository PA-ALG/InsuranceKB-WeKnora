"""Typed product-to-concept assertions carried by one existing release member.

No storage, model or release authority lives here. Subject/version, conditions and
Evidence belong to the containing page; only the relation meaning and target are
additional data. The stable identity survives an explicitly reviewed version update.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints

if TYPE_CHECKING:
    from .concept_free_wiki_830_g2 import ConceptDefinition, FreeWikiPage


class ProductConceptRelation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    contract: Literal["product-concept-relation.830.v1"]
    subject_type: Literal["PRODUCT"]
    object_type: Literal["CONCEPT"]
    predicate: Literal["benefit_reduced_by_advance_payment"]
    object_concept_id: Annotated[StrictStr, StringConstraints(pattern=r"^concept_[0-9a-f]{64}$")]
    object_definition_sha256: Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def relation_stable_key(space_id: str, entity_id: str, relation: ProductConceptRelation) -> str:
    from .concept_free_wiki_830_g2 import digest

    return "relation_" + digest(
        "product-concept-relation-identity",
        [space_id, entity_id, relation.predicate, relation.object_concept_id],
    )


def validate_relation_page(page: FreeWikiPage) -> None:
    """Validate one atomic assertion without inventing semantic evidence."""
    relation = page.business_relation
    if relation is None:
        return
    if (
        not page.entity_version.strip()
        or page.stable_key != relation_stable_key(page.space_id, page.entity_id, relation)
        or page.concept_ids != (relation.object_concept_id,)
    ):
        raise ValueError("RELATION_IDENTITY_MISMATCH")
    if (
        not page.evidence
        or page.content_provenance is None
        or any(s.origin != "SOURCE_SUPPORTED" for s in page.content_provenance.segments)
    ):
        raise ValueError("RELATION_SOURCE_SUPPORT_REQUIRED")


def validate_relation_targets(
    definitions: Sequence[ConceptDefinition], pages: Sequence[FreeWikiPage]
) -> None:
    """Require targets from this exact composition, including inherited relations."""
    from .batch_canonical_830_g3 import definition_sha256_830_g3

    targets = {d.concept_id: d for d in definitions}
    for page in pages:
        relation = page.business_relation
        if relation is None:
            continue
        validate_relation_page(page)
        target = targets.get(relation.object_concept_id)
        if (
            target is None
            or target.space_id != page.space_id
            or definition_sha256_830_g3(target) != relation.object_definition_sha256
        ):
            raise ValueError("RELATION_TARGET_REVISION_MISMATCH")


def validate_relation_update(old: FreeWikiPage, new: FreeWikiPage) -> None:
    if (old.business_relation is None) != (new.business_relation is None):
        raise ValueError("RELATION_MEMBER_TYPE_CHANGED")

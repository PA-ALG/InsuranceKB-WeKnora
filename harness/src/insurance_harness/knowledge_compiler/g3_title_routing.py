"""Deterministic title routing and source-evidenced year overlays for G3.

Captured C proposals and their model receipts stay immutable. The compatibility
projection returned here is a RULE-DERIVED resolver input, never a replacement
model response. A downstream admission must bind this overlay AND the original
successful C evidence, then call apply_title_routing_overlay to reproduce it.
No provider, PDF/native parser, database or release authority is opened here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from insurance_harness.product.classify import _LINE_KEYWORDS, detect_product_line

from .batch_canonical_830_g3 import batch_sha256_830_g3
from .batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    BatchEntityResolutionV1,
    BatchResolutionPolicyV1,
    EntityProposalV1,
    ExistingEntitySnapshotV1,
    Hash,
    MaterialProposalV1,
    ProposalBatchV1,
    ProposalEvidenceV1,
    _normalized,
    resolve_batch,
)
from .concept_free_wiki_830_g2 import Evidence, SourceBlock, evidence_for, verify_evidence
from .schema_pack_catalog_830_g3 import SchemaPackCatalogV1

RULE_VERSION: Literal["g3-formal-title-rules.830.v1"] = "g3-formal-title-rules.830.v1"
VersionAction = Literal[
    "FILLED_FROM_TITLE",
    "KEPT_EXISTING",
    "NO_EXACT_TITLE",
    "NO_EXPLICIT_YEAR",
    "TITLE_YEAR_AMBIGUOUS",
    "VERSION_CONFLICT",
    "CLASSIFICATION_CONFLICT",
]
# Existing product classifier line keys projected into the existing G3 Catalog.
_LINE_LABELS = {
    "medical": "medical_insurance",
    "accident-medical": "accident_medical_insurance",
    "accident": "accident_insurance",
    "critical-illness": "critical_illness_insurance",
    "term-life": "term_life_insurance",
    "whole-life": "whole_life_insurance",
    "endowment": "endowment_insurance",
    "annuity": "annuity_insurance",
    "long-term-care": "nursing_care_insurance",
    "supplementary-pension": "supplementary_pension_insurance",
    "disability-income": "disability_income_insurance",
}
_YEAR = re.compile(r"[（(]((?:19|20)\d{2})[）)]")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class FormalTitleRouteV1(_Frozen):
    title: StrictStr
    classification_status: Literal["KNOWN", "UNRESOLVED", "CATALOG_AMBIGUOUS", "AMBIGUOUS_TITLE"]
    product_line: StrictStr | None
    primary_label: StrictStr | None
    schema_pack_id: StrictStr | None
    schema_version: StrictStr | None
    schema_pack_sha256: Hash | None
    title_year: StrictStr | None
    title_year_status: Literal["EXPLICIT", "NOT_PRESENT", "AMBIGUOUS"]


class TitleRuleObservationV1(FormalTitleRouteV1):
    material_id: StrictStr
    proposal_ref: StrictStr
    original_proposal_sha256: Hash
    original_primary_label: StrictStr
    source_name_evidence_id: StrictStr | None
    title_evidence: Evidence | None
    original_version_label: StrictStr | None
    effective_version_label: StrictStr | None
    version_action: VersionAction


class TitleRoutingOverlayV1(_Frozen):
    contract: Literal["g3-title-routing-overlay.830.v1"] = "g3-title-routing-overlay.830.v1"
    origin: Literal["DETERMINISTIC_SOURCE_RULE"] = "DETERMINISTIC_SOURCE_RULE"
    rule_version: Literal["g3-formal-title-rules.830.v1"] = RULE_VERSION
    source_proposals_sha256: Hash
    source_model_receipts_sha256: Hash
    corpus_sha256: Hash
    catalog_sha256: Hash
    material_ids: tuple[StrictStr, ...] = Field(min_length=1)
    observations: tuple[TitleRuleObservationV1, ...]
    effective_proposals_sha256: Hash
    overlay_sha256: Hash

    @model_validator(mode="after")
    def verify_overlay(self) -> Self:
        if self.material_ids != tuple(sorted(set(self.material_ids))):
            raise ValueError("title overlay material selection must be canonical unique")
        keys = tuple((row.material_id, row.proposal_ref) for row in self.observations)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("title overlay observations must be canonical unique")
        if self.overlay_sha256 != batch_sha256_830_g3(
            self.contract,
            self.model_dump(exclude={"overlay_sha256"}),
        ):
            raise ValueError("title overlay hash mismatch")
        return self


def _multiple_title_lines(title: str) -> bool:
    """Reject separate product signals while preserving specific keyword overlaps."""
    spans = sorted(
        (match.start(), match.end())
        for keyword, _ in _LINE_KEYWORDS
        for match in re.finditer(re.escape(keyword), title)
    )
    groups: list[tuple[int, int]] = []
    for start, end in spans:
        if groups and start < groups[-1][1]:
            groups[-1] = (groups[-1][0], max(end, groups[-1][1]))
        elif (
            groups
            and start == groups[-1][1]
            and title[groups[-1][0] : start] == "补充养老"
            and title[start:end] == "年金保险"
        ):
            # One specific formal product phrase, not two product names.
            groups[-1] = (groups[-1][0], end)
        else:
            groups.append((start, end))
    if len({detect_product_line(title[start:end]) for start, end in groups}) > 1:
        return True
    return any(
        re.search(r"[、,，;；/+＋与和及]", title[left[1] : right[0]])
        for left, right in zip(groups, groups[1:], strict=False)
    )


def route_formal_title(title: str, *, catalog: SchemaPackCatalogV1) -> FormalTitleRouteV1:
    """Reuse the existing rule on the formal title, excluding unrelated body text."""
    normalized = _normalized(title)
    ambiguous = _multiple_title_lines(normalized)
    line = None if ambiguous else detect_product_line(normalized)
    label = None if line is None else _LINE_LABELS.get(line)
    packs = [
        entry.pack
        for entry in catalog.entries
        if label is not None and label in entry.pack.applicable_classifications
    ]
    pack = packs[0] if len(packs) == 1 else None
    years = tuple(sorted(set(_YEAR.findall(normalized))))
    return FormalTitleRouteV1(
        title=title,
        classification_status=(
            "AMBIGUOUS_TITLE"
            if ambiguous
            else "KNOWN"
            if pack is not None
            else "CATALOG_AMBIGUOUS"
            if len(packs) > 1
            else "UNRESOLVED"
        ),
        product_line=line,
        primary_label=label,
        schema_pack_id=None if pack is None else pack.schema_pack_id,
        schema_version=None if pack is None else pack.schema_version,
        schema_pack_sha256=None if pack is None else pack.schema_pack_sha256,
        title_year=years[0] if len(years) == 1 else None,
        title_year_status=(
            "EXPLICIT" if len(years) == 1 else "AMBIGUOUS" if years else "NOT_PRESENT"
        ),
    )


def _exact_title(
    entity: EntityProposalV1,
    proposal: MaterialProposalV1,
    sources: Sequence[SourceBlock],
) -> tuple[str | None, Evidence | None]:
    if not entity.name:
        return None, None
    pattern = re.compile(r"\s*".join(re.escape(char) for char in _normalized(entity.name)))
    blocks = {(row.revision_id, row.block_id): row for row in sources}
    # Only captured, source-verified name evidence can authorize a title-year fill.
    for row in proposal.evidence:
        if row.purpose != "name" or row.entity_proposal_ref != entity.proposal_ref:
            continue
        verify_evidence(row.evidence, sources)
        match = pattern.search(row.evidence.quote)
        if match is None:
            continue
        source = blocks[(row.evidence.revision_id, row.evidence.block_id)]
        start = row.evidence.start + match.start()
        end = row.evidence.start + match.end()
        title = evidence_for(source, start, end)
        verify_evidence(title, sources)
        return row.evidence_id, title
    return None, None


def _hashed[ModelT: BaseModel](
    model: type[ModelT], contract: str, hash_field: str, payload: dict[str, object]
) -> ModelT:
    return model.model_validate({**payload, hash_field: batch_sha256_830_g3(contract, payload)})


def build_title_routing_overlay(
    *,
    corpus: BatchCorpusV1,
    catalog: SchemaPackCatalogV1,
    source_proposals: ProposalBatchV1,
    material_ids: Sequence[str],
) -> tuple[TitleRoutingOverlayV1, ProposalBatchV1]:
    """Return an explicit derivation receipt plus the existing resolver's projection."""
    source_proposals = ProposalBatchV1.model_validate(source_proposals)
    corpus = BatchCorpusV1.model_validate(corpus)
    catalog = SchemaPackCatalogV1.model_validate(catalog)
    selected = tuple(sorted(set(material_ids)))
    entries = {row.material_id: row for row in corpus.entries}
    proposal_ids = {row.material_id for row in source_proposals.proposals}
    if (
        not selected
        or len(selected) != len(material_ids)
        or not set(selected) <= entries.keys() & proposal_ids
        or source_proposals.corpus_sha256 != corpus.corpus_sha256
    ):
        raise ValueError("title overlay source or selection mismatch")
    observations = []
    effective_materials = []
    for proposal in source_proposals.proposals:
        if proposal.material_id not in selected:
            effective_materials.append(proposal)
            continue
        entry = entries[proposal.material_id]
        if entry.entry_sha256 != proposal.corpus_entry_sha256:
            raise ValueError("title overlay source revision mismatch")
        evidence = list(proposal.evidence)
        entities = []
        for entity in proposal.entities:
            name_evidence_id, title = _exact_title(entity, proposal, entry.blocks)
            route = route_formal_title("" if title is None else title.quote, catalog=catalog)
            value = entity.version_label
            action: VersionAction
            if title is None:
                action = "NO_EXACT_TITLE"
            elif route.classification_status in {"AMBIGUOUS_TITLE", "CATALOG_AMBIGUOUS"} or (
                route.classification_status == "KNOWN"
                and route.primary_label != entity.primary_label
            ):
                action = "CLASSIFICATION_CONFLICT"
            elif route.title_year_status == "AMBIGUOUS":
                action = "TITLE_YEAR_AMBIGUOUS"
            elif value is not None:
                action = (
                    "VERSION_CONFLICT"
                    if route.title_year is not None and _normalized(value) != route.title_year
                    else "KEPT_EXISTING"
                )
            elif route.title_year is None:
                action = "NO_EXPLICIT_YEAR"
            else:
                action = "FILLED_FROM_TITLE"
                value = route.title_year
                evidence_id = batch_sha256_830_g3(
                    "g3-title-rule-evidence.830.v1",
                    {
                        "source_proposals_sha256": source_proposals.proposals_sha256,
                        "material_id": proposal.material_id,
                        "proposal_ref": entity.proposal_ref,
                        "version_label": value,
                        "title_evidence": title,
                    },
                )
                evidence.append(
                    ProposalEvidenceV1(
                        evidence_id=evidence_id,
                        entity_proposal_ref=entity.proposal_ref,
                        purpose="version",
                        field_key=None,
                        evidence=title,
                    )
                )
                entity = EntityProposalV1.model_validate(
                    {
                        **entity.model_dump(mode="python"),
                        "version_label": value,
                        "identity_evidence_ids": tuple(
                            sorted((*entity.identity_evidence_ids, evidence_id))
                        ),
                    }
                )
            original = next(
                row for row in proposal.entities if row.proposal_ref == entity.proposal_ref
            )
            observations.append(
                TitleRuleObservationV1(
                    **route.model_dump(mode="python"),
                    material_id=proposal.material_id,
                    proposal_ref=entity.proposal_ref,
                    original_proposal_sha256=proposal.proposal_sha256,
                    original_primary_label=original.primary_label,
                    source_name_evidence_id=name_evidence_id,
                    title_evidence=title,
                    original_version_label=original.version_label,
                    effective_version_label=value,
                    version_action=action,
                )
            )
            entities.append(entity)
        effective_materials.append(
            _hashed(
                MaterialProposalV1,
                "material-proposal.830.g3.v1",
                "proposal_sha256",
                {
                    **proposal.model_dump(mode="python", exclude={"proposal_sha256"}),
                    "entities": tuple(entities),
                    "evidence": tuple(sorted(evidence, key=lambda row: row.evidence_id)),
                },
            )
        )
    effective = _hashed(
        ProposalBatchV1,
        source_proposals.contract,
        "proposals_sha256",
        {
            **{
                name: getattr(source_proposals, name)
                for name in type(source_proposals).model_fields
                if name != "proposals_sha256"
            },
            "proposals": tuple(effective_materials),
        },
    )
    payload: dict[str, object] = {
        "contract": "g3-title-routing-overlay.830.v1",
        "origin": "DETERMINISTIC_SOURCE_RULE",
        "rule_version": RULE_VERSION,
        "source_proposals_sha256": source_proposals.proposals_sha256,
        "source_model_receipts_sha256": batch_sha256_830_g3(
            "g3-title-original-model-receipts.830.v1",
            source_proposals.model_receipts,
        ),
        "corpus_sha256": corpus.corpus_sha256,
        "catalog_sha256": catalog.catalog_sha256,
        "material_ids": selected,
        "observations": tuple(observations),
        "effective_proposals_sha256": effective.proposals_sha256,
    }
    overlay = _hashed(
        TitleRoutingOverlayV1,
        "g3-title-routing-overlay.830.v1",
        "overlay_sha256",
        payload,
    )
    return overlay, effective


def apply_title_routing_overlay(
    overlay: TitleRoutingOverlayV1,
    *,
    corpus: BatchCorpusV1,
    catalog: SchemaPackCatalogV1,
    source_proposals: ProposalBatchV1,
) -> ProposalBatchV1:
    """Recompute from original custody inputs, rejecting every unaudited alteration."""
    overlay = TitleRoutingOverlayV1.model_validate(overlay)
    expected, effective = build_title_routing_overlay(
        corpus=corpus,
        catalog=catalog,
        source_proposals=source_proposals,
        material_ids=overlay.material_ids,
    )
    if overlay != expected:
        raise ValueError("title overlay source, rules or projection mismatch")
    if any(
        row.version_action
        in {"VERSION_CONFLICT", "CLASSIFICATION_CONFLICT", "TITLE_YEAR_AMBIGUOUS"}
        for row in overlay.observations
    ):
        raise ValueError("title rule conflict requires a separate unresolved material disposition")
    return effective


def resolve_with_title_overlay(
    overlay: TitleRoutingOverlayV1,
    *,
    corpus: BatchCorpusV1,
    catalog: SchemaPackCatalogV1,
    source_proposals: ProposalBatchV1,
    existing_entities: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    compiler_version: str = "batch-entity-resolution-compiler.830.g3.v1",
) -> BatchEntityResolutionV1:
    effective = apply_title_routing_overlay(
        overlay,
        corpus=corpus,
        catalog=catalog,
        source_proposals=source_proposals,
    )
    return resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=effective,
        existing_entities=existing_entities,
        policy=policy,
        compiler_version=compiler_version,
    )

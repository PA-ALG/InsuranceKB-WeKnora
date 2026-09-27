"""Single owner of source-verified semantic proposal construction and policy checks."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping

from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    EntityProposalV1,
    LabelProposalV1,
    MaterialProposalV1,
    ProposalEvidenceV1,
    VersionAnchorV1,
    _batch_sha256,
    _normalized,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import Evidence, verify_evidence
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3SemanticEvidenceV1,
    G3SemanticLocatorV1,
    G3SemanticMaterialV1,
    G3SemanticReferenceResponseV1,
    G3SemanticResponseV1,
    _structural_id,
    _unique_json_bytes,
)
from insurance_harness.run_admission.g3_models import canonical_json


def assemble_source_proposals(
    *,
    response: G3SemanticResponseV1,
    corpus: BatchCorpusV1,
    requested_material_ids: tuple[str, ...],
    allowed_material_roles: tuple[str, ...],
    allowed_taxonomy_labels: tuple[str, ...],
    model_request_sha256: str,
    resolve_evidence: Callable[[str, G3SemanticLocatorV1], Evidence],
) -> tuple[MaterialProposalV1, ...]:
    if tuple(sorted(set(requested_material_ids))) != requested_material_ids:
        raise ValueError("requested materials must be sorted unique")
    entries = {entry.material_id: entry for entry in corpus.entries}
    material_ids = tuple(item.material_id for item in response.materials)
    if material_ids != tuple(sorted(set(material_ids))) or any(
        item not in requested_material_ids or item not in entries for item in material_ids
    ):
        raise ValueError("semantic material scope mismatch")
    proposals: list[MaterialProposalV1] = []
    for material in response.materials:
        entry = entries[material.material_id]
        if material.material_role not in allowed_material_roles:
            raise ValueError("material role outside policy")
        evidence_refs = tuple(item.evidence_ref for item in material.evidence)
        entity_refs = tuple(item.entity_ref for item in material.entities)
        if (
            evidence_refs != tuple(sorted(set(evidence_refs)))
            or entity_refs != tuple(sorted(set(entity_refs)))
            or material.material_role_evidence_refs
            != tuple(sorted(set(material.material_role_evidence_refs)))
            or not material.entities
            or not material.evidence
        ):
            raise ValueError("semantic refs must be sorted unique")
        sources = {(block.revision_id, block.block_id): block for block in entry.blocks}
        evidence_by_local: dict[str, tuple[G3SemanticEvidenceV1, Evidence]] = {}
        for semantic in material.evidence:
            evidence = resolve_evidence(material.material_id, semantic.locator)
            verify_evidence(evidence, tuple(sources.values()))
            if (evidence.start, evidence.end, evidence.quote, evidence.quote_hash) != (
                semantic.locator.start,
                semantic.locator.end,
                semantic.locator.quote,
                hashlib.sha256(semantic.locator.quote.encode()).hexdigest(),
            ):
                raise ValueError("resolved semantic evidence locator mismatch")
            if semantic.purpose == "material_role":
                valid_shape = semantic.entity_ref is None and semantic.field_key is None
            elif semantic.purpose == "field":
                valid_shape = semantic.entity_ref is not None and semantic.field_key is not None
            else:
                valid_shape = semantic.entity_ref is not None and semantic.field_key is None
            if not valid_shape:
                raise ValueError("semantic evidence scope invalid")
            evidence_by_local[semantic.evidence_ref] = (
                semantic,
                evidence,
            )
        final_evidence = tuple(
            ProposalEvidenceV1(
                evidence_id=_structural_id(
                    "g3-c-evidence-ref.830.v1",
                    material.material_id,
                    semantic.evidence_ref,
                ),
                entity_proposal_ref=(
                    None
                    if semantic.entity_ref is None
                    else _structural_id(
                        "g3-c-entity-ref.830.v1",
                        material.material_id,
                        semantic.entity_ref,
                    )
                ),
                purpose=semantic.purpose,
                field_key=semantic.field_key,
                evidence=evidence,
            )
            for semantic, evidence in evidence_by_local.values()
        )
        final_entities: list[EntityProposalV1] = []
        for entity in material.entities:
            if entity.identity_evidence_refs != tuple(sorted(set(entity.identity_evidence_refs))):
                raise ValueError("identity evidence refs must be sorted unique")
            if not entity.labels or any(
                label.taxonomy_label not in allowed_taxonomy_labels for label in entity.labels
            ):
                raise ValueError("taxonomy label outside policy")
            if tuple(label.taxonomy_label for label in entity.labels) != tuple(
                sorted({label.taxonomy_label for label in entity.labels})
            ):
                raise ValueError("labels must be sorted unique")
            if sum(label.taxonomy_label == entity.primary_label for label in entity.labels) != 1:
                raise ValueError("primary label mismatch")
            referenced = set(entity.identity_evidence_refs)
            referenced.update(ref for label in entity.labels for ref in label.evidence_refs)
            if any(ref not in evidence_by_local for ref in referenced):
                raise ValueError("dangling semantic evidence ref")
            for ref in entity.identity_evidence_refs:
                evidence_model = evidence_by_local[ref][0]
                if evidence_model.entity_ref != entity.entity_ref or evidence_model.purpose in {
                    "classification",
                    "material_role",
                    "field",
                }:
                    raise ValueError("wrong-purpose identity evidence")
            for label in entity.labels:
                if (
                    label.evidence_refs != tuple(sorted(set(label.evidence_refs)))
                    or not label.evidence_refs
                    or any(
                        evidence_by_local[ref][0].entity_ref != entity.entity_ref
                        or evidence_by_local[ref][0].purpose != "classification"
                        for ref in label.evidence_refs
                    )
                ):
                    raise ValueError("classification evidence mismatch")
            identity_values = {
                "issuer": () if entity.issuer is None else (entity.issuer,),
                "name": () if entity.name is None else (entity.name,),
                "product_code": (() if entity.product_code is None else (entity.product_code,)),
                "version": tuple(
                    value
                    for value in (
                        entity.version_label,
                        None
                        if entity.filing_or_registration is None
                        else entity.filing_or_registration.value,
                    )
                    if value is not None
                ),
            }
            identity_rows = tuple(
                evidence_by_local[ref][0] for ref in entity.identity_evidence_refs
            )
            if any(
                not any(
                    row.purpose == purpose and _normalized(value) in _normalized(row.locator.quote)
                    for row in identity_rows
                )
                for purpose, values in identity_values.items()
                for value in values
            ):
                raise ValueError("identity value lacks exact source evidence")
            for date in (entity.valid_from, entity.valid_through):
                if date is not None and not any(
                    row.purpose == "version" and date in row.locator.quote for row in identity_rows
                ):
                    raise ValueError("validity date lacks version evidence")
            final_entities.append(
                EntityProposalV1(
                    proposal_ref=_structural_id(
                        "g3-c-entity-ref.830.v1",
                        material.material_id,
                        entity.entity_ref,
                    ),
                    issuer=entity.issuer,
                    name=entity.name,
                    product_code=entity.product_code,
                    version_label=entity.version_label,
                    filing_or_registration=(
                        None
                        if entity.filing_or_registration is None
                        else VersionAnchorV1.model_validate(
                            entity.filing_or_registration.model_dump()
                        )
                    ),
                    identity_confidence=entity.identity_confidence,
                    identity_evidence_ids=tuple(
                        sorted(
                            _structural_id("g3-c-evidence-ref.830.v1", material.material_id, ref)
                            for ref in entity.identity_evidence_refs
                        )
                    ),
                    labels=tuple(
                        LabelProposalV1(
                            taxonomy_label=label.taxonomy_label,
                            confidence=label.confidence,
                            evidence_ids=tuple(
                                sorted(
                                    _structural_id(
                                        "g3-c-evidence-ref.830.v1",
                                        material.material_id,
                                        ref,
                                    )
                                    for ref in label.evidence_refs
                                )
                            ),
                        )
                        for label in entity.labels
                    ),
                    primary_label=entity.primary_label,
                    valid_from=entity.valid_from,
                    valid_through=entity.valid_through,
                )
            )
        payload: dict[str, object] = {
            "material_id": material.material_id,
            "corpus_entry_sha256": entry.entry_sha256,
            "model_request_sha256": model_request_sha256,
            "material_role": material.material_role,
            "material_role_evidence_ids": tuple(
                sorted(
                    _structural_id("g3-c-evidence-ref.830.v1", material.material_id, ref)
                    for ref in material.material_role_evidence_refs
                )
            ),
            "entities": tuple(sorted(final_entities, key=lambda item: item.proposal_ref)),
            "evidence": tuple(sorted(final_evidence, key=lambda item: item.evidence_id)),
        }
        proposals.append(
            MaterialProposalV1.model_validate(
                {
                    **payload,
                    "proposal_sha256": _batch_sha256("material-proposal.830.g3.v1", payload),
                }
            )
        )
    return tuple(proposals)


def resolve_source_references(
    raw: bytes,
    *,
    requested_material_ids: tuple[str, ...],
    locators: Mapping[tuple[str, str], G3SemanticLocatorV1],
) -> G3SemanticResponseV1:
    response = G3SemanticReferenceResponseV1.model_validate(_unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("reference response typed wire mismatch")
    materials = []
    for material in response.materials:
        if material.material_id not in requested_material_ids:
            raise ValueError("reference material outside call")
        evidence = []
        for row in material.evidence:
            resolved_locator = locators.get((material.material_id, row.locator_ref))
            if resolved_locator is None:
                raise ValueError("unknown or foreign source locator reference")
            evidence.append(
                G3SemanticEvidenceV1(
                    **row.model_dump(exclude={"locator_ref"}),
                    locator=resolved_locator,
                )
            )
        entities = []
        for entity in material.entities:
            labels = tuple(
                label.model_copy(update={"evidence_refs": tuple(sorted(label.evidence_refs))})
                for label in sorted(entity.labels, key=lambda row: row.taxonomy_label)
            )
            entities.append(
                entity.model_copy(
                    update={
                        "identity_evidence_refs": tuple(sorted(entity.identity_evidence_refs)),
                        "labels": labels,
                    }
                )
            )
        materials.append(
            G3SemanticMaterialV1(
                **material.model_dump(
                    exclude={"evidence", "entities", "material_role_evidence_refs"}
                ),
                evidence=tuple(sorted(evidence, key=lambda row: row.evidence_ref)),
                entities=tuple(sorted(entities, key=lambda row: row.entity_ref)),
                material_role_evidence_refs=tuple(sorted(material.material_role_evidence_refs)),
            )
        )
    return G3SemanticResponseV1(
        contract="g3-batch-resolution-semantic-response.local.v1",
        materials=tuple(sorted(materials, key=lambda row: row.material_id)),
    )

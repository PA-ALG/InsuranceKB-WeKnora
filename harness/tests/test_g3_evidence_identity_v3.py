from __future__ import annotations

from typing import TypedDict

import pytest

from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as g
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import _build_entity_bindings
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import SchemaPackCatalogV1
from tests.test_batch_entity_resolution_830_g3 import (
    _corpus,
    _entry,
    _existing,
    _material_proposal,
    _model_binding,
    _new,
    _policy,
    _proposal_batch,
)
from tests.test_batch_entity_resolution_830_g3 import (
    catalog as catalog,
)

V3 = "batch-entity-resolution-compiler.830.g3.v3"


class ResolutionArgs(TypedDict):
    corpus: g.BatchCorpusV1
    proposals: g.ProposalBatchV1
    existing_entities: g.ExistingEntitySnapshotV1
    policy: g.BatchResolutionPolicyV1


def joint_fixture() -> ResolutionArgs:
    rows: list[tuple[str, str, str | None, str | None, str | None]] = [
        ("a-brochure", "brochure", "平安保险", None, None),
        ("b-terms", "terms", None, "MED1", "REG1"),
        ("c-rates", "rate-table", None, None, None),
    ]
    entries = tuple(
        _entry(material_id=k, text="平安保险 平安测试医疗保险 2026 MED1 REG1 官方条款")
        for k, *_ in rows
    )
    corpus = _corpus(*entries)
    receipt = _model_binding(corpus, *entries)
    proposals = _proposal_batch(
        corpus,
        (receipt,),
        tuple(
            _material_proposal(
                entry,
                receipt,
                role=role,
                entities=(
                    {
                        "proposal_ref": "product",
                        "issuer": issuer,
                        "name": "平安测试医疗保险",
                        "product_code": code,
                        "version_label": "2026" if role == "terms" else None,
                        "filing": filing,
                    },
                ),
            )
            for entry, (_, role, issuer, code, filing) in zip(entries, rows, strict=True)
        ),
    )
    policy = _policy()
    rules = tuple(
        r.model_copy(update={"material_roles": ("brochure", "rate-table", "terms")})
        for r in policy.rules
    )
    policy = _new(
        g.BatchResolutionPolicyV1,
        policy.contract,
        "policy_sha256",
        **policy.model_dump(exclude={"rules", "policy_sha256"}),
        rules=rules,
    )
    return dict(corpus=corpus, proposals=proposals, existing_entities=_existing(), policy=policy)


def test_joint_complementary_sources_preserve_original_nulls_and_compile(
    catalog: SchemaPackCatalogV1,
) -> None:  # noqa: F811
    args = joint_fixture()
    original = args["proposals"].model_dump_json()
    old = [
        g.resolve_batch(catalog=catalog, **args, compiler_version=v)
        for v in (g._COMPILER_VERSION, g.COMPILER_VERSION_V2)
    ]
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=V3)
    assert [r.disposition for r in result.decisions] == ["CREATE"] * 3
    assert args["proposals"].model_dump_json() == original
    children = [p.children[0] for p in result.decisions]
    assert all(c.entity_candidate is not None for c in children)
    assert (
        len(
            {
                c.entity_candidate.candidate_sha256
                for c in children
                if c.entity_candidate is not None
            }
        )
        == 1
    )
    refs = tuple((p.material_id, p.entities[0].proposal_ref) for p in args["proposals"].proposals)
    bindings = _build_entity_bindings(
        catalog=catalog, proposals=args["proposals"], resolution=result, selected_decision_refs=refs
    )
    assert len(bindings) == 1
    assert bindings[0].source_material_ids == tuple(x[0] for x in refs)
    assert {e.material_id for e in bindings[0].resolution_evidence} == set(
        bindings[0].source_material_ids
    )
    with pytest.raises(ValueError, match="RESOLUTION_IDENTITY_SOURCE_REQUIRED"):
        _build_entity_bindings(
            catalog=catalog,
            proposals=args["proposals"],
            resolution=result,
            selected_decision_refs=refs[1:],
        )
    assert [
        g.resolve_batch(catalog=catalog, **args, compiler_version=v)
        for v in (g._COMPILER_VERSION, g.COMPILER_VERSION_V2)
    ] == old


def revise(
    args: ResolutionArgs,
    material_id: str,
    *,
    entity_updates: dict[str, object] | None = None,
    drop_purpose: str | None = None,
) -> ResolutionArgs:
    originals = args["proposals"]
    changed = []
    for proposal in originals.proposals:
        if proposal.material_id != material_id:
            changed.append(proposal)
            continue
        entity = proposal.entities[0]
        if entity_updates:
            entity = entity.model_copy(update=entity_updates)
        if drop_purpose:
            missing = {e.evidence_id for e in proposal.evidence if e.purpose == drop_purpose}
            entity = entity.model_copy(
                update={
                    "identity_evidence_ids": tuple(
                        e for e in entity.identity_evidence_ids if e not in missing
                    )
                }
            )
        changed.append(
            _new(
                g.MaterialProposalV1,
                "material-proposal.830.g3.v1",
                "proposal_sha256",
                **proposal.model_dump(exclude={"entities", "proposal_sha256"}),
                entities=(entity,),
            )
        )
    return {
        **args,
        "proposals": _proposal_batch(args["corpus"], originals.model_receipts, tuple(changed)),
    }


@pytest.mark.parametrize("purpose", ["issuer", "product_code", "version", "name"])
def test_missing_support_never_borrows_another_documents_evidence(
    catalog: SchemaPackCatalogV1, purpose: str
) -> None:  # noqa: F811
    args = joint_fixture()
    material = "a-brochure" if purpose == "issuer" else "b-terms"
    args = revise(args, material, drop_purpose=purpose)
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=V3)
    assert all(row.disposition not in {"CREATE", "MATCH"} for row in result.decisions)


def test_different_nonempty_claim_with_own_evidence_rejects_whole_same_name_group(
    catalog: SchemaPackCatalogV1,
) -> None:  # noqa: F811
    args = joint_fixture()
    # Both observed values are exact source evidence; different dates are a real conflict.
    entry = args["corpus"].entries[0]
    new_entry = _entry(material_id=entry.material_id, text=entry.blocks[0].text + " 2027")
    entries = (new_entry, *args["corpus"].entries[1:])
    corpus = _corpus(*entries)
    receipt = _model_binding(corpus, *entries)
    rows: list[g.MaterialProposalV1] = []
    for i, old in enumerate(args["proposals"].proposals):
        e = old.entities[0]
        rows.append(
            _material_proposal(
                entries[i],
                receipt,
                role=old.material_role,
                entities=(
                    {
                        "proposal_ref": e.proposal_ref,
                        "issuer": e.issuer,
                        "name": e.name,
                        "product_code": e.product_code,
                        "version_label": "2027" if i == 0 else e.version_label,
                        "filing": None
                        if e.filing_or_registration is None
                        else e.filing_or_registration.value,
                    },
                ),
            )
        )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), tuple(rows)),
        existing_entities=args["existing_entities"],
        policy=args["policy"],
        compiler_version=V3,
    )
    assert all(row.disposition == "NEEDS_CONFIRM" for row in result.decisions)
    assert all("AMBIGUOUS_IDENTITY" in row.children[0].reason_codes for row in result.decisions)


def test_source_revision_tampering_blocks_joint_group(catalog: SchemaPackCatalogV1) -> None:  # noqa: F811
    args = joint_fixture()
    own = args["proposals"].proposals[0]
    altered = _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **own.model_dump(exclude={"corpus_entry_sha256", "proposal_sha256"}),
        corpus_entry_sha256="f" * 64,
    )
    args["proposals"] = _proposal_batch(
        args["corpus"],
        args["proposals"].model_receipts,
        (altered, *args["proposals"].proposals[1:]),
    )
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=V3)
    assert result.decisions[0].disposition == "QUARANTINE"
    assert all(row.disposition not in {"CREATE", "MATCH"} for row in result.decisions)

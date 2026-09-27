from __future__ import annotations

from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as g
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import SchemaPackCatalogV1
from tests.test_batch_entity_resolution_830_g3 import (
    ResolveArgs,
    _corpus,
    _entry,
    _existing,
    _material_proposal,
    _model_binding,
    _policy,
    _proposal_batch,
)
from tests.test_batch_entity_resolution_830_g3 import catalog as catalog

V2 = "batch-entity-resolution-compiler.830.g3.v2"


def test_filing_anchored_versions_do_not_need_an_extra_title_label(
    catalog: SchemaPackCatalogV1,
) -> None:
    entries = tuple(
        _entry(
            material_id=f"m{i}",
            text=f"平安保险 平安长期医疗保险 产品代码 1072 备案编号 REG{i} 医疗保险 官方条款",
        )
        for i in (2020, 2021)
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
                entities=(
                    {
                        "proposal_ref": "product",
                        "name": "平安长期医疗保险",
                        "product_code": "1072",
                        "version_label": None,
                        "filing": f"REG{i}",
                    },
                ),
            )
            for i, entry in zip((2020, 2021), entries, strict=True)
        ),
    )
    args: ResolveArgs = dict(
        catalog=catalog,
        corpus=corpus,
        proposals=proposals,
        existing_entities=_existing(),
        policy=_policy(),
    )
    original = g.resolve_batch(**args)
    assert all(row.disposition == "NEEDS_CONFIRM" for row in original.decisions)
    result = g.resolve_batch(**args, compiler_version=V2)
    assert [row.disposition for row in result.decisions] == ["CREATE", "CREATE"]
    raw_candidates = [row.children[0].entity_candidate for row in result.decisions]
    assert all(row is not None for row in raw_candidates)
    candidates = [row for row in raw_candidates if row is not None]
    assert len({row.version_candidate_key_sha256 for row in candidates}) == 2
    assert {row.version_anchor.observed_value for row in candidates} == {"REG2020", "REG2021"}
    assert g.resolve_batch(**args) == original, "the existing v1 release semantics stay unchanged"


def test_brochure_association_keeps_each_documents_own_evidence(
    catalog: SchemaPackCatalogV1,
) -> None:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        _build_entity_bindings,
    )
    from tests.test_batch_entity_resolution_830_g3 import _new

    terms = _entry(
        material_id="m-terms",
        text="平安保险 平安全能版医疗保险 产品代码 MED1 备案编号 REG1 版本全能版 医疗保险 官方条款",
    )
    brochure = _entry(
        material_id="m-brochure",
        text="平安保险 平安全能版医疗保险 全能版 医疗保险 官方条款 产品说明书",
    )
    corpus = _corpus(brochure, terms)
    receipt = _model_binding(corpus, brochure, terms)
    proposals = _proposal_batch(
        corpus,
        (receipt,),
        tuple(
            sorted(
                (
                    _material_proposal(
                        terms,
                        receipt,
                        entities=(
                            {
                                "proposal_ref": "terms-product",
                                "name": "平安全能版医疗保险",
                                "product_code": "MED1",
                                "version_label": "全能版",
                                "filing": "REG1",
                            },
                        ),
                    ),
                    _material_proposal(
                        brochure,
                        receipt,
                        role="brochure",
                        entities=(
                            {
                                "proposal_ref": "brochure-product",
                                "name": "平安全能版医疗保险",
                                "product_code": None,
                                "version_label": "全能版",
                                "filing": None,
                            },
                        ),
                    ),
                ),
                key=lambda row: row.material_id,
            )
        ),
    )
    policy = _policy()
    rule = policy.rules[0].model_copy(update={"material_roles": ("brochure", "terms")})
    policy = _new(
        g.BatchResolutionPolicyV1,
        policy.contract,
        "policy_sha256",
        **policy.model_dump(exclude={"rules", "policy_sha256"}),
        rules=(rule,),
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=proposals,
        existing_entities=_existing(),
        policy=policy,
        compiler_version=V2,
    )
    assert [row.disposition for row in result.decisions] == ["CREATE", "CREATE"]
    by_id = {row.material_id: row.children[0] for row in result.decisions}
    assert by_id["m-brochure"].entity_candidate == by_id["m-terms"].entity_candidate
    bindings = _build_entity_bindings(
        catalog=catalog,
        proposals=proposals,
        resolution=result,
        selected_decision_refs=(("m-brochure", "brochure-product"), ("m-terms", "terms-product")),
    )
    assert len(bindings) == 1
    assert bindings[0].source_material_ids == ("m-brochure", "m-terms")
    assert {row.material_id for row in bindings[0].resolution_evidence} == {"m-brochure", "m-terms"}
    assert (
        next(row for row in proposals.proposals if row.material_id == "m-brochure")
        .entities[0]
        .product_code
        is None
    )
    import pytest

    with pytest.raises(ValueError, match="RESOLUTION_IDENTITY_SOURCE_REQUIRED"):
        _build_entity_bindings(
            catalog=catalog,
            proposals=proposals,
            resolution=result,
            selected_decision_refs=(("m-brochure", "brochure-product"),),
        )
    # A model string alone cannot establish any of the brochure's own claims.
    for purpose in ("name", "issuer", "version"):
        own = next(row for row in proposals.proposals if row.material_id == "m-brochure")
        missing_ids = {row.evidence_id for row in own.evidence if row.purpose == purpose}
        entity = own.entities[0].model_copy(
            update={
                "identity_evidence_ids": tuple(
                    eid for eid in own.entities[0].identity_evidence_ids if eid not in missing_ids
                )
            }
        )
        own = _new(
            g.MaterialProposalV1,
            "material-proposal.830.g3.v1",
            "proposal_sha256",
            **own.model_dump(exclude={"entities", "proposal_sha256"}),
            entities=(entity,),
        )
        missing = _proposal_batch(
            corpus,
            (receipt,),
            tuple(
                own if row.material_id == own.material_id else row for row in proposals.proposals
            ),
        )
        rejected = g.resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=missing,
            existing_entities=_existing(),
            policy=policy,
            compiler_version=V2,
        )
        assert rejected.decisions[0].disposition == "NEEDS_CONFIRM", purpose


def test_directory_resolver_covers_all_rows_instead_of_model_sample(
    catalog: SchemaPackCatalogV1,
) -> None:
    from tests.test_batch_entity_resolution_830_g3 import _new

    text = (
        "平安保险 产品一览表\n险种代码 险种名称\n001 平安甲医疗保险\n"
        "002 平安乙重大疾病保险\n003 平安丙年金保险\n官方条款"
    )
    entry = _entry(material_id="directory", text=text)
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        role="product-list",
        entities=(
            {
                "proposal_ref": "sample",
                "name": "平安甲医疗保险",
                "product_code": "001",
                "version_label": None,
                "filing": None,
            },
        ),
    )
    proposals = _proposal_batch(corpus, (receipt,), (proposal,))
    policy = _policy()
    rule = policy.rules[0].model_copy(update={"material_roles": ("product-list", "terms")})
    policy = _new(
        g.BatchResolutionPolicyV1,
        policy.contract,
        "policy_sha256",
        **policy.model_dump(exclude={"rules", "policy_sha256"}),
        rules=(rule,),
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=proposals,
        existing_entities=_existing(),
        policy=policy,
        compiler_version=V2,
    )
    assert result.decisions[0].disposition == "MULTI"
    codes = [child.anchors.product_code for child in result.decisions[0].children]
    assert all(code is not None for code in codes)
    assert {code.observed_value for code in codes if code is not None} == {"001", "002", "003"}
    assert len(proposals.proposals[0].entities) == 1, (
        "the original sampled model response is unchanged"
    )

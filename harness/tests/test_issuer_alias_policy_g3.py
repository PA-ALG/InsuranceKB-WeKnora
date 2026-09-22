"""A declared issuer equivalence is policy, never rewritten source evidence."""

from copy import deepcopy

import pytest

from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as g
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import _build_entity_bindings
from tests.test_batch_entity_resolution_830_g3 import (
    _corpus,
    _entry,
    _existing,
    _material_proposal,
    _model_binding,
    _new,
    _policy,
    _proposal_batch,
    catalog,  # noqa: F401
)
from tests.test_g3_evidence_identity_v3 import joint_fixture

DECLARATION = dict(
    canonical_name="中国平安人寿保险股份有限公司",
    aliases=["平安人寿"],
    space_ids=["space-g3"],
    confirmation_ref="user-confirmation-2026-09-22",
)


def declared_policy(*, declaration=None):
    p = joint_fixture()["policy"]
    return _new(
        g.BatchResolutionPolicyV1,
        p.contract,
        "policy_sha256",
        **p.model_dump(exclude={"policy_sha256", "policy_version"}),
        policy_version="issuer-confirmed-1",
        issuer_aliases=[declaration or DECLARATION],
    )


def issuer_fixture(*, policy=None, other_issuer="平安人寿", version="2026"):
    rows = [
        ("a-brochure", "brochure", DECLARATION["canonical_name"], None, None),
        ("b-terms", "terms", other_issuer, "MED1", "REG1"),
        ("c-rates", "rate-table", None, None, None),
    ]
    entries = tuple(
        _entry(
            material_id=k,
            text=(f"中国平安人寿保险股份有限公司 {other_issuer} "
                  f"平安测试医疗保险 {version} MED1 REG1 官方条款"),
        )
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
                        "version_label": version if role == "terms" else None,
                        "filing": filing,
                    },
                ),
            )
            for entry, (_, role, issuer, code, filing) in zip(entries, rows, strict=True)
        ),
    )
    return dict(
        corpus=corpus,
        proposals=proposals,
        existing_entities=_existing(),
        policy=policy or joint_fixture()["policy"],
    )


def test_confirmed_issuer_equivalence_keeps_own_evidence_and_one_binding(catalog):  # noqa: F811
    args = issuer_fixture(policy=declared_policy())
    raw = args["proposals"].model_dump_json()
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=g.COMPILER_VERSION_V3)
    assert [x.disposition for x in result.decisions] == ["CREATE"] * 3
    assert {x.children[0].anchors.issuer.observed_value for x in result.decisions} == {
        DECLARATION["canonical_name"]
    }
    assert args["proposals"].model_dump_json() == raw
    refs = tuple((p.material_id, p.entities[0].proposal_ref) for p in args["proposals"].proposals)
    bindings = _build_entity_bindings(
        catalog=catalog, proposals=args["proposals"], resolution=result, selected_decision_refs=refs
    )
    assert len(bindings) == 1
    assert len(bindings[0].source_material_ids) == 3


@pytest.mark.parametrize("mode", ["absent", "different_space", "different_issuer"])
def test_unconfirmed_or_unrelated_issuer_never_merges(catalog, mode):  # noqa: F811
    declaration = deepcopy(DECLARATION)
    if mode == "different_space":
        declaration["space_ids"] = ["another-space"]
    args = issuer_fixture(
        policy=None if mode == "absent" else declared_policy(declaration=declaration),
        other_issuer="另一保险公司" if mode == "different_issuer" else "平安人寿",
    )
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=g.COMPILER_VERSION_V3)
    assert all(x.disposition not in {"CREATE", "MATCH"} for x in result.decisions)


def test_legacy_policy_wire_is_unchanged():
    p = _policy()
    assert "issuer_aliases" not in p.model_dump()
    assert g.BatchResolutionPolicyV1.model_validate_json(p.model_dump_json()) == p


@pytest.mark.parametrize(
    "aliases",
    [
        [],
        None,
        [DECLARATION, DECLARATION],
        [{**DECLARATION, "aliases": ["平安人寿", "平安人寿"]}],
        [{**DECLARATION, "aliases": [DECLARATION["canonical_name"]]}],
        [{**DECLARATION, "space_ids": []}],
    ],
)
def test_invalid_declarations_rejected(aliases):
    p = _policy()
    with pytest.raises(ValueError):
        _new(
            g.BatchResolutionPolicyV1,
            p.contract,
            "policy_sha256",
            **p.model_dump(exclude={"policy_sha256"}),
            issuer_aliases=aliases,
        )


@pytest.mark.parametrize("existing_issuer", ["平安人寿", DECLARATION["canonical_name"]])
def test_confirmed_issuer_matches_published_product_without_mutating_it(catalog, existing_issuer):  # noqa: F811
    args = issuer_fixture(policy=declared_policy())
    existing = g.ExistingEntityV1(
        entity_id="published-product",
        entity_version="published-product@1",
        product_id=None,
        product_version_id=None,
        issuer=existing_issuer,
        name="平安测试医疗保险",
        product_code="MED1",
        version_label="2026",
        filing_or_registration=g.VersionAnchorV1(kind="registration_number", value="REG1"),
        approved_aliases=(),
        identity_evidence_sha256s=(),
    )
    args["existing_entities"] = _existing(existing)
    before = args["existing_entities"].model_dump_json()
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=g.COMPILER_VERSION_V3)
    assert [x.disposition for x in result.decisions] == ["MATCH"] * 3
    assert args["existing_entities"].model_dump_json() == before


def test_policy_declaration_is_bound_by_policy_hash():
    payload = declared_policy().model_dump(mode="json")
    payload["issuer_aliases"][0]["confirmation_ref"] = "unapproved-replacement"
    with pytest.raises(ValueError, match="policy hash mismatch"):
        g.BatchResolutionPolicyV1.model_validate(payload)


def test_overlapping_alias_declarations_are_rejected():
    p = _policy()
    rows = [DECLARATION, {**DECLARATION, "canonical_name": "另一个公司"}]
    rows.sort(key=lambda x: x["canonical_name"])
    with pytest.raises(ValueError, match="overlap"):
        _new(
            g.BatchResolutionPolicyV1,
            p.contract,
            "policy_sha256",
            **p.model_dump(exclude={"policy_sha256"}),
            issuer_aliases=rows,
        )

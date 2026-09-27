"""A declared issuer equivalence is policy, never rewritten source evidence."""

from copy import deepcopy
from typing import Any

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
from tests.test_g3_evidence_identity_v3 import ResolutionArgs, joint_fixture

DECLARATION: dict[str, Any] = dict(
    canonical_name="中国平安人寿保险股份有限公司",
    aliases=["平安人寿"],
    space_ids=["space-g3"],
    confirmation_ref="user-confirmation-2026-09-22",
)


def declared_policy(*, declaration: dict[str, Any] | None = None) -> g.BatchResolutionPolicyV1:
    p = joint_fixture()["policy"]
    return _new(
        g.BatchResolutionPolicyV1,
        p.contract,
        "policy_sha256",
        **p.model_dump(exclude={"policy_sha256", "policy_version"}),
        policy_version="issuer-confirmed-1",
        issuer_aliases=[declaration or DECLARATION],
    )


def issuer_fixture(
    *,
    policy: g.BatchResolutionPolicyV1 | None = None,
    other_issuer: str = "平安人寿",
    version: str = "2026",
) -> ResolutionArgs:
    rows: list[tuple[str, str, str | None, str | None, str | None]] = [
        ("a-brochure", "brochure", DECLARATION["canonical_name"], None, None),
        ("b-terms", "terms", other_issuer, "MED1", "REG1"),
        ("c-rates", "rate-table", None, None, None),
    ]
    entries = tuple(
        _entry(
            material_id=k,
            text=(
                f"中国平安人寿保险股份有限公司 {other_issuer} "
                f"平安测试医疗保险 {version} MED1 REG1 官方条款"
            ),
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


def test_confirmed_issuer_equivalence_keeps_own_evidence_and_one_binding(
    catalog: SchemaPackCatalogV1,
) -> None:  # noqa: F811
    args = issuer_fixture(policy=declared_policy())
    raw = args["proposals"].model_dump_json()
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=g.COMPILER_VERSION_V3)
    assert [x.disposition for x in result.decisions] == ["CREATE"] * 3
    issuers = [x.children[0].anchors.issuer for x in result.decisions]
    assert all(issuer is not None for issuer in issuers)
    assert {issuer.observed_value for issuer in issuers if issuer is not None} == {
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
def test_unconfirmed_or_unrelated_issuer_never_merges(
    catalog: SchemaPackCatalogV1, mode: str
) -> None:  # noqa: F811
    declaration = deepcopy(DECLARATION)
    if mode == "different_space":
        declaration["space_ids"] = ["another-space"]
    args = issuer_fixture(
        policy=None if mode == "absent" else declared_policy(declaration=declaration),
        other_issuer="另一保险公司" if mode == "different_issuer" else "平安人寿",
    )
    result = g.resolve_batch(catalog=catalog, **args, compiler_version=g.COMPILER_VERSION_V3)
    assert all(x.disposition not in {"CREATE", "MATCH"} for x in result.decisions)


def test_legacy_policy_wire_is_unchanged() -> None:
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
def test_invalid_declarations_rejected(aliases: list[str]) -> None:
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
def test_confirmed_issuer_matches_published_product_without_mutating_it(
    catalog: SchemaPackCatalogV1, existing_issuer: str
) -> None:  # noqa: F811
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


def test_policy_declaration_is_bound_by_policy_hash() -> None:
    payload = declared_policy().model_dump(mode="json")
    payload["issuer_aliases"][0]["confirmation_ref"] = "unapproved-replacement"
    with pytest.raises(ValueError, match="policy hash mismatch"):
        g.BatchResolutionPolicyV1.model_validate(payload)


def test_overlapping_alias_declarations_are_rejected() -> None:
    p = _policy()
    rows: list[dict[str, Any]] = [
        DECLARATION,
        {**DECLARATION, "canonical_name": "另一个公司"},
    ]
    rows.sort(key=lambda x: x["canonical_name"])
    with pytest.raises(ValueError, match="overlap"):
        _new(
            g.BatchResolutionPolicyV1,
            p.contract,
            "policy_sha256",
            **p.model_dump(exclude={"policy_sha256"}),
            issuer_aliases=rows,
        )


def test_legacy_issuer_policy_revalidates_default_without_explicit_aliases() -> None:
    policy = _policy()
    assert policy.issuer_aliases == ()
    assert "issuer_aliases" not in policy.model_fields_set
    assert g.BatchResolutionPolicyV1.model_validate(policy) == policy
    assert "issuer_aliases" not in policy.model_dump()
    assert g.BatchResolutionPolicyV1.model_validate(policy.model_dump()) == policy
    assert g.BatchResolutionPolicyV1.model_validate_json(policy.model_dump_json()) == policy


@pytest.mark.parametrize("explicit_empty", [[], ()])
def test_legacy_issuer_policy_still_rejects_explicit_empty_aliases(
    explicit_empty: list[object] | tuple[()],
) -> None:
    import json

    payload = {**_policy().model_dump(), "issuer_aliases": explicit_empty}
    with pytest.raises(ValueError, match="issuer_aliases"):
        g.BatchResolutionPolicyV1.model_validate(payload)
    with pytest.raises(ValueError, match="issuer_aliases"):
        g.BatchResolutionPolicyV1.model_validate_json(json.dumps(payload))

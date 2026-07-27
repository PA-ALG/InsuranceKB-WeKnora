"""OpenSpec 041: exact ProductVersion resolution without identity guessing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    InsuranceProduct,
    ProductAlias,
    ProductVersion,
)
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.version_resolver import (
    RESOLVER_POLICY_HASH,
    RESOLVER_VERSION,
    ProductVersionQuarantine,
    ProductVersionResolutionRequest,
    ProductVersionResolver,
    inherit_fragment_resolution,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "product_version_resolver_041.json"


@pytest.fixture
def scope(bound_scope: Callable[..., KnowledgeScope]) -> KnowledgeScope:
    return bound_scope(
        tenant_id="tenant-version-resolver",
        raw_kb_id="raw-version-resolver",
        wiki_kb_id="wiki-version-resolver",
    )


@pytest.fixture
def catalog(session: Session, scope: KnowledgeScope) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for product_data in payload["products"]:
        product = InsuranceProduct(
            id=product_data["id"],
            space_id=scope.space_id,
            product_code=product_data["product_code"],
            canonical_name=product_data["canonical_name"],
            category=product_data["category"],
            status="在售",
            filing_no=product_data["filing_no"],
        )
        session.add(product)
        session.flush()
        for version_data in product_data["versions"]:
            session.add(
                ProductVersion(
                    id=version_data["id"],
                    space_id=scope.space_id,
                    product_id=product.id,
                    version_label=version_data["version_label"],
                    terms_revision=version_data["terms_revision"],
                    channels=version_data["channels"],
                    regions=version_data["regions"],
                )
            )
        for alias_data in product_data["aliases"]:
            session.add(
                ProductAlias(
                    product_id=product.id,
                    alias=alias_data["alias"],
                    alias_type=alias_data["alias_type"],
                    source=alias_data["source"],
                )
            )
    session.commit()
    return payload


@pytest.fixture
def resolver(
    session: Session,
    scope: KnowledgeScope,
    catalog: dict[str, Any],
) -> ProductVersionResolver:
    assert catalog["schema_version"] == "041.fixture.v1"
    return ProductVersionResolver(session, scope)


def _request(scope: KnowledgeScope, **updates: object) -> ProductVersionResolutionRequest:
    values: dict[str, object] = {
        "source_space_id": scope.space_id,
        "document_ref": "dataset/version-materials/test.pdf",
    }
    values.update(updates)
    return ProductVersionResolutionRequest.model_validate(values)


def _quarantine(
    resolver: ProductVersionResolver,
    request: ProductVersionResolutionRequest,
    reason_code: str,
) -> ProductVersionQuarantine:
    with pytest.raises(ProductVersionQuarantine) as caught:
        resolver.resolve(request)
    assert caught.value.reason_code == reason_code
    assert caught.value.candidate_version_ids == tuple(
        sorted(caught.value.candidate_version_ids)
    )
    return caught.value


def test_real_version_material_fixture_is_byte_bound(catalog: dict[str, Any]) -> None:
    records = {
        version["version_label"]: version
        for product in catalog["products"]
        for version in product["versions"]
        if "source_document" in version
    }
    for label in ("1072-1", "1072-4", "596-1", "2609-1"):
        record = records[label]
        source = REPO_ROOT / record["source_document"]
        assert source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record["source_sha256"]


@pytest.mark.parametrize(
    ("filing_number", "version_id", "version_label"),
    [
        ("平安人寿[2020]医疗保险168号", "version-1072-1", "1072-1"),
        ("平安人寿〔2021〕医疗保险155号", "version-1072-4", "1072-4"),
    ],
)
def test_version_filing_resolves_real_1072_versions(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
    filing_number: str,
    version_id: str,
    version_label: str,
) -> None:
    result = resolver.resolve(
        _request(
            scope,
            filing_numbers=(filing_number,),
            product_codes=("1072",),
            product_names=("平安e生保长期医疗保险（费率可调）",),
        )
    )

    assert result.product_version_id == version_id
    assert result.version_label == version_label
    assert result.product_id == "product-1072"
    assert result.resolver_version == RESOLVER_VERSION
    assert result.resolver_hash == RESOLVER_POLICY_HASH
    assert len(result.resolution_hash) == 64
    assert [(item.anchor_kind, item.observed_value) for item in result.basis] == [
        ("filing_number", filing_number),
        ("product_code", "1072"),
        ("product_name", "平安e生保长期医疗保险（费率可调）"),
    ]


def test_real_1072_version_results_have_distinct_content_identity(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    first = resolver.resolve(
        _request(scope, filing_numbers=("平安人寿[2020]医疗保险168号",))
    )
    fourth = resolver.resolve(
        _request(scope, filing_numbers=("平安人寿〔2021〕医疗保险155号",))
    )

    assert first.product_version_id == "version-1072-1"
    assert fourth.product_version_id == "version-1072-4"
    assert first.resolution_hash != fourth.resolution_hash


def test_conflicting_strong_identity_signals_quarantine(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    caught = _quarantine(
        resolver,
        _request(
            scope,
            filing_numbers=("平安人寿[2020]医疗保险168号",),
            product_codes=("596",),
        ),
        "anchor_conflict",
    )
    assert set(caught.candidate_version_ids) == {"version-1072-1", "version-596-1"}


def test_unique_version_anchor_is_not_overridden_by_lower_priority_name_ambiguity(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    result = resolver.resolve(
        _request(
            scope,
            registration_numbers=("注册-NAME-A-1",),
            product_names=("平安同名测试医疗保险",),
        )
    )

    assert result.product_id == "product-name-a"
    assert result.product_version_id == "version-name-a"
    assert result.basis[0].priority == 1
    assert result.basis[1].priority == 2
    assert set(result.basis[1].matched_product_ids) == {
        "product-name-a",
        "product-name-b",
    }


def test_registration_number_resolves_only_exact_version_terms_revision(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    result = resolver.resolve(
        _request(scope, registration_numbers=("注册-NAME-A-1",))
    )
    assert result.product_version_id == "version-name-a"
    assert result.basis[0].matched_field == "terms_revision"


def test_product_root_filing_number_cannot_mint_version_identity(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    _quarantine(
        resolver,
        _request(scope, filing_numbers=("产品根备案-NAME-A",)),
        "anchor_not_found",
    )


def test_auto_registration_alias_cannot_mint_version_identity(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    _quarantine(
        resolver,
        _request(scope, registration_numbers=("注册-596-1",)),
        "anchor_not_found",
    )
    _quarantine(
        resolver,
        _request(scope, aliases=("注册-596-1",)),
        "no_authoritative_anchor",
    )


def test_unflushed_version_anchor_mutation_cannot_mint_identity(
    session: Session,
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    version = session.get(ProductVersion, "version-596-1")
    assert version is not None
    version.terms_revision = "未落库伪锚点"

    _quarantine(
        resolver,
        _request(scope, filing_numbers=("未落库伪锚点",)),
        "anchor_not_found",
    )


def test_unflushed_alias_mutation_cannot_promote_auto_alias(
    session: Session,
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    alias = session.scalar(
        select(ProductAlias).where(ProductAlias.alias == "e生保长期医疗")
    )
    assert alias is not None
    alias.alias_type = "manual"
    alias.source = "manual"

    _quarantine(
        resolver,
        _request(scope, aliases=("e生保长期医疗",)),
        "no_authoritative_anchor",
    )


def test_cross_space_rejected_before_product_catalog_query(
    session: Session,
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    statements: list[str] = []
    bind = session.get_bind()
    engine = bind.engine if hasattr(bind, "engine") else bind
    assert isinstance(engine, Engine)

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        lowered = statement.lower()
        if any(
            table in lowered
            for table in ("insurance_products", "product_versions", "product_aliases")
        ):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        _quarantine(
            resolver,
            ProductVersionResolutionRequest(
                source_space_id=f"{scope.space_id}-foreign",
                document_ref="foreign.pdf",
                product_codes=("1072",),
            ),
            "cross_space",
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements == []


def test_catalog_snapshot_uses_one_database_statement(
    session: Session,
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    statements: list[str] = []
    bind = session.get_bind()
    engine = bind.engine if hasattr(bind, "engine") else bind
    assert isinstance(engine, Engine)

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if "insurance_products" in statement.lower():
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        resolver.resolve(
            _request(
                scope,
                filing_numbers=("平安人寿[2020]医疗保险168号",),
            )
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "product_versions" in statements[0]
    assert "product_aliases" in statements[0]


@pytest.mark.parametrize(
    ("updates", "reason_code"),
    [
        ({"product_names": ("平安同名测试医疗保险",)}, "ambiguous_product"),
        ({"product_codes": ("1072",)}, "ambiguous_version"),
        ({"product_codes": ("NO-VERSION",)}, "version_missing"),
        ({"product_codes": ("UNKNOWN",)}, "anchor_not_found"),
    ],
)
def test_ambiguous_or_missing_identity_never_guesses(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
    updates: dict[str, tuple[str, ...]],
    reason_code: str,
) -> None:
    _quarantine(resolver, _request(scope, **updates), reason_code)


def test_only_manual_approved_alias_can_resolve(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    _quarantine(
        resolver,
        _request(scope, aliases=("e生保长期医疗",)),
        "no_authoritative_anchor",
    )

    result = resolver.resolve(
        _request(
            scope,
            aliases=("平安长期医疗1072",),
            filing_numbers=("平安人寿[2020]医疗保险168号",),
        )
    )
    assert result.product_version_id == "version-1072-1"
    assert any(item.anchor_kind == "approved_alias" for item in result.basis)


def test_manual_allowlist_alias_resolves_only_when_product_version_is_unique(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    result = resolver.resolve(
        _request(scope, aliases=("平安尊享医疗人工别名",))
    )
    assert result.product_version_id == "version-596-1"
    assert result.basis[0].anchor_kind == "approved_alias"


def test_manual_alias_shared_by_multiple_products_is_ambiguous(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    _quarantine(
        resolver,
        _request(scope, aliases=("平安同名人工别名",)),
        "ambiguous_product",
    )


def test_recall_hints_and_master_data_cannot_mint_identity(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    caught = _quarantine(
        resolver,
        _request(
            scope,
            recall_candidate_version_ids=("version-596-1",),
            expected_category="medical",
            expected_channel="互联网",
            expected_region="CN",
        ),
        "no_authoritative_anchor",
    )
    assert caught.candidate_version_ids == ()
    assert [item.anchor_kind for item in caught.basis] == ["candidate_only_hint"]
    assert caught.basis[0].matched_product_version_ids == ("version-596-1",)


def test_master_data_only_vetoes_already_unique_candidate(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    caught = _quarantine(
        resolver,
        _request(
            scope,
            filing_numbers=("平安人寿[2020]医疗保险168号",),
            expected_channel="互联网",
        ),
        "master_data_mismatch",
    )
    assert caught.basis[-1].anchor_kind == "master_channel"
    assert caught.basis[-1].matched_product_version_ids == ()
    accepted = resolver.resolve(
        _request(
            scope,
            filing_numbers=("平安人寿[2020]医疗保险168号",),
            expected_channel="个人代理",
            expected_region="CN",
        )
    )
    assert accepted.product_version_id == "version-1072-1"
    assert [item.anchor_kind for item in accepted.basis[-2:]] == [
        "master_channel",
        "master_region",
    ]
    unconstrained = resolver.resolve(
        _request(
            scope,
            filing_numbers=("平安人寿[2020]医疗保险168号",),
        )
    )
    assert accepted.resolution_hash != unconstrained.resolution_hash


def test_similar_add_on_product_never_attaches_to_golden(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    result = resolver.resolve(
        _request(
            scope,
            product_names=("平安附加e生保（尊享版）长期医疗保险（费率可调）",),
        )
    )
    assert result.product_id == "product-2609"
    assert result.product_version_id == "version-2609-1"
    assert result.product_id != "product-596"


def test_resolution_and_fragment_hashes_are_stable(
    resolver: ProductVersionResolver,
    scope: KnowledgeScope,
) -> None:
    request = _request(
        scope,
        document_ref="1072-1.pdf",
        section_ref="terms",
        filing_numbers=("平安人寿[2020]医疗保险168号",),
    )
    first = resolver.resolve(request)
    second = resolver.resolve(request)
    assert first == second
    assert first.resolution_hash == second.resolution_hash

    fragment_a = inherit_fragment_resolution(first, fragment_ref="page-1:block-1")
    fragment_b = inherit_fragment_resolution(first, fragment_ref="page-1:block-2")
    assert fragment_a.product_version_id == first.product_version_id
    assert fragment_a.parent_resolution_hash == first.resolution_hash
    assert fragment_a.binding_hash != fragment_b.binding_hash

    tampered = first.model_copy(update={"product_version_id": "version-596-1"})
    with pytest.raises(ProductVersionQuarantine) as caught:
        inherit_fragment_resolution(tampered, fragment_ref="page-2:block-1")
    assert caught.value.reason_code == "resolution_hash_mismatch"

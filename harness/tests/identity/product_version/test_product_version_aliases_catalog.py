"""ProductVersion resolution: scoped catalog, manual aliases, master data and stable hashes."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.version_resolver import (
    ProductVersionQuarantine,
    ProductVersionResolutionRequest,
    ProductVersionResolver,
    inherit_fragment_resolution,
)
from tests.identity.product_version.helpers import _quarantine, _request


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

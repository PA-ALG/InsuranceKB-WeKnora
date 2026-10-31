"""ProductVersion resolution: real materials, strong identity signals, what cannot mint identity."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    ProductAlias,
    ProductVersion,
)
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.version_resolver import (
    RESOLVER_POLICY_HASH,
    RESOLVER_VERSION,
    ProductVersionResolver,
)
from tests.identity.product_version.helpers import _quarantine, _request

REPO_ROOT = Path(__file__).resolve().parents[4]


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

"""OpenSpec 041 ProductVersion resolution: shared fixture path and request helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

from insurance_harness.db.models import (
    InsuranceProduct,
    ProductAlias,
    ProductVersion,
)
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.version_resolver import (
    ProductVersionResolver,
)
from tests.identity.product_version.helpers import FIXTURE_PATH


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

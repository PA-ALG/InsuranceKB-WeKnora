"""Shared PV-1 test data: synthetic version catalogs and a registry with every kind of record."""

from typing import Literal

from insurance_harness.identity.attribution import Attribution
from insurance_harness.ingest.registry import (
    ConfirmationRef,
    DecisionEntry,
    MaterialEntry,
    PendingEntry,
    ProductRegistry,
    Settlement,
)
from insurance_harness.ingest.version_catalog import VersionCatalog, VersionRecord
from tests.ingest.upload_helpers import PRODUCTS, entry, registry

COMMIT = "c" * 40
POLICY = "attribution-policy@2026-11-01.1"


def version(
    key: str,
    name: str,
    code: str | None,
    start: str | None = "2025-10-01",
    end: str | None = None,
    status: Literal["on_sale", "discontinued"] | None = "on_sale",
) -> VersionRecord:
    plan, number = key.rsplit("-", 1)
    return VersionRecord(
        version_key=key,
        plan_code=plan,
        version_no=int(number),
        name=name,
        clause_code=code,
        sale_start=start,
        sale_end=end,
        source_status=status,
        channel="个人代理",
        plan_type="普通型",
    )


def of(product_id: str, key: str | None = None, **override: object) -> VersionRecord:
    """The catalog record of a fixture product, under its own plan code by default."""
    product = PRODUCTS[product_id]
    fields: dict[str, object] = {
        "key": key or f"{product_id}-1",
        "name": product["name"],
        "code": product["clause_code"],
    }
    fields.update(override)
    return version(**fields)  # type: ignore[arg-type]


def catalog(*records: VersionRecord, commit: str = COMMIT) -> VersionCatalog:
    return VersionCatalog(
        contract="product-catalog.v1",
        repository="PA-ALG/pingan-life-product-documents",
        commit=commit,
        versions=tuple(records),
    )


def rich_v1() -> ProductRegistry:
    """A v1 registry holding a retired material, a waiting item with a saved settlement and a
    person's decision, so a migration has every kind of record to preserve."""
    value = registry(
        p1828=entry("1828", "terms", "brochure"),
        p1814=entry("1814", "terms", "brochure", "rate_table"),
    )
    product = value.products["1828"]
    product.retired = [
        MaterialEntry(
            knowledge_id="k-1828-old-terms",
            parse_attempt=1,
            sha256="1" * 64,
            role="terms",
            file_name="旧条款.pdf",
        )
    ]
    asked = Attribution(
        outcome="NEEDS_CONFIRM",
        reason="same_role_differs",
        product_id="1828",
        role="rate_table",
        candidates=("1828",),
        policy_ref=POLICY,
    )
    answer = ConfirmationRef(
        item_id="item-1", answer_id="answer-1", option_key="supplement", answerer="reviewer"
    )
    value.pending = [
        PendingEntry(
            knowledge_id="k-1828-rate",
            parse_attempt=2,
            sha256="2" * 64,
            file_name="费率表.pdf",
            attribution=asked,
            settlement=Settlement(
                item_id="item-1",
                knowledge_id="k-1828-rate",
                parse_attempt=2,
                sha256="2" * 64,
                revision="rev-1",
                reason="applied",
                confirmation=answer,
                conclusion=Attribution(
                    outcome="SUPPLEMENT",
                    reason="confirmed_supplement",
                    product_id="1828",
                    role="rate_table",
                    policy_ref=POLICY,
                ),
            ),
        )
    ]
    value.decisions = [
        DecisionEntry(
            knowledge_id="k-1814-rate_table",
            parse_attempt=1,
            sha256=entry("1814", "rate_table").materials[0].sha256,
            attribution=Attribution(
                outcome="SUPPLEMENT",
                reason="confirmed_by_person",
                product_id="1814",
                role="rate_table",
                policy_ref=POLICY,
            ),
            confirmation=ConfirmationRef(
                item_id="item-0", answer_id="answer-0", option_key="product:x", answerer="reviewer"
            ),
        )
    ]
    return value

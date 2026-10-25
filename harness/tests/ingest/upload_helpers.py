"""Shared S5b-2 test data: real material openings (S5b-1 fixture), a fake RAW listing and pages."""

import json
from pathlib import Path

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    MaterialEntry,
    ProductEntry,
    ProductRegistry,
)

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "identity" / "fixtures" / "attribution_heads.json").read_text(
        encoding="utf-8"
    )
)
PRODUCTS = {product["product_id"]: product for product in FIXTURE["products"]}
KEYWORDS = {"terms": "条款", "brochure": "说明书", "rate_table": "费率表"}
SPACE = "space-1"
RAW_KB = "raw-1"


def material(product_id: str, role: str) -> dict[str, str]:
    keyword = KEYWORDS[role]
    return next(m for m in PRODUCTS[product_id]["materials"] if keyword in m["file_name"])


def knowledge_id(product_id: str, role: str) -> str:
    return f"k-{product_id}-{role}"


def raw(product_id: str, role: str, attempt: int = 1, **override: str) -> RawSource:
    m = material(product_id, role)
    fields: dict[str, object] = {
        "knowledge_id": knowledge_id(product_id, role),
        "parse_attempt": attempt,
        "file_name": m["file_name"],
        "sha256": m["sha256"],
    }
    fields.update(override)
    return RawSource.model_validate(fields)


def entry(product_id: str, *roles: str) -> ProductEntry:
    product = PRODUCTS[product_id]
    return ProductEntry(
        names=[product["name"]],
        clause_codes=[product["clause_code"]],
        schema_pack_id=product["schema_pack_id"],
        origin="seeded",
        materials=[
            MaterialEntry(
                knowledge_id=knowledge_id(product_id, role),
                parse_attempt=1,
                sha256=material(product_id, role)["sha256"],
                role=role,
                file_name=material(product_id, role)["file_name"],
            )
            for role in roles
        ],
    )


def registry(**products: ProductEntry) -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products={key.removeprefix("p"): value for key, value in products.items()},
        pending=[],
        decisions=[],
    )


class Pages:
    """A fake page reader: each knowledge's first page is its fixture opening."""

    def __init__(self, heads: dict[str, str] | None = None, failing: tuple[str, ...] = ()) -> None:
        self.heads = heads or {}
        self.failing = failing
        self.calls: list[tuple[str, str, int]] = []

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        self.calls.append((space_id, knowledge_id, attempt))
        if knowledge_id in self.failing:
            raise SourcePagesError("SOURCE_UNAVAILABLE")
        if knowledge_id in self.heads:
            head = self.heads[knowledge_id]
        else:
            _, product_id, role = knowledge_id.split("-", 2)
            head = material(product_id, role)["head"]
        return [PageText(knowledge_id, "0" * 64, 1, head), PageText(knowledge_id, "0" * 64, 2, "")]

"""Shared SK-1 test data (written by Claude): invented Office decks and a v2 registry.

The deck texts are invented sales-training phrases; product names are public filed names. No
private sample text is used anywhere.
"""

from collections.abc import Sequence

from insurance_harness.contracts.enums import LocatorKind
from insurance_harness.contracts.knowledge import Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import BLOCK_SEPARATOR, OfficeBlock, OfficePageText
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.product_versions import MetadataBasis, ProductVersion
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import MaterialEntry, ProductEntry, ProductRegistry
from tests.ingest.upload_helpers import RAW_KB, SPACE

NURSING = "schemapack_nursing_care_insurance"
ZYBH = "平安智盈倍护终身护理保险"

# A sales-method deck: method words on two slides, one insurance category (护理险), no product
# brand anywhere, a date on the cover.
METHOD_SLIDES = (
    ("护理险销售方法课程", "2024年5月"),
    ("讲解步骤一：了解客户的家庭情况", "讲解关键句：先听客户怎么说"),
    ("异议应对：客户说保费太高", "促成：确认保障方案后再约时间"),
)
# A plain product deck: no method word at all.
PLAIN_SLIDES = (("护理险产品介绍", "2024年5月"), ("保障责任概览",))


def slide_page(document: str, sha256: str, number: int, texts: Sequence[str]) -> OfficePageText:
    """One PPTX slide whose blocks are `texts`, joined as the platform joins them."""
    blocks, parts, position = [], [], 0
    for text in texts:
        blocks.append(
            OfficeBlock(
                start=position,
                end=position + len(text),
                locator=Locator(kind=LocatorKind.PPTX_SHAPE, slide=number),
            )
        )
        parts.append(text)
        position += len(text) + len(BLOCK_SEPARATOR)
    return OfficePageText(document, sha256, number, BLOCK_SEPARATOR.join(parts), tuple(blocks))


def deck_pages(
    document: str, sha256: str, slides: Sequence[Sequence[str]]
) -> list[OfficePageText]:
    return [slide_page(document, sha256, n, texts) for n, texts in enumerate(slides, 1)]


def source(
    kid: str, file_name: str, sha256: str = "d" * 64, attempt: int = 1
) -> RawSource:
    return RawSource(knowledge_id=kid, parse_attempt=attempt, file_name=file_name, sha256=sha256)


class DeckPages:
    """A fake page reader serving whole decks (all pages, with blocks) by knowledge id."""

    def __init__(self, decks: dict[str, Sequence[PageText]] | None = None) -> None:
        self.decks = dict(decks or {})
        self.calls: list[tuple[str, int]] = []

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        self.calls.append((knowledge_id, attempt))
        if knowledge_id not in self.decks:
            raise SourcePagesError("SOURCE_UNAVAILABLE")
        return list(self.decks[knowledge_id])


def basis() -> MetadataBasis:
    return MetadataBasis(
        repository="PA-ALG/pingan-life-product-documents",
        commit="c" * 40,
        catalog_sha256="a" * 64,
        synced_at="2026-11-01T00:00:00Z",
    )


def nursing_entry(
    key: str = "2635-1",
    start: str = "2024-04-23",
    end: str | None = "2024-09-01",
    materials: list[MaterialEntry] | None = None,
) -> ProductEntry:
    return ProductEntry(
        names=[ZYBH],
        clause_codes=[],
        schema_pack_id=NURSING,
        origin="created",
        materials=materials if materials is not None else [held()],
        version=ProductVersion(
            version_key=key,
            plan_code=key.split("-")[0],
            version_no=int(key.split("-")[1]),
            sale_start=start,
            sale_end=end,
            source_status="discontinued" if end else "on_sale",
            plan_type="普通型",
        ),
    )


def held() -> MaterialEntry:
    """The terms an entry already holds, so a deck is a supplement (and detach is allowed)."""
    return MaterialEntry(
        knowledge_id="k-terms", parse_attempt=1, sha256="e" * 64, role="terms", file_name="条款.pdf"
    )


def v2(**products: ProductEntry) -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v2",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products=dict(products),
        pending=[],
        decisions=[],
        metadata_basis=basis(),
    )


def v1() -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products={},
        pending=[],
        decisions=[],
    )

"""Shared S5b-3c-2 test data (protected, written by Claude): questions raised the way S5b-2 raises
them, from real openings of endowment, accident, critical illness and annuity products."""

import hashlib
import unicodedata

from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.upload_helpers import PRODUCTS, Pages, entry, material, raw, registry

BASE = "http://weknora.test"
UNNAMED = "平安安心保障计划"


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def product_key(product_id: str) -> str:
    return "product:" + hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:16]


TWO_NAMED = (
    fold(PRODUCTS["1828"]["name"])
    + "、"
    + fold(PRODUCTS["1814"]["name"])
    + "产品说明书在本说明书中"
)
RENAMED = material("1826", "terms")["head"].replace(fold(PRODUCTS["1826"]["name"]), UNNAMED, 1)
UPLOADS: dict[str, tuple[RawSource, str]] = {
    "k-new": (
        raw("1818", "brochure", knowledge_id="k-new", sha256="f" * 64),
        material("1818", "brochure")["head"],
    ),
    "k-two": (raw("1828", "brochure", knowledge_id="k-two", sha256="c" * 64), TWO_NAMED),
    "k-scan": (
        raw("1830", "brochure", knowledge_id="k-scan", file_name="scan-0001.pdf"),
        material("1830", "brochure")["head"],
    ),
    "k-unnamed": (raw("1826", "terms", knowledge_id="k-unnamed", sha256="d" * 64), RENAMED),
    "k-orphan": (
        raw("1826", "brochure", knowledge_id="k-orphan"),
        material("1826", "brochure")["head"],
    ),
}


def pages(*failing: str) -> Pages:
    sources = [source for source, _ in UPLOADS.values()]
    return Pages(
        heads={k: head for k, (_, head) in UPLOADS.items()}, failing=failing, sources=sources
    )


def products() -> ProductRegistry:
    return registry(
        p1818=entry("1818", "terms", "brochure"),
        p1814=entry("1814", "terms", "brochure"),
        p1828=entry("1828", "terms"),
        p1830=entry("1830", "terms"),
    )


def asked(current: ProductRegistry, *ids: str) -> ProductRegistry:
    """Raise the questions as S5b-2 does: judged once, then waiting in pending."""
    sources = [UPLOADS[k][0] for k in ids]
    return attribute_uploads(current, sources, pages()).registry


def waiting(current: ProductRegistry) -> list[str]:
    return sorted(
        p.knowledge_id for p in current.pending if p.attribution.outcome == "NEEDS_CONFIRM"
    )


def only_item(platform: FakePlatform, kid: str) -> str:
    [item] = platform.find(f"material:{kid}")
    return str(item["id"])


def platform_for_command() -> FakePlatform:
    """A platform that also serves the pages of the uploads outside the fixture."""
    return FakePlatform(uploads={k: (head, source.sha256) for k, (source, head) in UPLOADS.items()})

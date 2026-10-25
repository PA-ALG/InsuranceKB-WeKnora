"""One Space's products and the materials each one is built from (S5b-2 Spec §2.1, §2.4).

The registry replaces the hand-written source maps as the single record of which product owns which
fixed source revision. The existing compile and publish commands still read a source map; the
registry exports one on demand instead of a second copy being kept. It also keeps the materials
waiting for a person or for their terms (`pending`) and an append-only record of every decision,
each with the attribution policy version it was made under.
"""

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
)
from insurance_harness.identity.material_roles import load_material_roles, role_of
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.source_map import PageReader, SourceEntry, SourceMap

CONTRACT: Literal["product-registry.v1"] = "product-registry.v1"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_Name = Annotated[str, StringConstraints(pattern=r"\S")]


class RegistryError(ValueError):
    """A caller-safe code; never the file path or its content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class MaterialEntry(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    role: str
    file_name: _Name


class ProductEntry(_Strict):
    names: list[_Name] = Field(min_length=1)  # the canonical name first, then approved aliases
    clause_codes: list[_Name]
    schema_pack_id: _Name
    origin: Literal["seeded", "created"]
    materials: list[MaterialEntry]
    retired: list[MaterialEntry] = Field(default_factory=list)  # replaced by a new version


class PendingEntry(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    file_name: _Name
    attribution: Attribution


class DecisionEntry(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    attribution: Attribution


class ProductFacts(_Strict):
    name: str
    schema_pack_id: str


class SeedProduct(_Strict):
    name: _Name
    clause_code: _Name
    schema_pack_id: _Name


class ProductRegistry(_Strict):
    contract: Literal["product-registry.v1"]
    space_id: _Identifier
    raw_kb_id: _Identifier
    products: dict[_Identifier, ProductEntry]
    pending: list[PendingEntry]
    decisions: list[DecisionEntry]

    @model_validator(mode="after")
    def _consistent(self) -> "ProductRegistry":
        recorded = [m for p in self.products.values() for m in (*p.materials, *p.retired)]
        ids = [m.knowledge_id for m in recorded] + [p.knowledge_id for p in self.pending]
        if len(set(ids)) != len(ids):
            raise ValueError("a knowledge id is registered twice")
        roles = {role.role for role in load_material_roles().roles}
        if any(m.role not in roles for m in recorded):
            raise ValueError("unknown material role")
        if any(p.attribution.outcome not in {"NEEDS_CONFIRM", "QUARANTINE"} for p in self.pending):
            raise ValueError("an automatic conclusion cannot wait in pending")
        return self

    def registered(self) -> list[RegisteredProduct]:
        """The products as the attribution core sees them."""
        return [
            RegisteredProduct(
                product_id=product_id,
                names=tuple(product.names),
                clause_codes=tuple(product.clause_codes),
                schema_pack_id=product.schema_pack_id,
                materials=tuple(
                    RegisteredMaterial(knowledge_id=m.knowledge_id, sha256=m.sha256, role=m.role)
                    for m in product.materials
                ),
            )
            for product_id, product in sorted(self.products.items())
        ]

    def source_map(self) -> SourceMap:
        """The same source map the compile and publish commands read today."""
        return SourceMap(
            space_id=self.space_id,
            products={
                product_id: [
                    SourceEntry(knowledge_id=m.knowledge_id, parse_attempt=m.parse_attempt)
                    for m in sorted(product.materials, key=lambda m: m.knowledge_id)
                ]
                for product_id, product in sorted(self.products.items())
            },
        )

    def facts(self, product_id: str) -> ProductFacts:
        """The canonical name and pack that compiling a product needs (S5b-4)."""
        product = self.products.get(product_id)
        if product is None:
            raise RegistryError("PRODUCT_UNKNOWN")
        return ProductFacts(name=product.names[0], schema_pack_id=product.schema_pack_id)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_registry(path: Path) -> ProductRegistry:
    """A repeated JSON key is refused first: parsing would otherwise keep only the last one."""
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text, object_pairs_hook=_unique_object)
        return ProductRegistry.model_validate_json(text)
    except (OSError, ValueError, ValidationError, RecursionError):
        raise RegistryError("REGISTRY_INVALID") from None


def save_registry(registry: ProductRegistry, path: Path) -> None:
    """Replace the file in one step: a failed write leaves the previous registry in place."""
    data = registry.model_dump_json(indent=1).encode("utf-8") + b"\n"
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def head_of(pages: PageReader, space_id: str, source: RawSource) -> str:
    """The text attribution reads: the first two pages, in page order.

    Every page must belong to the file the listing names: the page reader checks the revision and
    its own page hashes, not that the captured document is the listed one.
    """
    read = sorted(
        pages.pages(space_id, source.knowledge_id, source.parse_attempt), key=lambda p: p.page
    )
    if not read or any(page.document_sha256 != source.sha256 for page in read):
        raise SourcePagesError("PARSE_ARTIFACT_INTEGRITY")
    return "\n".join(page.text for page in read[:2])


def seed_registry(
    space_id: str,
    raw_kb_id: str,
    source_maps: Sequence[SourceMap],
    sources: Sequence[RawSource],
    pages: PageReader,
    products: Mapping[str, SeedProduct],
) -> ProductRegistry:
    """The first registry of a Space, equivalent to its hand-written source maps."""
    listed = {source.knowledge_id: source for source in sources}
    merged: dict[str, list[SourceEntry]] = {}
    for source_map in source_maps:
        if source_map.space_id != space_id or set(merged) & set(source_map.products):
            raise RegistryError("SEED_INVALID")
        merged.update(source_map.products)
    entries: dict[str, ProductEntry] = {}
    for product_id, mapped in sorted(merged.items()):
        facts = products.get(product_id)
        if facts is None:
            raise RegistryError("SEED_INVALID")
        materials = []
        for item in sorted(mapped, key=lambda e: e.knowledge_id):
            source = listed.get(item.knowledge_id)
            if source is None or source.parse_attempt != item.parse_attempt:
                raise RegistryError("SEED_INVALID")
            try:
                role = role_of(source.file_name, head_of(pages, space_id, source))
            except ValueError:
                raise RegistryError("SEED_INVALID") from None
            if role is None:
                raise RegistryError("SEED_INVALID")
            materials.append(
                MaterialEntry(
                    knowledge_id=source.knowledge_id,
                    parse_attempt=source.parse_attempt,
                    sha256=source.sha256,
                    role=role,
                    file_name=source.file_name,
                )
            )
        entries[product_id] = ProductEntry(
            names=[facts.name],
            clause_codes=[facts.clause_code],
            schema_pack_id=facts.schema_pack_id,
            origin="seeded",
            materials=materials,
        )
    try:
        return ProductRegistry(
            contract=CONTRACT,
            space_id=space_id,
            raw_kb_id=raw_kb_id,
            products=entries,
            pending=[],
            decisions=[],
        )
    except ValidationError:
        raise RegistryError("SEED_INVALID") from None

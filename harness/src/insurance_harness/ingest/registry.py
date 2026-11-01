"""One Space's products and the materials each one is built from (S5b-2 Spec §2.1, §2.4).

The registry replaces the hand-written source maps as the single record of which product owns which
fixed source revision. The existing compile and publish commands still read a source map; the
registry exports one on demand instead of a second copy being kept. It also keeps the materials
waiting for a person or for their terms (`pending`) and an append-only record of every decision,
each with the attribution policy version it was made under and, when a person made it, the answer it
came from (S5b-3c-1).

A v2 registry also records the filed version each entry stands for (PV-1 Spec §2.3), the
material-level method uses (SK-1 Spec §2.3) and the methods admitted from them (SK-2 Spec §2.1);
a v1 registry is read and written back as v1, so only the migration command turns one into the
other.
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

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
)
from insurance_harness.identity.material_roles import load_material_roles, role_of
from insurance_harness.ingest.method_registry import MethodEntry, check_methods
from insurance_harness.ingest.method_use_model import MethodUse, check_method_uses
from insurance_harness.ingest.product_versions import (
    MetadataBasis,
    ProductVersion,
    check_versions,
    entry_version,
    registered_version,
    relinked,
    v1_excluded,
)
from insurance_harness.ingest.raw_sources import RawSource, head_of
from insurance_harness.ingest.source_map import PageReader, SourceEntry, SourceMap
from insurance_harness.ingest.version_catalog import VersionCatalog

CONTRACT: Literal["product-registry.v1"] = "product-registry.v1"
V2: Literal["product-registry.v2"] = "product-registry.v2"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_Name = Annotated[str, StringConstraints(pattern=r"\S")]
_OptionKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9:._-]{0,127}$")]
_Principal = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f-\x9f]{1,256}$")]
# Applied outcomes change the products; waiting ones stay in pending; final ones end judging.
APPLIED = frozenset({"SUPPLEMENT", "NEW_VERSION", "CREATE", "REPLACE"})
WAITING = frozenset({"NEEDS_CONFIRM", "QUARANTINE", "METHOD_MATERIAL"})  # judged again (SK-1)
FINAL = frozenset({"DUPLICATE", "SUPPLEMENT", "NEW_VERSION", "CREATE", "REPLACE", "IGNORED"})
_PERSON_ONLY = frozenset({"REPLACE", "IGNORED"})


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
    retired: list[MaterialEntry] = Field(default_factory=list)  # REPLACE, or DETACHED (PV-3)
    version: ProductVersion | None = None  # v2 only (PV-1)


class ConfirmationRef(_Strict):
    """The platform confirmation answer a person's decision came from (S5b-3a)."""

    item_id: _Identifier
    answer_id: _Identifier
    option_key: _OptionKey
    answerer: _Principal


class Settlement(_Strict):
    """What a run decided to do with a material's confirmation item, saved before closing it
    (S5b-3c-2 Spec §2.2, §3.5): an interrupted run completes exactly this, never a re-derived one.
    It names the material version and the question it was made for."""

    item_id: _Identifier
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    revision: _Identifier
    reason: Literal["applied", "obsolete"]
    confirmation: ConfirmationRef | None
    conclusion: Attribution | None

    @model_validator(mode="after")
    def _complete(self) -> "Settlement":
        applied = self.reason == "applied"
        if applied != (self.confirmation is not None) or applied != (self.conclusion is not None):
            raise ValueError(
                "an applied settlement names its answer and conclusion, an obsolete one neither"
            )
        if self.confirmation is not None and self.confirmation.item_id != self.item_id:
            raise ValueError("a settlement's answer belongs to another item")
        return self


class PendingEntry(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    file_name: _Name
    attribution: Attribution
    settlement: Settlement | None = None  # absent in files written before S5b-3c-2


class DecisionEntry(_Strict):
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    attribution: Attribution
    confirmation: ConfirmationRef | None = None  # absent in files written before S5b-3c-1


class ProductFacts(_Strict):
    name: str
    schema_pack_id: str


class SeedProduct(_Strict):
    name: _Name
    clause_code: _Name
    schema_pack_id: _Name


class ProductRegistry(_Strict):
    contract: Literal["product-registry.v1", "product-registry.v2"]
    space_id: _Identifier
    raw_kb_id: _Identifier
    products: dict[_Identifier, ProductEntry]
    pending: list[PendingEntry]
    decisions: list[DecisionEntry]
    metadata_basis: MetadataBasis | None = None  # v2 only (PV-1)
    method_uses: list[MethodUse] = Field(default_factory=list)  # v2 only (SK-1)
    methods: list[MethodEntry] = Field(default_factory=list)  # v2 only (SK-2)

    @model_validator(mode="after")
    def _consistent(self) -> "ProductRegistry":
        versions = {product_id: p.version for product_id, p in self.products.items()}
        concluded = [p.settlement.conclusion for p in self.pending if p.settlement]
        decided = [p.attribution for p in self.pending] + [d.attribution for d in self.decisions]
        keys = [a.version_key for a in (*decided, *concluded) if a is not None]
        found = [a for a in (*decided, *concluded) if a is not None]
        evidence = bool(self.method_uses or self.methods) or any(
            a.version_basis or a.shared_versions or a.outcome in {"DETACHED", "METHOD_MATERIAL"}
            for a in found
        )  # PV-3 and SK-1 fields and outcomes: v2 only (review R7)
        check_versions(self.contract, self.metadata_basis, versions, keys, evidence)
        check_method_uses(self.method_uses)
        check_methods(self.methods, self.method_uses)
        recorded = [m for p in self.products.values() for m in (*p.materials, *p.retired)]
        ids = [m.knowledge_id for m in recorded] + [p.knowledge_id for p in self.pending]
        if len(set(ids)) != len(ids):
            raise ValueError("a knowledge id is registered twice")
        roles = {role.role for role in load_material_roles().roles}
        if any(m.role not in roles for m in recorded):
            raise ValueError("unknown material role")
        if any(p.attribution.outcome not in WAITING for p in self.pending):
            raise ValueError("an automatic conclusion cannot wait in pending")
        if any(
            d.attribution.outcome in _PERSON_ONLY and not d.confirmation for d in self.decisions
        ):
            raise ValueError("a person-only conclusion without its confirmation")
        answers = [d.confirmation.answer_id for d in self.decisions if d.confirmation]
        if len(set(answers)) != len(answers):
            raise ValueError("an answer is recorded twice")
        settled = [(entry, entry.settlement) for entry in self.pending if entry.settlement]
        for entry, settlement in settled:
            if entry.attribution.outcome not in WAITING:  # NEEDS_CONFIRM, or QUARANTINE (S11a)
                raise ValueError("only a material waiting for a person has a settlement")
            if (settlement.knowledge_id, settlement.parse_attempt, settlement.sha256) != (
                entry.knowledge_id,
                entry.parse_attempt,
                entry.sha256,
            ):
                raise ValueError("a settlement made for another material version")
        items = [settlement.item_id for _, settlement in settled]
        settled_answers = [s.confirmation.answer_id for _, s in settled if s.confirmation]
        if len(set(items)) != len(items) or len(set(settled_answers)) != len(settled_answers):
            raise ValueError("two settlements name one item or answer")
        if set(settled_answers) & set(answers):
            raise ValueError("a settlement for an answer already recorded")
        if set(items) & {d.confirmation.item_id for d in self.decisions if d.confirmation}:
            raise ValueError("a settlement for an item already recorded")
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
                version_key=product.version.version_key if product.version else None,
                version=registered_version(product.version, self.metadata_basis),
            )
            for product_id, product in sorted(self.products.items())
        ]

    def source_map(self) -> SourceMap:
        """The same source map the compile and publish commands read today."""
        return SourceMap(
            space_id=self.space_id,
            products={
                product_id: [
                    SourceEntry(
                        knowledge_id=m.knowledge_id,
                        parse_attempt=m.parse_attempt,
                        role=m.role,
                        sha256=m.sha256.lower(),
                    )
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
    except OSError:  # missing, a directory, unreadable: a file problem, not bad content
        raise RegistryError("REGISTRY_IO_ERROR") from None
    except UnicodeDecodeError:
        raise RegistryError("REGISTRY_INVALID") from None
    try:
        json.loads(text, object_pairs_hook=_unique_object)
        return ProductRegistry.model_validate_json(text)
    except (ValueError, ValidationError, RecursionError):
        raise RegistryError("REGISTRY_INVALID") from None


def registry_document(registry: ProductRegistry) -> bytes:
    """The file bytes; a v1 registry keeps the v1 format, without the v2 fields."""
    if registry.contract == CONTRACT:
        return registry.model_dump_json(indent=1, exclude=v1_excluded()).encode("utf-8") + b"\n"
    return registry.model_dump_json(indent=1).encode("utf-8") + b"\n"


def save_registry(registry: ProductRegistry, path: Path) -> None:
    """Replace the file in one step: a failed write leaves the previous registry in place."""
    data = registry_document(registry)
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


def record(
    registry: ProductRegistry,
    source: RawSource,
    attribution: Attribution,
    confirmation: ConfirmationRef | None = None,
    catalog: VersionCatalog | None = None,
) -> bool:
    """Record one decision in place; True when the products changed.

    A person's decision names the answer it came from and must settle a material waiting for a
    person at this exact revision. All or nothing: the changes are made on a copy and kept only when
    every step succeeds, so a refusal leaves the registry as it was. In a v2 registry an entry
    added by CREATE or NEW_VERSION gets its version fields from the catalog (PV-1 Spec §3).
    """
    if attribution.outcome in _PERSON_ONLY and confirmation is None:
        raise RegistryError("CONFIRMATION_REQUIRED")
    if confirmation is not None:
        waiting = [
            p
            for p in registry.pending
            if (p.knowledge_id, p.parse_attempt, p.sha256)
            == (source.knowledge_id, source.parse_attempt, source.sha256)
            and p.attribution.outcome in WAITING  # a quarantined one too (S11a Spec §2.4)
        ]
        if not waiting:
            raise RegistryError("CONFIRMATION_UNEXPECTED")
        recorded = {d.confirmation.answer_id for d in registry.decisions if d.confirmation}
        if confirmation.answer_id in recorded:
            raise RegistryError("CONFIRMATION_RECORDED")
    staged = registry.model_copy(deep=True)
    try:
        changed = _apply(staged, source, attribution, confirmation, catalog)
        ProductRegistry.model_validate(staged.model_dump())  # the registry-wide rules still hold
    except ValidationError:  # an entry the registry format refuses, such as a blank file name
        raise RegistryError("RECORD_INVALID") from None
    registry.products, registry.pending = staged.products, staged.pending
    registry.decisions = staged.decisions
    return changed


def _apply(
    registry: ProductRegistry,
    source: RawSource,
    attribution: Attribution,
    confirmation: ConfirmationRef | None,
    catalog: VersionCatalog | None,
) -> bool:
    previous = next((p for p in registry.pending if p.knowledge_id == source.knowledge_id), None)
    registry.pending = [p for p in registry.pending if p.knowledge_id != source.knowledge_id]
    if attribution.outcome in WAITING:
        registry.pending.append(
            PendingEntry(
                knowledge_id=source.knowledge_id,
                parse_attempt=source.parse_attempt,
                sha256=source.sha256,
                file_name=source.file_name,
                attribution=attribution,
            )
        )
        registry.pending.sort(key=lambda p: p.knowledge_id)
        if previous is not None and previous.attribution == attribution:
            return False  # judged again, same conclusion: nothing new to record
    registry.decisions.append(
        DecisionEntry(
            knowledge_id=source.knowledge_id,
            parse_attempt=source.parse_attempt,
            sha256=source.sha256,
            attribution=attribution,
            confirmation=confirmation,
        )
    )
    if attribution.outcome not in APPLIED:
        return False
    if attribution.product_id is None or attribution.role is None:
        raise RegistryError("ATTRIBUTION_INCOMPLETE")
    material = MaterialEntry(
        knowledge_id=source.knowledge_id,
        parse_attempt=source.parse_attempt,
        sha256=source.sha256,
        role=attribution.role,
        file_name=source.file_name,
    )
    if attribution.outcome in {"CREATE", "NEW_VERSION"}:  # a new version is a new entry (PV-1)
        if not (
            attribution.display_name and attribution.clause_code and attribution.schema_pack_id
        ) or attribution.replaces:
            raise RegistryError("ATTRIBUTION_INCOMPLETE")
        if attribution.product_id in registry.products:
            raise RegistryError("PRODUCT_EXISTS")
        registry.products[attribution.product_id] = ProductEntry(
            names=[attribution.display_name],
            clause_codes=[attribution.clause_code],
            schema_pack_id=attribution.schema_pack_id,
            origin="created",
            materials=[material],
            version=entry_version(
                registry.contract != CONTRACT,
                attribution.version_key,
                attribution.display_name,
                catalog,
            ),
        )
        _link(registry)
        return True
    product = registry.products.get(attribution.product_id)
    if product is None:
        raise RegistryError("PRODUCT_UNKNOWN")
    kept = [m for m in product.materials if m.knowledge_id not in attribution.replaces]
    replaced = [m for m in product.materials if m.knowledge_id in attribution.replaces]
    product.materials = sorted([*kept, material], key=lambda m: m.knowledge_id)
    product.retired = sorted([*product.retired, *replaced], key=lambda m: m.knowledge_id)
    return True


def _link(registry: ProductRegistry) -> None:
    """Recompute every entry's unique predecessor (PV-0 appendix A §1.4)."""
    linked = relinked({k: p.version for k, p in registry.products.items()})
    for product_id, version in linked.items():
        registry.products[product_id].version = version


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

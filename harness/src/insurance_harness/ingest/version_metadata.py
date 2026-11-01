"""A registered product version's published identity (PV-4 Spec §3.1, PV-0 appendix A §1.2).

The entity of a product carries what the registry knows of its filed version: the real plan
code, the version key, its single clause code as filing number, the sale period with the pinned
repository commit it came from, and the brand family. Unknown parts are omitted, never guessed.
An entry without a version record (a v1 registry, or one not yet migrated) keeps exactly the
identity it has always been published with, so nothing changes before a migration.
"""

from pathlib import Path

from insurance_harness.compilers.schema_fields.page import EntityMetadata
from insurance_harness.contracts.knowledge import ProductFamily, ProductLifecycle
from insurance_harness.ingest.product_versions import MetadataBasis
from insurance_harness.ingest.registry import ProductEntry, RegistryError, load_registry


def entity_metadata(
    product_id: str, entry: ProductEntry, basis: MetadataBasis | None
) -> EntityMetadata:
    version = entry.version
    if version is None:
        return EntityMetadata(identifiers={"product_code": product_id})
    identifiers: dict[str, str] = {}
    if version.plan_code:
        identifiers["product_code"] = version.plan_code
    if version.version_key:
        identifiers["version_key"] = version.version_key
    if len(entry.clause_codes) == 1:
        identifiers["filing_no"] = entry.clause_codes[0]
    lifecycle = None
    if any(v is not None for v in (version.sale_start, version.sale_end, version.source_status)):
        lifecycle = ProductLifecycle(
            sale_start=version.sale_start,
            sale_end=version.sale_end,
            source_status=version.source_status,  # type: ignore[arg-type]  # checked by both models
            basis_commit=basis.commit if basis else None,
            basis_date=basis.synced_at[:10] if basis else None,
        )
    family = (
        ProductFamily(key=version.family.key, display_name=version.family.display_name)
        if version.family is not None
        else None
    )
    return EntityMetadata(identifiers=identifiers, lifecycle=lifecycle, family=family)


def registry_metadata(path: Path, product_id: str) -> EntityMetadata:
    """One registered product's metadata, read without writing (a pure read like publish uses)."""
    registry = load_registry(path)
    entry = registry.products.get(product_id)
    if entry is None:
        raise RegistryError("PRODUCT_UNKNOWN")
    return entity_metadata(product_id, entry, registry.metadata_basis)

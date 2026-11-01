"""A compiled product's page data: who it is and how its fields are grouped (S3d-2 Spec §3.2).

Both come from the catalog as data. The Entity takes the pack's entity type and classification
labels and the product's filed name; the PresentationProfile is the pack's catalog profile,
labelled with the same classifications so a reader can match the two. The catalog must agree
with itself (profile reference, pack, fields and titles, one pack per label): anything else
stops the build rather than publishing a page a reader would show wrongly.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.contracts import Entity, PresentationProfile
from insurance_harness.contracts.knowledge import ProductFamily, ProductLifecycle

OWNER_MODULE = "harness/schema_fields"


@dataclass(frozen=True)
class ProductPage:
    entity: Entity
    profile: PresentationProfile


@dataclass(frozen=True)
class EntityMetadata:
    """A product version's published identity (PV-4 Spec §3.1): what the registry knows of it."""

    identifiers: Mapping[str, str]
    lifecycle: ProductLifecycle | None = None
    family: ProductFamily | None = None


class _Record(BaseModel):
    # The generated catalog carries more than a page needs; only these keys are read.
    model_config = ConfigDict(strict=True, extra="ignore")


class _Field(_Record):
    field_key: str
    short_title: str


class _PackField(_Field):
    # The schema's definition and category travel to readers for concept pages (S3e).
    description: str | None = None
    schema_category: str | None = None


class _Section(_Record):
    section_key: str
    display_name: str
    fields: list[_Field]


class _Profile(_Record):
    profile_id: str
    profile_version: str
    profile_sha256: str
    schema_pack_id: str
    sections: list[_Section]


class _ProfileRef(_Record):
    profile_id: str
    profile_version: str


class _Pack(_Record):
    schema_pack_id: str
    display_name: str | None = None
    entity_type: str
    applicable_classifications: list[str]
    presentation_profile_ref: _ProfileRef
    fields: list[_PackField]


class _Entry(_Record):
    pack: _Pack
    profile: _Profile


class _Catalog(_Record):
    entries: list[_Entry]


def product_page(
    catalog_path: str | Path,
    pack_id: str,
    *,
    entity_id: str,
    name: str,
    metadata: EntityMetadata | None = None,
) -> ProductPage:
    """The Entity and PresentationProfile of one product compiled with the given pack.

    Without metadata (no registry, or an entry without a version record) the entity keeps the
    identity it has always had: the internal ID as product code, no lifecycle or family.
    """
    try:
        catalog = _Catalog.model_validate_json(Path(catalog_path).read_bytes())
    except (OSError, ValidationError):
        raise BundleError("CATALOG_UNREADABLE") from None
    matches = [entry for entry in catalog.entries if entry.pack.schema_pack_id == pack_id]
    if not matches:
        raise BundleError("PACK_UNKNOWN")
    if len(matches) > 1:
        raise BundleError("CATALOG_UNREADABLE")
    [entry] = matches
    pack, profile = entry.pack, entry.profile
    ref = pack.presentation_profile_ref
    if (profile.profile_id, profile.profile_version, profile.schema_pack_id) != (
        ref.profile_id,
        ref.profile_version,
        pack.schema_pack_id,
    ):
        raise BundleError("PROFILE_MISMATCH")
    labels = set(pack.applicable_classifications)
    if any(
        labels & set(other.pack.applicable_classifications)
        for other in catalog.entries
        if other is not entry
    ):
        raise BundleError("PROFILE_INVALID")  # a reader could not tell which profile applies
    definitions = {field.field_key: field for field in pack.fields}
    data = profile.model_dump()
    for section in data["sections"]:
        for field in section["fields"]:
            defined = definitions.get(field["field_key"])
            if defined is not None:
                field["description"] = defined.description
                field["schema_category"] = defined.schema_category
    try:
        presentation = PresentationProfile.model_validate(
            {
                **data,
                "display_name": pack.display_name,
                "classification_labels": pack.applicable_classifications,
            }
        )
    except ValidationError:
        raise BundleError("PROFILE_INVALID") from None
    titles = {field.field_key: field.short_title for field in pack.fields}
    if any(
        titles.get(field.field_key) != field.short_title
        for section in presentation.sections
        for field in section.fields
    ):
        raise BundleError("PROFILE_INVALID")
    try:
        entity = Entity(
            entity_id=entity_id,
            entity_type=pack.entity_type,
            names=[name],
            identifiers=(
                dict(metadata.identifiers) if metadata is not None else {"product_code": entity_id}
            ),
            classification_labels=pack.applicable_classifications,
            owner_module=OWNER_MODULE,
            lifecycle=metadata.lifecycle if metadata is not None else None,
            product_family=metadata.family if metadata is not None else None,
        )
    except ValidationError:
        raise BundleError("ENTITY_INVALID") from None  # blank identity: nothing to name the page
    return ProductPage(entity=entity, profile=presentation)

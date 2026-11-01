"""The filed version a registry entry stands for (PV-1 Spec §2.3; PV-0 §3.1, appendix A §1.4).

One entry is one filed version. Its external key, sale period and source status come from the
pinned catalog; its family and year tag are derived from its name by the attribution policy's
brand rules, for grouping and candidates only — never an attribution anchor. The sale status is
not stored: readers derive it from the period and the source status (PV-0 appendix A §3.2).
"""

from collections.abc import Iterable, Mapping
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.main import IncEx

from insurance_harness.identity.attribution import AttributionPolicy, load_attribution_policy
from insurance_harness.identity.brands import brand_core, years
from insurance_harness.identity.text import fold
from insurance_harness.identity.version_basis import RegisteredVersion
from insurance_harness.ingest.version_catalog import DateText, VersionCatalog, VersionRecord


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ProductFamily(_Strict):
    key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class ProductVersion(_Strict):
    version_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{1,32}-[0-9]{1,4}$")
    plan_code: str | None = None
    version_no: int | None = Field(default=None, ge=1)
    sale_start: DateText | None = None
    sale_end: DateText | None = None
    source_status: str | None = Field(default=None, pattern=r"^(on_sale|discontinued)$")
    channel: str | None = None
    plan_type: str | None = None
    year_tag: int | None = Field(default=None, ge=2000, le=2099)
    family: ProductFamily | None = None
    predecessor: str | None = None
    version_ambiguous: bool = False  # several filed versions share its clause code(s)

    @model_validator(mode="after")
    def _consistent(self) -> "ProductVersion":
        for text in (self.sale_start, self.sale_end):
            if text is not None:
                date.fromisoformat(text)
        if self.sale_start and self.sale_end and self.sale_start >= self.sale_end:
            raise ValueError("a sale period that ends before it starts")
        if self.version_ambiguous and self.version_key is not None:
            raise ValueError("an ambiguous entry names no version")
        return self


class MetadataBasis(_Strict):
    """Where the version fields came from: the pinned repository commit and its stored catalog."""

    repository: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    synced_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def family_of(name: str, policy: AttributionPolicy) -> ProductFamily | None:
    key = brand_core(name, policy)
    shown = brand_core(name, policy, casefold=False)
    return ProductFamily(key=key, display_name=shown) if key and shown else None


def year_tag_of(name: str, policy: AttributionPolicy) -> int | None:
    found = years(fold(name), policy.product_year_patterns)
    return 2000 + int(found.pop()) if len(found) == 1 else None


def version_of(
    record: VersionRecord | None,
    name: str,
    policy: AttributionPolicy,
    *,
    ambiguous: bool = False,
) -> ProductVersion:
    """The version fields of an entry: the catalog record's when it names exactly one version."""
    derived = {"year_tag": year_tag_of(name, policy), "family": family_of(name, policy)}
    if record is None:
        return ProductVersion(version_ambiguous=ambiguous, **derived)  # type: ignore[arg-type]
    return ProductVersion(
        version_key=record.version_key,
        plan_code=record.plan_code,
        version_no=record.version_no,
        sale_start=record.sale_start,
        sale_end=record.sale_end,
        source_status=record.source_status,
        channel=record.channel,
        plan_type=record.plan_type,
        **derived,  # type: ignore[arg-type]
    )


def entry_version(
    v2: bool, key: str | None, name: str | None, catalog: VersionCatalog | None
) -> ProductVersion | None:
    """The version of an entry CREATE or NEW_VERSION adds: none in a v1 registry; in a v2 one,
    the catalog record of the attributed key, when the catalog has it."""
    if not v2:
        return None
    found = catalog.get(key) if catalog is not None and key is not None else None
    return version_of(found, name or "", load_attribution_policy())


def v1_excluded() -> IncEx:
    """The v2 fields a v1 registry file never contains (PV-1 Spec §2.3), so code without them can
    still read it: an entry's version, the basis, and an attribution's version key (only ever set
    with a v2 registry's catalog)."""
    key: dict[str, IncEx | bool] = {  # PV-1, PV-3
        "version_key": True,
        "version_basis": True,
        "shared_versions": True,
    }
    conclusion: dict[str, IncEx | bool] = {"conclusion": key}
    pending: dict[str, IncEx | bool] = {"attribution": key, "settlement": conclusion}
    decision: dict[str, IncEx | bool] = {"attribution": key}
    excluded: dict[str, IncEx | bool] = {
        "metadata_basis": True,
        "products": {"__all__": {"version": True}},
        "pending": {"__all__": pending},
        "decisions": {"__all__": decision},
    }
    return excluded


def registered_version(
    version: ProductVersion | None, basis: MetadataBasis | None
) -> RegisteredVersion | None:
    """What attribution reads of an entry's version (PV-3 Spec §2.5): None in a v1 registry."""
    if version is None:
        return None
    return RegisteredVersion(
        version_key=version.version_key,
        year_tag=version.year_tag,
        sale_start=version.sale_start,
        sale_end=version.sale_end,
        source_status=version.source_status,
        plan_type=version.plan_type,
        basis_commit=basis.commit if basis is not None else None,
    )


def predecessors(versions: Mapping[str, ProductVersion | None]) -> dict[str, str | None]:
    """The unique predecessor of each entry (appendix A §1.4): same plan code, its sale ending the
    day this one starts, and exactly one such entry. Never inferred from names or date order."""
    linked: dict[str, str | None] = {}
    for product_id, version in versions.items():
        found = [
            other_id
            for other_id, other in versions.items()
            if version is not None
            and other is not None
            and other_id != product_id
            and version.plan_code is not None
            and other.plan_code == version.plan_code
            and version.sale_start is not None
            and other.sale_end == version.sale_start
        ]
        linked[product_id] = found[0] if len(found) == 1 else None
    return linked


def relinked(versions: Mapping[str, ProductVersion | None]) -> dict[str, ProductVersion | None]:
    """The versions with every predecessor recomputed (an entry without a version stays so)."""
    linked = predecessors(versions)
    return {
        pid: v.model_copy(update={"predecessor": linked[pid]}) if v is not None else None
        for pid, v in versions.items()
    }


def check_versions(
    contract: str,
    basis: MetadataBasis | None,
    versions: Mapping[str, ProductVersion | None],
    decided_keys: Iterable[str | None] = (),
    decided_evidence: bool = False,
) -> None:
    """The registry-wide rules of PV-1 Spec §2.3, raised as ValueError for the model validator.

    `decided_keys` are the version keys of every recorded attribution (pending, settlement and
    decision): a v1 registry holds none, rather than dropping them when it is saved (review R5);
    likewise no PV-3 field or outcome (`decided_evidence`: version evidence, shared versions or
    DETACHED; PV-3 Spec §2.8, §4).
    """
    if contract == "product-registry.v1":
        if basis is not None or any(v is not None for v in versions.values()):
            raise ValueError("a v1 registry holds no version fields")
        if any(key is not None for key in decided_keys) or decided_evidence:
            raise ValueError("a v1 registry records no version key or PV-3 field")
        return
    if basis is None:
        raise ValueError("a v2 registry names its metadata basis")
    keys = [v.version_key for v in versions.values() if v is not None and v.version_key]
    if len(set(keys)) != len(keys):
        raise ValueError("two entries name one filed version")
    for product_id, version in versions.items():
        target = version.predecessor if version is not None else None
        if target is not None and (target == product_id or target not in versions):
            raise ValueError("a predecessor that is not another registered entry")


def same_name(left: str, right: str) -> bool:
    """Names compared as titles are: folded, so brackets of either width are alike."""
    return fold(left) == fold(right)

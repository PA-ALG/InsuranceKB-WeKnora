"""Read-only, fail-closed ProductVersion identity resolution (OpenSpec 041).

Candidate recall never mints identity; only exact persisted anchors may resolve.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from insurance_harness.canonical import canonical_hash
from insurance_harness.db.models import InsuranceProduct, ProductAlias, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, require_current_scope

RESOLVER_VERSION: Final[str] = "p5a0.product-version-resolver.v1"
_POLICY_MANIFEST: Final[dict[str, object]] = {
    "resolver_version": RESOLVER_VERSION,
    "priority": (
        "version_filing_or_registration",
        "exact_product_code_or_name",
        "approved_alias",
    ),
    "approved_alias": {"alias_type": "manual", "source": "manual"},
    "candidate_only": ("fuzzy", "embedding", "llm", "legacy_auto_alias"),
    "version_anchor": "product_version.terms_revision_only",
    "master_data": "veto_only",
}
RESOLVER_POLICY_HASH: Final[str] = canonical_hash(
    "product-version-resolver-policy",
    _POLICY_MANIFEST,
)

QuarantineReason = Literal[
    "anchor_conflict", "anchor_not_found", "ambiguous_product",
    "ambiguous_version", "cross_space", "master_data_mismatch",
    "no_authoritative_anchor", "resolution_hash_mismatch", "version_missing",
]
AnchorKind = Literal[
    "filing_number", "registration_number", "product_code",
    "product_name", "approved_alias", "candidate_only_alias",
    "candidate_only_hint", "master_category", "master_channel", "master_region",
]


def _require_text(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("identity text must be a non-empty exact string")
    return value


class ProductVersionResolutionRequest(BaseModel):
    """Exact resolver inputs; recall hints are carried but never authoritative."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_space_id: str
    document_ref: str
    section_ref: str | None = None
    filing_numbers: tuple[str, ...] = ()
    registration_numbers: tuple[str, ...] = ()
    product_codes: tuple[str, ...] = ()
    product_names: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    recall_candidate_version_ids: tuple[str, ...] = ()
    expected_category: str | None = None
    expected_channel: str | None = None
    expected_region: str | None = None

    @field_validator(
        "source_space_id",
        "document_ref",
        "section_ref",
        "expected_category",
        "expected_channel",
        "expected_region",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _require_text(value)

    @field_validator(
        "filing_numbers",
        "registration_numbers",
        "product_codes",
        "product_names",
        "aliases",
        "recall_candidate_version_ids",
    )
    @classmethod
    def _validate_text_tuple(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_require_text(value) for value in values)


class ResolutionBasis(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    priority: int
    anchor_kind: AnchorKind
    observed_value: str
    normalized_value: str
    matched_field: str
    matched_product_ids: tuple[str, ...]
    matched_product_version_ids: tuple[str, ...]
    authoritative: bool


class ResolvedProductVersion(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    space_id: str
    document_ref: str
    section_ref: str | None
    product_id: str
    product_version_id: str
    product_code: str
    canonical_name: str
    version_label: str
    resolver_version: str
    resolver_hash: str
    basis: tuple[ResolutionBasis, ...]
    resolution_hash: str


class FragmentProductVersionBinding(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    fragment_ref: str
    space_id: str
    product_id: str
    product_version_id: str
    parent_resolution_hash: str
    binding_hash: str


class ProductVersionQuarantine(ValueError):
    """Typed fail-closed result with deterministic evidence."""

    def __init__(
        self,
        reason_code: QuarantineReason,
        *,
        basis: tuple[ResolutionBasis, ...] = (),
        candidate_version_ids: tuple[str, ...] = (),
    ) -> None:
        self.reason_code = reason_code
        self.basis = basis
        self.candidate_version_ids = tuple(sorted(candidate_version_ids))
        super().__init__(f"product version quarantined: {reason_code}")


@dataclass(frozen=True, slots=True)
class _Product:
    product_id: str
    product_code: str
    canonical_name: str
    category: str


@dataclass(frozen=True, slots=True)
class _Version:
    product_id: str
    product_version_id: str
    version_label: str
    terms_revision: str | None
    channels: tuple[str, ...] | None
    regions: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class _Alias:
    product_id: str
    alias: str
    alias_type: str
    source: str


@dataclass(frozen=True, slots=True)
class _Catalog:
    products: tuple[_Product, ...]
    versions: tuple[_Version, ...]
    aliases: tuple[_Alias, ...]


class ProductVersionResolver:
    """Resolve one document/section against fresh scoped master data."""

    def __init__(self, session: Session, scope: KnowledgeScope) -> None:
        self._session = session
        self._scope = scope

    def resolve(
        self,
        request: ProductVersionResolutionRequest,
    ) -> ResolvedProductVersion:
        if request.source_space_id != self._scope.space_id:
            raise ProductVersionQuarantine("cross_space")

        require_current_scope(self._session, self._scope)
        catalog = self._load_catalog()
        basis = self._match_anchors(catalog, request)
        authoritative = tuple(item for item in basis if item.authoritative)
        if not authoritative:
            self._quarantine("no_authoritative_anchor", basis=basis)

        primary_priority = min(item.priority for item in authoritative)
        primary = tuple(
            item for item in authoritative if item.priority == primary_priority
        )
        if any(not item.matched_product_ids for item in primary):
            self._quarantine(
                "anchor_not_found",
                basis=basis,
                candidate_ids=self._candidate_union(primary),
            )
        if any(len(item.matched_product_ids) > 1 for item in primary):
            self._quarantine(
                "ambiguous_product",
                basis=basis,
                candidate_ids=self._candidate_union(primary),
            )
        if any(
            item.matched_product_ids and not item.matched_product_version_ids
            for item in primary
        ):
            self._quarantine(
                "version_missing",
                basis=basis,
                candidate_ids=self._candidate_union(primary),
            )

        candidate_sets = [
            set(item.matched_product_version_ids) for item in primary
        ]
        intersection = set.intersection(*candidate_sets)
        candidate_union = self._candidate_union(primary)
        if not intersection:
            self._quarantine(
                "anchor_conflict",
                basis=basis,
                candidate_ids=candidate_union,
            )
        if len(intersection) > 1:
            product_ids = {
                product_id
                for item in primary
                for product_id in item.matched_product_ids
            }
            reason: QuarantineReason = (
                "ambiguous_product" if len(product_ids) > 1 else "ambiguous_version"
            )
            self._quarantine(reason, basis=basis, candidate_ids=candidate_union)

        version_id = next(iter(intersection))
        version = next(
            item for item in catalog.versions if item.product_version_id == version_id
        )
        product = next(
            item for item in catalog.products if item.product_id == version.product_id
        )
        lower_priority = tuple(
            item for item in authoritative if item.priority > primary_priority
        )
        if any(
            (
                item.matched_product_version_ids
                and version_id not in item.matched_product_version_ids
            )
            or (
                item.matched_product_ids
                and product.product_id not in item.matched_product_ids
            )
            for item in lower_priority
        ):
            self._quarantine(
                "anchor_conflict",
                basis=basis,
                candidate_ids=self._candidate_union(authoritative),
            )
        basis = self._apply_master_data_veto(request, product, version, basis)
        return self._build_resolution(request, product, version, basis)

    def _load_catalog(self) -> _Catalog:
        with self._session.no_autoflush:
            rows = self._session.execute(
                select(
                    InsuranceProduct.id.label("product_id"),
                    InsuranceProduct.product_code.label("product_code"),
                    InsuranceProduct.canonical_name.label("canonical_name"),
                    InsuranceProduct.category.label("category"),
                    ProductVersion.id.label("product_version_id"),
                    ProductVersion.product_id.label("version_product_id"),
                    ProductVersion.version_label.label("version_label"),
                    ProductVersion.terms_revision.label("terms_revision"),
                    ProductVersion.channels.label("channels"),
                    ProductVersion.regions.label("regions"),
                    ProductAlias.id.label("alias_id"),
                    ProductAlias.product_id.label("alias_product_id"),
                    ProductAlias.alias.label("alias"),
                    ProductAlias.alias_type.label("alias_type"),
                    ProductAlias.source.label("alias_source"),
                )
                .outerjoin(
                    ProductVersion,
                    and_(
                        ProductVersion.space_id == InsuranceProduct.space_id,
                        ProductVersion.product_id == InsuranceProduct.id,
                    ),
                )
                .outerjoin(
                    ProductAlias,
                    ProductAlias.product_id == InsuranceProduct.id,
                )
                .where(InsuranceProduct.space_id == self._scope.space_id)
                .order_by(
                    InsuranceProduct.id,
                    ProductVersion.id,
                    ProductAlias.id,
                )
            ).mappings()
        products: dict[str, _Product] = {}
        versions: dict[str, _Version] = {}
        aliases: dict[str, _Alias] = {}
        for row in rows:
            product_id = row["product_id"]
            products[product_id] = _Product(
                product_id=product_id,
                product_code=row["product_code"],
                canonical_name=row["canonical_name"],
                category=row["category"],
            )
            product_version_id = row["product_version_id"]
            if product_version_id is not None:
                channels = row["channels"]
                regions = row["regions"]
                versions[product_version_id] = _Version(
                    product_id=row["version_product_id"],
                    product_version_id=product_version_id,
                    version_label=row["version_label"],
                    terms_revision=row["terms_revision"],
                    channels=(
                        None if channels is None else tuple(channels)
                    ),
                    regions=(
                        None if regions is None else tuple(regions)
                    ),
                )
            alias_id = row["alias_id"]
            if alias_id is not None:
                aliases[alias_id] = _Alias(
                    product_id=row["alias_product_id"],
                    alias=row["alias"],
                    alias_type=row["alias_type"],
                    source=row["alias_source"],
                )
        return _Catalog(
            products=tuple(products[key] for key in sorted(products)),
            versions=tuple(versions[key] for key in sorted(versions)),
            aliases=tuple(aliases[key] for key in sorted(aliases)),
        )

    def _match_anchors(
        self,
        catalog: _Catalog,
        request: ProductVersionResolutionRequest,
    ) -> tuple[ResolutionBasis, ...]:
        basis: list[ResolutionBasis] = []
        for value in request.filing_numbers:
            basis.append(
                self._match_version_identifier(catalog, "filing_number", value)
            )
        for value in request.registration_numbers:
            basis.append(
                self._match_version_identifier(catalog, "registration_number", value)
            )
        for value in request.product_codes:
            basis.append(
                self._match_product_field(
                    catalog,
                    "product_code",
                    value,
                    field_name="product_code",
                )
            )
        for value in request.product_names:
            basis.append(
                self._match_product_field(
                    catalog,
                    "product_name",
                    value,
                    field_name="canonical_name",
                )
            )
        for value in request.aliases:
            basis.append(self._match_alias(catalog, value))
        versions = {item.product_version_id: item for item in catalog.versions}
        for value in request.recall_candidate_version_ids:
            candidate = versions.get(value)
            basis.append(
                self._basis(
                    priority=4,
                    kind="candidate_only_hint",
                    observed=value,
                    matched_field=(
                        "recall_candidate_version_id"
                        if candidate is not None
                        else "none"
                    ),
                    product_ids=(
                        set() if candidate is None else {candidate.product_id}
                    ),
                    version_ids=set() if candidate is None else {value},
                    authoritative=False,
                )
            )
        return tuple(basis)

    def _match_version_identifier(
        self,
        catalog: _Catalog,
        kind: Literal["filing_number", "registration_number"],
        observed: str,
    ) -> ResolutionBasis:
        normalized = _normalize(observed)
        version_ids = {
            version.product_version_id
            for version in catalog.versions
            if version.terms_revision is not None
            and _normalize(version.terms_revision) == normalized
        }
        product_ids = {
            version.product_id
            for version in catalog.versions
            if version.product_version_id in version_ids
        }
        return self._basis(
            priority=1,
            kind=kind,
            observed=observed,
            matched_field="terms_revision" if version_ids else "none",
            product_ids=product_ids,
            version_ids=version_ids,
            authoritative=True,
        )

    def _match_product_field(
        self,
        catalog: _Catalog,
        kind: Literal["product_code", "product_name"],
        observed: str,
        *,
        field_name: Literal["product_code", "canonical_name"],
    ) -> ResolutionBasis:
        normalized = _normalize(observed)
        product_ids = {
            product.product_id
            for product in catalog.products
            if _normalize(getattr(product, field_name)) == normalized
        }
        return self._basis(
            priority=2,
            kind=kind,
            observed=observed,
            matched_field=field_name if product_ids else "none",
            product_ids=product_ids,
            version_ids=self._versions_for_products(catalog, product_ids),
            authoritative=True,
        )

    def _match_alias(self, catalog: _Catalog, observed: str) -> ResolutionBasis:
        normalized = _normalize(observed)
        approved_product_ids = {
            alias.product_id
            for alias in catalog.aliases
            if alias.alias_type == "manual"
            and alias.source == "manual"
            and _normalize(alias.alias) == normalized
        }
        if approved_product_ids:
            return self._basis(
                priority=3,
                kind="approved_alias",
                observed=observed,
                matched_field="approved_alias",
                product_ids=approved_product_ids,
                version_ids=self._versions_for_products(
                    catalog,
                    approved_product_ids,
                ),
                authoritative=True,
            )
        candidate_product_ids = {
            alias.product_id
            for alias in catalog.aliases
            if _normalize(alias.alias) == normalized
        }
        return self._basis(
            priority=4,
            kind="candidate_only_alias",
            observed=observed,
            matched_field="candidate_only_alias" if candidate_product_ids else "none",
            product_ids=candidate_product_ids,
            version_ids=self._versions_for_products(
                catalog,
                candidate_product_ids,
            ),
            authoritative=False,
        )

    @staticmethod
    def _versions_for_products(
        catalog: _Catalog,
        product_ids: set[str],
    ) -> set[str]:
        return {
            version.product_version_id
            for version in catalog.versions
            if version.product_id in product_ids
        }

    @staticmethod
    def _basis(
        *,
        priority: int,
        kind: AnchorKind,
        observed: str,
        matched_field: str,
        product_ids: set[str],
        version_ids: set[str],
        authoritative: bool,
    ) -> ResolutionBasis:
        return ResolutionBasis(
            priority=priority,
            anchor_kind=kind,
            observed_value=observed,
            normalized_value=_normalize(observed),
            matched_field=matched_field,
            matched_product_ids=tuple(sorted(product_ids)),
            matched_product_version_ids=tuple(sorted(version_ids)),
            authoritative=authoritative,
        )

    @staticmethod
    def _candidate_union(basis: tuple[ResolutionBasis, ...]) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    version_id
                    for item in basis
                    for version_id in item.matched_product_version_ids
                }
            )
        )

    @staticmethod
    def _apply_master_data_veto(
        request: ProductVersionResolutionRequest,
        product: _Product,
        version: _Version,
        basis: tuple[ResolutionBasis, ...],
    ) -> tuple[ResolutionBasis, ...]:
        checks: list[ResolutionBasis] = []
        constraints: tuple[
            tuple[AnchorKind, str | None, str | tuple[str, ...] | None, str],
            ...,
        ] = (
            (
                "master_category",
                request.expected_category,
                product.category,
                "category",
            ),
            (
                "master_channel",
                request.expected_channel,
                version.channels,
                "channel",
            ),
            (
                "master_region",
                request.expected_region,
                version.regions,
                "region",
            ),
        )
        for kind, observed, actual, field_name in constraints:
            if observed is None:
                continue
            matched = (
                observed == actual
                if type(actual) is str
                else actual is not None and observed in actual
            )
            checks.append(
                ProductVersionResolver._basis(
                    priority=5,
                    kind=kind,
                    observed=observed,
                    matched_field=field_name if matched else "none",
                    product_ids={product.product_id} if matched else set(),
                    version_ids=(
                        {version.product_version_id} if matched else set()
                    ),
                    authoritative=False,
                )
            )
        complete_basis = basis + tuple(checks)
        if any(not item.matched_product_version_ids for item in checks):
            raise ProductVersionQuarantine(
                "master_data_mismatch",
                basis=complete_basis,
                candidate_version_ids=(version.product_version_id,),
            )
        return complete_basis

    @staticmethod
    def _build_resolution(
        request: ProductVersionResolutionRequest,
        product: _Product,
        version: _Version,
        basis: tuple[ResolutionBasis, ...],
    ) -> ResolvedProductVersion:
        payload = {
            "space_id": request.source_space_id,
            "document_ref": request.document_ref,
            "section_ref": request.section_ref,
            "product_id": product.product_id,
            "product_version_id": version.product_version_id,
            "product_code": product.product_code,
            "canonical_name": product.canonical_name,
            "version_label": version.version_label,
            "resolver_version": RESOLVER_VERSION,
            "resolver_hash": RESOLVER_POLICY_HASH,
            "basis": tuple(item.model_dump(mode="python") for item in basis),
        }
        return ResolvedProductVersion(
            space_id=request.source_space_id,
            document_ref=request.document_ref,
            section_ref=request.section_ref,
            product_id=product.product_id,
            product_version_id=version.product_version_id,
            product_code=product.product_code,
            canonical_name=product.canonical_name,
            version_label=version.version_label,
            resolver_version=RESOLVER_VERSION,
            resolver_hash=RESOLVER_POLICY_HASH,
            basis=basis,
            resolution_hash=canonical_hash("product-version-resolution", payload),
        )

    @staticmethod
    def _quarantine(
        reason: QuarantineReason,
        *,
        basis: tuple[ResolutionBasis, ...],
        candidate_ids: tuple[str, ...] = (),
    ) -> None:
        raise ProductVersionQuarantine(
            reason,
            basis=basis,
            candidate_version_ids=candidate_ids,
        )


def inherit_fragment_resolution(
    parent: ResolvedProductVersion,
    *,
    fragment_ref: str,
) -> FragmentProductVersionBinding:
    """Bind a fragment to an existing resolution without any identity lookup."""
    fragment_ref = _require_text(fragment_ref)
    parent_payload = parent.model_dump(
        mode="python",
        exclude={"resolution_hash"},
    )
    if (
        canonical_hash("product-version-resolution", parent_payload)
        != parent.resolution_hash
    ):
        raise ProductVersionQuarantine(
            "resolution_hash_mismatch",
            basis=parent.basis,
            candidate_version_ids=(parent.product_version_id,),
        )
    payload = {
        "fragment_ref": fragment_ref,
        "space_id": parent.space_id,
        "product_id": parent.product_id,
        "product_version_id": parent.product_version_id,
        "parent_resolution_hash": parent.resolution_hash,
    }
    return FragmentProductVersionBinding(
        **payload,
        binding_hash=canonical_hash("fragment-product-version-binding", payload),
    )


def _normalize(value: str) -> str:
    return "".join(unicodedata.normalize("NFC", value).split())


__all__ = [
    "RESOLVER_POLICY_HASH",
    "RESOLVER_VERSION",
    "FragmentProductVersionBinding",
    "ProductVersionQuarantine",
    "ProductVersionResolutionRequest",
    "ProductVersionResolver",
    "ResolutionBasis",
    "ResolvedProductVersion",
    "inherit_fragment_resolution",
]

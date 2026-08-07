"""Private 096 receipt bytes to exact public 092 admission inputs.

This task-local adapter owns file custody and composition only. It never derives
relations, endpoints, source authority, parse authority, or admission outcomes.
"""

from __future__ import annotations

import inspect
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Never, Protocol, cast

from pydantic import ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureIntakeError,
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    POLICY_SHA256,
    CrossPageBindingError,
    CrossPageRelationBindingV1,
    replay_cross_page_relation_binding_v1,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    SourceAdmissionAuthorityV1,
    TypedMarkerEndpointMapV1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    DerivedRelationReceipt5961V1,
    RelationReceiptBridgeError,
    replay_relation_receipt_596_1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
    EXPECTED_596_1_PARSE_SOURCES,
)

_MAX_RECEIPT_BYTES = 1024 * 1024
_EXPECTED_ROLES = ("terms", "brochure", "rate")
_ROOT_KEYS = {
    "contract",
    "status",
    "intake_bundle_digest_sha256",
    "relations",
    "receipt_digest_sha256",
}


class RelationReceiptAuthorityAdapterError(ValueError):
    """Privacy-safe fixed-code adapter failure."""

    def __init__(
        self,
        status: Literal["DEPENDENCY_UNAVAILABLE", "BLOCKED_ON_CROSS_PAGE_BINDING"],
        reason_code: str,
    ) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(f"{status}:{reason_code}")

    def __repr__(self) -> str:
        return (
            "RelationReceiptAuthorityAdapterError("
            f"{self.status!r}, {self.reason_code!r})"
        )


def _fail(
    status: Literal["DEPENDENCY_UNAVAILABLE", "BLOCKED_ON_CROSS_PAGE_BINDING"],
    reason_code: str,
) -> Never:
    raise RelationReceiptAuthorityAdapterError(status, reason_code)


class _DuplicateKeyError(ValueError):
    pass


def _leading_rows_signature(
    structure: dict[str, Any], table: dict[str, Any]
) -> tuple[tuple[object, ...], ...] | None:
    if table.get("row_count", 0) < 2:
        return None
    cells = tuple(
        cell
        for cell in structure.get("cells", ())
        if cell.get("table_id") == table.get("table_id")
        and cell.get("row_index", 2) < 2
    )
    occupied: set[tuple[int, int]] = set()
    signature: list[tuple[object, ...]] = []
    for cell in sorted(cells, key=lambda item: (item["row_index"], item["column_index"])):
        for row_index in range(
            cell["row_index"], min(2, cell["row_index"] + cell["row_span"])
        ):
            for column_index in range(
                cell["column_index"], cell["column_index"] + cell["column_span"]
            ):
                position = (row_index, column_index)
                if position in occupied:
                    return None
                occupied.add(position)
        signature.append(
            (
                cell["row_index"],
                cell["column_index"],
                cell["row_span"],
                cell["column_span"],
                cell["content_hash"],
            )
        )
    expected = {
        (row_index, column_index)
        for row_index in range(2)
        for column_index in range(table["column_count"])
    }
    return tuple(signature) if occupied == expected else None


def _derived_rate_binding_matches_capture(
    *, item: Any, binding: CrossPageRelationBindingV1
) -> bool:
    try:
        facts = item.evidence.cross_page_facts
        if (
            facts is None
            or facts.status != "NATIVE_CROSS_PAGE_FACT_ABSENT"
            or facts.required_capability != "cross_page_tables"
            or facts.relation_count != 0
            or facts.relations
            or facts.ambiguous_marker_count != 0
            or facts.ambiguous_observation_hashes
        ):
            return False
        structure = json.loads(item.evidence.sanitized_structure)
        tables = tuple(structure["tables"])
        pairs: list[tuple[dict[str, Any], dict[str, Any], tuple[tuple[object, ...], ...]]] = []
        for source in tables:
            source_signature = _leading_rows_signature(structure, source)
            if source_signature is None:
                continue
            for target in tables:
                target_signature = _leading_rows_signature(structure, target)
                if (
                    target["page_number"] == source["page_number"] + 1
                    and target["column_count"] == source["column_count"]
                    and target_signature == source_signature
                ):
                    pairs.append((source, target, source_signature))
        if len(pairs) != 1:
            return False
        source, target, signature = pairs[0]
        if (
            source["table_id"] != binding.source_endpoint.endpoint_id
            or source["page_number"] != binding.source_endpoint.page_number
            or target["table_id"] != binding.target_endpoint.endpoint_id
            or target["page_number"] != binding.target_endpoint.page_number
        ):
            return False
        preimage = {
            "contract": "unique-repeated-leading-table-grid.v1",
            "source_sha256": item.source_sha256,
            "raw_structure_sha256": item.evidence.raw_structure_sha256,
            "artifact_sha256": item.evidence.sanitized_structure_sha256,
            "source_table_id": source["table_id"],
            "source_page_number": source["page_number"],
            "target_table_id": target["table_id"],
            "target_page_number": target["page_number"],
            "column_count": source["column_count"],
            "leading_rows": signature,
        }
        expected_observation = canonical_hash(
            "unique-repeated-leading-table-grid.v1", preimage
        )
        expected_evidence = canonical_hash("derived-table-grid-evidence.v1", preimage)
        expected_path = canonical_hash(
            "derived-table-grid-path.v1",
            {
                "source": (source["page_number"], source["table_index"]),
                "target": (target["page_number"], target["table_index"]),
            },
        )
        return (
            binding.native_projection_sha256 == facts.projection_sha256
            and binding.native_observation_sha256 == expected_observation
            and binding.typed_marker_evidence_digest_sha256 == expected_evidence
            and binding.marker_path_sha256 == expected_path
        )
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonfinite(_: str) -> Never:
    raise ValueError


class _MarkerMapBuilder(Protocol):
    def __call__(
        self,
        *,
        bundle: MinerUCaptureBundle5961V1,
        receipt: DerivedRelationReceipt5961V1,
    ) -> tuple[TypedMarkerEndpointMapV1, ...]: ...


def _resolve_098_marker_map_builder() -> _MarkerMapBuilder | None:
    """Resolve only the future exact 098 public seam; current 098 is incomplete."""

    try:
        from insurance_harness.knowledge_compiler import (
            marker_endpoint_pair_bridge_596_1 as bridge,
        )

        candidate = getattr(bridge, "build_092_marker_endpoint_mappings_596_1", None)
        if not callable(candidate):
            return None
        parameters = inspect.signature(candidate).parameters
        if tuple(parameters) != ("bundle", "receipt") or any(
            parameter.kind is not inspect.Parameter.KEYWORD_ONLY
            for parameter in parameters.values()
        ):
            return None
        return cast(_MarkerMapBuilder, candidate)
    except (AttributeError, ImportError, TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class _ReceiptRelationProvider:
    bundle: MinerUCaptureBundle5961V1 = field(repr=False)
    receipt: DerivedRelationReceipt5961V1 = field(repr=False)

    def __call__(
        self,
        bundle: MinerUCaptureBundle5961V1,
        document: ParsedDocumentV1,
        manifest: ParseManifestV1,
        *,
        relation_kind: Literal["section", "table"],
    ) -> CrossPageRelationBindingV1 | tuple[CrossPageRelationBindingV1, ...]:
        try:
            if bundle != self.bundle or relation_kind not in {"section", "table"}:
                raise ValueError
            expected_role = (
                "rate_table"
                if relation_kind == "table"
                else "terms"
                if document.subject.source_sha256 == self.bundle.sources[0].source_sha256
                else "brochure"
            )
            entries = tuple(
                entry for entry in self.receipt.relations if entry.receipt_role == expected_role
            )
            bindings = tuple(
                replay_cross_page_relation_binding_v1(entry.binding)
                for entry in entries
            )
            if (
                not bindings
                or any(binding.relation_kind != relation_kind for binding in bindings)
                or not isinstance(document, ParsedDocumentV1)
                or not isinstance(manifest, ParseManifestV1)
                or any(
                    document.document_hash != binding.parsed_document_hash
                    or manifest.manifest_hash != binding.parse_manifest_hash
                    for binding in bindings
                )
                or manifest.document_hash != document.document_hash
                or document.subject != manifest.subject
                or any(
                    document.subject.source_sha256 != binding.source_sha256
                    for binding in bindings
                )
            ):
                raise ValueError
            return bindings[0] if len(bindings) == 1 else bindings
        except (
            AttributeError,
            CrossPageBindingError,
            IndexError,
            TypeError,
            ValidationError,
            ValueError,
        ):
            _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_PROVIDER_IDENTITY_MISMATCH")


@dataclass(frozen=True, slots=True)
class ValidatedRelationAdmissionInputs5961V1:
    """The five public inputs accepted by 092, without a builder or outcome."""

    status: Literal["VALIDATED"]
    bundle: MinerUCaptureBundle5961V1 = field(repr=False)
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...] = field(repr=False)
    material_profile_resolutions: tuple[MaterialProfileResolution, ...] = field(repr=False)
    marker_endpoint_mappings: tuple[TypedMarkerEndpointMapV1, ...] = field(repr=False)
    relation_binding_provider: _ReceiptRelationProvider = field(repr=False)

    @property
    def bundle_digest_sha256(self) -> str:
        """Expose the already-validated bundle identity required by the 095 port."""

        return self.bundle.bundle_digest_sha256

    def as_092_kwargs(self) -> dict[str, object]:
        """Return exactly the authority inputs owned by public 092."""

        return {
            "bundle": self.bundle,
            "source_authorities": self.source_authorities,
            "material_profile_resolutions": self.material_profile_resolutions,
            "marker_endpoint_mappings": self.marker_endpoint_mappings,
            "relation_binding_provider": self.relation_binding_provider,
        }


def _parse_receipt_bytes(payload: bytes) -> DerivedRelationReceipt5961V1:
    if (
        type(payload) is not bytes
        or not 0 < len(payload) <= _MAX_RECEIPT_BYTES
        or not payload.endswith(b"\n")
        or payload.endswith(b"\n\n")
    ):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_BYTES_INVALID")
    try:
        text = payload[:-1].decode("utf-8")
        if "\r" in text:
            raise ValueError
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError, TypeError, ValueError):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_BYTES_INVALID")
    if not isinstance(value, dict) or set(value) != _ROOT_KEYS:
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_BYTES_INVALID")
    canonical = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    if canonical != payload:
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_BYTES_INVALID")
    try:
        return replay_relation_receipt_596_1(
            DerivedRelationReceipt5961V1.model_validate(value)
        )
    except (RelationReceiptBridgeError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_REPLAY_FAILED")


def _validate_cross_contracts(
    *,
    receipt: DerivedRelationReceipt5961V1,
    capture_payloads: tuple[bytes, bytes, bytes] | object,
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...] | object,
    material_profile_resolutions: tuple[MaterialProfileResolution, ...] | object,
) -> tuple[
    MinerUCaptureBundle5961V1,
    tuple[SourceAdmissionAuthorityV1, ...],
    tuple[MaterialProfileResolution, ...],
]:
    try:
        if not isinstance(capture_payloads, tuple) or len(capture_payloads) != 3:
            raise ValueError
        checked_bundle = intake_mineru_capture_bundle_596_1(
            cast(tuple[bytes, bytes, bytes], capture_payloads)
        )
        if not isinstance(source_authorities, tuple) or not isinstance(
            material_profile_resolutions, tuple
        ):
            raise ValueError
        authorities = tuple(
            SourceAdmissionAuthorityV1.model_validate(item) for item in source_authorities
        )
        resolutions = tuple(
            MaterialProfileResolution.model_validate(item)
            for item in material_profile_resolutions
        )
        if len(authorities) != 3 or len(resolutions) != 3:
            raise ValueError
        if tuple(item.role for item in authorities) != _EXPECTED_ROLES:
            raise ValueError
        if tuple(item.role for item in checked_bundle.sources) != _EXPECTED_ROLES:
            raise ValueError
        if len({item.space_id for item in authorities}) != 1:
            raise ValueError
        expected = EXPECTED_596_1_PARSE_SOURCES
        observed: list[tuple[str, str, str]] = []
        for item, authority, resolution in zip(
            checked_bundle.sources, authorities, resolutions, strict=True
        ):
            profile_role = "rate_table" if authority.role == "rate" else authority.role
            if (
                item.role != authority.role
                or resolution.catalog_hash != APPROVED_MATERIAL_PROFILE_CATALOG_SHA256
                or resolution.profile.material_role != profile_role
                or resolution.request.classified_material_role != profile_role
                or resolution.request.space_id != authority.space_id
                or resolution.request.product_version != "596-1"
                or resolution.profile.source.sha256 != item.source_sha256
                or resolution.request.source != resolution.profile.source
                or resolution.parse_policy_receipt.bounded_upgrade_profile_ref is None
                or resolution.profile.parse_policy.max_parser_attempts != 2
            ):
                raise ValueError
            observed.append((profile_role, item.source_sha256, resolution.profile.profile_id))
        if tuple(observed) != tuple(expected):
            raise ValueError
        if receipt.intake_bundle_digest_sha256 != checked_bundle.bundle_digest_sha256:
            raise ValueError
        roles = tuple(entry.receipt_role for entry in receipt.relations)
        ordered = ("terms", "brochure", "rate_table")
        if not roles or roles != tuple(sorted(roles, key=ordered.index)):
            raise ValueError
        for entry in receipt.relations:
            relation_kind = "table" if entry.receipt_role == "rate_table" else "section"
            source_index = {"terms": 0, "brochure": 1, "rate_table": 2}[entry.receipt_role]
            item = checked_bundle.sources[source_index]
            binding = replay_cross_page_relation_binding_v1(entry.binding)
            facts = item.evidence.cross_page_facts
            provenance = item.evidence.cross_page_marker_provenance
            observation_matches = (
                facts is not None
                and binding.native_observation_sha256
                in facts.ambiguous_observation_hashes
            ) or (
                entry.receipt_role == "rate_table"
                and _derived_rate_binding_matches_capture(item=item, binding=binding)
            )
            if (
                facts is None
                or provenance is None
                or binding.relation_kind != relation_kind
                or binding.source_sha256 != item.source_sha256
                or binding.parser_config_sha256 != item.evidence.parser.config_sha256
                or binding.intake_bundle_digest_sha256 != checked_bundle.bundle_digest_sha256
                or binding.intake_item_digest_sha256 != item.intake_digest_sha256
                or binding.capture_identity_sha256 != item.capture_identity_sha256
                or binding.raw_structure_sha256 != item.evidence.raw_structure_sha256
                or binding.artifact_sha256 != item.evidence.sanitized_structure_sha256
                or binding.cross_page_facts_digest_sha256 != item.cross_page_facts_digest_sha256
                or entry.marker_provenance_digest_sha256
                != item.marker_provenance_digest_sha256
                or facts.source_sha256 != item.source_sha256
                or facts.parser_model != item.evidence.parser.model
                or facts.raw_zip_sha256 != provenance.raw_zip_sha256
                or facts.native_member_sha256 != provenance.native_member_sha256
                or facts.projection_sha256 != binding.native_projection_sha256
                or not observation_matches
                or binding.policy_sha256 != POLICY_SHA256
            ):
                raise ValueError
        return checked_bundle, authorities, resolutions
    except (
        AttributeError,
        CaptureIntakeError,
        CrossPageBindingError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "CROSS_CONTRACT_AUTHORITY_MISMATCH")


def _validate_relation_receipt_authority_inputs_with_builder_596_1(
    receipt_bytes: bytes,
    *,
    capture_payloads: tuple[bytes, bytes, bytes] | object,
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...] | object,
    material_profile_resolutions: tuple[MaterialProfileResolution, ...] | object,
    marker_map_builder: _MarkerMapBuilder,
) -> ValidatedRelationAdmissionInputs5961V1:
    """Replay one private receipt with one already-resolved exact map authority."""

    receipt = _parse_receipt_bytes(receipt_bytes)
    intake, authorities, resolutions = _validate_cross_contracts(
        receipt=receipt,
        capture_payloads=capture_payloads,
        source_authorities=source_authorities,
        material_profile_resolutions=material_profile_resolutions,
    )
    try:
        marker_maps = marker_map_builder(bundle=intake, receipt=receipt)
        maps = tuple(TypedMarkerEndpointMapV1.model_validate(item) for item in marker_maps)
        if not maps or len(maps) != len(receipt.relations):
            raise ValueError
        relation_sources = tuple(entry.binding.source_sha256 for entry in receipt.relations)
        if tuple(item.source_sha256 for item in maps) != relation_sources:
            raise ValueError
    except (AttributeError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "EXACT_098_MARKER_MAP_INVALID")
    return ValidatedRelationAdmissionInputs5961V1(
        status="VALIDATED",
        bundle=intake,
        source_authorities=authorities,
        material_profile_resolutions=resolutions,
        marker_endpoint_mappings=maps,
        relation_binding_provider=_ReceiptRelationProvider(intake, receipt),
    )


def validate_relation_receipt_authority_inputs_with_marker_map_builder_596_1(
    receipt_bytes: bytes,
    *,
    capture_payloads: tuple[bytes, bytes, bytes] | object,
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...] | object,
    material_profile_resolutions: tuple[MaterialProfileResolution, ...] | object,
    marker_map_builder: _MarkerMapBuilder,
) -> ValidatedRelationAdmissionInputs5961V1:
    """Narrow composition seam for separately verified terms/rate map authorities."""

    try:
        parameters = tuple(inspect.signature(marker_map_builder).parameters.values())
        if tuple(parameter.name for parameter in parameters) != ("bundle", "receipt") or any(
            parameter.kind is not inspect.Parameter.KEYWORD_ONLY for parameter in parameters
        ):
            raise ValueError
    except (TypeError, ValueError):
        _fail("DEPENDENCY_UNAVAILABLE", "EXACT_DUAL_MAP_BUILDER_UNAVAILABLE")
    return _validate_relation_receipt_authority_inputs_with_builder_596_1(
        receipt_bytes,
        capture_payloads=capture_payloads,
        source_authorities=source_authorities,
        material_profile_resolutions=material_profile_resolutions,
        marker_map_builder=marker_map_builder,
    )


def validate_relation_receipt_authority_inputs_596_1(
    receipt_bytes: bytes,
    *,
    capture_payloads: tuple[bytes, bytes, bytes] | object,
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...] | object,
    material_profile_resolutions: tuple[MaterialProfileResolution, ...] | object,
) -> ValidatedRelationAdmissionInputs5961V1:
    """Replay one private receipt and resolve the frozen default map authority."""

    builder = _resolve_098_marker_map_builder()
    if builder is None:
        _fail("DEPENDENCY_UNAVAILABLE", "EXACT_098_MARKER_MAP_BUILDER_UNAVAILABLE")
    return _validate_relation_receipt_authority_inputs_with_builder_596_1(
        receipt_bytes,
        capture_payloads=capture_payloads,
        source_authorities=source_authorities,
        material_profile_resolutions=material_profile_resolutions,
        marker_map_builder=builder,
    )


def _read_private_receipt(path: Path) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= _MAX_RECEIPT_BYTES
        ):
            _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_FILE_UNSAFE")
        payload = os.pread(descriptor, before.st_size + 1, 0)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after or len(payload) != before.st_size:
            _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_FILE_CHANGED")
        return payload
    except RelationReceiptAuthorityAdapterError:
        raise
    except OSError:
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING", "RELATION_RECEIPT_FILE_UNSAFE")
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def read_private_relation_receipt_authority_inputs_596_1(
    path: Path,
    *,
    capture_payloads: tuple[bytes, bytes, bytes] | object,
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...] | object,
    material_profile_resolutions: tuple[MaterialProfileResolution, ...] | object,
) -> ValidatedRelationAdmissionInputs5961V1:
    """Read one private snapshot and validate it without disclosing the path."""

    return validate_relation_receipt_authority_inputs_596_1(
        _read_private_receipt(path),
        capture_payloads=capture_payloads,
        source_authorities=source_authorities,
        material_profile_resolutions=material_profile_resolutions,
    )

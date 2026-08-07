"""Task-local bridge from 091 marker custody to a private derived-relation receipt."""

from __future__ import annotations

import errno
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Annotated, Any, Literal, Never, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    marker_provenance_custody_preimage,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    CrossPageBindingError,
    CrossPageRelationBindingV1,
    derive_cross_page_relation_596_1,
    replay_cross_page_relation_binding_v1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
_BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
_RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
_FINAL_NAME = "596-1-relation-receipt.json"


class RelationReceiptBridgeError(ValueError):
    """Fixed-code error that never echoes captured or filesystem material."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)

    def __repr__(self) -> str:
        return f"RelationReceiptBridgeError({self.reason_code!r})"


def _fail(reason_code: str) -> Never:
    raise RelationReceiptBridgeError(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class RelationReceiptEntry5961V1(_FrozenModel):
    receipt_role: Literal["terms", "brochure", "rate_table"]
    intake_item_digest_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    marker_provenance_digest_sha256: Sha256Hex
    binding: CrossPageRelationBindingV1

    @model_validator(mode="after")
    def _role_and_relation_match(self) -> Self:
        expected = "table" if self.receipt_role == "rate_table" else "section"
        if (
            self.binding.relation_kind != expected
            or self.binding.intake_item_digest_sha256 != self.intake_item_digest_sha256
            or self.binding.capture_identity_sha256 != self.capture_identity_sha256
        ):
            raise ValueError("receipt role and relation mismatch")
        return self


class DerivedRelationReceipt5961V1(_FrozenModel):
    contract: Literal["596-1-derived-relation-receipt.v1"]
    status: Literal["DERIVED_RELATION_RECEIPT_VERIFIED"]
    intake_bundle_digest_sha256: Sha256Hex
    relations: tuple[RelationReceiptEntry5961V1, ...]
    receipt_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_order_and_digest(self) -> Self:
        roles = tuple(item.receipt_role for item in self.relations)
        ordered = ("terms", "brochure", "rate_table")
        if (
            not roles
            or roles != tuple(sorted(roles, key=ordered.index))
            or any(role not in ordered for role in roles)
        ):
            raise ValueError("receipt relation order mismatch")
        expected = canonical_hash(
            "relation-receipt-596-1.v1",
            self.model_dump(mode="python", exclude={"receipt_digest_sha256"}),
        )
        if self.receipt_digest_sha256 != expected:
            raise ValueError("receipt digest mismatch")
        return self


def build_relation_receipt_from_entries_596_1(
    *,
    intake_bundle_digest_sha256: str,
    relations: tuple[RelationReceiptEntry5961V1, ...],
) -> DerivedRelationReceipt5961V1:
    """Close ordered terms/brochure section relations plus one rate receipt."""

    values: dict[str, Any] = {
        "contract": "596-1-derived-relation-receipt.v1",
        "status": "DERIVED_RELATION_RECEIPT_VERIFIED",
        "intake_bundle_digest_sha256": intake_bundle_digest_sha256,
        "relations": relations,
    }
    values["receipt_digest_sha256"] = canonical_hash(
        "relation-receipt-596-1.v1",
        {
            **values,
            "relations": tuple(item.model_dump(mode="python") for item in relations),
        },
    )
    try:
        return replay_relation_receipt_596_1(
            DerivedRelationReceipt5961V1.model_validate(values)
        )
    except (RelationReceiptBridgeError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING")


def _validate_bundle_identity(bundle: MinerUCaptureBundle5961V1) -> None:
    if not isinstance(bundle, MinerUCaptureBundle5961V1):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING")
    expected = (
        ("terms", _TERMS_SHA),
        ("brochure", _BROCHURE_SHA),
        ("rate", _RATE_SHA),
    )
    if tuple((item.role, item.source_sha256) for item in bundle.sources) != expected:
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING")


def _validate_marker_mapping(bundle: MinerUCaptureBundle5961V1) -> None:
    """Reject the current incomplete 091 endpoint shape without inference.

    A complete future companion must expose two distinct cross-page nodes for
    each relation. The frozen current terms evidence has one cross-page node and
    one lines-deleted observation, so it stops here before 086 is invoked.
    """

    for index, node_type in ((0, "text"), (2, "table")):
        item = bundle.sources[index]
        provenance = item.evidence.cross_page_marker_provenance
        facts = item.evidence.cross_page_facts
        if (
            provenance is None
            or facts is None
            or provenance.source_sha256 != item.source_sha256
            or facts.source_sha256 != item.source_sha256
            or provenance.parser_model != facts.parser_model
            or provenance.mineru_version != facts.mineru_version
            or provenance.raw_zip_sha256 != facts.raw_zip_sha256
            or provenance.native_member_sha256 != facts.native_member_sha256
            or provenance.marker_count != len(provenance.markers)
            or provenance.marker_count != facts.ambiguous_marker_count
            or item.marker_provenance_digest_sha256
            != canonical_hash(
                "mineru-cross-page-marker-provenance-custody.v1",
                marker_provenance_custody_preimage(provenance),
            )
            or item.cross_page_facts_digest_sha256
            != canonical_hash(
                "mineru-native-cross-page-facts-custody.v1",
                facts.model_dump(mode="json", exclude_none=True),
            )
        ):
            _fail("BLOCKED_ON_CROSS_PAGE_BINDING")
        markers = tuple(
            marker for marker in provenance.markers if marker.marker_kind == "cross_page"
        )
        if (
            len(markers) != 2
            or any(marker.node_type != node_type for marker in markers)
            or len({(marker.page_index, marker.local_index) for marker in markers}) != 2
            or len({marker.page_index for marker in markers}) != 2
            or len({marker.structural_path_sha256 for marker in markers}) != 2
            or any(marker.marker_kind == "lines_deleted" for marker in provenance.markers)
        ):
            _fail("BLOCKED_ON_CROSS_PAGE_BINDING")


def _derive_binding(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    *,
    relation_kind: Literal["section", "table"],
) -> CrossPageRelationBindingV1:
    """Invoke frozen 086; its own replay remains the binding authority."""

    return derive_cross_page_relation_596_1(
        bundle,
        document,
        manifest,
        relation_kind=relation_kind,
    )


def replay_relation_receipt_596_1(
    receipt: DerivedRelationReceipt5961V1 | object,
) -> DerivedRelationReceipt5961V1:
    try:
        checked = DerivedRelationReceipt5961V1.model_validate(receipt)
        replayed = tuple(
            replay_cross_page_relation_binding_v1(item.binding) for item in checked.relations
        )
    except (CrossPageBindingError, TypeError, ValueError, ValidationError):
        _fail("RELATION_RECEIPT_REPLAY_FAILED")
    if replayed != tuple(item.binding for item in checked.relations):
        _fail("RELATION_RECEIPT_REPLAY_FAILED")
    return checked


def build_relation_receipt_596_1(
    bundle: MinerUCaptureBundle5961V1,
    terms_document: ParsedDocumentV1,
    terms_manifest: ParseManifestV1,
    rate_document: ParsedDocumentV1,
    rate_manifest: ParseManifestV1,
) -> DerivedRelationReceipt5961V1:
    """Derive the complete receipt in memory; expose no partial relation."""

    _validate_bundle_identity(bundle)
    _validate_marker_mapping(bundle)
    try:
        terms = _derive_binding(bundle, terms_document, terms_manifest, relation_kind="section")
        rate = _derive_binding(bundle, rate_document, rate_manifest, relation_kind="table")
        terms = replay_cross_page_relation_binding_v1(terms)
        rate = replay_cross_page_relation_binding_v1(rate)
    except (CrossPageBindingError, TypeError, ValueError, ValidationError):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING")
    if (
        terms.status != "DERIVED_STRUCTURAL_BINDING_VERIFIED"
        or rate.status != "DERIVED_STRUCTURAL_BINDING_VERIFIED"
        or terms.source_sha256 != _TERMS_SHA
        or rate.source_sha256 != _RATE_SHA
        or terms.intake_bundle_digest_sha256 != bundle.bundle_digest_sha256
        or rate.intake_bundle_digest_sha256 != bundle.bundle_digest_sha256
        or terms.intake_item_digest_sha256 != bundle.sources[0].intake_digest_sha256
        or rate.intake_item_digest_sha256 != bundle.sources[2].intake_digest_sha256
        or terms.capture_identity_sha256 != bundle.sources[0].capture_identity_sha256
        or rate.capture_identity_sha256 != bundle.sources[2].capture_identity_sha256
        or terms.raw_structure_sha256 != bundle.sources[0].evidence.raw_structure_sha256
        or rate.raw_structure_sha256 != bundle.sources[2].evidence.raw_structure_sha256
        or terms.artifact_sha256 != bundle.sources[0].evidence.sanitized_structure_sha256
        or rate.artifact_sha256 != bundle.sources[2].evidence.sanitized_structure_sha256
        or terms.cross_page_facts_digest_sha256 != bundle.sources[0].cross_page_facts_digest_sha256
        or rate.cross_page_facts_digest_sha256 != bundle.sources[2].cross_page_facts_digest_sha256
        or terms.parser_config_sha256 != bundle.sources[0].evidence.parser.config_sha256
        or rate.parser_config_sha256 != bundle.sources[2].evidence.parser.config_sha256
        or bundle.sources[0].marker_provenance_digest_sha256 is None
        or bundle.sources[2].marker_provenance_digest_sha256 is None
    ):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING")
    relations = (
        RelationReceiptEntry5961V1(
            receipt_role="terms",
            intake_item_digest_sha256=bundle.sources[0].intake_digest_sha256,
            capture_identity_sha256=bundle.sources[0].capture_identity_sha256,
            marker_provenance_digest_sha256=bundle.sources[0].marker_provenance_digest_sha256,
            binding=terms,
        ),
        RelationReceiptEntry5961V1(
            receipt_role="rate_table",
            intake_item_digest_sha256=bundle.sources[2].intake_digest_sha256,
            capture_identity_sha256=bundle.sources[2].capture_identity_sha256,
            marker_provenance_digest_sha256=bundle.sources[2].marker_provenance_digest_sha256,
            binding=rate,
        ),
    )
    values: dict[str, Any] = {
        "contract": "596-1-derived-relation-receipt.v1",
        "status": "DERIVED_RELATION_RECEIPT_VERIFIED",
        "intake_bundle_digest_sha256": bundle.bundle_digest_sha256,
        "relations": relations,
    }
    values["receipt_digest_sha256"] = canonical_hash(
        "relation-receipt-596-1.v1",
        {
            **values,
            "relations": tuple(item.model_dump(mode="python") for item in relations),
        },
    )
    try:
        return replay_relation_receipt_596_1(DerivedRelationReceipt5961V1.model_validate(values))
    except (RelationReceiptBridgeError, ValidationError):
        _fail("BLOCKED_ON_CROSS_PAGE_BINDING")


def _receipt_bytes(receipt: DerivedRelationReceipt5961V1) -> bytes:
    checked = replay_relation_receipt_596_1(receipt)
    return (
        json.dumps(
            checked.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _open_private_root(root: Path) -> int:
    descriptor = -1
    try:
        descriptor = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        info = os.fstat(descriptor)
    except OSError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _fail("OUTPUT_ROOT_NOT_PRIVATE")
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(descriptor)
        _fail("OUTPUT_ROOT_NOT_PRIVATE")
    return descriptor


def publish_relation_receipt_596_1(
    receipt: DerivedRelationReceipt5961V1,
    output_root: Path,
) -> Path:
    """Publish one private canonical receipt atomically without replacement."""

    root = Path(output_root)
    root_descriptor = _open_private_root(root)
    payload = _receipt_bytes(receipt)
    final = root / _FINAL_NAME
    descriptor = -1
    temporary = f".relation-receipt-{secrets.token_hex(16)}"
    temporary_exists = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=root_descriptor,
        )
        temporary_exists = True
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(
            temporary,
            _FINAL_NAME,
            src_dir_fd=root_descriptor,
            dst_dir_fd=root_descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=root_descriptor)
        temporary_exists = False
        return final
    except FileExistsError:
        _fail("RECEIPT_OUTPUT_EXISTS")
    except OSError as error:
        if error.errno == errno.EEXIST:
            _fail("RECEIPT_OUTPUT_EXISTS")
        _fail("RECEIPT_PUBLISH_FAILED")
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_exists:
            try:
                os.unlink(temporary, dir_fd=root_descriptor)
            except OSError:
                pass
        os.close(root_descriptor)

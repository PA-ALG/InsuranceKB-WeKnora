"""OpenSpec 100: private 096 receipt bytes to exact 092 inputs."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import native_mineru_cloud
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
    ParseSubjectV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    CrossPageRelationBindingV1,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    TypedMarkerEndpointMapV1,
    assemble_relation_bound_admission_596_1,
)
from insurance_harness.knowledge_compiler.relation_receipt_authority_adapter_596_1 import (
    RelationReceiptAuthorityAdapterError,
    read_private_relation_receipt_authority_inputs_596_1,
    validate_relation_receipt_authority_inputs_596_1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    DerivedRelationReceipt5961V1,
    RelationReceiptEntry5961V1,
    replay_relation_receipt_596_1,
)
from tests import test_mineru_capture_intake_596_1_083 as intake_cases
from tests import test_relation_bound_admission_596_1_092 as admission_cases
from tests import test_relation_receipt_bridge_596_1_096 as receipt_cases


def _canonical_bytes(receipt: DerivedRelationReceipt5961V1) -> bytes:
    return (
        json.dumps(
            receipt.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    bytes,
    tuple[bytes, bytes, bytes],
    tuple[object, ...],
    tuple[object, ...],
]:
    original = cast(
        DerivedRelationReceipt5961V1,
        receipt_cases._verified_receipt(monkeypatch),
    )
    capture_payloads = intake_cases._inputs()
    bundle = intake_mineru_capture_bundle_596_1(capture_payloads)
    entries: list[RelationReceiptEntry5961V1] = []
    for entry, item in zip(
        original.relations,
        (bundle.sources[0], bundle.sources[2]),
        strict=True,
    ):
        facts = item.evidence.cross_page_facts
        assert facts is not None and facts.ambiguous_observation_hashes
        subject = ParseSubjectV1.model_construct(source_sha256=item.source_sha256)
        document = ParsedDocumentV1.model_construct(subject=subject)
        manifest = ParseManifestV1.model_construct(
            subject=subject,
            document_hash=document.document_hash,
        )
        values = entry.binding.model_dump(mode="python", exclude={"replay_digest_sha256"})
        values["parser_config_sha256"] = item.evidence.parser.config_sha256
        values["intake_bundle_digest_sha256"] = bundle.bundle_digest_sha256
        values["intake_item_digest_sha256"] = item.intake_digest_sha256
        values["capture_identity_sha256"] = item.capture_identity_sha256
        values["raw_structure_sha256"] = item.evidence.raw_structure_sha256
        values["artifact_sha256"] = item.evidence.sanitized_structure_sha256
        values["cross_page_facts_digest_sha256"] = item.cross_page_facts_digest_sha256
        values["native_projection_sha256"] = facts.projection_sha256
        values["native_observation_sha256"] = facts.ambiguous_observation_hashes[0]
        values["parsed_document_hash"] = document.document_hash
        values["parse_manifest_hash"] = manifest.manifest_hash
        binding = CrossPageRelationBindingV1.model_validate(
            {
                **values,
                "replay_digest_sha256": canonical_hash(
                    "cross-page-relation-binding.v1", values
                ),
            }
        )
        entries.append(
            RelationReceiptEntry5961V1(
                receipt_role=entry.receipt_role,
                intake_item_digest_sha256=item.intake_digest_sha256,
                capture_identity_sha256=item.capture_identity_sha256,
                marker_provenance_digest_sha256=cast(
                    str, item.marker_provenance_digest_sha256
                ),
                binding=binding,
            )
        )
    receipt_values: dict[str, object] = {
        "contract": original.contract,
        "status": original.status,
        "intake_bundle_digest_sha256": bundle.bundle_digest_sha256,
        "relations": tuple(entries),
    }
    receipt = DerivedRelationReceipt5961V1.model_validate(
        {
            **receipt_values,
            "receipt_digest_sha256": canonical_hash(
                "relation-receipt-596-1.v1",
                {
                    **receipt_values,
                    "relations": tuple(item.model_dump(mode="python") for item in entries),
                },
            ),
        }
    )
    return (
        _canonical_bytes(receipt),
        capture_payloads,
        admission_cases._authorities(),
        admission_cases._resolutions(),
    )


def _future_marker_maps() -> tuple[TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1]:
    return admission_cases._marker_maps()


def _install_future_098(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def build(*, bundle: object, receipt: object) -> tuple[
        TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1
    ]:
        calls.append("build")
        assert bundle is not None and receipt is not None
        return _future_marker_maps()

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_authority_adapter_596_1._resolve_098_marker_map_builder",
        lambda: build,
    )
    return calls


def _assert_fixed_failure(call: Callable[[], object], reason: str) -> None:
    with pytest.raises(RelationReceiptAuthorityAdapterError) as caught:
        call()
    assert caught.value.reason_code == reason
    rendered = f"{caught.value!s} {caught.value!r}"
    assert all(token not in rendered for token in ("/private/", "secret", "https://"))


def test_actual_098_surface_rejects_receipt_without_native_hierarchy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, capture_payloads, authorities, resolutions = _inputs(monkeypatch)

    _assert_fixed_failure(
        lambda: validate_relation_receipt_authority_inputs_596_1(
            receipt,
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        "EXACT_098_MARKER_MAP_INVALID",
    )


def test_future_exact_098_surface_yields_only_092_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, capture_payloads, authorities, resolutions = _inputs(monkeypatch)
    calls = _install_future_098(monkeypatch)

    context = validate_relation_receipt_authority_inputs_596_1(
        receipt,
        capture_payloads=capture_payloads,
        source_authorities=authorities,
        material_profile_resolutions=resolutions,
    )

    assert calls == ["build"]
    assert context.status == "VALIDATED"
    assert context.bundle == intake_mineru_capture_bundle_596_1(capture_payloads)
    assert context.source_authorities == authorities
    assert context.material_profile_resolutions == resolutions
    assert tuple(item.relation_kind for item in context.marker_endpoint_mappings) == (
        "section",
        "table",
    )
    assert callable(context.relation_binding_provider)
    assert set(context.as_092_kwargs()) == {
        "bundle",
        "source_authorities",
        "material_profile_resolutions",
        "marker_endpoint_mappings",
        "relation_binding_provider",
    }
    composed = assemble_relation_bound_admission_596_1(
        bundle=context.bundle,
        source_authorities=context.source_authorities,
        material_profile_resolutions=context.material_profile_resolutions,
        marker_endpoint_mappings=context.marker_endpoint_mappings,
        relation_binding_provider=context.relation_binding_provider,
        trusted_builder=cast(Any, native_mineru_cloud.build_mineru_parsed_document_v1),
    )
    assert composed.status.startswith("BLOCKED_")
    assert composed.provider_calls == composed.golden_reads == 0
    assert "ADMIT" not in repr(context) and "READY" not in repr(context)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data[:-1],
        lambda data: data + b"\n",
        lambda data: b'{' + data[1:-2] + b',"contract":"596-1-derived-relation-receipt.v1"}\n',
        lambda data: data.replace(b'"status":', b'"extra":0,"status":', 1),
        lambda data: data.replace(b'"status":', b'"x":NaN,"status":', 1),
    ],
)
def test_noncanonical_duplicate_extra_or_nonfinite_receipt_blocks(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[bytes], bytes],
) -> None:
    receipt, capture_payloads, authorities, resolutions = _inputs(monkeypatch)
    _install_future_098(monkeypatch)

    _assert_fixed_failure(
        lambda: validate_relation_receipt_authority_inputs_596_1(
            mutate(receipt),
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        "RELATION_RECEIPT_BYTES_INVALID",
    )


def test_receipt_nested_hash_source_policy_and_context_drift_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_bytes, capture_payloads, authorities, resolutions = _inputs(monkeypatch)
    _install_future_098(monkeypatch)
    value = json.loads(receipt_bytes)
    mutations: list[tuple[list[str | int], object]] = [
        (["intake_bundle_digest_sha256"], "0" * 64),
        (["relations", 0, "binding", "source_sha256"], receipt_cases.RATE_SHA),
        (["relations", 0, "binding", "parser_config_sha256"], "0" * 64),
        (["relations", 0, "binding", "policy_sha256"], "0" * 64),
        (["relations", 0, "binding", "replay_digest_sha256"], "0" * 64),
    ]
    for path, replacement in mutations:
        changed = json.loads(json.dumps(value))
        cursor: Any = changed
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = replacement
        encoded = json.dumps(
            changed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"

        def check_receipt(encoded: bytes = encoded) -> object:
            return validate_relation_receipt_authority_inputs_596_1(
                encoded,
                capture_payloads=capture_payloads,
                source_authorities=authorities,
                material_profile_resolutions=resolutions,
            )

        _assert_fixed_failure(
            check_receipt,
            "RELATION_RECEIPT_REPLAY_FAILED",
        )


def test_custody_authority_profile_and_cross_product_drift_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, capture_payloads, authorities, resolutions = _inputs(monkeypatch)
    _install_future_098(monkeypatch)
    calls: tuple[Callable[[], object], ...] = (
        lambda: validate_relation_receipt_authority_inputs_596_1(
            receipt,
            capture_payloads=(b"{}\n", *capture_payloads[1:]),
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        lambda: validate_relation_receipt_authority_inputs_596_1(
            receipt,
            capture_payloads=capture_payloads,
            source_authorities=(
                cast(Any, authorities)[0].model_copy(update={"space_id": "foreign"}),
                *cast(Any, authorities)[1:],
            ),
            material_profile_resolutions=resolutions,
        ),
        lambda: validate_relation_receipt_authority_inputs_596_1(
            receipt,
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=(
                cast(Any, resolutions)[0].model_copy(
                    update={
                        "request": cast(Any, resolutions)[0].request.model_copy(
                            update={"product_version": "other-product"}
                        )
                    }
                ),
                *cast(Any, resolutions)[1:],
            ),
        ),
    )
    for call in calls:
        _assert_fixed_failure(
            call,
            "CROSS_CONTRACT_AUTHORITY_MISMATCH",
        )


def test_private_file_requires_0600_regular_no_follow_and_stable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt, capture_payloads, authorities, resolutions = _inputs(monkeypatch)
    _install_future_098(monkeypatch)
    path = tmp_path / "receipt.json"
    path.write_bytes(receipt)
    path.chmod(0o600)
    context = read_private_relation_receipt_authority_inputs_596_1(
        path,
        capture_payloads=capture_payloads,
        source_authorities=authorities,
        material_profile_resolutions=resolutions,
    )
    assert context.status == "VALIDATED"

    path.chmod(0o644)
    _assert_fixed_failure(
        lambda: read_private_relation_receipt_authority_inputs_596_1(
            path,
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        "RELATION_RECEIPT_FILE_UNSAFE",
    )

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    oversized.chmod(0o600)
    _assert_fixed_failure(
        lambda: read_private_relation_receipt_authority_inputs_596_1(
            oversized,
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        "RELATION_RECEIPT_FILE_UNSAFE",
    )
    path.chmod(0o600)
    link = tmp_path / "receipt-link.json"
    link.symlink_to(path)
    _assert_fixed_failure(
        lambda: read_private_relation_receipt_authority_inputs_596_1(
            link,
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        "RELATION_RECEIPT_FILE_UNSAFE",
    )

    real_fstat = os.fstat
    calls = 0

    def drifting_fstat(fd: int) -> os.stat_result:
        nonlocal calls
        info = real_fstat(fd)
        calls += 1
        if calls == 2:
            values = list(info)
            values[stat.ST_SIZE] = info.st_size + 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_authority_adapter_596_1.os.fstat",
        drifting_fstat,
    )
    _assert_fixed_failure(
        lambda: read_private_relation_receipt_authority_inputs_596_1(
            path,
            capture_payloads=capture_payloads,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
        ),
        "RELATION_RECEIPT_FILE_CHANGED",
    )


def test_provider_replays_only_exact_receipt_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, capture_payloads, authorities, resolutions = _inputs(monkeypatch)
    _install_future_098(monkeypatch)
    context = validate_relation_receipt_authority_inputs_596_1(
        receipt,
        capture_payloads=capture_payloads,
        source_authorities=authorities,
        material_profile_resolutions=resolutions,
    )
    replayed = replay_relation_receipt_596_1(
        DerivedRelationReceipt5961V1.model_validate(json.loads(receipt))
    )
    section = replayed.relations[0].binding
    document = ParsedDocumentV1.model_construct(
        subject=ParseSubjectV1.model_construct(source_sha256=section.source_sha256),
    )
    manifest = ParseManifestV1.model_construct(
        document_hash=document.document_hash,
        subject=document.subject,
    )
    assert context.relation_binding_provider(
        context.bundle, document, manifest, relation_kind="section"
    ) == section
    changed = document.model_copy(
        update={"subject": ParseSubjectV1.model_construct(source_sha256="0" * 64)}
    )
    _assert_fixed_failure(
        lambda: context.relation_binding_provider(
            context.bundle, changed, manifest, relation_kind="section"
        ),
        "RELATION_PROVIDER_IDENTITY_MISMATCH",
    )

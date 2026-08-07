"""OpenSpec 107 section-anchor readiness injection tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler import (
    marker_authority_envelope_596_1 as authority_module,
)
from insurance_harness.knowledge_compiler import (
    marker_authority_readiness_wiring_596_1 as readiness_module,
)
from insurance_harness.knowledge_compiler import (
    section_anchor_readiness_injection_596_1 as subject,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from tests.test_bounded_real_capture_readiness_596_1_099 import (
    _authority as readiness_authority,
)
from tests.test_bounded_real_capture_readiness_596_1_099 import (
    _bundle as readiness_bundle,
)
from tests.test_marker_endpoint_pair_bridge_596_1_098 import (
    _capture as rate_capture,
)
from tests.test_marker_endpoint_pair_bridge_596_1_098 import (
    _document_manifest as rate_document_manifest,
)
from tests.test_marker_endpoint_pair_bridge_596_1_098 import (
    _structure as rate_structure,
)
from tests.test_terms_section_endpoint_pair_bridge_596_1_103 import (
    BROCHURE_SHA,
    RATE_SHA,
    TERMS_SHA,
)
from tests.test_terms_section_endpoint_pair_bridge_596_1_103 import (
    _capture as terms_capture,
)
from tests.test_terms_section_endpoint_pair_bridge_596_1_103 import (
    _document_manifest as terms_document_manifest,
)
from tests.test_terms_section_endpoint_pair_bridge_596_1_103 import (
    _structure as terms_structure,
)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    authority_module.MarkerAuthorityEnvelopeV1,
    MinerUCaptureBundle5961V1,
    object,
    object,
    object,
    object,
]:
    terms_native = terms_structure(decoy=True)
    rate_native = rate_structure()
    payloads = (
        terms_capture(
            TERMS_SHA,
            role="terms",
            structure=terms_native,
            kinds=("cross_page",),
        ),
        terms_capture(BROCHURE_SHA, role="brochure"),
        rate_capture(
            RATE_SHA,
            structure=rate_native,
            markers=(("cross_page", "p0/b0"),),
        ),
    )
    bundle = intake_mineru_capture_bundle_596_1(payloads)

    def reconstructed(source: object) -> dict[str, str]:
        provenance = source.evidence.cross_page_marker_provenance  # type: ignore[attr-defined]
        assert provenance is not None
        return {
            "\0".join(
                (
                    marker.marker_kind,
                    str(marker.page_index),
                    marker.structural_path_sha256,
                    marker.node_type,
                    str(marker.local_index),
                )
            ): f"p{marker.page_index}/b{marker.local_index}"
            for marker in provenance.markers
        }

    monkeypatch.setattr(authority_module, "_reconstruct_paths", reconstructed)
    envelope = authority_module._build_envelope(payloads)
    terms_document, terms_manifest = terms_document_manifest(terms_native)
    rate_document, rate_manifest = rate_document_manifest(rate_native)
    return (
        envelope,
        bundle,
        terms_document,
        terms_manifest,
        rate_document,
        rate_manifest,
    )


def _anchor_evidence(
    bundle: MinerUCaptureBundle5961V1,
    document: object,
    manifest: object,
) -> subject.SectionAnchorEvidenceViewV1:
    source = document.blocks[0]  # type: ignore[attr-defined]
    target = document.blocks[1]  # type: ignore[attr-defined]
    ancestry = (_sha("outline-root"), _sha("section-7"))
    outline = (_sha("heading-anchor-7"),)
    source_anchor = subject.SectionAnchorEndpointV1(
        endpoint_id=source.block_id,
        page_number=source.locator.page_number,
        block_index=source.locator.block_index,
        order_index=source.order_index,
        endpoint_path_sha256=canonical_hash(
            "block-locator.v1", source.locator.model_dump(mode="python")
        ),
        section_ancestry_node_hashes=ancestry,
        outline_anchor_node_hashes=outline,
    )
    target_anchor = subject.SectionAnchorEndpointV1(
        endpoint_id=target.block_id,
        page_number=target.locator.page_number,
        block_index=target.locator.block_index,
        order_index=target.order_index,
        endpoint_path_sha256=canonical_hash(
            "block-locator.v1", target.locator.model_dump(mode="python")
        ),
        section_ancestry_node_hashes=ancestry,
        outline_anchor_node_hashes=outline,
    )
    reading_order = (
        subject.ReadingOrderFactV1(
            endpoint_id=source.block_id,
            page_number=source.locator.page_number,
            order_index=source.order_index,
        ),
        subject.ReadingOrderFactV1(
            endpoint_id=target.block_id,
            page_number=target.locator.page_number,
            order_index=target.order_index,
        ),
    )
    interval = subject.SectionAnchorIntervalV1(
        source_order_index=source.order_index,
        target_order_index=target.order_index,
        source_page_number=source.locator.page_number,
        target_page_number=target.locator.page_number,
        target_starts_new_heading=False,
    )
    parser_identity = canonical_hash(
        "parser-identity.v1", document.parser.model_dump(mode="python")  # type: ignore[attr-defined]
    )
    evidence_values: dict[str, object] = {
        "contract": "section-anchor-evidence-view-596-1.v1",
        "status": "SECTION_ANCHOR_EVIDENCE_VERIFIED",
        "evidence_class": "TEST_ONLY_COMPLETE_FIXTURE",
        "source_sha256": TERMS_SHA,
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": "2" * 64,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "parser_identity_sha256": parser_identity,
        "parser_config_sha256": document.parser.parser_config_hash,  # type: ignore[attr-defined]
        "document_hash": document.document_hash,  # type: ignore[attr-defined]
        "manifest_hash": manifest.manifest_hash,  # type: ignore[attr-defined]
        "marker_evidence_sha256": (
            bundle.sources[0].evidence.cross_page_marker_provenance.markers[0].marker_sha256  # type: ignore[union-attr]
        ),
        "reading_order": reading_order,
        "reading_order_sha256": canonical_hash(
            "section-anchor-reading-order.v1",
            tuple(item.model_dump(mode="python") for item in reading_order),
        ),
        "source_anchor": source_anchor,
        "target_anchor": target_anchor,
        "anchor_interval": interval,
        "anchor_interval_sha256": canonical_hash(
            "section-anchor-interval.v1", interval.model_dump(mode="python")
        ),
        "authority_version_sha256": _sha("106-section-anchor-v1"),
    }
    evidence_preimage = {
        **evidence_values,
        "reading_order": tuple(item.model_dump(mode="python") for item in reading_order),
        "source_anchor": source_anchor.model_dump(mode="python"),
        "target_anchor": target_anchor.model_dump(mode="python"),
        "anchor_interval": interval.model_dump(mode="python"),
    }
    evidence_values["evidence_preimage_sha256"] = canonical_hash(
        "section-anchor-evidence-preimage-596-1.v1", evidence_preimage
    )
    evidence_digest = {
        **evidence_preimage,
        "evidence_preimage_sha256": evidence_values["evidence_preimage_sha256"],
    }
    evidence_values["evidence_digest_sha256"] = canonical_hash(
        "section-anchor-evidence-view-596-1.v1", evidence_digest
    )
    return subject.SectionAnchorEvidenceViewV1.model_validate(evidence_values)


class _AnchorSource:
    def __init__(self, evidence: object | None) -> None:
        self.evidence = evidence

    def load_section_anchor_evidence(self) -> object | None:
        return self.evidence


class _FutureDependencies:
    def load_test_only_readiness_inputs(
        self,
    ) -> readiness_module.FutureReadinessInputsV1:
        return readiness_module.FutureReadinessInputsV1(
            bundle=readiness_bundle(), authority=readiness_authority()
        )


def test_current_missing_106_evidence_stops_before_all_downstream_calls() -> None:
    result = subject.evaluate_section_anchor_readiness_596_1(
        marker_authority=object(),
        anchor_source=None,
    )

    assert result.reason_code == "SECTION_ANCHOR_EVIDENCE_UNAVAILABLE"
    assert result.capture_authorized is False
    assert result.downstream_calls == 0


def test_protocol_fake_cannot_satisfy_current_formal_authority() -> None:
    result = subject.evaluate_section_anchor_readiness_596_1(
        marker_authority=object(),
        anchor_source=_AnchorSource(object()),
    )

    assert result.reason_code == "SECTION_ANCHOR_EVIDENCE_UNAVAILABLE"
    assert result.downstream_calls == 0


def test_future_anchor_replays_actual_103_086_096_then_104_098_099(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(monkeypatch)
    evidence = _anchor_evidence(case[1], case[2], case[3])

    result = subject.evaluate_test_only_future_section_anchor_readiness_596_1(
        *case,
        anchor_source=_AnchorSource(evidence),
        future_dependencies=_FutureDependencies(),
    )

    assert result.reason_code == "READY_FOR_ONE_BOUNDED_CAPTURE"
    assert result.evidence_class == "TEST_ONLY"
    assert result.capture_authorized is False
    assert result.downstream_calls == 2
    assert result.terms_receipt_sha256 is not None
    assert result.readiness is not None
    assert result.readiness.capture_authorized is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.model_copy(update={"source_sha256": "f" * 64}),
        lambda value: value.model_copy(update={"raw_zip_sha256": "f" * 64}),
        lambda value: value.model_copy(update={"native_member_sha256": "f" * 64}),
        lambda value: value.model_copy(update={"parser_model": "foreign"}),
        lambda value: value.model_copy(update={"mineru_version": "0.0.0"}),
        lambda value: value.model_copy(update={"parser_config_sha256": "f" * 64}),
        lambda value: value.model_copy(update={"document_hash": "f" * 64}),
        lambda value: value.model_copy(update={"manifest_hash": "f" * 64}),
        lambda value: value.model_copy(update={"marker_evidence_sha256": "f" * 64}),
        lambda value: value.model_copy(update={"reading_order_sha256": "f" * 64}),
        lambda value: value.model_copy(update={"anchor_interval_sha256": "f" * 64}),
        lambda value: value.model_copy(
            update={"source_anchor": value.target_anchor, "target_anchor": value.source_anchor}
        ),
        lambda value: value.model_copy(
            update={
                "source_anchor": value.source_anchor.model_copy(
                    update={"section_ancestry_node_hashes": ()}
                )
            }
        ),
        lambda value: value.model_copy(
            update={
                "target_anchor": value.target_anchor.model_copy(
                    update={"outline_anchor_node_hashes": (_sha("foreign"),)}
                )
            }
        ),
        lambda value: value.model_copy(
            update={
                "source_anchor": value.source_anchor.model_copy(
                    update={
                        "section_ancestry_node_hashes": (
                            value.source_anchor.section_ancestry_node_hashes[0],
                            value.source_anchor.section_ancestry_node_hashes[0],
                        )
                    }
                )
            }
        ),
        lambda value: value.model_copy(
            update={
                "target_anchor": value.target_anchor.model_copy(update={"page_number": 3})
            }
        ),
        lambda value: value.model_copy(
            update={
                "anchor_interval": value.anchor_interval.model_copy(
                    update={"target_starts_new_heading": True}
                )
            }
        ),
        lambda value: value.model_copy(update={"evidence_digest_sha256": "f" * 64}),
    ],
)
def test_all_anchor_identity_role_order_and_hash_drift_stops_before_103(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[subject.SectionAnchorEvidenceViewV1], object],
) -> None:
    case = _case(monkeypatch)
    evidence = mutate(_anchor_evidence(case[1], case[2], case[3]))
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("103 must not run")

    monkeypatch.setattr(subject, "derive_terms_section_receipt_entry_596_1", forbidden)
    result = subject.evaluate_test_only_future_section_anchor_readiness_596_1(
        *case,
        anchor_source=_AnchorSource(evidence),
        future_dependencies=_FutureDependencies(),
    )

    assert result.reason_code == "SECTION_ANCHOR_EVIDENCE_INVALID"
    assert result.capture_authorized is False
    assert result.downstream_calls == 0
    assert calls == 0


def test_missing_anchor_is_unavailable_and_calls_no_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(monkeypatch)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("downstream must not run")

    monkeypatch.setattr(subject, "derive_terms_section_receipt_entry_596_1", forbidden)
    monkeypatch.setattr(
        subject, "evaluate_test_only_future_marker_authority_readiness_596_1", forbidden
    )
    result = subject.evaluate_test_only_future_section_anchor_readiness_596_1(
        *case,
        anchor_source=_AnchorSource(None),
        future_dependencies=_FutureDependencies(),
    )

    assert result.reason_code == "SECTION_ANCHOR_EVIDENCE_UNAVAILABLE"
    assert result.downstream_calls == 0
    assert calls == 0

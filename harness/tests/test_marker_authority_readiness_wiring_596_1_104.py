"""OpenSpec 104: public marker authority to readiness wiring."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace

import pytest

from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler import (
    marker_authority_envelope_596_1 as authority_module,
)
from insurance_harness.knowledge_compiler import (
    marker_authority_readiness_wiring_596_1 as subject,
)
from insurance_harness.knowledge_compiler import (
    marker_endpoint_pair_bridge_596_1 as endpoint_module,
)
from insurance_harness.knowledge_compiler.bounded_real_capture_readiness_596_1 import (
    BoundProof,
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
from tests.test_marker_authority_envelope_596_1_101 import (
    _capture as authority_capture,
)
from tests.test_marker_authority_envelope_596_1_101 import _compact
from tests.test_marker_endpoint_pair_bridge_596_1_098 import (
    BROCHURE_SHA,
    RATE_SHA,
    TERMS_SHA,
    _document_manifest,
    _structure,
)
from tests.test_marker_endpoint_pair_bridge_596_1_098 import (
    _capture as endpoint_capture,
)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _proof(label: str, **values: str) -> BoundProof:
    payload = json.dumps({"label": label, **values}, sort_keys=True, separators=(",", ":")).encode()
    return BoundProof(preimage=payload, sha256=_sha(payload))


def _hybrid_case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    authority_module.MarkerAuthorityEnvelopeV1,
    MinerUCaptureBundle5961V1,
    ParsedDocumentV1,
    ParseManifestV1,
]:
    """Build an explicitly TEST_ONLY DTO set accepted by both frozen contracts."""

    native = _structure()
    payloads = (
        _compact(authority_capture(TERMS_SHA, (("cross_page", 0, "text"),))) + b"\n",
        endpoint_capture(BROCHURE_SHA),
        endpoint_capture(RATE_SHA, structure=native, markers=(("cross_page", "p0/b0"),)),
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

    # This bypass is test-only and proves composition, never formal provenance.
    monkeypatch.setattr(authority_module, "_reconstruct_paths", reconstructed)
    envelope = authority_module._build_envelope(payloads)
    document, manifest = _document_manifest(native)
    return envelope, bundle, document, manifest


class _TermsBinding:
    def __init__(self, *, evidence_class: str = "TEST_ONLY_COMPLETE_FIXTURE") -> None:
        self.evidence_class = evidence_class

    def bind_terms_section(
        self, envelope: authority_module.MarkerAuthorityEnvelopeV1
    ) -> subject.TermsSectionBindingEvidenceV1:
        canonical = _proof("terms-section", envelope=envelope.envelope_sha256)
        receipt = _proof("terms-section-receipt", canonical=canonical.sha256)
        return subject.TermsSectionBindingEvidenceV1(
            evidence_class=self.evidence_class,
            contract_id="terms-section-binding-596-1.v1",
            contract_version="v1",
            implementation_blob_sha256=_sha("103-implementation"),
            api_schema_sha256=_sha("103-schema"),
            source_sha256=TERMS_SHA,
            marker_authority_envelope_sha256=envelope.envelope_sha256,
            canonical_preimage=canonical,
            receipt=receipt,
            context_sha256=_sha("103-context"),
            policy_sha256=_sha("103-policy"),
            replay_sha256=_sha("103-replay"),
            status="TERMS_SECTION_BINDING_VERIFIED",
        )


class _FutureDependencies:
    def load_test_only_readiness_inputs(self) -> subject.FutureReadinessInputsV1:
        return subject.FutureReadinessInputsV1(
            bundle=readiness_bundle(), authority=readiness_authority()
        )


def test_current_authority_moves_earliest_reason_to_terms_without_098_or_099(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, _, _, _ = _hybrid_case(monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("downstream must not run")

    monkeypatch.setattr(subject, "derive_marker_endpoint_pair_input_596_1", forbidden)
    monkeypatch.setattr(subject, "evaluate_test_only_future_readiness", forbidden)

    result = subject.evaluate_marker_authority_readiness_596_1(envelope)

    assert result.status == "TERMS_SECTION_BINDING_UNAVAILABLE"
    assert result.reason_code == result.status
    assert result.capture_authorized is False
    assert result.endpoint_replay_sha256 is None
    assert result.readiness is None


def test_future_complete_fixture_calls_actual_098_then_099_but_never_authorizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bundle, document, manifest = _hybrid_case(monkeypatch)
    calls = 0
    actual = endpoint_module.derive_marker_endpoint_pair_input_596_1

    def counted(
        supplied_bundle: MinerUCaptureBundle5961V1,
        supplied_document: ParsedDocumentV1,
        supplied_manifest: ParseManifestV1,
        *,
        relation_kind: str = "table",
    ) -> endpoint_module.MarkerEndpointPairInputV1:
        nonlocal calls
        calls += 1
        assert relation_kind == "table"
        return actual(supplied_bundle, supplied_document, supplied_manifest)

    monkeypatch.setattr(subject, "derive_marker_endpoint_pair_input_596_1", counted)

    result = subject.evaluate_test_only_future_marker_authority_readiness_596_1(
        envelope,
        bundle,
        document,
        manifest,
        terms_binding=_TermsBinding(),
        future_dependencies=_FutureDependencies(),
    )

    assert calls == 1
    assert result.status == "READY_FOR_ONE_BOUNDED_CAPTURE"
    assert result.evidence_class == "TEST_ONLY"
    assert result.capture_authorized is False
    assert result.endpoint_replay_sha256 is not None
    assert result.readiness is not None
    assert result.readiness.evaluated_dependencies == (
        "091",
        "098",
        "086",
        "096",
        "095_087",
        "094",
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda envelope: envelope.model_copy(update={"relation_authority": "BOUND"}),
        lambda envelope: envelope.model_copy(update={"bundle_digest_sha256": "f" * 64}),
        lambda envelope: envelope.model_copy(
            update={"source_order": ("rate", "brochure", "terms")}
        ),
        lambda envelope: envelope.model_copy(
            update={
                "marker_sources": (
                    envelope.marker_sources[0],
                    envelope.marker_sources[1].model_copy(
                        update={
                            "native_member": (
                                envelope.marker_sources[1].native_member.model_copy(
                                    update={"sha256": "f" * 64}
                                )
                            )
                        }
                    ),
                )
            }
        ),
        lambda envelope: envelope.model_copy(
            update={
                "marker_sources": (
                    envelope.marker_sources[0],
                    envelope.marker_sources[1].model_copy(
                        update={
                            "markers": (
                                envelope.marker_sources[1]
                                .markers[0]
                                .model_copy(update={"local_index": 9}),
                            )
                        }
                    ),
                )
            }
        ),
    ],
)
def test_authority_preimage_role_member_and_marker_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[
        [authority_module.MarkerAuthorityEnvelopeV1],
        authority_module.MarkerAuthorityEnvelopeV1,
    ],
) -> None:
    envelope, _, _, _ = _hybrid_case(monkeypatch)
    drifted = mutate(envelope)

    result = subject.evaluate_marker_authority_readiness_596_1(drifted)

    assert result.status == "MARKER_AUTHORITY_INVALID"
    assert result.capture_authorized is False


def test_fake_terms_binding_stops_before_actual_098(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bundle, document, manifest = _hybrid_case(monkeypatch)
    calls = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(subject, "derive_marker_endpoint_pair_input_596_1", counted)
    result = subject.evaluate_test_only_future_marker_authority_readiness_596_1(
        envelope,
        bundle,
        document,
        manifest,
        terms_binding=_TermsBinding(evidence_class="PROTOCOL_FAKE"),
        future_dependencies=_FutureDependencies(),
    )

    assert calls == 0
    assert result.status == "TERMS_SECTION_BINDING_EVIDENCE_CLASS_BLOCKED"
    assert result.capture_authorized is False


def test_intake_source_parser_member_and_marker_drift_stops_before_098(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bundle, document, manifest = _hybrid_case(monkeypatch)
    rate = bundle.sources[2]
    drifted_rate = rate.model_copy(update={"source_sha256": "f" * 64})
    drifted = bundle.model_copy(
        update={"sources": (bundle.sources[0], bundle.sources[1], drifted_rate)}
    )
    calls = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(subject, "derive_marker_endpoint_pair_input_596_1", counted)
    result = subject.evaluate_test_only_future_marker_authority_readiness_596_1(
        envelope,
        drifted,
        document,
        manifest,
        terms_binding=_TermsBinding(),
        future_dependencies=_FutureDependencies(),
    )

    assert calls == 0
    assert result.status == "MARKER_AUTHORITY_INTAKE_DRIFT"
    assert result.capture_authorized is False


def test_synthetic_only_downstream_cannot_be_relabelled_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bundle, document, manifest = _hybrid_case(monkeypatch)
    original = readiness_bundle()
    dependencies = tuple(
        replace(item, evidence_class="REAL_PUBLIC_ADAPTER") for item in original.dependencies
    )

    class Relabelled:
        def load_test_only_readiness_inputs(self) -> subject.FutureReadinessInputsV1:
            return subject.FutureReadinessInputsV1(
                bundle=replace(original, dependencies=dependencies),
                authority=readiness_authority(),
            )

    result = subject.evaluate_test_only_future_marker_authority_readiness_596_1(
        envelope,
        bundle,
        document,
        manifest,
        terms_binding=_TermsBinding(),
        future_dependencies=Relabelled(),
    )

    assert result.status == "DEPENDENCY_EVIDENCE_CLASS_BLOCKED_086"
    assert result.capture_authorized is False
    assert "READY" not in result.status

from __future__ import annotations

import asyncio
import builtins
import copy
import gc
import hashlib
import json
import pickle
import threading
import weakref
from collections.abc import Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from inspect import iscoroutinefunction, signature
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

import insurance_harness.model_policy as model_policy_package
import insurance_harness.model_policy.admission as admission_module
import insurance_harness.model_policy.composition as composition_module
import insurance_harness.model_policy.gateway as gateway_module
import insurance_harness.model_policy.policy as policy_module
from insurance_harness.model_policy import (
    AdmissionBinding,
    AdmissionPolicyDenied,
    AdmissionVerificationReceipt,
    AdmissionVerifier,
    GuardedModelClient,
    IssuedModelPermit,
    ModelCallContext,
    ModelCallFacts,
    ModelCallRequest,
    ModelGatewayDenied,
    ModelIdentity,
    ModelPermitView,
    ModelPolicyDenied,
    ModelTransportError,
    PolicyReceipt,
    ProductionModelComposition,
    ProductionModelPolicy,
    ReceiptSink,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
)
from insurance_harness.model_policy.admission import (
    _is_issued_model_permit,
    _is_verified_admission,
    _issue_model_permit,
    _issue_verified_admission,
)
from insurance_harness.model_policy.composition import (
    _bind_verified_production_model_composition,
    _build_production_model_composition,
)
from insurance_harness.model_policy.policy import (
    _decision_authorizes_call,
    _is_policy_decision,
    _permit_matches_call_context,
    _permit_view_digest,
    _PolicyDecision,
)


def _identity(
    deployment_id: str = "qwen3.6-prod-20260715",
    *,
    family: str = "qwen",
    role: str = "extract",
) -> ModelIdentity:
    return ModelIdentity(
        provider="bailian",
        deployment_id=deployment_id,
        family=family,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        policy_version="pwb-v1",
    )


def _policy_for(*identities: ModelIdentity) -> ProductionModelPolicy:
    return ProductionModelPolicy(
        approved_identity_keys=frozenset(identity.identity_key for identity in identities)
    )


class _MutableIdentityKey(tuple[object, ...]):
    pass


class _MutableIdentityPart(str):
    pass


class _ExplodingIdentityKeys:
    def __iter__(self) -> Iterator[tuple[str, str, str, str, str]]:
        raise RuntimeError("caller iterator failure")


@pytest.mark.parametrize(
    "keys",
    [
        {_MutableIdentityKey(_identity().identity_key)},
        {
            (
                    _MutableIdentityPart("bailian"),
                    "qwen3.6-prod-20260715",
                    "qwen",
                    "extract",
                    "pwb-v1",
            )
        },
        (_identity().identity_key, _identity().identity_key),
        (("bailian", "qwen3.6-prod-20260715", "qwen", "extract"),),
        (("", "qwen3.6-prod-20260715", "qwen", "extract", "pwb-v1"),),
        ((" bailian", "qwen3.6-prod-20260715", "qwen", "extract", "pwb-v1"),),
        (("bailian", "qwen3.6-prod-20260715", "qwen", "admin", "pwb-v1"),),
        _ExplodingIdentityKeys(),
    ],
)
def test_pwb1_policy_and_composition_reject_noncanonical_allowlist_keys(
    keys: object,
) -> None:
    with pytest.raises(ValueError, match="invalid approved identity keys"):
        ProductionModelPolicy(keys)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        cast(Any, _build_production_model_composition)(approved_identity_keys=keys)


def test_pwb1_allowlist_snapshot_does_not_retain_caller_container() -> None:
    identity = _identity()
    identities = [identity]
    policy = ProductionModelPolicy([identity.identity_key])
    verified = _verified()
    composition = _bind_verified_production_model_composition(
        verified,
        expected_identities=identities,
        expected_model_plan_hash=verified.request.expected_model_plan_hash,
    )
    digest = policy.policy_snapshot_digest
    context = _call_context(verified)

    identities.clear()

    assert policy.policy_snapshot_digest == digest
    assert policy.evaluate(identity) == identity
    assert composition._evaluate_for_guard(verified, context).receipt.decision == "ALLOW"


def test_pwb1_identity_rejects_blank_deployment() -> None:
    with pytest.raises(ValidationError):
        _identity("   ")


@pytest.mark.parametrize(
    "deployment_id",
    ["qwen-latest", "latest", "qwen3", "qwen", "qwen-prod-blue"],
)
def test_pwb1_rolling_identity_is_denied_even_when_exact_key_is_allowlisted(
    deployment_id: str,
) -> None:
    identity = _identity(deployment_id)

    with pytest.raises(ModelPolicyDenied) as denied:
        _policy_for(identity).evaluate(identity)

    assert denied.value.reason_code == "rolling_identity"


@pytest.mark.parametrize(
    ("deployment_id", "family"),
    [
        ("qwen3.6-prod-20260715", "qwen"),
        ("qwen3-prod-2026-07-15", "qwen"),
        ("qwen3-235b-a22b-instruct-2507", "qwen"),
        ("qwen3-prod-sha256-a1b2c3d4", "qwen"),
        ("qwen-vl3-prod-20260715", "qwen-vl"),
        ("minimax-m2.5-prod-20260715", "minimax"),
    ],
)
def test_pwb1_code_owned_catalog_accepts_supported_immutable_id_shapes(
    deployment_id: str,
    family: str,
) -> None:
    identity = _identity(deployment_id, family=family)

    assert _policy_for(identity).evaluate(identity) == identity


@pytest.mark.parametrize(
    ("provider", "deployment_id"),
    [
        ("Bailian", "qwen3-prod-20260722"),
        (" bailian", "qwen3-prod-20260722"),
        ("ｂａｉｌｉａｎ", "qwen3-prod-20260722"),
        ("b\u0332ailian", "qwen3-prod-20260722"),
        ("bailian", "QWEN3-PROD-20260722"),
        ("bailian", "qwen3-prod-20260722 "),
        ("bailian", "ｑｗｅｎ３-prod-20260722"),
        ("bailian", "q\u0332wen3-prod-20260722"),
        ("bailian", "qwen3_prod_20260722"),
    ],
)
def test_pwb1_provider_and_deployment_must_be_original_canonical_ascii_lowercase(
    provider: str,
    deployment_id: str,
) -> None:
    identity = _identity(deployment_id).model_copy(update={"provider": provider})
    policy = _policy_for(_identity())

    with pytest.raises(ModelPolicyDenied) as denied:
        policy.evaluate(identity)

    assert denied.value.reason_code == "invalid_identity"


@pytest.mark.parametrize(
    "deployment_id",
    [
        "qwen-gpt-04-prod-20260722",
        "qwen-g-p-t-04-prod-20260722",
        "qwen-g.p.t.0.4-prod-20260722",
        "qwen-o-03-prod-20260722",
        "qwen-minimax-m2-5-prod-20260722",
        "qwen3-minimax-m2.5-prod-20260722",
        "qwen3-attacker-prod-20260722",
        "qwen3-prod-20260722-sha256-a1",
    ],
)
def test_pwb1_anchored_catalog_rejects_unknown_or_cross_family_grammar(
    deployment_id: str,
) -> None:
    identity = _identity(deployment_id)

    with pytest.raises(ModelPolicyDenied) as denied:
        _policy_for(identity).evaluate(identity)

    assert denied.value.reason_code in {"invalid_identity", "strong_model"}


@pytest.mark.parametrize(
    "deployment_id",
    [
        "claude-opus",
        "deepseek-v4",
        "gpt_4o-20260722",
        "gpt.4o-20260722",
        "gpt/4o-20260722",
        "gpt 4o-20260722",
        "deep_seek-v4-20260722",
        "o_3-20260722",
        "qwen-gpt-04-prod-20260722",
        "qwen-g-p-t-04-prod-20260722",
        "qwen-g.p.t.0.4-prod-20260722",
        "qwen-o-03-prod-20260722",
    ],
)
def test_pwb1_strong_identity_is_denied_even_when_exact_key_is_allowlisted(
    deployment_id: str,
) -> None:
    identity = _identity(deployment_id)

    with pytest.raises(ModelPolicyDenied) as denied:
        _policy_for(identity).evaluate(identity)

    assert denied.value.reason_code == "strong_model"
    assert "secret-value" not in str(denied.value)


def test_pwb1_identity_requires_exact_approved_key() -> None:
    identity = _identity()

    with pytest.raises(ModelPolicyDenied) as denied:
        ProductionModelPolicy(approved_identity_keys=frozenset()).evaluate(identity)

    assert denied.value.reason_code == "identity_not_approved"


def test_pwb1_identity_key_is_exact_and_family_is_constrained() -> None:
    identity = _identity()

    assert identity.identity_key == (
        "bailian",
        "qwen3.6-prod-20260715",
        "qwen",
        "extract",
        "pwb-v1",
    )
    assert _policy_for(identity).evaluate(identity) == identity

    with pytest.raises(ValidationError):
        _identity(family="claude")

    forged_family = ModelIdentity.model_construct(
        **{**identity.model_dump(), "family": "claude"}
    )
    with pytest.raises(ModelPolicyDenied) as denied:
        _policy_for(identity).evaluate(forged_family)
    assert denied.value.reason_code == "invalid_identity"


def test_pwb1_identity_key_binds_approved_family_without_label_collision() -> None:
    approved = _identity(family="qwen")
    disguised = approved.model_copy(update={"family": "qwen-vl"})

    assert disguised.identity_key != approved.identity_key
    with pytest.raises(ModelPolicyDenied) as denied:
        _policy_for(approved).evaluate(disguised)

    assert denied.value.reason_code == "invalid_identity"


@pytest.mark.parametrize(
    ("deployment_id", "family"),
    [
        ("qwen3.6-prod-20260715", "qwen-vl"),
        ("qwen-vl3-prod-20260715", "qwen"),
        ("minimax-m2.5-prod-20260715", "qwen"),
        ("qwen3-minimax-m2.5-prod-20260715", "qwen"),
    ],
)
def test_pwb1_deployment_namespace_and_family_are_mutually_consistent(
    deployment_id: str,
    family: str,
) -> None:
    disguised = _identity(deployment_id, family=family)
    verified = _issue_verified_admission(
        _strict_request(),
        _binding().model_copy(update={"approved_identities": (disguised,)}),
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    sink = _CountingReceiptSink()

    with pytest.raises(AdmissionPolicyDenied) as denied:
        composition = _bind_verified_production_model_composition(
            verified,
            expected_identities=(disguised,),
            expected_model_plan_hash=verified.request.expected_model_plan_hash,
        )
        client = _build_test_gateway(
            composition=composition,
            transport_identity=disguised,
            receipt_sink=sink,
        )
        request = _gateway_request()
        _run_gateway_call(client, verified, _gateway_facts(verified, request), request)

    assert denied.value.reason_code == "production_identity_mismatch"
    assert sink.receipts == []


def test_pwb1_identity_model_is_frozen_extra_forbid_and_copy_revalidates() -> None:
    identity = _identity()

    with pytest.raises(ValidationError):
        identity.provider = "other"
    with pytest.raises(ValidationError):
        ModelIdentity.model_validate({**identity.model_dump(), "unexpected": "field"})


def test_pwb1_policy_model_construct_malformed_identity_is_stable_denial() -> None:
    valid = _identity().model_dump()
    malformed_payloads = []
    for field, value in (
        ("deployment_id", None),
        ("deployment_id", 123),
        ("family", []),
        ("provider", []),
    ):
        malformed_payloads.append({**valid, field: value})
    malformed_payloads.append({key: value for key, value in valid.items() if key != "role"})
    malformed_payloads.append({key: value for key, value in valid.items() if key != "provider"})

    policy = ProductionModelPolicy(approved_identity_keys=frozenset())
    for payload in malformed_payloads:
        forged = ModelIdentity.model_construct(**payload)
        with pytest.raises(ModelPolicyDenied) as denied:
            policy.evaluate(forged)
        assert denied.value.reason_code == "invalid_identity"

    invalid_copy = ModelIdentity.model_construct(**{**valid, "deployment_id": None})
    with pytest.raises(ValidationError):
        invalid_copy.model_copy()


_EXPECTED_HASH_FIELDS = (
    "expected_admission_artifact_digest",
    "expected_manifest_hash",
    "expected_eligibility_hash",
    "expected_golden_slice_hash",
    "expected_routing_policy_hash",
    "expected_schema_hash",
    "expected_template_lock_hash",
    "expected_structured_dispatch_hash",
    "expected_model_plan_hash",
    "expected_deployment_roles_hash",
    "expected_resource_caps_hash",
    "expected_rights_hash",
    "expected_provenance_hash",
    "expected_clean_integration_sha",
)


def _strict_request() -> StrictAdmissionRequestBinding:
    values: dict[str, object] = {
        "expected_purpose": "production-compilation",
        "expected_run_schema_version": "run-schema-v1",
        "expected_run_id": "run-030",
        "expected_run_revision": "revision-a",
        "expected_space_id": "space-insurance",
        "expected_admission_artifact_ref": "admission/030/run-030.json",
    }
    values.update(
        {field: f"{index:x}" * 64 for index, field in enumerate(_EXPECTED_HASH_FIELDS, 1)}
    )
    values["expected_clean_integration_sha"] = "d" * 40
    return StrictAdmissionRequestBinding.model_validate(values)


def _binding() -> AdmissionBinding:
    request = _strict_request()
    values: dict[str, object] = {
        field.removeprefix("expected_").join(("actual_", "")): value
        for field, value in request.model_dump().items()
    }
    values.update(
        {
            "actual_state": "READY",
            "actual_expires_at": datetime(2099, 8, 1, tzinfo=UTC),
            "approved_identities": (_identity(),),
            "approved_template_hashes": ("f" * 64,),
        }
    )
    return AdmissionBinding.model_validate(values)


def _verified() -> VerifiedAdmission:
    return _issue_verified_admission(
        _strict_request(),
        _binding(),
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def _raw_model_values(value: BaseModel) -> dict[str, object]:
    return {
        field: getattr(value, field)
        for field in type(value).model_fields
    }


def _permit_view(verified: VerifiedAdmission) -> ModelPermitView:
    binding = verified.binding
    return ModelPermitView(
        identity=binding.approved_identities[0],
        purpose=binding.actual_purpose,
        run_schema_version=binding.actual_run_schema_version,
        space_id=binding.actual_space_id,
        run_id=binding.actual_run_id,
        run_revision=binding.actual_run_revision,
        admission_hash=binding.actual_admission_artifact_digest,
        verified_binding_digest=verified.verified_binding_digest,
        template_hash=binding.approved_template_hashes[0],
        model_plan_hash=binding.actual_model_plan_hash,
        policy_snapshot_digest="a" * 64,
        call_scope_hash="e" * 64,
        expires_at=binding.actual_expires_at,
    )


def _issued_permit(
    view: ModelPermitView,
    verified: VerifiedAdmission,
    *,
    issued_at: datetime = datetime(2026, 7, 22, tzinfo=UTC),
) -> IssuedModelPermit:
    return _issue_model_permit(view, verified, issued_at=issued_at)


def test_pwb4_strict_admission_request_requires_every_expected_field() -> None:
    complete = _strict_request().model_dump()

    for field in tuple(complete):
        incomplete = dict(complete)
        incomplete.pop(field)
        with pytest.raises(ValidationError, match=field):
            StrictAdmissionRequestBinding.model_validate(incomplete)


def test_pwb4_raw_ready_binding_is_serializable_data_not_verified_authority() -> None:
    binding = _binding()
    loaded = AdmissionBinding.model_validate_json(binding.model_dump_json())

    assert loaded == binding
    assert binding.binding_digest == loaded.binding_digest
    assert not isinstance(binding, VerifiedAdmission)
    with pytest.raises(TypeError):
        VerifiedAdmission(_strict_request(), binding)


def test_pwb4_blocked_binding_can_record_empty_approved_roles_and_templates() -> None:
    blocked = _binding().model_copy(
        update={
            "actual_state": "BLOCKED",
            "approved_identities": (),
            "approved_template_hashes": (),
        }
    )

    assert blocked.approved_identities == ()
    assert blocked.approved_template_hashes == ()
    with pytest.raises(ValueError, match="READY"):
        _issue_verified_admission(
            _strict_request(),
            blocked,
            verifier_id="canonical-admission",
            verifier_version="v1",
            verified_at=datetime(2026, 7, 22, tzinfo=UTC),
        )


def test_pwb4_binding_digest_changes_for_every_actual_field() -> None:
    binding = _binding()

    for index, field in enumerate(type(binding).model_fields, 1):
        if field == "approved_identities":
            replacement: object = (_identity(family="qwen-vl"),)
        elif field == "approved_template_hashes":
            replacement = ("0" * 64,)
        elif field == "actual_state":
            replacement = "BLOCKED"
        elif field == "actual_expires_at":
            replacement = datetime(2026, 8, 2, tzinfo=UTC)
        elif field.endswith(("_digest", "_hash", "_sha")):
            replacement = f"{(index + 1) % 16:x}" * 64
        else:
            replacement = f"changed-{index}"
        changed = binding.model_copy(update={field: replacement})
        assert changed.binding_digest != binding.binding_digest, field


def test_pwb4_verified_admission_is_process_opaque_and_nontransferable() -> None:
    request = _strict_request()
    binding = _binding()
    verified = _verified()

    assert _is_verified_admission(verified)
    assert verified.request == request
    assert verified.binding == binding
    assert len(verified.verified_binding_digest) == 64
    receipt = verified.receipt
    loaded_receipt = AdmissionVerificationReceipt.model_validate_json(
        receipt.model_dump_json()
    )
    assert loaded_receipt == receipt
    assert receipt.request_digest == request.request_digest
    assert receipt.binding_digest == binding.binding_digest
    assert receipt.verified_binding_digest == verified.verified_binding_digest
    assert not isinstance(loaded_receipt, VerifiedAdmission)
    with pytest.raises(TypeError):
        copy.copy(verified)
    with pytest.raises(TypeError):
        copy.deepcopy(verified)
    with pytest.raises(TypeError):
        pickle.dumps(verified)
    with pytest.raises(TypeError):
        json.dumps(verified)
    assert not hasattr(VerifiedAdmission, "model_validate_json")

    forged = object.__new__(VerifiedAdmission)
    assert not _is_verified_admission(forged)


def test_pwb4_admission_verifier_protocol_has_only_strict_verify_port() -> None:
    parameters = tuple(signature(AdmissionVerifier.verify).parameters)

    assert parameters == ("self", "request")
    assert signature(AdmissionVerifier.verify).return_annotation in {
        "VerifiedAdmission",
        VerifiedAdmission,
    }


def test_pwb4_public_permit_is_view_only_and_legacy_authority_is_removed() -> None:
    verified = _verified()
    view = _permit_view(verified)
    loaded = ModelPermitView.model_validate_json(view.model_dump_json())

    assert loaded == view
    assert isinstance(loaded, ModelPermitView)
    assert not isinstance(loaded, IssuedModelPermit)
    assert "ModelPermit" not in model_policy_package.__all__
    assert not hasattr(model_policy_package, "ModelPermit")
    with pytest.raises(ImportError):
        exec("from insurance_harness.model_policy import ModelPermit", {})
    with pytest.raises(ValidationError):
        view.model_copy(update={"expires_at": datetime(2026, 8, 1)})


def test_pwb4_issued_permit_is_opaque_and_view_never_becomes_authority() -> None:
    verified = _verified()
    view = _permit_view(verified)
    issued = _issued_permit(view, verified)

    assert _is_issued_model_permit(issued)
    assert issued.view == view
    with pytest.raises(TypeError):
        IssuedModelPermit(view, verified)
    with pytest.raises(TypeError):
        copy.copy(issued)
    with pytest.raises(TypeError):
        copy.deepcopy(issued)
    with pytest.raises(TypeError):
        pickle.dumps(issued)
    with pytest.raises(TypeError):
        json.dumps(issued)
    assert not hasattr(IssuedModelPermit, "model_validate_json")

    forged = object.__new__(IssuedModelPermit)
    assert not _is_issued_model_permit(forged)


def test_pwb4_issued_permit_template_must_be_in_approved_exact_set() -> None:
    verified = _verified()
    unapproved = _permit_view(verified).model_copy(update={"template_hash": "0" * 64})

    with pytest.raises(ValueError, match="permit view"):
        _issued_permit(unapproved, verified)


def test_pwb4_model_construct_invalid_admission_objects_never_gain_authority() -> None:
    request = _strict_request()
    binding = _binding()
    forged_identity = ModelIdentity.model_construct(
        **{**_identity().model_dump(), "deployment_id": None}
    )
    invalid_binding = AdmissionBinding.model_construct(
        **{  # type: ignore[arg-type]
            **_raw_model_values(binding),
            "approved_identities": (forged_identity,),
        }
    )
    invalid_request = StrictAdmissionRequestBinding.model_construct(
        **{  # type: ignore[arg-type]
            **_raw_model_values(request),
            "expected_manifest_hash": "not-a-hash",
        }
    )

    for bad_request, bad_binding in (
        (invalid_request, binding),
        (request, invalid_binding),
    ):
        with pytest.raises(ValueError):
            _issue_verified_admission(
                bad_request,
                bad_binding,
                verifier_id="canonical-admission",
                verifier_version="v1",
                verified_at=datetime(2026, 7, 22, tzinfo=UTC),
            )

    verified = _verified()
    with pytest.raises(AttributeError):
        object.__setattr__(verified, "_binding", invalid_binding)
    assert _is_verified_admission(verified)

    invalid_receipt = AdmissionVerificationReceipt.model_construct(
        **{  # type: ignore[arg-type]
            **_raw_model_values(_verified().receipt),
            "verifier_id": None,
        }
    )
    verified_with_bad_receipt = _verified()
    with pytest.raises(AttributeError):
        object.__setattr__(verified_with_bad_receipt, "_receipt", invalid_receipt)
    assert _is_verified_admission(verified_with_bad_receipt)

    valid_verified = _verified()
    valid_view = _permit_view(valid_verified)
    invalid_view = ModelPermitView.model_construct(
        **{  # type: ignore[arg-type]
            **_raw_model_values(valid_view),
            "call_scope_hash": "not-a-hash",
        }
    )
    with pytest.raises(ValueError):
        _issued_permit(invalid_view, valid_verified)

    issued = _issued_permit(valid_view, valid_verified)
    with pytest.raises(AttributeError):
        object.__setattr__(issued, "_view", invalid_view)
    assert _is_issued_model_permit(issued)

    with pytest.raises(ValidationError):
        invalid_binding.model_copy()
    with pytest.raises(ValidationError):
        invalid_receipt.model_copy()
    with pytest.raises(ValidationError):
        invalid_view.model_copy()


@pytest.mark.parametrize(
    "verified_at",
    [
        datetime(2099, 8, 1, tzinfo=UTC),
        datetime(2099, 8, 2, tzinfo=UTC),
    ],
)
def test_pwb4_expired_or_equal_expiry_cannot_issue_verified_admission(
    verified_at: datetime,
) -> None:
    with pytest.raises(ValueError, match="expired"):
        _issue_verified_admission(
            _strict_request(),
            _binding(),
            verifier_id="canonical-admission",
            verifier_version="v1",
            verified_at=verified_at,
        )

    future = _issue_verified_admission(
        _strict_request(),
        _binding(),
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2099, 7, 31, 23, 59, 59, tzinfo=UTC),
    )
    assert _is_verified_admission(future)


def test_pwb4_binding_canonicalizes_sets_and_equivalent_expiry_instants() -> None:
    first = _binding().model_copy(
        update={
            "approved_identities": (
                _identity(role="gap"),
                _identity(role="extract"),
            ),
            "approved_template_hashes": ("f" * 64, "0" * 64),
            "actual_expires_at": datetime(2026, 8, 1, tzinfo=UTC),
        }
    )
    second = _binding().model_copy(
        update={
            "approved_identities": tuple(reversed(first.approved_identities)),
            "approved_template_hashes": tuple(reversed(first.approved_template_hashes)),
            "actual_expires_at": datetime(
                2026,
                8,
                1,
                8,
                tzinfo=timezone(timedelta(hours=8)),
            ),
        }
    )

    assert first == second
    assert first.binding_digest == second.binding_digest
    assert first.actual_expires_at.tzinfo is UTC
    assert first.approved_identities == tuple(
        sorted(first.approved_identities, key=lambda identity: identity.identity_key)
    )
    assert first.approved_template_hashes == tuple(sorted(first.approved_template_hashes))

    with pytest.raises(ValidationError, match="template"):
        _binding().model_copy(update={"approved_template_hashes": ("f" * 64, "f" * 64)})


@pytest.mark.parametrize(
    "issued_at",
    [
        datetime(2099, 8, 1, tzinfo=UTC),
        datetime(2099, 8, 2, tzinfo=UTC),
    ],
)
def test_pwb4_expired_or_equal_expiry_cannot_issue_model_permit(
    issued_at: datetime,
) -> None:
    verified = _verified()
    with pytest.raises(ValueError, match="expired"):
        _issue_model_permit(_permit_view(verified), verified, issued_at=issued_at)

    future = _issue_model_permit(
        _permit_view(verified),
        verified,
        issued_at=datetime(
            2026,
            7,
            22,
            8,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )
    assert _is_issued_model_permit(future)
    assert future.issued_at.tzinfo is UTC


def test_pwb4_permit_view_and_verification_receipt_normalize_times_to_utc() -> None:
    verified = _verified()
    offset = timezone(timedelta(hours=8))
    view = _permit_view(verified).model_copy(
        update={"expires_at": datetime(2026, 8, 1, 8, tzinfo=offset)}
    )
    receipt = verified.receipt.model_copy(
        update={"verified_at": datetime(2026, 7, 22, 8, tzinfo=offset)}
    )

    assert view.expires_at.tzinfo is UTC
    assert receipt.verified_at.tzinfo is UTC


_ACTUAL_EXPECTED_FIELDS = (
    "purpose",
    "run_schema_version",
    "run_id",
    "run_revision",
    "space_id",
    "admission_artifact_ref",
    "admission_artifact_digest",
    "manifest_hash",
    "eligibility_hash",
    "golden_slice_hash",
    "routing_policy_hash",
    "schema_hash",
    "template_lock_hash",
    "structured_dispatch_hash",
    "model_plan_hash",
    "deployment_roles_hash",
    "resource_caps_hash",
    "rights_hash",
    "provenance_hash",
    "clean_integration_sha",
)


@pytest.mark.parametrize("field", _ACTUAL_EXPECTED_FIELDS)
def test_pwb4_admission_issuer_rejects_every_expected_actual_mismatch(
    field: str,
) -> None:
    binding = _binding()
    actual_field = f"actual_{field}"
    old_value = getattr(binding, actual_field)
    if field == "clean_integration_sha":
        replacement = "0" * 40
    elif field.endswith(("_digest", "_hash")):
        replacement = "0" * 64
    else:
        replacement = f"different-{field}"
    assert replacement != old_value

    with pytest.raises(AdmissionPolicyDenied) as denied:
        _issue_verified_admission(
            _strict_request(),
            binding.model_copy(update={actual_field: replacement}),
            verifier_id="canonical-admission",
            verifier_version="v1",
            verified_at=datetime(2026, 7, 22, tzinfo=UTC),
        )

    assert denied.value.reason_code == f"{field}_mismatch"


def test_pwb4_mvp_030_request_cannot_borrow_020_admission() -> None:
    borrowed = _binding().model_copy(
        update={
            "actual_purpose": "canonical-13-product-baseline",
            "actual_run_id": "run-020",
            "actual_run_revision": "revision-020",
            "actual_admission_artifact_ref": "admission/020/canonical.json",
        }
    )

    with pytest.raises(AdmissionPolicyDenied) as denied:
        _issue_verified_admission(
            _strict_request(),
            borrowed,
            verifier_id="canonical-admission",
            verifier_version="v1",
            verified_at=datetime(2026, 7, 22, tzinfo=UTC),
        )

    assert denied.value.reason_code == "purpose_mismatch"


class _CanonicalTestVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, request: StrictAdmissionRequestBinding, /) -> VerifiedAdmission:
        self.calls += 1
        return _issue_verified_admission(
            request,
            _binding(),
            verifier_id="test-only-canonical-verifier",
            verifier_version="v1",
            verified_at=datetime(2026, 7, 22, tzinfo=UTC),
        )


def _composition() -> ProductionModelComposition:
    verified = _verified()
    identity = _identity()
    return _bind_verified_production_model_composition(
        verified,
        expected_identities=(identity,),
        expected_model_plan_hash=verified.request.expected_model_plan_hash,
    )


def _install_test_canonical_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> _CanonicalTestVerifier:
    verifier = _CanonicalTestVerifier()

    def select(purpose: str, run_schema_version: str) -> AdmissionVerifier:
        if (purpose, run_schema_version) != (
            "production-compilation",
            "run-schema-v1",
        ):
            raise AdmissionPolicyDenied("unknown_admission_profile")
        return verifier

    monkeypatch.setattr(
        composition_module,
        "_select_canonical_admission_verifier",
        select,
    )
    return verifier


def test_pwb4_production_builder_cannot_register_mirror_or_custom_verifier() -> None:
    assert tuple(signature(_build_production_model_composition).parameters) == ()
    with pytest.raises(TypeError):
        _build_production_model_composition(  # type: ignore[call-arg]
            canonical_verifiers={
                ("attacker-purpose", "attacker-schema"): _CanonicalTestVerifier()
            },
        )
    assert "_build_production_model_composition" not in model_policy_package.__all__
    assert not hasattr(ProductionModelComposition, "register_verifier")


def test_pwb4_production_composition_selects_only_exact_purpose_schema_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _install_test_canonical_bridge(monkeypatch)
    composition = _composition()

    verified = composition.verify(_strict_request())

    assert _is_verified_admission(verified)
    assert verifier.calls == 1
    for field, value in (
        ("expected_purpose", "wrong-purpose"),
        ("expected_run_schema_version", "unknown-schema"),
    ):
        with pytest.raises(AdmissionPolicyDenied) as denied:
            composition.verify(_strict_request().model_copy(update={field: value}))
        assert denied.value.reason_code == "unknown_admission_profile"
    assert verifier.calls == 1


def test_pwb4_missing_canonical_030_bridge_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_module_name: str) -> object:
        raise ModuleNotFoundError("030 is not installed")

    monkeypatch.setattr(composition_module, "import_module", missing)

    with pytest.raises(AdmissionPolicyDenied) as denied:
        _composition().verify(_strict_request())

    assert denied.value.reason_code == "canonical_verifier_unavailable"


def test_pwb4_production_composition_has_no_actual_only_or_verifier_override() -> None:
    composition = _composition()
    custom = _CanonicalTestVerifier()

    with pytest.raises(AdmissionPolicyDenied) as denied:
        composition.verify(_binding())  # type: ignore[arg-type]
    assert denied.value.reason_code == "invalid_admission_request"
    with pytest.raises(TypeError):
        composition.verify(_strict_request(), verifier=custom)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ProductionModelComposition(
            approved_identity_keys=frozenset(),
        )


def _call_context(verified: VerifiedAdmission) -> ModelCallContext:
    binding = verified.binding
    return ModelCallContext(
        identity=binding.approved_identities[0],
        purpose=binding.actual_purpose,
        run_schema_version=binding.actual_run_schema_version,
        space_id=binding.actual_space_id,
        run_id=binding.actual_run_id,
        run_revision=binding.actual_run_revision,
        admission_hash=binding.actual_admission_artifact_digest,
        verified_binding_digest=verified.verified_binding_digest,
        template_hash=binding.approved_template_hashes[0],
        model_plan_hash=binding.actual_model_plan_hash,
        call_scope_hash="e" * 64,
    )


def test_pwb4_policy_allow_issues_opaque_permit_and_secret_free_receipt() -> None:
    verified = _verified()
    context = _call_context(verified)

    decision = _composition()._evaluate_for_guard(verified, context)

    assert isinstance(decision, _PolicyDecision)
    assert _is_policy_decision(decision)
    assert _decision_authorizes_call(decision, verified, context)
    assert not hasattr(decision, "_issued_permit")
    assert "PolicyDecision" not in model_policy_package.__all__
    assert not hasattr(model_policy_package, "PolicyDecision")
    assert isinstance(decision.receipt, PolicyReceipt)
    assert isinstance(decision.receipt.permit_view, ModelPermitView)
    assert decision.receipt.permit_digest is not None
    assert decision.receipt.request_digest == verified.request.request_digest
    assert decision.receipt.space_id == verified.binding.actual_space_id
    assert decision.receipt.verified_binding_digest == verified.verified_binding_digest
    assert decision.receipt.call_scope_hash == context.call_scope_hash
    serialized = decision.receipt.model_dump_json()
    assert "api-key-secret-sentinel" not in serialized
    assert "raw-prompt-secret-sentinel" not in serialized
    assert "api_key" not in serialized
    assert "raw_prompt" not in serialized


@pytest.mark.parametrize(
    ("field", "replacement", "reason_code"),
    [
        ("purpose", "wrong-purpose", "purpose_mismatch"),
        ("run_schema_version", "wrong-schema", "run_schema_version_mismatch"),
        ("space_id", "other-space", "space_id_mismatch"),
        ("run_id", "run-020", "run_id_mismatch"),
        ("run_revision", "other-revision", "run_revision_mismatch"),
        ("admission_hash", "0" * 64, "admission_artifact_digest_mismatch"),
        ("verified_binding_digest", "0" * 64, "verified_binding_digest_mismatch"),
        ("template_hash", "0" * 64, "template_not_approved"),
        ("model_plan_hash", "0" * 64, "model_plan_hash_mismatch"),
    ],
)
def test_pwb4_policy_denies_cross_scope_replay_with_receipt(
    field: str,
    replacement: str,
    reason_code: str,
) -> None:
    verified = _verified()
    context = _call_context(verified).model_copy(update={field: replacement})

    decision = _composition()._evaluate_for_guard(verified, context)

    assert not _decision_authorizes_call(decision, verified, context)
    assert decision.receipt.reason_code == reason_code
    assert decision.receipt.decision == "DENY"
    assert decision.receipt.request_digest == verified.request.request_digest
    assert decision.receipt.verified_binding_digest == verified.verified_binding_digest


def test_pwb4_issued_permit_cannot_replay_across_call_scope() -> None:
    verified = _verified()
    original_context = _call_context(verified)
    decision = _composition()._evaluate_for_guard(
        verified,
        original_context,
    )
    replay_context = original_context.model_copy(update={"call_scope_hash": "0" * 64})

    assert _decision_authorizes_call(decision, verified, original_context)
    assert not _decision_authorizes_call(decision, verified, replay_context)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("space_id", "other-space"),
        ("manifest_hash", "0" * 64),
        ("template_lock_hash", "0" * 64),
        ("clean_integration_sha", "0" * 40),
    ],
)
def test_pwb4_issued_permit_cannot_replay_across_full_binding(
    field: str,
    replacement: str,
) -> None:
    original_verified = _verified()
    original_context = _call_context(original_verified)
    original_decision = _composition()._evaluate_for_guard(
        original_verified,
        original_context,
    )
    next_request = _strict_request().model_copy(
        update={f"expected_{field}": replacement}
    )
    next_binding = _binding().model_copy(update={f"actual_{field}": replacement})
    next_verified = _issue_verified_admission(
        next_request,
        next_binding,
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )

    assert not _decision_authorizes_call(
        original_decision,
        next_verified,
        _call_context(next_verified),
    )


def test_pwb4_policy_denies_identity_or_role_outside_admission() -> None:
    verified = _verified()
    gap_identity = _identity(role="gap")

    with pytest.raises(AdmissionPolicyDenied) as denied:
        _bind_verified_production_model_composition(
            verified,
            expected_identities=(gap_identity,),
            expected_model_plan_hash=verified.request.expected_model_plan_hash,
        )

    assert denied.value.reason_code == "production_identity_mismatch"


def test_pwb1_verified_composition_binds_every_role_and_model_plan() -> None:
    verified = _verified()
    extract_identity = _identity()

    with pytest.raises(AdmissionPolicyDenied) as role_denied:
        _bind_verified_production_model_composition(
            verified,
            expected_identities=(extract_identity, _identity(role="gap")),
            expected_model_plan_hash=verified.request.expected_model_plan_hash,
        )
    assert role_denied.value.reason_code == "production_identity_mismatch"

    with pytest.raises(AdmissionPolicyDenied) as plan_denied:
        _bind_verified_production_model_composition(
            verified,
            expected_identities=(extract_identity,),
            expected_model_plan_hash="0" * 64,
        )
    assert plan_denied.value.reason_code == "model_plan_hash_mismatch"


@pytest.mark.parametrize("replacement", ["extra-role", "missing-role"])
def test_pwb1_bound_composition_rechecks_complete_admission_identity_set_per_call(
    replacement: str,
) -> None:
    extract_identity = _identity()
    gap_identity = _identity(role="gap")
    one_role_verified = _verified()
    two_role_verified = _issue_verified_admission(
        _strict_request(),
        _binding().model_copy(
            update={"approved_identities": (extract_identity, gap_identity)}
        ),
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    if replacement == "extra-role":
        bound_verified = one_role_verified
        current_verified = two_role_verified
        expected_identities: tuple[ModelIdentity, ...] = (extract_identity,)
    else:
        bound_verified = two_role_verified
        current_verified = one_role_verified
        expected_identities = (extract_identity, gap_identity)
    composition = _bind_verified_production_model_composition(
        bound_verified,
        expected_identities=expected_identities,
        expected_model_plan_hash=bound_verified.request.expected_model_plan_hash,
    )
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=composition,
        transport_identity=extract_identity,
        receipt_sink=sink,
    )

    with pytest.raises(AdmissionPolicyDenied) as denied:
        _run_gateway_call(
            client,
            current_verified,
            _gateway_facts(current_verified, request),
            request,
        )

    assert denied.value.reason_code == "production_identity_mismatch"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


@pytest.mark.parametrize(
    "deployment_id",
    [
        "gpt_4o-20260722",
        "gpt.4o-20260722",
        "gpt/4o-20260722",
        "gpt 4o-20260722",
        "deep_seek-v4-20260722",
        "o_3-20260722",
        "qwen-gpt-04-prod-20260722",
        "qwen-g-p-t-04-prod-20260722",
        "qwen-g.p.t.0.4-prod-20260722",
        "qwen-o-03-prod-20260722",
        "qwen-minimax-m2-5-prod-20260722",
        "QWEN3-PROD-20260722",
        "ｑｗｅｎ３-prod-20260722",
        "q\u0332wen3-prod-20260722",
    ],
)
def test_pwb1_disguised_strong_identity_cannot_build_guarded_transport(
    deployment_id: str,
) -> None:
    disguised = _identity(deployment_id)
    verified = _issue_verified_admission(
        _strict_request(),
        _binding().model_copy(update={"approved_identities": (disguised,)}),
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    sink = _CountingReceiptSink()

    with pytest.raises(AdmissionPolicyDenied) as denied:
        composition = _bind_verified_production_model_composition(
            verified,
            expected_identities=(disguised,),
            expected_model_plan_hash=verified.request.expected_model_plan_hash,
        )
        client = _build_test_gateway(
            composition=composition,
            transport_identity=disguised,
            receipt_sink=sink,
        )
        request = _gateway_request()
        _run_gateway_call(
            client,
            verified,
            _gateway_facts(verified, request),
            request,
        )

    assert denied.value.reason_code == "production_identity_mismatch"
    assert sink.receipts == []


def test_pwb4_policy_denies_expired_verified_scope_without_issuing_permit() -> None:
    request = _strict_request()
    binding = _binding().model_copy(
        update={"actual_expires_at": datetime(2020, 8, 1, tzinfo=UTC)}
    )
    verified = _issue_verified_admission(
        request,
        binding,
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2020, 7, 22, tzinfo=UTC),
    )

    context = _call_context(verified)
    decision = _composition()._evaluate_for_guard(verified, context)

    assert not _decision_authorizes_call(decision, verified, context)
    assert decision.receipt.reason_code == "admission_expired"


def test_pwb4_production_composition_rejects_custom_policy_or_guard_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_canonical_bridge(monkeypatch)
    composition = _composition()
    verified = composition.verify(_strict_request())
    context = _call_context(verified)

    assert not hasattr(composition, "evaluate")
    assert not hasattr(ProductionModelPolicy, "evaluate_call")
    with pytest.raises(TypeError):
        composition._evaluate_for_guard(  # type: ignore[call-arg]
            verified,
            context,
            policy=_policy_for(context.identity),
        )
    with pytest.raises(TypeError):
        composition._evaluate_for_guard(  # type: ignore[call-arg]
            verified, context, guard=object()
        )


def test_pwb4_policy_decision_is_sealed_immutable_and_nontransferable() -> None:
    verified = _verified()
    context = _call_context(verified)
    decision = _composition()._evaluate_for_guard(verified, context)

    with pytest.raises(TypeError):
        _PolicyDecision()
    with pytest.raises(TypeError):
        decision.receipt = decision.receipt  # type: ignore[misc]
    with pytest.raises(TypeError):
        copy.copy(decision)
    with pytest.raises(TypeError):
        copy.deepcopy(decision)
    with pytest.raises(TypeError):
        pickle.dumps(decision)
    forged = object.__new__(_PolicyDecision)
    assert not _is_policy_decision(forged)

    spliced = _composition()._evaluate_for_guard(verified, context)
    forged_receipt = PolicyReceipt.model_construct(
        **{  # type: ignore[arg-type]
            **_raw_model_values(spliced.receipt),
            "reason_code": "forged-allow",
        }
    )
    with pytest.raises(AttributeError):
        object.__setattr__(spliced, "_receipt", forged_receipt)
    assert _is_policy_decision(spliced)


def test_pwb4_transport_matcher_rechecks_permit_expiry_at_use_time() -> None:
    verified = _verified()
    context = _call_context(verified)
    permit = _issue_model_permit(
        _permit_view(verified),
        verified,
        issued_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    expires_at = permit.view.expires_at

    assert _permit_matches_call_context(
        permit,
        verified,
        context,
        _checked_at=expires_at - timedelta(microseconds=1),
    )
    assert not _permit_matches_call_context(
        permit,
        verified,
        context,
        _checked_at=expires_at,
    )
    assert not _permit_matches_call_context(
        permit,
        verified,
        context,
        _checked_at=expires_at + timedelta(microseconds=1),
    )

    old_verified = _issue_verified_admission(
        _strict_request(),
        _binding().model_copy(
            update={"actual_expires_at": datetime(2020, 8, 1, tzinfo=UTC)}
        ),
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2020, 7, 22, tzinfo=UTC),
    )
    old_permit = _issue_model_permit(
        _permit_view(old_verified),
        old_verified,
        issued_at=datetime(2020, 7, 22, tzinfo=UTC),
    )
    assert not _permit_matches_call_context(
        old_permit,
        old_verified,
        _call_context(old_verified),
    )


def test_pwb4_public_composition_signatures_have_no_clock_rollback() -> None:
    assert "clock" not in signature(ProductionModelComposition.verify).parameters
    assert "checked_at" not in signature(ProductionModelComposition.verify).parameters
    assert "clock" not in signature(
        ProductionModelComposition._evaluate_for_guard
    ).parameters
    assert "checked_at" not in signature(
        ProductionModelComposition._evaluate_for_guard
    ).parameters


def test_pwb4_receipt_sink_protocol_records_receipt_only() -> None:
    assert tuple(signature(ReceiptSink.record).parameters) == ("self", "receipt")


def _alternate_verified(**updates: object) -> VerifiedAdmission:
    request = _strict_request().model_copy(
        update={f"expected_{field}": value for field, value in updates.items()}
    )
    binding = _binding().model_copy(
        update={f"actual_{field}": value for field, value in updates.items()}
    )
    return _issue_verified_admission(
        request,
        binding,
        verifier_id="canonical-admission",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def test_pwb4_coordinated_verified_payload_rebind_cannot_cross_space() -> None:
    original = _verified()
    alternate = _alternate_verified(
        space_id="other-space",
        manifest_hash="0" * 64,
        template_lock_hash="1" * 64,
    )
    try:
        object.__setattr__(original, "_request", alternate.request)
        object.__setattr__(original, "_binding", alternate.binding)
        object.__setattr__(original, "_receipt", alternate.receipt)
    except AttributeError:
        pass

    context = _call_context(alternate)
    decision = _composition()._evaluate_for_guard(original, context)
    provider_calls = int(_decision_authorizes_call(decision, original, context))

    assert provider_calls == 0
    assert decision.receipt.decision == "DENY"


def test_pwb4_coordinated_permit_view_rebind_cannot_change_call_scope() -> None:
    verified = _verified()
    permit = _issue_model_permit(
        _permit_view(verified),
        verified,
        issued_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    rebound_context = _call_context(verified).model_copy(
        update={"call_scope_hash": "0" * 64}
    )
    try:
        object.__setattr__(
            permit,
            "_view",
            permit.view.model_copy(update={"call_scope_hash": "0" * 64}),
        )
    except AttributeError:
        pass

    provider_calls = int(
        _permit_matches_call_context(permit, verified, rebound_context)
    )

    assert provider_calls == 0


def test_pwb4_coordinated_decision_receipt_permit_context_rebind_is_denied() -> None:
    verified = _verified()
    original_context = _call_context(verified)
    decision = _composition()._evaluate_for_guard(verified, original_context)
    rebound_context = original_context.model_copy(update={"call_scope_hash": "0" * 64})
    try:
        permit = decision._permit  # type: ignore[attr-defined]
        rebound_view = permit.view.model_copy(update={"call_scope_hash": "0" * 64})
        object.__setattr__(permit, "_view", rebound_view)
        rebound_receipt = decision.receipt.model_copy(
            update={
                "call_scope_hash": "0" * 64,
                "permit_view": rebound_view,
                "permit_digest": _permit_view_digest(rebound_view),
            }
        )
        object.__setattr__(decision, "_context", rebound_context)
        object.__setattr__(decision, "_receipt", rebound_receipt)
    except AttributeError:
        pass

    provider_calls = int(
        _decision_authorizes_call(decision, verified, rebound_context)
    )

    assert provider_calls == 0


def test_pwb4_composition_and_policy_allowlist_cannot_be_swapped_after_issue() -> None:
    verified = _verified()
    context = _call_context(verified)
    composition = _build_production_model_composition()
    with pytest.raises(AdmissionPolicyDenied) as denied:
        composition._evaluate_for_guard(verified, context)
    assert denied.value.reason_code == "invalid_production_composition"

    replacement = _policy_for(context.identity)
    try:
        object.__setattr__(composition, "_policy", replacement)
    except AttributeError:
        pass
    with pytest.raises(AdmissionPolicyDenied) as denied:
        composition._evaluate_for_guard(verified, context)
    assert denied.value.reason_code == "invalid_production_composition"

    mutable = ProductionModelPolicy(approved_identity_keys=frozenset())
    with pytest.raises(ModelPolicyDenied):
        mutable.evaluate(context.identity)
    with pytest.raises((AttributeError, TypeError)):
        mutable._approved_identity_keys = frozenset({context.identity.identity_key})
    with pytest.raises(ModelPolicyDenied):
        mutable.evaluate(context.identity)


def test_pwb4_permit_records_immutable_policy_snapshot_digest() -> None:
    verified = _verified()
    context = _call_context(verified)
    decision = _composition()._evaluate_for_guard(verified, context)
    receipt = decision.receipt
    permit_view = receipt.permit_view

    assert permit_view is not None
    assert receipt.policy_snapshot_digest == permit_view.policy_snapshot_digest


def test_pwb4_policy_receipt_rejects_incoherent_allow_and_deny_shapes() -> None:
    verified = _verified()
    decision = _composition()._evaluate_for_guard(verified, _call_context(verified))
    allow = decision.receipt.model_dump()
    allow["permit_view"] = None
    allow["permit_digest"] = None
    with pytest.raises(ValidationError):
        PolicyReceipt.model_validate(allow)

    deny = {**decision.receipt.model_dump(), "decision": "DENY"}
    with pytest.raises(ValidationError):
        PolicyReceipt.model_validate(deny)


@pytest.mark.parametrize(
    "field",
    [
        "purpose",
        "run_schema_version",
        "space_id",
        "run_id",
        "run_revision",
        "identity_provider",
        "identity_deployment_id",
        "identity_policy_version",
    ],
)
def test_pwb4_deny_receipt_digests_untrusted_context_without_secret_leak(
    field: str,
) -> None:
    sentinel = "api-key-secret-sentinel"
    verified = _verified()
    context = _call_context(verified)
    if field.startswith("identity_"):
        identity_field = field.removeprefix("identity_")
        context = context.model_copy(
            update={
                "identity": context.identity.model_copy(
                    update={identity_field: sentinel}
                )
            }
        )
    else:
        context = context.model_copy(update={field: sentinel})

    decision = _composition()._evaluate_for_guard(verified, context)
    serialized = decision.receipt.model_dump_json()

    assert decision.receipt.decision == "DENY"
    assert len(decision.receipt.attempted_context_digest) == 64
    assert sentinel not in serialized


def test_pwb4_deny_receipt_does_not_echo_untrusted_call_scope_hash() -> None:
    sentinel = "0123456789abcdef" * 4
    verified = _verified()
    context = _call_context(verified).model_copy(
        update={"purpose": "wrong-purpose", "call_scope_hash": sentinel}
    )

    decision = _composition()._evaluate_for_guard(verified, context)

    assert decision.receipt.decision == "DENY"
    assert decision.receipt.call_scope_hash != sentinel
    assert sentinel not in decision.receipt.model_dump_json()


def test_pwb4_authority_registry_uses_identity_weak_lifecycle_and_fork_reset() -> None:
    from insurance_harness.model_policy.admission import (
        _reset_admission_authority_after_fork,
    )

    verified = _verified()
    same_payload = _verified()
    assert verified is not same_payload
    assert verified != same_payload
    assert len({verified, same_payload}) == 2
    assert verified.request is not verified.request

    reference = weakref.ref(verified)
    _reset_admission_authority_after_fork()
    assert not _is_verified_admission(verified)
    del verified
    gc.collect()
    assert reference() is None


def test_pwb4_every_authority_registry_rotates_without_reusing_inherited_locks() -> None:
    verified = _verified()
    context = _call_context(verified)
    policy = _policy_for(context.identity)
    decision = _composition()._evaluate_for_guard(verified, context)
    composition = _composition()
    old_policy_lock = policy_module._POLICY_LOCK
    old_decision_lock = policy_module._DECISION_LOCK
    old_policy_states = policy_module._POLICY_STATES
    old_decision_states = policy_module._DECISION_STATES

    policy_module._reset_policy_authority_after_fork()

    assert policy_module._POLICY_LOCK is not old_policy_lock
    assert policy_module._DECISION_LOCK is not old_decision_lock
    assert policy_module._POLICY_STATES is not old_policy_states
    assert policy_module._DECISION_STATES is not old_decision_states
    with pytest.raises(ModelPolicyDenied):
        policy.evaluate(context.identity)
    assert not _is_policy_decision(decision)

    old_composition_lock = composition_module._COMPOSITION_LOCK
    old_composition_states = composition_module._COMPOSITION_STATES
    composition_module._reset_composition_authority_after_fork()

    assert composition_module._COMPOSITION_LOCK is not old_composition_lock
    assert composition_module._COMPOSITION_STATES is not old_composition_states
    with pytest.raises(AdmissionPolicyDenied) as denied:
        composition._evaluate_for_guard(verified, context)
    assert denied.value.reason_code == "invalid_production_composition"

    old_verified_lock = admission_module._VERIFIED_LOCK
    old_permit_lock = admission_module._PERMIT_LOCK
    admission_module._reset_admission_authority_after_fork()
    assert admission_module._VERIFIED_LOCK is not old_verified_lock
    assert admission_module._PERMIT_LOCK is not old_permit_lock


def test_pwb4_authority_registry_concurrent_reads_do_not_transfer_authority() -> None:
    verified = _verified()
    permit = _issue_model_permit(
        _permit_view(verified),
        verified,
        issued_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    forged_verified = object.__new__(VerifiedAdmission)
    forged_permit = object.__new__(IssuedModelPermit)

    with ThreadPoolExecutor(max_workers=8) as pool:
        valid = tuple(pool.map(lambda _index: _is_verified_admission(verified), range(64)))
        invalid = tuple(
            pool.map(lambda _index: _is_verified_admission(forged_verified), range(64))
        )
        permits = tuple(
            pool.map(lambda _index: _is_issued_model_permit(permit), range(64))
        )
        forged_permits = tuple(
            pool.map(lambda _index: _is_issued_model_permit(forged_permit), range(64))
        )

    assert all(valid)
    assert not any(invalid)
    assert all(permits)
    assert not any(forged_permits)


def test_pwb4_gateway_public_call_has_only_raw_facts_and_request() -> None:
    gateway_type = getattr(model_policy_package, "GuardedModelClient", None)

    assert gateway_type is not None
    assert "GuardedModelClient" in model_policy_package.__all__
    assert tuple(signature(gateway_type.call).parameters) == (
        "self",
        "verified_admission",
        "facts",
        "request",
    )
    assert iscoroutinefunction(gateway_type.call)
    assert signature(gateway_type.call).return_annotation == "str"
    assert {
        "permit",
        "decision",
        "policy",
        "guard",
        "verifier",
        "binding",
        "clock",
        "checked_at",
        "call_scope_hash",
    }.isdisjoint(signature(gateway_type.call).parameters)


def test_pwb4_gateway_public_facts_and_request_are_frozen_without_scope_hash() -> None:
    facts_type = getattr(model_policy_package, "ModelCallFacts", None)
    request_type = getattr(model_policy_package, "ModelCallRequest", None)

    assert facts_type is not None
    assert request_type is not None
    assert "call_scope_hash" not in facts_type.model_fields
    assert "call_scope_hash" not in request_type.model_fields
    facts = facts_type(
        job_id="job-1",
        stage="extract",
        attempt=1,
        input_digest="1" * 64,
        content_digest="2" * 64,
        rendered_prompt_digest="3" * 64,
        purpose="production-compilation",
        run_schema_version="run-schema-v1",
        space_id="space-insurance",
        run_id="run-030",
        run_revision="revision-a",
        admission_artifact_digest="1" * 64,
        template_hash="f" * 64,
        model_plan_hash="a" * 64,
        identity=_identity(),
        role="extract",
    )
    request = request_type(content=b"content", rendered_prompt=b"secret prompt")

    with pytest.raises(ValidationError):
        facts.stage = "gap"
    with pytest.raises(ValidationError):
        request.content = b"changed"


_TEST_CLIENT_EXECUTORS: weakref.WeakKeyDictionary[object, object] = (
    weakref.WeakKeyDictionary()
)
_raw_build_guarded_model_client_for_test = (
    gateway_module._build_guarded_model_client_for_test
)


def _gateway_executor_terminal_observations(
    client: GuardedModelClient,
) -> list[tuple[ModelIdentity, ModelCallRequest]]:
    executor = _TEST_CLIENT_EXECUTORS.get(client)
    return (
        []
        if executor is None
        else list(gateway_module._test_executor_terminal_observations(executor))
    )


def _gateway_executor_terminal_details(
    client: GuardedModelClient,
) -> tuple[tuple[ModelIdentity, ModelCallRequest, object, int], ...]:
    executor = _TEST_CLIENT_EXECUTORS.get(client)
    return () if executor is None else gateway_module._test_executor_terminal_details(executor)


def _build_test_gateway(
    *,
    composition: ProductionModelComposition,
    transport_identity: ModelIdentity,
    receipt_sink: object,
    mode: str = "success",
) -> GuardedModelClient:
    executor = gateway_module._issue_test_model_executor_for_test(
        composition=composition,
        transport_identity=transport_identity,
        mode=mode,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=receipt_sink,
    )
    _TEST_CLIENT_EXECUTORS[client] = executor
    return client


def _build_raw_arbitrary_gateway(
    *,
    composition: ProductionModelComposition,
    transport: object,
    transport_identity: ModelIdentity,
    receipt_sink: object,
) -> GuardedModelClient:
    del transport_identity
    return _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=transport,  # type: ignore[arg-type]
        receipt_sink=receipt_sink,
    )


class _CountingReceiptSink:
    def __init__(self) -> None:
        self.receipts: list[PolicyReceipt] = []

    def record(self, receipt: PolicyReceipt, /) -> None:
        self.receipts.append(receipt)


def _gateway_request() -> ModelCallRequest:
    return ModelCallRequest(
        content=b"input-content-secret-sentinel",
        rendered_prompt=b"raw-prompt-secret-sentinel",
    )


def _gateway_facts(
    verified: VerifiedAdmission,
    request: ModelCallRequest,
    **updates: object,
) -> ModelCallFacts:
    binding = verified.binding
    values: dict[str, object] = {
        "job_id": "job-1",
        "stage": "extract",
        "attempt": 1,
        "input_digest": "b" * 64,
        "content_digest": hashlib.sha256(request.content).hexdigest(),
        "rendered_prompt_digest": hashlib.sha256(
            request.rendered_prompt
        ).hexdigest(),
        "purpose": binding.actual_purpose,
        "run_schema_version": binding.actual_run_schema_version,
        "space_id": binding.actual_space_id,
        "run_id": binding.actual_run_id,
        "run_revision": binding.actual_run_revision,
        "admission_artifact_digest": binding.actual_admission_artifact_digest,
        "template_hash": binding.approved_template_hashes[0],
        "model_plan_hash": binding.actual_model_plan_hash,
        "identity": binding.approved_identities[0],
        "role": binding.approved_identities[0].role,
    }
    values.update(updates)
    return ModelCallFacts.model_validate(values)


def _run_gateway_call(
    client: GuardedModelClient,
    verified_admission: object,
    facts: object,
    request: object,
    **kwargs: object,
) -> object:
    return asyncio.run(
        client.call(
            verified_admission,  # type: ignore[arg-type]
            facts,  # type: ignore[arg-type]
            request,  # type: ignore[arg-type]
            **kwargs,
        )
    )


def test_pwb4_gateway_allow_persists_once_then_calls_weak_transport_once() -> None:
    verified = _verified()
    request = _gateway_request()
    facts = _gateway_facts(verified, request)
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    result = _run_gateway_call(client, verified, facts, request)

    assert result == "weak-result"
    assert _gateway_executor_terminal_observations(client) == [(_identity(), request)]
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"
    serialized = sink.receipts[0].model_dump_json()
    assert "input-content-secret-sentinel" not in serialized
    assert "raw-prompt-secret-sentinel" not in serialized
    with pytest.raises(TypeError):
        GuardedModelClient(
            composition=_composition(),
            receipt_sink=sink,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "reason_code"),
    [
        ("purpose", "wrong-purpose", "purpose_mismatch"),
        ("run_schema_version", "wrong-schema", "run_schema_version_mismatch"),
        ("space_id", "other-space", "space_id_mismatch"),
        ("run_id", "other-run", "run_id_mismatch"),
        ("run_revision", "other-revision", "run_revision_mismatch"),
        (
            "admission_artifact_digest",
            "0" * 64,
            "admission_artifact_digest_mismatch",
        ),
        ("template_hash", "0" * 64, "template_not_approved"),
        ("model_plan_hash", "0" * 64, "model_plan_hash_mismatch"),
    ],
)
def test_pwb4_gateway_scope_mismatch_persists_one_deny_and_zero_transport(
    field: str,
    replacement: str,
    reason_code: str,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelPolicyDenied) as denied:
        _run_gateway_call(
            client,
            verified,
            _gateway_facts(verified, request, **{field: replacement}),
            request,
        )

    assert denied.value.reason_code == reason_code
    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "DENY"
    assert sink.receipts[0].reason_code == reason_code


@pytest.mark.parametrize(
    "identity",
    [
        _identity("qwen3.6-unlisted-20260715"),
        _identity("qwen-latest"),
        _identity("claude-opus"),
        _identity("qwen-gpt-04-prod-20260722"),
        _identity("qwen-g-p-t-04-prod-20260722"),
        _identity("qwen-minimax-m2-5-prod-20260722"),
        _identity("QWEN3-PROD-20260722"),
        _identity("ｑｗｅｎ３-prod-20260722"),
        _identity("q\u0332wen3-prod-20260722"),
    ],
)
def test_pwb4_gateway_invalid_identity_never_calls_or_falls_back(
    identity: ModelIdentity,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client,
            verified,
            _gateway_facts(
                verified,
                request,
                identity=identity,
                role=identity.role,
            ),
            request,
        )

    assert denied.value.reason_code == "invalid_transport_identity"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []
    with pytest.raises(TypeError):
        _build_test_gateway(
            composition=_composition(),
            transport_identity=_identity(),
            receipt_sink=sink,
            fallback_transport=object(),
        )  # type: ignore[call-arg]


def test_pwb4_gateway_invalid_capability_context_and_request_are_zero_sink() -> None:
    verified = _verified()
    request = _gateway_request()
    facts = _gateway_facts(verified, request)
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    forged = object.__new__(VerifiedAdmission)
    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(client, forged, facts, request)
    assert denied.value.reason_code == "invalid_verified_admission"

    with pytest.raises(ModelGatewayDenied) as invalid_context:
        _run_gateway_call(client, verified, _call_context(verified), request)
    assert invalid_context.value.reason_code == "invalid_call_facts"

    malformed = ModelCallRequest.model_construct(
        content="raw-prompt-secret-sentinel", rendered_prompt=b"prompt"
    )
    with pytest.raises(ModelGatewayDenied) as invalid_request:
        _run_gateway_call(client, verified, facts, malformed)
    assert invalid_request.value.reason_code == "invalid_call_request"
    assert "raw-prompt-secret-sentinel" not in str(invalid_request.value)
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


@pytest.mark.parametrize(
    ("field", "replacement", "reason_code"),
    [
        ("role", "gap", "role_mismatch"),
        ("content_digest", "0" * 64, "call_content_digest_mismatch"),
        (
            "rendered_prompt_digest",
            "0" * 64,
            "rendered_prompt_digest_mismatch",
        ),
    ],
)
def test_pwb4_gateway_tampered_raw_facts_fail_before_policy_receipt(
    field: str,
    replacement: str,
    reason_code: str,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client,
            verified,
            _gateway_facts(verified, request, **{field: replacement}),
            request,
        )

    assert denied.value.reason_code == reason_code
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_sink_failure_prevents_transport() -> None:
    class _FailingSink:
        def record(self, receipt: PolicyReceipt, /) -> None:
            del receipt
            raise RuntimeError("api-key-secret-sentinel")

    verified = _verified()
    request = _gateway_request()
    sink = _FailingSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "receipt_sink_failure"
    assert "api-key-secret-sentinel" not in str(denied.value)
    assert _gateway_executor_terminal_observations(client) == []


def test_pwb4_gateway_transport_exception_has_no_retry_or_secret_echo() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode="failure",
    )

    with pytest.raises(ModelTransportError) as failed:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert "raw-prompt-secret-sentinel" not in str(failed.value)
    assert len(_gateway_executor_terminal_observations(client)) == 1
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_rechecks_expiry_before_persisting_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    monkeypatch.setattr(
        gateway_module,
        "_utc_now",
        lambda: verified.binding.actual_expires_at,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_is_opaque_nontransferable_and_reset_revokes() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(TypeError):
        copy.copy(client)
    with pytest.raises(TypeError):
        copy.deepcopy(client)
    with pytest.raises(TypeError):
        pickle.dumps(client)
    forged = object.__new__(GuardedModelClient)
    with pytest.raises(ModelGatewayDenied) as forged_denied:
        _run_gateway_call(
            forged, verified, _gateway_facts(verified, request), request
        )
    assert forged_denied.value.reason_code == "invalid_gateway"

    old_lock = gateway_module._GATEWAY_LOCK
    old_states = gateway_module._GATEWAY_STATES
    gateway_module._reset_gateway_authority_after_fork()

    assert gateway_module._GATEWAY_LOCK is not old_lock
    assert gateway_module._GATEWAY_STATES is not old_states
    with pytest.raises(ModelGatewayDenied) as reset_denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )
    assert reset_denied.value.reason_code == "invalid_gateway"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_registry_value_does_not_retain_weak_key() -> None:
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=_CountingReceiptSink(),
    )
    reference = weakref.ref(client)

    del client
    gc.collect()

    assert reference() is None


def test_pwb4_gateway_fork_reset_captures_private_authority_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    registered_reset = gateway_module._reset_gateway_authority_after_fork
    monkeypatch.setattr(
        gateway_module,
        "_reset_bound_transport_authority_after_fork",
        lambda: None,
    )

    registered_reset()

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )
    assert denied.value.reason_code == "invalid_gateway"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_sink_backref_does_not_retain_weak_key() -> None:
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    sink.gateway = client  # type: ignore[attr-defined]
    reference = weakref.ref(client)

    del client, sink
    gc.collect()

    assert reference() is None


def test_pwb4_gateway_sink_type_backref_does_not_retain_weak_key() -> None:
    sink_type = type("EphemeralSink", (_CountingReceiptSink,), {})
    sink = sink_type()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    sink_type.gateway = client  # type: ignore[attr-defined]
    reference = weakref.ref(client)

    del client, sink, sink_type
    gc.collect()

    assert reference() is None


def test_pwb4_gateway_fails_closed_when_stateful_target_is_dropped() -> None:
    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
    )
    sink = _CountingReceiptSink()
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )
    target_ref = weakref.ref(target)

    del target
    gc.collect()

    assert target_ref() is None
    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
    )
    assert denied.value.reason_code == "invalid_gateway"
    assert sink.receipts == []


def test_pwb4_gateway_captured_authority_cannot_be_swapped_by_sink() -> None:
    class _SwappingSink(_CountingReceiptSink):
        def __init__(self) -> None:
            super().__init__()
            self.client: GuardedModelClient | None = None

        def record(self, receipt: PolicyReceipt, /) -> None:
            assert self.client is not None
            for field, replacement in (
                ("_composition", _composition()),
                ("_transport", object()),
                ("_receipt_sink", _CountingReceiptSink()),
            ):
                with pytest.raises((AttributeError, TypeError)):
                    object.__setattr__(self.client, field, replacement)
            _CountingReceiptSink.record(self, receipt)

    verified = _verified()
    request = _gateway_request()
    sink = _SwappingSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    sink.client = client

    result = _run_gateway_call(
        client, verified, _gateway_facts(verified, request), request
    )

    assert result == "weak-result"
    assert len(_gateway_executor_terminal_observations(client)) == 1
    assert len(sink.receipts) == 1


def test_pwb4_gateway_authority_mutation_before_receipt_is_zero_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    def revoke_gateway() -> datetime:
        gateway_module._reset_gateway_authority_after_fork()
        return datetime.now(UTC)

    monkeypatch.setattr(gateway_module, "_utc_now", revoke_gateway)

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_builder_and_call_expose_no_override_or_fallback_ports() -> None:
    assert "_build_guarded_model_client_for_test" not in model_policy_package.__all__
    assert not hasattr(
        model_policy_package, "_build_guarded_model_client_for_test"
    )
    assert tuple(
        signature(gateway_module._build_guarded_model_client_for_test).parameters
    ) == ("composition", "executor", "receipt_sink")
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    facts = _gateway_facts(verified, request)

    for kwargs in (
        {"permit": object()},
        {"decision": object()},
        {"policy": object()},
        {"guard": object()},
        {"verifier": object()},
        {"binding": _binding()},
        {"clock": lambda: datetime.now(UTC)},
        {"checked_at": datetime.now(UTC)},
        {"call_scope_hash": "0" * 64},
        {"fallback": object()},
        {"candidate_promoter": lambda: None},
    ):
        with pytest.raises(TypeError):
            _run_gateway_call(client, verified, facts, request, **kwargs)
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


@pytest.mark.parametrize("outcome", ["truncated", "exhausted", "no_consensus"])
def test_pwb4_gateway_does_not_accept_orchestrator_outcomes_or_promotion(
    outcome: str,
) -> None:
    verified = _verified()
    request = _gateway_request()
    values = _gateway_facts(verified, request).model_dump()
    values["outcome"] = outcome

    with pytest.raises(ValidationError):
        ModelCallFacts.model_validate(values)


def test_pwb4_gateway_revalidates_model_constructed_malformed_facts() -> None:
    verified = _verified()
    request = _gateway_request()
    valid = _gateway_facts(verified, request)
    malformed_values: dict[str, Any] = valid.model_dump()
    malformed_values["job_id"] = None
    malformed = ModelCallFacts.model_construct(**malformed_values)
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(client, verified, malformed, request)

    assert denied.value.reason_code == "invalid_call_facts"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_privately_derives_distinct_full_call_scopes() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    base = _gateway_facts(verified, request)
    variants = (
        base,
        base.model_copy(update={"job_id": "job-2"}),
        base.model_copy(update={"stage": "gap"}),
        base.model_copy(update={"attempt": 2}),
        base.model_copy(update={"input_digest": "c" * 64}),
    )
    for facts in variants:
        _run_gateway_call(client, verified, facts, request)
    changed_prompt = ModelCallRequest(
        content=request.content,
        rendered_prompt=b"another raw prompt",
    )
    _run_gateway_call(
        client,
        verified,
        _gateway_facts(verified, changed_prompt),
        changed_prompt,
    )

    scope_hashes = {receipt.call_scope_hash for receipt in sink.receipts}
    assert len(scope_hashes) == len(sink.receipts) == 6
    for receipt in sink.receipts:
        assert receipt.permit_view is not None
        assert receipt.call_scope_hash == receipt.permit_view.call_scope_hash


def test_pwb4_gateway_scope_includes_full_verified_binding() -> None:
    original = _verified()
    alternate = _alternate_verified(
        manifest_hash="0" * 64,
        template_lock_hash="1" * 64,
        clean_integration_sha="0" * 40,
    )
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    _run_gateway_call(client, original, _gateway_facts(original, request), request)
    _run_gateway_call(client, alternate, _gateway_facts(alternate, request), request)

    assert len(sink.receipts) == 2
    assert sink.receipts[0].call_scope_hash != sink.receipts[1].call_scope_hash
    assert (
        sink.receipts[0].verified_binding_digest
        != sink.receipts[1].verified_binding_digest
    )


@pytest.mark.parametrize(
    "transport_identity",
    [
        _identity().model_copy(update={"provider": "other-provider"}),
        _identity("qwen3.6-other-20260715"),
        _identity(role="gap"),
        _identity().model_copy(update={"policy_version": "other-policy"}),
        _identity("claude-opus"),
    ],
)
def test_pwb4_gateway_factory_rejects_wrong_bound_transport_identity(
    transport_identity: ModelIdentity,
) -> None:
    sink = _CountingReceiptSink()

    with pytest.raises(ModelGatewayDenied) as denied:
        _build_test_gateway(
            composition=_composition(),
            transport_identity=transport_identity,
            receipt_sink=sink,
        )

    assert denied.value.reason_code == "invalid_transport_identity"
    assert sink.receipts == []


def test_pwb4_gateway_wrong_bound_transport_family_is_zero_call() -> None:
    sink = _CountingReceiptSink()
    wrong_family = _identity().model_copy(update={"family": "qwen-vl"})

    with pytest.raises(ModelGatewayDenied) as denied:
        _build_test_gateway(
            composition=_composition(),
            transport_identity=wrong_family,
            receipt_sink=sink,
        )

    assert denied.value.reason_code == "invalid_transport_identity"
    assert sink.receipts == []


def test_pwb4_gateway_bound_transport_is_opaque_and_nontransferable() -> None:
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    state = gateway_module._get_gateway_state(client)

    assert state is not None
    binding = state.transport_binding
    assert "_BoundModelTransport" not in model_policy_package.__all__
    assert not hasattr(model_policy_package, "_BoundModelTransport")
    with pytest.raises(TypeError):
        copy.copy(binding)
    with pytest.raises(TypeError):
        copy.deepcopy(binding)
    with pytest.raises(TypeError):
        pickle.dumps(binding)
    forged = object.__new__(gateway_module._BoundModelTransport)
    assert gateway_module._bound_transport_snapshot(forged) is None


def test_pwb4_gateway_executor_is_opaque_and_retained_only_by_live_gateway() -> None:
    composition = _composition()
    executor = gateway_module._issue_test_model_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
    )
    sink = _CountingReceiptSink()
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )
    executor_ref = weakref.ref(executor)

    with pytest.raises(TypeError):
        copy.copy(executor)
    with pytest.raises(TypeError):
        copy.deepcopy(executor)
    with pytest.raises(TypeError):
        pickle.dumps(executor)
    del executor
    gc.collect()

    assert executor_ref() is not None
    verified = _verified()
    request = _gateway_request()
    assert (
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )
        == "weak-result"
    )

    del client
    gc.collect()
    assert executor_ref() is None


@pytest.mark.parametrize("invalid_dependency", ["sync_transport", "async_sink"])
def test_pwb4_gateway_factory_rejects_wrong_dependency_execution_model(
    invalid_dependency: str,
) -> None:
    class _SyncTransport:
        __slots__ = ("__weakref__",)

        def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            del identity, request
            return "deferred"

    class _AsyncSink:
        records = 0

        async def record(self, receipt: PolicyReceipt, /) -> None:
            del receipt
            type(self).records += 1

    class _AsyncTransport:
        __slots__ = ("__weakref__",)

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            del identity, request
            return "unused"

    transport: object = (
        _SyncTransport()
        if invalid_dependency == "sync_transport"
        else _AsyncTransport()
    )
    sink: object = (
        _AsyncSink()
        if invalid_dependency == "async_sink"
        else _CountingReceiptSink()
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _build_raw_arbitrary_gateway(
            composition=_composition(),
            transport=transport,
            transport_identity=_identity(),
            receipt_sink=sink,
    )

    assert denied.value.reason_code == "invalid_gateway"
    assert _AsyncSink.records == 0


def test_pwb4_gateway_transport_code_mutation_before_use_is_zero_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def strong_call(
        self: object,
        identity: ModelIdentity,
        request: ModelCallRequest,
        /,
    ) -> object:
        del self, identity, request
        return "strong"

    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    adapter_type = gateway_module._CanonicalModelTransportAdapter
    original_code = adapter_type.call.__code__

    def mutate_code() -> datetime:
        adapter_type.call.__code__ = strong_call.__code__
        return datetime.now(UTC)

    monkeypatch.setattr(gateway_module, "_utc_now", mutate_code)
    try:
        with pytest.raises(ModelGatewayDenied):
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        adapter_type.call.__code__ = original_code

    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_sink_advancing_clock_to_expiry_prevents_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [datetime.now(UTC)]

    class _AdvancingSink(_CountingReceiptSink):
        def __init__(self, expires_at: datetime, clock: list[datetime]) -> None:
            _CountingReceiptSink.__init__(self)
            self.expires_at = expires_at
            self.clock = clock

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            self.clock[0] = self.expires_at

    verified = _verified()
    request = _gateway_request()
    sink = _AdvancingSink(verified.binding.actual_expires_at, clock)
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    monkeypatch.setattr(gateway_module, "_utc_now", lambda: clock[0])

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_clock_crossing_expiry_during_authority_snapshot_is_zero_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [datetime.now(UTC)]
    digest_calls = 0
    original_digest = policy_module._approved_keys_digest

    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    def advance_during_second_snapshot(keys: frozenset[object]) -> str:
        nonlocal digest_calls
        digest_calls += 1
        if digest_calls == 2:
            clock[0] = verified.binding.actual_expires_at
        return original_digest(keys)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_module, "_utc_now", lambda: clock[0])
    monkeypatch.setattr(
        gateway_module,
        "_approved_keys_digest",
        advance_during_second_snapshot,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


@pytest.mark.parametrize("authority", ["gateway", "composition", "transport"])
def test_pwb4_gateway_sink_revoking_authority_prevents_transport(
    authority: str,
) -> None:
    class _RevokingSink(_CountingReceiptSink):
        def __init__(self, authority: str) -> None:
            _CountingReceiptSink.__init__(self)
            self.authority = authority

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            if self.authority == "gateway":
                gateway_module._reset_gateway_authority_after_fork()
            elif self.authority == "composition":
                composition_module._reset_composition_authority_after_fork()
            else:
                gateway_module._reset_bound_transport_authority_after_fork()

    verified = _verified()
    request = _gateway_request()
    sink = _RevokingSink(authority)
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_sink_mutating_transport_code_prevents_transport() -> None:
    async def strong_call(
        self: object,
        identity: ModelIdentity,
        request: ModelCallRequest,
        /,
    ) -> object:
        del self, identity, request
        return "strong"

    class _MutatingSink(_CountingReceiptSink):
        def __init__(self, transport_type: type[object], code: object) -> None:
            _CountingReceiptSink.__init__(self)
            self.transport_type = transport_type
            self.code = code

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            self.transport_type.call.__code__ = self.code  # type: ignore[attr-defined]

    adapter_type = gateway_module._CanonicalModelTransportAdapter
    original_code = adapter_type.call.__code__
    verified = _verified()
    request = _gateway_request()
    sink = _MutatingSink(adapter_type, strong_call.__code__)
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    try:
        with pytest.raises(ModelGatewayDenied):
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        adapter_type.call.__code__ = original_code

    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1


def test_pwb4_gateway_sink_rebinding_bound_snapshot_to_same_identity_executor_is_zero_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SnapshotRebindingSink(_CountingReceiptSink):
        def __init__(
            self,
            patcher: pytest.MonkeyPatch,
            replacement: object,
        ) -> None:
            _CountingReceiptSink.__init__(self)
            self.patcher = patcher
            self.replacement = replacement

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            self.patcher.setattr(
                gateway_module,
                "_bound_transport_snapshot",
                self.replacement,
            )

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    weak_executor = gateway_module._issue_test_model_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
    )
    replacement_executor = gateway_module._issue_test_model_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
    )

    def replacement_snapshot(_binding: object) -> object:
        return gateway_module._consume_executor(replacement_executor)

    sink = _SnapshotRebindingSink(monkeypatch, replacement_snapshot)
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=weak_executor,
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert gateway_module._test_executor_terminal_observations(weak_executor) == ()
    assert gateway_module._test_executor_terminal_observations(replacement_executor) == ()
    assert len(sink.receipts) == 1


def test_pwb4_gateway_sink_mutating_own_code_prevents_transport() -> None:
    def replacement_record(self: object, _receipt: PolicyReceipt, /) -> None:
        type(self).replacement_calls += 1  # type: ignore[attr-defined]

    class _SelfMutatingSink(_CountingReceiptSink):
        replacement_calls = 0

        def __init__(self, replacement_code: object) -> None:
            _CountingReceiptSink.__init__(self)
            self.replacement_code = replacement_code

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            type(self).record.__code__ = self.replacement_code  # type: ignore[assignment]

    original_code = _SelfMutatingSink.record.__code__
    verified = _verified()
    request = _gateway_request()
    sink = _SelfMutatingSink(replacement_record.__code__)
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    try:
        with pytest.raises(ModelGatewayDenied):
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        _SelfMutatingSink.record.__code__ = original_code

    assert _gateway_executor_terminal_observations(client) == []
    assert _SelfMutatingSink.replacement_calls == 0
    assert len(sink.receipts) == 1


def test_pwb4_gateway_sink_code_mutated_before_call_is_zero_transport() -> None:
    class _MutableSink(_CountingReceiptSink):
        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)

    def replacement_record(self: object, _receipt: PolicyReceipt, /) -> None:
        type(self).replacement_calls += 1  # type: ignore[attr-defined]

    _MutableSink.replacement_calls = 0  # type: ignore[attr-defined]
    original_code = _MutableSink.record.__code__
    verified = _verified()
    request = _gateway_request()
    sink = _MutableSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    _MutableSink.record.__code__ = replacement_record.__code__

    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        _MutableSink.record.__code__ = original_code

    assert denied.value.reason_code == "invalid_gateway"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []
    assert _MutableSink.replacement_calls == 0  # type: ignore[attr-defined]


async def _deferred_transport_result() -> object:
    return "deferred-result"


def test_pwb4_gateway_canonical_async_executor_runs_once() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )
    async def invoke() -> object:
        expected_loop = asyncio.get_running_loop()
        expected_thread = threading.get_ident()
        result = await client.call(
            verified,
            _gateway_facts(verified, request),
            request,
        )
        observations = _gateway_executor_terminal_details(client)
        assert len(observations) == 1
        assert observations[0][2] is expected_loop
        assert observations[0][3] == expected_thread
        return result

    result = asyncio.run(invoke())

    assert result == "weak-result"
    assert _gateway_executor_terminal_observations(client) == [(_identity(), request)]
    assert len(sink.receipts) == 1


def test_pwb4_gateway_sealed_stateful_model_client_bridge_maps_utf8_on_same_loop() -> None:
    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="api-key-secret-sentinel",
    )
    sink = _CountingReceiptSink()
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )
    async def invoke() -> object:
        return await client.call(verified, _gateway_facts(verified, request), request)

    result = asyncio.run(invoke())

    assert result == "stateful-result"
    assert gateway_module._test_stateful_target_calls(target) == (
        (
            request.rendered_prompt.decode("utf-8"),
            request.content.decode("utf-8"),
        ),
    )
    observations = gateway_module._test_stateful_target_observations(target)
    assert len(observations) == 1
    assert observations[0][2].is_closed()
    assert observations[0][3] == threading.get_ident()
    assert gateway_module._test_executor_terminal_observations(executor) == (
        (_identity(), request),
    )
    assert len(sink.receipts) == 1
    assert "api-key-secret-sentinel" not in sink.receipts[0].model_dump_json()


def test_pwb4_gateway_sink_cannot_mutate_stateful_target_route() -> None:
    class _RouteMutatingSink(_CountingReceiptSink):
        def __init__(self, target: Any) -> None:
            _CountingReceiptSink.__init__(self)
            self.target = target

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            self.target.endpoint = "https://strong.example.test"
            self.target.model = "strong-model"

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
    )
    sink = _RouteMutatingSink(target)
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client, verified, _gateway_facts(verified, request), request
        )

    assert denied.value.reason_code == "receipt_sink_failure"
    assert gateway_module._test_stateful_target_calls(target) == ()
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_json_helper_rebind_cannot_redirect_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RedirectingJson:
        @staticmethod
        def loads(_value: object) -> dict[str, str]:
            return {"result": "strong-result"}

    class _JsonHelperRebindingSink(_CountingReceiptSink):
        def __init__(
            self,
            patcher: pytest.MonkeyPatch,
            redirecting_json: type[object],
        ) -> None:
            _CountingReceiptSink.__init__(self)
            self.patcher = patcher
            self.redirecting_json = redirecting_json

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            self.patcher.setattr(
                gateway_module,
                "json",
                self.redirecting_json,
            )

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
        result="weak-result",
    )
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    sink = _JsonHelperRebindingSink(monkeypatch, _RedirectingJson)
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    result = _run_gateway_call(
        client, verified, _gateway_facts(verified, request), request
    )

    assert result == "weak-result"
    assert gateway_module._test_stateful_target_calls(target) == (
        (
            request.rendered_prompt.decode("utf-8"),
            request.content.decode("utf-8"),
        ),
    )
    assert len(sink.receipts) == 1


@pytest.mark.parametrize("helper_name", ["target_snapshot", "target_invoke"])
def test_pwb4_gateway_executor_closure_helper_rebind_is_zero_call(
    helper_name: str,
) -> None:
    class _ClosureHelperRebindingSink(_CountingReceiptSink):
        def __init__(
            self,
            owner: Any,
            selected_helper: str,
            replacement: Any,
        ) -> None:
            _CountingReceiptSink.__init__(self)
            self.owner = owner
            self.selected_helper = selected_helper
            self.replacement = replacement
            self.mutated_cell: Any = None
            self.original: Any = None

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            closure = self.owner.__closure__
            if closure is None:
                raise AssertionError("executor consumer must close over its helpers")
            cells = dict(zip(self.owner.__code__.co_freevars, closure, strict=True))
            self.mutated_cell = cells[self.selected_helper]
            self.original = self.mutated_cell.cell_contents
            self.mutated_cell.cell_contents = self.replacement

        def restore(self) -> None:
            if self.mutated_cell is not None:
                self.mutated_cell.cell_contents = self.original

    async def redirected_invoke(
        _target: object,
        _system: str,
        _user: str,
    ) -> str:
        return "redirected-result"

    original_snapshot = gateway_module._stateful_target_snapshot

    def equivalent_snapshot(target: object) -> object:
        return original_snapshot(target)

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
        result="weak-result",
    )
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    replacement = (
        equivalent_snapshot
        if helper_name == "target_snapshot"
        else redirected_invoke
    )
    consume = gateway_module._consume_executor
    consume_closure = consume.__closure__
    assert consume_closure is not None
    consume_cells = dict(
        zip(consume.__code__.co_freevars, consume_closure, strict=True)
    )
    mutation_owner = (
        consume
        if helper_name in consume_cells
        else consume_cells["validate_locked"].cell_contents
    )
    sink = _ClosureHelperRebindingSink(
        mutation_owner,
        helper_name,
        replacement,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        sink.restore()

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert gateway_module._test_executor_terminal_observations(executor) == ()
    assert gateway_module._test_stateful_target_calls(target) == ()
    assert len(sink.receipts) == 1


def test_pwb4_gateway_executor_helper_dependency_rebind_is_zero_call() -> None:
    class _HelperDependencyRebindingSink(_CountingReceiptSink):
        def __init__(self, helper: Any, replacement: Any) -> None:
            _CountingReceiptSink.__init__(self)
            self.helper = helper
            self.replacement = replacement
            self.mutated_cell: Any = None
            self.original: Any = None

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            closure = self.helper.__closure__
            if closure is None:
                raise AssertionError("target helper must close over dependencies")
            cells = dict(zip(self.helper.__code__.co_freevars, closure, strict=True))
            self.mutated_cell = cells["json_loads"]
            self.original = self.mutated_cell.cell_contents
            self.mutated_cell.cell_contents = self.replacement

        def restore(self) -> None:
            if self.mutated_cell is not None:
                self.mutated_cell.cell_contents = self.original

    def redirected_loads(_value: object) -> dict[str, str]:
        return {"result": "redirected-result"}

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
        result="weak-result",
    )
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    sink = _HelperDependencyRebindingSink(
        gateway_module._invoke_stateful_target,
        redirected_loads,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        sink.restore()

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert gateway_module._test_executor_terminal_observations(executor) == ()
    assert gateway_module._test_stateful_target_calls(target) == ()
    assert len(sink.receipts) == 1


def test_pwb4_gateway_second_thread_route_mutation_after_validation_is_ignored() -> None:
    validated = threading.Event()
    mutated = threading.Event()
    mutation_blocked: list[bool] = []

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
        result="weak-result",
    )
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    assert gateway_module._set_stateful_target_barrier_for_test(
        target,
        validated,
        mutated,
    )
    sink = _CountingReceiptSink()
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    def mutate_route() -> None:
        try:
            assert validated.wait(timeout=5)
            target.result = "strong-result"  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            mutation_blocked.append(True)
        finally:
            mutated.set()

    mutator = threading.Thread(target=mutate_route)
    mutator.start()
    result = _run_gateway_call(
        client, verified, _gateway_facts(verified, request), request
    )
    mutator.join(timeout=5)

    assert not mutator.is_alive()
    assert mutation_blocked == [True]
    assert result == "weak-result"
    assert gateway_module._test_stateful_target_calls(target) == (
        (
            request.rendered_prompt.decode("utf-8"),
            request.content.decode("utf-8"),
        ),
    )
    assert len(sink.receipts) == 1


def test_pwb4_gateway_stateful_test_issuer_rejects_custom_target_shape() -> None:
    class _CustomTarget:
        async def complete(self, system: str, user: str) -> str:
            return f"{system}:{user}"

    with pytest.raises(ModelGatewayDenied) as denied:
        gateway_module._issue_stateful_model_client_executor_for_test(
            composition=_composition(),
            transport_identity=_identity(),
            target=_CustomTarget(),
        )

    assert denied.value.reason_code == "invalid_gateway"


def test_pwb4_gateway_stateful_test_issuer_rejects_model_identity_mismatch() -> None:
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model="strong-or-other-model",
        credential="weak-credential",
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        gateway_module._issue_stateful_model_client_executor_for_test(
            composition=_composition(),
            transport_identity=_identity(),
            target=target,
        )

    assert denied.value.reason_code == "invalid_gateway"
    assert gateway_module._test_stateful_target_calls(target) == ()


def test_pwb4_gateway_stateful_target_exposes_no_mutable_route_fields() -> None:
    identity = _identity()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=identity.deployment_id,
        credential="weak-credential",
    )

    for field in ("endpoint", "model", "credential", "result"):
        with pytest.raises((AttributeError, TypeError)):
            setattr(target, field, "replacement")

    assert gateway_module._test_stateful_target_calls(target) == ()


def test_pwb4_gateway_sink_mutating_stateful_complete_code_is_zero_target_call() -> None:
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
    )
    target_type = type(target)
    original_code = target_type.complete.__code__  # type: ignore[attr-defined]

    strong_result = "strong-result"

    async def replacement_complete(self: object, system: str, user: str) -> str:
        del self, system, user
        return strong_result

    class _TargetCodeMutatingSink(_CountingReceiptSink):
        def __init__(self, target_type: type[object], code: object) -> None:
            _CountingReceiptSink.__init__(self)
            self.target_type = target_type
            self.code = code

        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            self.target_type.complete.__code__ = self.code  # type: ignore[attr-defined]

    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    sink = _TargetCodeMutatingSink(target_type, replacement_complete.__code__)
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _run_gateway_call(
                client, verified, _gateway_facts(verified, request), request
            )
    finally:
        target_type.complete.__code__ = original_code  # type: ignore[attr-defined]

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert gateway_module._test_stateful_target_calls(target) == ()
    assert len(sink.receipts) == 1


@pytest.mark.parametrize("field", ["content", "rendered_prompt"])
def test_pwb4_gateway_request_rejects_non_utf8_before_authority(
    field: str,
) -> None:
    values = {
        "content": b"valid-user",
        "rendered_prompt": b"valid-system",
    }
    values[field] = b"\xff"

    with pytest.raises(ValidationError):
        ModelCallRequest.model_validate(values)

    malformed = ModelCallRequest.model_construct(
        content=values["content"],
        rendered_prompt=values["rendered_prompt"],
    )
    verified = _verified()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        _run_gateway_call(
            client,
            verified,
            _gateway_facts(verified, malformed),
            malformed,
        )

    assert denied.value.reason_code == "invalid_call_request"
    assert _gateway_executor_terminal_observations(client) == []
    assert sink.receipts == []


def test_pwb4_gateway_factory_rejects_regular_function_returning_coroutine() -> None:
    class _DeferredTransport:
        __slots__ = ("__weakref__",)

        def call(
            self,
            _identity: ModelIdentity,
            _request: ModelCallRequest,
            /,
        ) -> object:
            return _deferred_transport_result()

    sink = _CountingReceiptSink()
    with pytest.raises(ModelGatewayDenied) as denied:
        _build_raw_arbitrary_gateway(
            composition=_composition(),
            transport=_DeferredTransport(),
            transport_identity=_identity(),
            receipt_sink=sink,
        )

    assert denied.value.reason_code == "invalid_gateway"
    assert sink.receipts == []


def test_pwb4_gateway_rejects_and_closes_nested_transport_awaitable() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode="nested",
    )

    with pytest.raises(ModelTransportError):
        asyncio.run(
            client.call(verified, _gateway_facts(verified, request), request)
        )

    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1


@pytest.mark.parametrize(
    ("mode", "frame_attribute"),
    [
        ("generator", "gi_frame"),
        ("async-generator", "ag_frame"),
    ],
)
def test_pwb4_gateway_rejects_and_closes_deferred_generator_results(
    mode: str,
    frame_attribute: str,
    recwarn: pytest.WarningsRecorder,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode=mode,
    )

    with pytest.raises(ModelTransportError):
        asyncio.run(
            client.call(verified, _gateway_facts(verified, request), request)
        )

    executor = _TEST_CLIENT_EXECUTORS[client]
    deferred = gateway_module._test_executor_deferred_results(executor)
    assert len(deferred) == 1
    assert getattr(deferred[0], frame_attribute) is None
    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"
    gc.collect()
    assert list(recwarn) == []


@pytest.mark.parametrize("mode", ["bytes", "object"])
def test_pwb4_gateway_accepts_only_exact_str_terminal_values(mode: str) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode=mode,
    )

    with pytest.raises(ModelTransportError):
        asyncio.run(
            client.call(verified, _gateway_facts(verified, request), request)
        )

    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_rejects_bare_awaitable_without_executing_it(
    recwarn: pytest.WarningsRecorder,
) -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode="bare-awaitable",
    )

    with pytest.raises(ModelTransportError):
        asyncio.run(
            client.call(verified, _gateway_facts(verified, request), request)
        )

    executor = _TEST_CLIENT_EXECUTORS[client]
    deferred = gateway_module._test_executor_deferred_results(executor)
    assert len(deferred) == 1
    assert cast(Any, deferred[0]).deferred_calls == 0
    assert gateway_module._test_executor_terminal_observations(executor) == ()
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"
    gc.collect()
    assert list(recwarn) == []


def test_pwb4_gateway_cleanup_cancellation_propagates_without_observation() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode="slow-aclose",
    )
    executor = _TEST_CLIENT_EXECUTORS[client]

    async def cancel_during_cleanup() -> None:
        call = asyncio.create_task(
            client.call(verified, _gateway_facts(verified, request), request)
        )
        deferred: tuple[object, ...] = ()
        while not deferred:
            await asyncio.sleep(0)
            deferred = gateway_module._test_executor_deferred_results(executor)
        cleanup_target = cast(Any, deferred[0])
        await cleanup_target.cleanup_entered.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert call.cancelled()

    asyncio.run(cancel_during_cleanup())

    assert gateway_module._test_executor_terminal_observations(executor) == ()
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_sync_sink_returning_awaitable_is_receipt_failure() -> None:
    class _DeferredSink:
        def __init__(self) -> None:
            self.receipts: list[PolicyReceipt] = []

        def record(self, receipt: PolicyReceipt, /) -> object:
            self.receipts.append(receipt)
            return _deferred_transport_result()

    verified = _verified()
    request = _gateway_request()
    sink = _DeferredSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        asyncio.run(
            client.call(verified, _gateway_facts(verified, request), request)
        )

    assert denied.value.reason_code == "receipt_sink_failure"
    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.receipts) == 1


def test_pwb4_gateway_sync_sink_returning_generator_closes_frame() -> None:
    class _GeneratorSink:
        def __init__(self) -> None:
            self.results: list[Generator[None, None, None]] = []

        def record(self, receipt: PolicyReceipt, /) -> object:
            del receipt

            def deferred() -> Generator[None, None, None]:
                yield

            result = deferred()
            self.results.append(result)
            return result

    verified = _verified()
    request = _gateway_request()
    sink = _GeneratorSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
    )

    with pytest.raises(ModelGatewayDenied) as denied:
        asyncio.run(client.call(verified, _gateway_facts(verified, request), request))

    assert denied.value.reason_code == "receipt_sink_failure"
    assert _gateway_executor_terminal_observations(client) == []
    assert len(sink.results) == 1
    assert cast(Any, sink.results[0]).gi_frame is None


def test_pwb4_gateway_propagates_transport_cancellation_without_retry() -> None:
    verified = _verified()
    request = _gateway_request()
    sink = _CountingReceiptSink()
    client = _build_test_gateway(
        composition=_composition(),
        transport_identity=_identity(),
        receipt_sink=sink,
        mode="cancel",
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            client.call(verified, _gateway_facts(verified, request), request)
        )

    assert _gateway_executor_terminal_observations(client) == [(_identity(), request)]
    assert len(sink.receipts) == 1


def test_pwb4_gateway_final_target_revocation_is_typed_zero_observation() -> None:
    verified = _verified()
    request = _gateway_request()
    composition = _composition()
    target = gateway_module._build_stateful_model_client_target_for_test(
        endpoint="https://weak.example.test",
        model=_identity().deployment_id,
        credential="weak-credential",
    )
    executor = gateway_module._issue_stateful_model_client_executor_for_test(
        composition=composition,
        transport_identity=_identity(),
        target=target,
    )
    sink = _CountingReceiptSink()
    client = _raw_build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )

    async def invoke_after_revocation() -> None:
        entered = asyncio.Event()
        resume = asyncio.Event()
        assert gateway_module._set_stateful_target_precheck_barrier_for_test(
            target,
            entered,
            resume,
        )
        call = asyncio.create_task(
            client.call(verified, _gateway_facts(verified, request), request)
        )
        await entered.wait()
        gateway_module._reset_stateful_target_authority_after_fork()
        resume.set()
        await call

    with pytest.raises(ModelGatewayDenied) as denied:
        asyncio.run(invoke_after_revocation())

    assert denied.value.reason_code == "authority_revalidation_failed"
    assert gateway_module._test_executor_terminal_observations(executor) == ()
    assert gateway_module._test_stateful_target_calls(target) == ()
    assert len(sink.receipts) == 1
    assert sink.receipts[0].decision == "ALLOW"


def test_pwb4_gateway_factory_rejects_noncanonical_mutable_adapter_shape() -> None:
    class _MutableRouteTransport:
        __slots__ = ("route", "__weakref__")
        calls = 0

        def __init__(self) -> None:
            self.route = "weak"

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            type(self).calls += 1
            del identity, request
            return self.route

    transport = _MutableRouteTransport()
    sink = _CountingReceiptSink()

    with pytest.raises(ModelGatewayDenied) as denied:
        _build_raw_arbitrary_gateway(
            composition=_composition(),
            transport=transport,
            transport_identity=_identity(),
            receipt_sink=sink,
        )

    transport.route = "strong"
    assert denied.value.reason_code == "invalid_gateway"
    assert _MutableRouteTransport.calls == 0
    assert sink.receipts == []


async def _weak_async_route(
    _identity: ModelIdentity,
    _request: ModelCallRequest,
) -> object:
    return "weak-route"


async def _strong_async_route(
    _identity: ModelIdentity,
    _request: ModelCallRequest,
) -> object:
    return "strong-route"


_ASYNC_ROUTE_DELEGATE = _weak_async_route


def test_pwb4_gateway_rejects_noncanonical_adapter_with_module_global_route() -> None:
    class _GlobalRouteTransport:
        __slots__ = ("__weakref__",)
        calls = 0

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            type(self).calls += 1
            return await _ASYNC_ROUTE_DELEGATE(identity, request)

    class _RouteMutatingSink(_CountingReceiptSink):
        def record(self, receipt: PolicyReceipt, /) -> None:
            global _ASYNC_ROUTE_DELEGATE
            _CountingReceiptSink.record(self, receipt)
            _ASYNC_ROUTE_DELEGATE = _strong_async_route

    global _ASYNC_ROUTE_DELEGATE
    _ASYNC_ROUTE_DELEGATE = _weak_async_route
    transport = _GlobalRouteTransport()
    sink = _RouteMutatingSink()
    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _build_raw_arbitrary_gateway(
                composition=_composition(),
                transport=transport,
                transport_identity=_identity(),
                receipt_sink=sink,
            )
    finally:
        _ASYNC_ROUTE_DELEGATE = _weak_async_route

    assert denied.value.reason_code == "invalid_gateway"
    assert _GlobalRouteTransport.calls == 0
    assert sink.receipts == []


def test_pwb4_gateway_rejects_noncanonical_adapter_with_builtin_route() -> None:
    class _BuiltinRouteTransport:
        __slots__ = ("__weakref__",)
        calls = 0

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            type(self).calls += 1
            return await _pwb4_builtin_route(  # type: ignore[name-defined]  # noqa: F821
                identity, request
            )

    class _BuiltinMutatingSink(_CountingReceiptSink):
        def record(self, receipt: PolicyReceipt, /) -> None:
            _CountingReceiptSink.record(self, receipt)
            vars(builtins)["_pwb4_builtin_route"] = _strong_async_route

    vars(builtins)["_pwb4_builtin_route"] = _weak_async_route
    transport = _BuiltinRouteTransport()
    sink = _BuiltinMutatingSink()
    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _build_raw_arbitrary_gateway(
                composition=_composition(),
                transport=transport,
                transport_identity=_identity(),
                receipt_sink=sink,
            )
    finally:
        vars(builtins).pop("_pwb4_builtin_route", None)

    assert denied.value.reason_code == "invalid_gateway"
    assert _BuiltinRouteTransport.calls == 0
    assert sink.receipts == []


@pytest.mark.parametrize("defaults_kind", ["defaults", "kwdefaults"])
def test_pwb4_gateway_rejects_noncanonical_adapter_with_function_defaults(
    defaults_kind: str,
) -> None:
    async def mutable_route_with_defaults(
        _identity: ModelIdentity,
        _request: ModelCallRequest,
        route: str = "weak",
    ) -> object:
        return route

    async def mutable_route_with_kwdefaults(
        _identity: ModelIdentity,
        _request: ModelCallRequest,
        *,
        route: str = "weak",
    ) -> object:
        return route

    mutable_route = (
        mutable_route_with_defaults
        if defaults_kind == "defaults"
        else mutable_route_with_kwdefaults
    )

    globals()["_PWB4_DEFAULTED_ROUTE"] = mutable_route

    class _DefaultedRouteTransport:
        __slots__ = ("__weakref__",)

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            return await _PWB4_DEFAULTED_ROUTE(  # type: ignore[name-defined]  # noqa: F821
                identity, request
            )

    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _build_raw_arbitrary_gateway(
                composition=_composition(),
                transport=_DefaultedRouteTransport(),
                transport_identity=_identity(),
                receipt_sink=_CountingReceiptSink(),
            )
    finally:
        globals().pop("_PWB4_DEFAULTED_ROUTE", None)

    assert denied.value.reason_code == "invalid_gateway"


def test_pwb4_gateway_rejects_noncanonical_adapter_with_type_global_route() -> None:
    class _MutableRouteType:
        route = "weak"

    globals()["_PWB4_ROUTE_TYPE"] = _MutableRouteType

    class _TypeRouteTransport:
        __slots__ = ("__weakref__",)
        calls = 0

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            type(self).calls += 1
            del identity, request
            return _PWB4_ROUTE_TYPE.route  # type: ignore[name-defined]  # noqa: F821

    transport = _TypeRouteTransport()
    try:
        with pytest.raises(ModelGatewayDenied) as denied:
            _build_raw_arbitrary_gateway(
                composition=_composition(),
                transport=transport,
                transport_identity=_identity(),
                receipt_sink=_CountingReceiptSink(),
            )
    finally:
        globals().pop("_PWB4_ROUTE_TYPE", None)

    assert denied.value.reason_code == "invalid_gateway"
    assert _TypeRouteTransport.calls == 0


def test_pwb4_gateway_rejects_noncanonical_adapter_with_local_import() -> None:
    class _ImportingTransport:
        __slots__ = ("__weakref__",)

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            del identity, request
            import math

            return math.pi

    with pytest.raises(ModelGatewayDenied) as denied:
        _build_raw_arbitrary_gateway(
            composition=_composition(),
            transport=_ImportingTransport(),
            transport_identity=_identity(),
            receipt_sink=_CountingReceiptSink(),
        )

    assert denied.value.reason_code == "invalid_gateway"


_PWB4_INDIRECT_ROUTE = _weak_async_route
_PWB4_HELPER_ROUTE_KIND = "indirect_global"


async def _pwb4_indirect_route_helper(
    identity: ModelIdentity,
    request: ModelCallRequest,
) -> object:
    return await _PWB4_INDIRECT_ROUTE(identity, request)


async def _pwb4_attribute_route_helper(
    identity: ModelIdentity,
    request: ModelCallRequest,
) -> object:
    route = _pwb4_attribute_route_helper.__dict__["route"]
    return await route(identity, request)


async def _pwb4_import_route_helper(
    identity: ModelIdentity,
    request: ModelCallRequest,
) -> object:
    import builtins as runtime_builtins

    route = vars(runtime_builtins)["_pwb4_indirect_import_route"]
    return await route(identity, request)


@pytest.mark.parametrize(
    "route_kind",
    ["indirect_global", "helper_attribute", "helper_import"],
)
def test_pwb4_gateway_rejects_noncanonical_adapter_with_indirect_helper(
    route_kind: str,
) -> None:
    class _IndirectTransport:
        __slots__ = ("__weakref__",)
        calls = 0

        async def call(
            self,
            identity: ModelIdentity,
            request: ModelCallRequest,
            /,
        ) -> object:
            type(self).calls += 1
            if _PWB4_HELPER_ROUTE_KIND == "indirect_global":
                return await _pwb4_indirect_route_helper(identity, request)
            if _PWB4_HELPER_ROUTE_KIND == "helper_attribute":
                return await _pwb4_attribute_route_helper(identity, request)
            return await _pwb4_import_route_helper(identity, request)

    class _IndirectMutatingSink(_CountingReceiptSink):
        def record(self, receipt: PolicyReceipt, /) -> None:
            global _PWB4_INDIRECT_ROUTE
            _CountingReceiptSink.record(self, receipt)
            if _PWB4_HELPER_ROUTE_KIND == "indirect_global":
                _PWB4_INDIRECT_ROUTE = _strong_async_route
            elif _PWB4_HELPER_ROUTE_KIND == "helper_attribute":
                _pwb4_attribute_route_helper.__dict__["route"] = _strong_async_route
            else:
                vars(builtins)["_pwb4_indirect_import_route"] = _strong_async_route

    global _PWB4_HELPER_ROUTE_KIND, _PWB4_INDIRECT_ROUTE
    _PWB4_HELPER_ROUTE_KIND = route_kind
    _PWB4_INDIRECT_ROUTE = _weak_async_route
    _pwb4_attribute_route_helper.__dict__["route"] = _weak_async_route
    vars(builtins)["_pwb4_indirect_import_route"] = _weak_async_route
    verified = _verified()
    request = _gateway_request()
    transport = _IndirectTransport()
    sink = _IndirectMutatingSink()

    try:
        with pytest.raises(ModelGatewayDenied):
            client = _build_raw_arbitrary_gateway(
                composition=_composition(),
                transport=transport,
                transport_identity=_identity(),
                receipt_sink=sink,
            )
            asyncio.run(
                client.call(verified, _gateway_facts(verified, request), request)
            )
    finally:
        _PWB4_INDIRECT_ROUTE = _weak_async_route
        _pwb4_attribute_route_helper.__dict__["route"] = _weak_async_route
        vars(builtins).pop("_pwb4_indirect_import_route", None)

    assert _IndirectTransport.calls == 0
    assert sink.receipts == []

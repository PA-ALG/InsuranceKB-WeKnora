from __future__ import annotations

import copy
import json
import pickle
from datetime import UTC, datetime
from inspect import signature

import pytest
from pydantic import ValidationError

import insurance_harness.model_policy as model_policy_package
from insurance_harness.model_policy import (
    AdmissionBinding,
    AdmissionVerificationReceipt,
    AdmissionVerifier,
    IssuedModelPermit,
    ModelIdentity,
    ModelPermitView,
    ModelPolicyDenied,
    ProductionModelPolicy,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
)
from insurance_harness.model_policy.admission import (
    _is_issued_model_permit,
    _is_verified_admission,
    _issue_model_permit,
    _issue_verified_admission,
)


def _identity(
    deployment_id: str = "qwen3.6-prod-20260715",
    *,
    family: str = "qwen",
) -> ModelIdentity:
    return ModelIdentity(
        provider="bailian",
        deployment_id=deployment_id,
        family=family,
        role="extract",
        policy_version="pwb-v1",
    )


def _policy_for(*identities: ModelIdentity) -> ProductionModelPolicy:
    return ProductionModelPolicy(
        approved_identity_keys=frozenset(identity.identity_key for identity in identities)
    )


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


@pytest.mark.parametrize("deployment_id", ["claude-opus", "deepseek-v4"])
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
    assert denied.value.reason_code == "family_not_approved"


def test_pwb1_identity_model_is_frozen_extra_forbid_and_copy_revalidates() -> None:
    identity = _identity()

    with pytest.raises(ValidationError):
        identity.provider = "other"
    with pytest.raises(ValidationError):
        ModelIdentity.model_validate({**identity.model_dump(), "unexpected": "field"})


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
            "actual_expires_at": datetime(2026, 8, 1, tzinfo=UTC),
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
        call_scope_hash="e" * 64,
        expires_at=binding.actual_expires_at,
    )


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
    issued = _issue_model_permit(view, verified)

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
        _issue_model_permit(unapproved, verified)

from __future__ import annotations

import copy
import gc
import json
import pickle
import weakref
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from inspect import signature

import pytest
from pydantic import BaseModel, ValidationError

import insurance_harness.model_policy as model_policy_package
import insurance_harness.model_policy.admission as admission_module
import insurance_harness.model_policy.composition as composition_module
import insurance_harness.model_policy.policy as policy_module
from insurance_harness.model_policy import (
    AdmissionBinding,
    AdmissionPolicyDenied,
    AdmissionVerificationReceipt,
    AdmissionVerifier,
    IssuedModelPermit,
    ModelCallContext,
    ModelIdentity,
    ModelPermitView,
    ModelPolicyDenied,
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
    def __iter__(self) -> Iterator[tuple[str, str, str, str]]:
        raise RuntimeError("caller iterator failure")


@pytest.mark.parametrize(
    "keys",
    [
        {_MutableIdentityKey(_identity().identity_key)},
        {
            (
                _MutableIdentityPart("bailian"),
                "qwen3.6-prod-20260715",
                "extract",
                "pwb-v1",
            )
        },
        (_identity().identity_key, _identity().identity_key),
        (("bailian", "qwen3.6-prod-20260715", "extract"),),
        (("", "qwen3.6-prod-20260715", "extract", "pwb-v1"),),
        ((" bailian", "qwen3.6-prod-20260715", "extract", "pwb-v1"),),
        (("bailian", "qwen3.6-prod-20260715", "admin", "pwb-v1"),),
        _ExplodingIdentityKeys(),
    ],
)
def test_pwb1_policy_and_composition_reject_noncanonical_allowlist_keys(
    keys: object,
) -> None:
    with pytest.raises(ValueError, match="invalid approved identity keys"):
        ProductionModelPolicy(keys)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid approved identity keys"):
        _build_production_model_composition(
            approved_identity_keys=keys,  # type: ignore[arg-type]
        )


def test_pwb1_allowlist_snapshot_does_not_retain_caller_container() -> None:
    identity = _identity()
    keys = [identity.identity_key]
    policy = ProductionModelPolicy(keys)
    composition = _build_production_model_composition(approved_identity_keys=keys)
    digest = policy.policy_snapshot_digest
    verified = _verified()
    context = _call_context(verified)

    keys.clear()

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
    assert denied.value.reason_code == "invalid_identity"


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
    identity = _identity()
    return _build_production_model_composition(
        approved_identity_keys=frozenset({identity.identity_key}),
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
    assert tuple(signature(_build_production_model_composition).parameters) == (
        "approved_identity_keys",
    )
    with pytest.raises(TypeError):
        _build_production_model_composition(  # type: ignore[call-arg]
            canonical_verifiers={
                ("attacker-purpose", "attacker-schema"): _CanonicalTestVerifier()
            },
            approved_identity_keys=frozenset({_identity().identity_key}),
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
    context = _call_context(verified).model_copy(update={"identity": gap_identity})

    decision = _build_production_model_composition(
        approved_identity_keys=frozenset({gap_identity.identity_key})
    )._evaluate_for_guard(verified, context)

    assert not _decision_authorizes_call(decision, verified, context)
    assert decision.receipt.reason_code == "identity_not_admission_approved"


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
    composition = _build_production_model_composition(approved_identity_keys=frozenset())
    assert composition._evaluate_for_guard(verified, context).receipt.decision == "DENY"

    replacement = _policy_for(context.identity)
    try:
        object.__setattr__(composition, "_policy", replacement)
    except AttributeError:
        pass
    decision = composition._evaluate_for_guard(verified, context)
    provider_calls = int(_decision_authorizes_call(decision, verified, context))
    assert provider_calls == 0

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

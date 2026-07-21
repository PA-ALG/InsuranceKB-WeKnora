"""020 D1.1a/D1.1d: typed run admission and detached approval contracts."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from insurance_harness.goldenset.admission_models import (
    AdmissionDerivedState,
    AdmissionObservation,
    ApprovalDomain,
    ApprovalVerificationError,
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    BudgetPlan,
    HistoricalProvenance,
    ModelRolePlan,
    PendingModelRolePlan,
    PendingProductInputPlan,
    ProductInputPlan,
    ProvenanceApprovalEntry,
    ProvenanceApprovalEnvelope,
    ProvenanceApprovalPayload,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
    canonical_json_bytes,
    plan_payload_hash,
    verify_approval_envelope,
)

_NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
_PLAN_HASH = "a" * 64


def _role(*, revision: str | None = "revision-2026-07-19") -> ModelRolePlan:
    return ModelRolePlan(
        provider="provider-a",
        model_id="model-1",
        expected_model_revision=revision,
        immutable_deployment_id=None,
        protocol="https",
        base_url="https://provider.example",
        provider_policy="provider-a-metadata-v1",
        credential_env_name="PROVIDER_A_API_KEY",
    )


def _plan_payload(**overrides: object) -> RunAdmissionPlanPayload:
    values: dict[str, object] = {
        "run_identity": "gs-v0.1-run-001",
        "purpose": "gs-v0.1-baseline",
        "budget_contract_hash": "c" * 64,
        "model_roles": {
            "annotator": _role(),
            "weak_extractor": _role(),
            "judge": _role(),
        },
    }
    values.update(overrides)
    return RunAdmissionPlanPayload.model_validate(values)


def _budget_payload(**overrides: object) -> BudgetApprovalPayload:
    values: dict[str, object] = {
        "plan_payload_hash": _PLAN_HASH,
        "run_identity": "gs-v0.1-run-001",
        "purpose": "gs-v0.1-baseline",
        "scope": "budget:gs-v0.1",
        "approver_identity": "finance-owner@example.com",
        "approver_role": "budget_approver",
        "issued_at": _NOW - timedelta(minutes=5),
        "expires_at": _NOW + timedelta(minutes=5),
        "budget_entries": (
            BudgetApprovalEntry(
                currency="CNY",
                max_input_tokens=1_000_000,
                max_output_tokens=100_000,
                max_cost_minor_units=50_000,
                budget_contract_hash="d" * 64,
            ),
        ),
    }
    values.update(overrides)
    return BudgetApprovalPayload.model_validate(values)


def _provenance_payload(**overrides: object) -> ProvenanceApprovalPayload:
    values: dict[str, object] = {
        "plan_payload_hash": _PLAN_HASH,
        "run_identity": "gs-v0.1-run-001",
        "purpose": "gs-v0.1-baseline",
        "scope": "provenance:wip-gs-v0.1",
        "approver_identity": "golden-owner@example.com",
        "approver_role": "provenance_approver",
        "issued_at": _NOW - timedelta(minutes=5),
        "expires_at": _NOW + timedelta(minutes=5),
        "product_entries": (
            ProvenanceApprovalEntry(
                product_id="product-01",
                annotator_provider="provider-a",
                annotator_model_id="model-1",
                annotated_at_start=_NOW - timedelta(days=1),
                annotated_at_end=_NOW - timedelta(hours=23),
                evidence_basis="provider audit export 42",
            ),
        ),
    }
    values.update(overrides)
    return ProvenanceApprovalPayload.model_validate(values)


def _signature(
    private_key: Ed25519PrivateKey, domain: ApprovalDomain, payload: object
) -> str:
    raw = private_key.sign(approval_signed_bytes(domain, payload))
    return base64.b64encode(raw).decode("ascii")


def _budget_envelope(
    private_key: Ed25519PrivateKey,
    payload: BudgetApprovalPayload | None = None,
    *,
    signing_domain: ApprovalDomain = "budget",
    key_id: str = "key-1",
) -> BudgetApprovalEnvelope:
    actual_payload = payload or _budget_payload()
    return BudgetApprovalEnvelope(
        domain="budget",
        key_id=key_id,
        payload=actual_payload,
        signature=_signature(private_key, signing_domain, actual_payload),
    )


def _verify_budget(
    envelope: BudgetApprovalEnvelope | ProvenanceApprovalEnvelope,
    public_key: object,
    **overrides: object,
) -> None:
    values: dict[str, object] = {
        "expected_domain": "budget",
        "expected_plan_payload_hash": _PLAN_HASH,
        "expected_run_identity": "gs-v0.1-run-001",
        "expected_purpose": "gs-v0.1-baseline",
        "expected_scope": "budget:gs-v0.1",
        "trusted_public_keys": {"key-1": public_key},
        "allowed_roles": frozenset({"budget_approver"}),
        "now": _NOW,
    }
    values.update(overrides)
    verify_approval_envelope(envelope, **values)  # type: ignore[arg-type]


def test_d1_1a_requires_exact_three_roles_and_signed_expected_revision() -> None:
    payload = _plan_payload()
    assert tuple(payload.model_roles) == ("annotator", "weak_extractor", "judge")

    for invalid_roles in (
        {"annotator": _role(), "weak_extractor": _role()},
        {
            "annotator": _role(),
            "weak_extractor": _role(),
            "judge": _role(),
            "reviewer": _role(),
        },
    ):
        with pytest.raises(ValidationError):
            _plan_payload(model_roles=invalid_roles)

    with pytest.raises(ValidationError):
        _role(revision=None)
    with pytest.raises(ValidationError):
        ModelRolePlan(
            **{
                **_role().model_dump(),
                "immutable_deployment_id": "deployment-42",
            }
        )


def test_d1_1a_pending_identity_is_explicit_and_never_looks_verified() -> None:
    pending = PendingModelRolePlan(
        identity_status="pending_immutable_identity",
        provider="bailian",
        model_id="deepseek-v4-flash",
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )
    payload = _plan_payload(
        model_roles={
            "annotator": pending,
            "weak_extractor": _role(),
            "judge": pending,
        },
        budget_contract_hash=None,
    )

    assert payload.model_roles["annotator"].identity_status == (
        "pending_immutable_identity"
    )
    assert payload.budget_contract_hash is None
    with pytest.raises(ValidationError):
        PendingModelRolePlan.model_validate(
            {**pending.model_dump(), "expected_model_revision": "invented"}
        )


def test_d1_1b_missing_required_product_input_has_typed_pending_state() -> None:
    pending = PendingProductInputPlan(
        input_status="pending_required_input",
        product_id="product-01",
        line_key="medical",
        pdf_digests={"terms.pdf": "a" * 64},
        product_meta_digest=None,
        fields_digest="b" * 64,
        consumed_input_digests={},
    )

    assert pending.product_meta_digest is None
    with pytest.raises(ValidationError):
        PendingProductInputPlan.model_validate(
            {
                **pending.model_dump(),
                "product_meta_digest": "c" * 64,
                "fields_digest": "d" * 64,
            }
        )


def test_d1_1d_run_identity_and_purpose_reject_blank_values() -> None:
    for field_name in ("run_identity", "purpose"):
        with pytest.raises(ValidationError):
            _plan_payload(**{field_name: "   "})


def test_d1_1d_payload_hash_excludes_approvals_observations_and_state() -> None:
    payload = _plan_payload()
    payload_hash = plan_payload_hash(payload)
    private_key = Ed25519PrivateKey.generate()
    budget_payload = _budget_payload(plan_payload_hash=payload_hash)
    envelope = _budget_envelope(private_key, budget_payload)

    bare = RunAdmissionPlan(payload=payload)
    evaluated = RunAdmissionPlan(
        payload=payload,
        approval_envelopes=(envelope,),
        observations=(
            AdmissionObservation(
                name="provider_revision",
                observed_at=_NOW,
                value="revision-2026-07-19",
            ),
        ),
        derived_state=AdmissionDerivedState(state="BLOCKED", blockers=("021 not merged",)),
    )
    assert plan_payload_hash(bare) == payload_hash
    assert plan_payload_hash(evaluated) == payload_hash
    assert plan_payload_hash(_plan_payload(run_identity="another-run")) != payload_hash
    assert plan_payload_hash(
        _plan_payload(budget_contract_hash="d" * 64)
    ) != payload_hash
    assert plan_payload_hash(
        _plan_payload(identity_contract_hash="e" * 64)
    ) != payload_hash


def test_d1_1d_canonical_bytes_reject_float_extra_and_type_confusion() -> None:
    assert canonical_json_bytes({"z": "保单", "a": [2, 1]}) == (
        b'{"a":[2,1],"z":"\xe4\xbf\x9d\xe5\x8d\x95"}'
    )
    with pytest.raises(TypeError, match="float"):
        canonical_json_bytes({"nested": [1, {"bad": 1.0}]})
    with pytest.raises(TypeError, match="string"):
        canonical_json_bytes({1: "not-a-string-key"})

    with pytest.raises(ValidationError):
        ModelRolePlan.model_validate({**_role().model_dump(), "unexpected": "field"})
    with pytest.raises(ValidationError):
        _plan_payload(run_identity=123)
    with pytest.raises(ValidationError):
        _plan_payload().run_identity = "mutated"


def test_d1_1d_model_copy_update_revalidates_and_refreezes_nested_mappings() -> None:
    payload = _plan_payload()

    with pytest.raises(ValidationError):
        payload.model_copy(update={"model_roles": {"annotator": _role()}})

    copied = payload.model_copy(
        update={
            "model_roles": {
                "annotator": _role(revision="revision-a"),
                "weak_extractor": _role(revision="revision-b"),
                "judge": _role(revision="revision-c"),
            }
        }
    )
    mutable_view = cast(dict[str, ModelRolePlan], copied.model_roles)
    with pytest.raises(TypeError):
        mutable_view["judge"] = _role(revision="replacement")

    with pytest.raises(TypeError, match="disabled"):
        payload.copy(update={"model_roles": {"annotator": _role()}})


def test_d1_1d_signed_bytes_lock_exact_versioned_domain_labels() -> None:
    budget_payload = _budget_payload()
    provenance_payload = _provenance_payload()

    assert approval_signed_bytes("budget", budget_payload) == (
        b"insurancekb.run-admission.budget.v1\0" + canonical_json_bytes(budget_payload)
    )
    assert approval_signed_bytes("provenance", provenance_payload) == (
        b"insurancekb.run-admission.provenance.v1\0"
        + canonical_json_bytes(provenance_payload)
    )


def test_d1_1d_ed25519_rejects_cross_domain_scope_run_and_payload_replay() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    envelope = _budget_envelope(private_key)
    _verify_budget(envelope, public_key)

    for mismatch in (
        {"expected_domain": "provenance"},
        {"expected_scope": "budget:another-run"},
        {"expected_run_identity": "another-run"},
        {"expected_plan_payload_hash": "b" * 64},
    ):
        with pytest.raises(ApprovalVerificationError):
            _verify_budget(envelope, public_key, **mismatch)

    cross_domain_signature = _budget_envelope(private_key, signing_domain="provenance")
    with pytest.raises(ApprovalVerificationError):
        _verify_budget(cross_domain_signature, public_key)

    modified_payload = _budget_payload(
        budget_entries=(
            BudgetApprovalEntry(
                currency="CNY",
                max_input_tokens=1_000_000,
                max_output_tokens=100_000,
                max_cost_minor_units=99_999,
                budget_contract_hash="d" * 64,
            ),
        )
    )
    replay = BudgetApprovalEnvelope(
        domain="budget",
        key_id=envelope.key_id,
        payload=modified_payload,
        signature=envelope.signature,
    )
    with pytest.raises(ApprovalVerificationError):
        _verify_budget(replay, public_key)


def test_d1_1d_rejects_unknown_key_role_expired_and_invalid_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    envelope = _budget_envelope(private_key)

    with pytest.raises(ApprovalVerificationError, match="unknown key"):
        _verify_budget(envelope, public_key, trusted_public_keys={})

    wrong_role_payload = _budget_payload(approver_role="viewer")
    wrong_role = _budget_envelope(private_key, wrong_role_payload)
    with pytest.raises(ApprovalVerificationError, match="role"):
        _verify_budget(wrong_role, public_key)

    expired_payload = _budget_payload(
        issued_at=_NOW - timedelta(hours=2),
        expires_at=_NOW - timedelta(hours=1),
    )
    expired = _budget_envelope(private_key, expired_payload)
    with pytest.raises(ApprovalVerificationError, match="expired"):
        _verify_budget(expired, public_key)

    naive_payload = _budget_payload(
        issued_at=(_NOW - timedelta(minutes=5)).replace(tzinfo=None),
        expires_at=(_NOW + timedelta(minutes=5)).replace(tzinfo=None),
    )
    naive = _budget_envelope(private_key, naive_payload)
    with pytest.raises(ApprovalVerificationError, match="timezone"):
        _verify_budget(naive, public_key)

    invalid_signature = envelope.model_copy(update={"signature": base64.b64encode(b"bad").decode()})
    with pytest.raises(ApprovalVerificationError, match="signature"):
        _verify_budget(invalid_signature, public_key)


def test_d1_1d_provenance_envelope_verifies_only_for_its_scope_and_role() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = _provenance_payload()
    envelope = ProvenanceApprovalEnvelope(
        domain="provenance",
        key_id="provenance-key",
        payload=payload,
        signature=_signature(private_key, "provenance", payload),
    )
    verify_approval_envelope(
        envelope,
        expected_domain="provenance",
        expected_plan_payload_hash=_PLAN_HASH,
        expected_run_identity="gs-v0.1-run-001",
        expected_purpose="gs-v0.1-baseline",
        expected_scope="provenance:wip-gs-v0.1",
        trusted_public_keys={"provenance-key": private_key.public_key()},
        allowed_roles=frozenset({"provenance_approver"}),
        now=_NOW,
    )


@pytest.mark.parametrize("bad_value", ["100", True, 1.5])
@pytest.mark.parametrize(
    "field_name",
    ["max_input_tokens", "max_output_tokens", "max_cost_minor_units"],
)
def test_d1_3a_budget_numbers_reject_type_confusion(
    field_name: str, bad_value: object
) -> None:
    values: dict[str, object] = {
        "currency": "CNY",
        "max_input_tokens": 1_000,
        "max_output_tokens": 100,
        "max_cost_minor_units": 500,
    }
    values[field_name] = bad_value

    with pytest.raises(ValidationError):
        BudgetApprovalEntry.model_validate(values)


def test_d1_1a_model_roles_are_deeply_immutable() -> None:
    payload = _plan_payload()
    mutable_view = cast(dict[str, ModelRolePlan], payload.model_roles)

    with pytest.raises((TypeError, AttributeError)):
        mutable_view.pop("judge")
    with pytest.raises(TypeError):
        mutable_view["judge"] = _role(revision="replacement")
    with pytest.raises(TypeError):
        mutable_view["reviewer"] = _role()

    assert tuple(payload.model_roles) == ("annotator", "weak_extractor", "judge")
    assert plan_payload_hash(payload) == plan_payload_hash(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "provider",
        "model_id",
        "protocol",
        "base_url",
        "provider_policy",
        "credential_env_name",
    ],
)
def test_d1_1a_model_role_rejects_blank_critical_fields(field_name: str) -> None:
    with pytest.raises(ValidationError):
        ModelRolePlan.model_validate({**_role().model_dump(), field_name: " \t "})


@pytest.mark.parametrize(
    ("field_name", "placeholder"),
    [
        ("model_id", "latest"),
        ("model_id", "best"),
        ("model_id", "manual"),
        ("model_id", "claude-session"),
        ("expected_model_revision", "latest"),
        ("immutable_deployment_id", "best"),
    ],
)
def test_d1_1a_model_role_rejects_drifting_identity_placeholders(
    field_name: str, placeholder: str
) -> None:
    values = _role().model_dump()
    if field_name == "immutable_deployment_id":
        values["expected_model_revision"] = None
    values[field_name] = placeholder

    with pytest.raises(ValidationError):
        ModelRolePlan.model_validate(values)


def test_d1_1b_d1_1c_d1_3a_foundation_contracts_are_frozen_and_forbid_extra() -> None:
    product = ProductInputPlan(
        product_id="product-01",
        line_key="life",
        pdf_digests={"terms.pdf": "a" * 64},
        product_meta_digest="b" * 64,
        fields_digest="c" * 64,
        consumed_input_digests={"prompts/extract.md": "d" * 64},
    )
    provenance = HistoricalProvenance(
        product_id="product-01",
        annotator_provider="provider-a",
        annotator_model_id="model-1",
        annotated_at_start=_NOW - timedelta(days=1),
        annotated_at_end=_NOW,
        evidence_basis="provider audit export 42",
    )
    budget = BudgetPlan(
        currency="CNY",
        max_input_tokens=1_000_000,
        max_output_tokens=100_000,
        max_cost_minor_units=50_000,
        budget_contract_hash="d" * 64,
    )

    for model in (product, provenance, budget):
        with pytest.raises(ValidationError):
            type(model).model_validate({**model.model_dump(), "unexpected": "value"})
        with pytest.raises(ValidationError):
            model.__setattr__(next(iter(type(model).model_fields)), "mutated")

    digests = cast(dict[str, str], product.consumed_input_digests)
    with pytest.raises(TypeError):
        digests["prompts/extract.md"] = "e" * 64
    pdf_digests = cast(dict[str, str], product.pdf_digests)
    with pytest.raises(TypeError):
        pdf_digests["terms.pdf"] = "e" * 64


@pytest.mark.parametrize(
    "updates",
    (
        {"annotator_provider": " "},
        {"annotator_model_id": ""},
        {"evidence_basis": "\t"},
        {"annotated_at_start": datetime(2026, 7, 18, 8, 0)},
        {"annotated_at_end": datetime(2026, 7, 18, 8, 0)},
        {
            "annotated_at_start": _NOW,
            "annotated_at_end": _NOW - timedelta(seconds=1),
        },
    ),
)
def test_d1_1c_provenance_rejects_blank_or_invalid_time_window(
    updates: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "product_id": "product-01",
        "annotator_provider": "provider-a",
        "annotator_model_id": "model-1",
        "annotated_at_start": _NOW - timedelta(days=1),
        "annotated_at_end": _NOW,
        "evidence_basis": "provider audit export 42",
    }
    values.update(updates)
    with pytest.raises(ValidationError):
        HistoricalProvenance.model_validate(values)


def test_d1_3a_d1_3c_budget_approval_binds_contract_and_explicit_chain() -> None:
    entry = BudgetApprovalEntry.model_validate(
        {
            "currency": "CNY",
            "max_input_tokens": 1_000,
            "max_output_tokens": 500,
            "max_cost_minor_units": 100,
            "budget_contract_hash": "a" * 64,
        }
    )
    first = BudgetApprovalPayload.model_validate(
        {
            "plan_payload_hash": _PLAN_HASH,
            "run_identity": "gs-v0.1-run-001",
            "purpose": "gs-v0.1-baseline",
            "scope": "golden-v01-budget",
            "approver_identity": "finance-owner",
            "approver_role": "budget-approver",
            "issued_at": _NOW - timedelta(minutes=1),
            "expires_at": _NOW + timedelta(hours=1),
            "revision": 1,
            "previous_approval_digest": None,
            "budget_entries": (entry,),
        }
    )
    second = first.model_copy(
        update={"revision": 2, "previous_approval_digest": "b" * 64}
    )

    assert first.revision == 1
    assert first.previous_approval_digest is None
    assert second.revision == 2
    assert second.previous_approval_digest == "b" * 64

    invalid_entry = entry.model_dump()
    invalid_entry["budget_contract_hash"] = "not-a-digest"
    with pytest.raises(ValidationError):
        BudgetApprovalEntry.model_validate(invalid_entry)
    with pytest.raises(ValidationError):
        first.model_copy(update={"revision": 1, "previous_approval_digest": "b" * 64})
    with pytest.raises(ValidationError):
        first.model_copy(update={"revision": 2, "previous_approval_digest": None})

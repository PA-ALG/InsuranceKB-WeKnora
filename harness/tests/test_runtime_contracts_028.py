"""Pure contract-kernel tests for OpenSpec 028 TR3/TR7."""

from __future__ import annotations

import ast
import copy
import gc
import inspect
import os
import pickle
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from insurance_harness import runtime
from insurance_harness.runtime import ports as runtime_ports
from insurance_harness.runtime.models import (
    CHILD_STAGE_SEQUENCE,
    PARENT_STAGE_SEQUENCE,
    CandidateFactBatch,
    ChildCompilationIdentity,
    ConsensusResult,
    GapResult,
    GovernanceResult,
    IntakeContext,
    JobState,
    MaterializedBatch,
    ParentIntakeIdentity,
    ProductCompilationInput,
    ProductSectionRoute,
    ProductVersionBinding,
    ResolvedRouteBinding,
    ResolvedRouteSet,
    RoutedSections,
    RuntimeContractError,
    StageBinding,
    StagePlan,
    StageState,
    VerifiedFactBatch,
)
from insurance_harness.runtime.ports import (
    ClassifyRouteStage,
    ConsensusStage,
    ExtractStage,
    GapStage,
    KnowledgeSink,
    MaterializeStage,
    ResolveTemplateStage,
    VerifyStage,
)
from insurance_harness.runtime.settings import RuntimeSettings
from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    ResolutionRequest,
    ResolvedTemplate,
    ResolvedTemplateSource,
    TemplatePackageContent,
    TemplateScope,
    ValidatorRef,
    canonical_content_hash,
)


def _digest(marker: str) -> str:
    return marker.encode("utf-8").hex().ljust(64, "0")[:64]


def _parent_values() -> dict[str, str]:
    return {
        "space_id": "space-a",
        "source_revision": "source-revision-a",
        "run_revision": "run-revision-a",
        "admission_artifact_hash": _digest("admission"),
        "strict_request_digest": _digest("request"),
        "verified_binding_digest": _digest("binding"),
        "routing_policy_hash": _digest("routing"),
        "template_lock_hash": _digest("template-lock"),
        "structured_dispatch_lock_hash": _digest("dispatch"),
        "model_plan_hash": _digest("model-plan"),
    }


def _parent() -> ParentIntakeIdentity:
    return ParentIntakeIdentity(**_parent_values())


def _unsafe_parent(*, verified_binding_digest: str) -> ParentIntakeIdentity:
    values = _parent_values()
    return cast(
        ParentIntakeIdentity,
        cast(Any, BaseModel.model_construct).__func__(
            ParentIntakeIdentity,
            space_id=values["space_id"],
            source_revision=values["source_revision"],
            run_revision=values["run_revision"],
            admission_artifact_hash=values["admission_artifact_hash"],
            strict_request_digest=values["strict_request_digest"],
            verified_binding_digest=verified_binding_digest,
            routing_policy_hash=values["routing_policy_hash"],
            template_lock_hash=values["template_lock_hash"],
            structured_dispatch_lock_hash=values["structured_dispatch_lock_hash"],
            model_plan_hash=values["model_plan_hash"],
        ),
    )


def _resolved_template(
    *,
    space_id: str = "space-a",
    schema_version: str = "schema-v1",
    product_line_id: str = "line-a",
    document_type_id: str = "terms",
    product_family_id: str = "family-a",
    package_id: str = "package-a",
    version_id: str = "version-a",
) -> ResolvedTemplate:
    provenance = ProvenanceReceipt(
        migration_id="runtime-contract-fixture",
        source_repository="project/llm-wiki-black",
        source_branch="main",
        source_commit="a" * 40,
        source_path="src/template.ts",
        source_language="typescript",
        rights_status="project-owned",
        accepted_behavior="template content fixture",
        rejected_behavior="runtime bridge",
        python_target="harness/src/insurance_harness/runtime/models.py",
        translation_method="behavior_port_with_characterization_tests",
        characterization_tests=("harness/tests/test_runtime_contracts_028.py",),
    )
    content = TemplatePackageContent(
        schema_version=schema_version,
        field_groups=(
            FieldGroup(
                group_id="identity",
                field_ids=("product_name",),
                evidence_roles=("primary",),
            ),
        ),
        role_prompts={"extract": "Extract one evidenced fact."},
        validators=(
            ValidatorRef(
                validator_id="quote",
                validator_version="v1",
                config_hash=_digest("validator"),
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 2},
        golden_slice_ref="golden/runtime-contract",
        provenance=(provenance,),
    )
    scope = TemplateScope(space_id=space_id, level="global")
    source = ResolvedTemplateSource(
        scope=scope,
        package_id=package_id,
        version_id=version_id,
        content=content,
        content_hash=canonical_content_hash(content),
    )
    return ResolvedTemplate(
        request=ResolutionRequest(
            space_id=space_id,
            product_line_id=product_line_id,
            document_type_id=document_type_id,
            product_family_id=product_family_id,
        ),
        content=content,
        content_hash=canonical_content_hash(content),
        source_chain=(source,),
    )


def _product_route(
    *,
    product_version_id: str = "product-version-a",
    space_id: str = "space-a",
    section_markers: tuple[str, ...] = ("section-a",),
) -> ProductSectionRoute:
    return ProductSectionRoute(
        product=ProductVersionBinding(
            space_id=space_id,
            product_version_id=product_version_id,
        ),
        section_hashes=tuple(_digest(marker) for marker in section_markers),
    )


def _route_values(
    *,
    product_route: ProductSectionRoute | None = None,
    resolved_template: ResolvedTemplate | None = None,
) -> dict[str, object]:
    return {
        "product_route": product_route or _product_route(),
        "resolved_template": resolved_template or _resolved_template(),
        "template_lock_hash": _digest("template-lock"),
        "model_plan_hash": _digest("model-plan"),
    }


def _contract_flow() -> tuple[
    IntakeContext,
    MaterializedBatch,
    RoutedSections,
    ResolvedRouteSet,
    ProductCompilationInput,
    CandidateFactBatch,
    VerifiedFactBatch,
    GapResult,
    ConsensusResult,
]:
    context = IntakeContext(identity=_parent(), source_ref="sources/source-a")
    materialized = MaterializedBatch(
        context=context,
        materialized_batch_hash=_digest("materialized"),
        lineage_hash=_digest("lineage"),
        section_hashes=(_digest("section-a"), _digest("unassigned")),
    )
    product_route = _product_route()
    routed = RoutedSections(
        materialized=materialized,
        product_routes=(product_route,),
        unassigned_section_hashes=(_digest("unassigned"),),
    )
    resolved = ResolvedRouteSet(
        routed_sections=routed,
        routes=(ResolvedRouteBinding.model_validate(_route_values()),),
    )
    child = ChildCompilationIdentity(parent=_parent(), route=resolved.routes[0])
    compilation = ProductCompilationInput(
        child_identity=child,
    )
    candidates = CandidateFactBatch(
        compilation=compilation,
        candidate_batch_hash=_digest("candidates"),
    )
    verified = VerifiedFactBatch(
        candidates=candidates,
        verified_batch_hash=_digest("verified"),
    )
    gap = GapResult(
        verified=verified,
        gap_result_hash=_digest("gap"),
        exhausted=False,
    )
    consensus = ConsensusResult(
        verified=verified,
        gap=gap,
        consensus_hash=_digest("consensus"),
        outcome="agreed",
    )
    return (
        context,
        materialized,
        routed,
        resolved,
        compilation,
        candidates,
        verified,
        gap,
        consensus,
    )


def test_tr3_parent_intake_identity_is_deterministic_and_fully_bound() -> None:
    original = ParentIntakeIdentity(**_parent_values())
    replay = ParentIntakeIdentity(**_parent_values())

    assert original.job_id == replay.job_id
    assert len(original.job_id) == 64

    for field_name in _parent_values():
        changed = _parent_values()
        value = changed[field_name]
        changed[field_name] = (
            _digest(f"changed-{field_name}")
            if field_name.endswith("hash") or field_name.endswith("digest")
            else f"{value}-changed"
        )
        assert ParentIntakeIdentity(**changed).job_id != original.job_id


@pytest.mark.parametrize("unknown_field", ["product_version_id", "resolved_template_hash"])
def test_tr3_parent_identity_cannot_claim_product_or_template_before_routing(
    unknown_field: str,
) -> None:
    values: dict[str, object] = dict(_parent_values())
    values[unknown_field] = "not-known-at-intake"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ParentIntakeIdentity.model_validate(values)


def test_tr3_parent_identity_is_immutable() -> None:
    identity = ParentIntakeIdentity(**_parent_values())

    with pytest.raises(ValidationError, match="Instance is frozen"):
        identity.space_id = "space-b"


@pytest.mark.parametrize(
    "field_name",
    ["space_id", "source_revision", "run_revision"],
)
def test_tr3_parent_identity_rejects_unresolved_and_control_variants(
    field_name: str,
) -> None:
    for sentinel in ("unknown", "UNKNOWN", "ｕｎｋｎｏｗｎ", "unknown\u200b"):
        values = _parent_values()
        values[field_name] = sentinel
        with pytest.raises(ValidationError, match="resolved identity must not be a fallback"):
            ParentIntakeIdentity(**values)


def test_tr3_child_identity_inherits_parent_and_binds_resolved_route() -> None:
    parent = _parent()
    route = ResolvedRouteBinding.model_validate(_route_values())

    child = ChildCompilationIdentity(parent=parent, route=route)
    replay = ChildCompilationIdentity(parent=_parent(), route=route.model_copy())

    assert child.job_id == replay.job_id
    assert child.parent_intake_job_id == parent.job_id
    assert child.space_id == parent.space_id == route.space_id
    assert child.run_revision == parent.run_revision
    assert child.verified_binding_digest == parent.verified_binding_digest
    assert child.template_lock_hash == parent.template_lock_hash
    assert child.model_plan_hash == parent.model_plan_hash
    assert child.product_version_id == route.product_version_id
    assert child.resolved_template_hash == route.resolved_template.content_hash


@pytest.mark.parametrize("reason_code", ["template_lock_mismatch", "model_plan_mismatch"])
def test_tr3_child_identity_fails_closed_when_route_does_not_match_parent(
    reason_code: str,
) -> None:
    route_values = _route_values()
    field_name = (
        "template_lock_hash"
        if reason_code == "template_lock_mismatch"
        else "model_plan_hash"
    )
    route_values[field_name] = _digest(f"other-{field_name}")

    with pytest.raises(RuntimeContractError, match=reason_code) as exc_info:
        ChildCompilationIdentity(
            parent=_parent(),
            route=ResolvedRouteBinding.model_validate(route_values),
        )

    assert exc_info.value.reason_code == reason_code


@pytest.mark.parametrize(
    "sentinel",
    [
        "unknown",
        "unassigned",
        "UNKNOWN",
        "ｕｎｋｎｏｗｎ",
        "unknown\u200b",
        "product\x00id",
    ],
)
def test_tr3_resolved_route_rejects_unknown_or_unresolved_identity_fallbacks(
    sentinel: str,
) -> None:
    with pytest.raises(ValidationError, match="resolved identity must not be a fallback"):
        ProductVersionBinding(space_id="space-a", product_version_id=sentinel)


@pytest.mark.parametrize(
    ("field_name", "sentinel"),
    [
        ("product_line_id", "unknown"),
        ("document_type_id", "UNKNOWN"),
        ("product_family_id", "ｕｎｋｎｏｗｎ"),
        ("package_id", "unresolved"),
        ("version_id", "unknown\u200b"),
    ],
)
def test_tr3_resolved_route_rejects_nested_unknown_template_identity(
    field_name: str,
    sentinel: str,
) -> None:
    with pytest.raises(ValidationError, match="resolved identity must not be a fallback"):
        ResolvedRouteBinding.model_validate(
            _route_values(resolved_template=_resolved_template(**{field_name: sentinel}))
        )


def test_tr3_resolved_route_rejects_unknown_schema_from_template_content() -> None:
    values = _route_values()
    values["resolved_template"] = _resolved_template(schema_version="unresolved")

    with pytest.raises(ValidationError, match="resolved identity must not be a fallback"):
        ResolvedRouteBinding.model_validate(values)


def test_tr3_resolved_route_derives_hash_schema_space_and_provenance_from_template() -> None:
    route = ResolvedRouteBinding.model_validate(_route_values())

    assert route.space_id == route.resolved_template.request.space_id
    assert route.schema_version == route.resolved_template.content.schema_version
    assert route.resolved_template_hash == route.resolved_template.content_hash
    assert route.resolved_template.content.provenance[0].rights_status == "project-owned"

    for self_reported_field in (
        "space_id",
        "schema_version",
        "resolved_template_hash",
        "template_provenance_hash",
    ):
        values = _route_values()
        values[self_reported_field] = "caller-self-report"
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ResolvedRouteBinding.model_validate(values)


def test_tr3_child_identity_changes_across_parent_binding_or_route() -> None:
    original = ChildCompilationIdentity(
        parent=_parent(),
        route=ResolvedRouteBinding.model_validate(_route_values()),
    )
    changed_parent_values = _parent_values()
    changed_parent_values["verified_binding_digest"] = _digest("binding-b")
    changed_parent = ParentIntakeIdentity(**changed_parent_values)
    changed_route_values = _route_values(
        product_route=_product_route(section_markers=("other-section",))
    )

    assert (
        ChildCompilationIdentity(
            parent=changed_parent,
            route=ResolvedRouteBinding.model_validate(_route_values()),
        ).job_id
        != original.job_id
    )
    assert (
        ChildCompilationIdentity(
            parent=_parent(),
            route=ResolvedRouteBinding.model_validate(changed_route_values),
        ).job_id
        != original.job_id
    )


def test_tr3_job_kind_stage_sequences_are_exact_and_fan_out_is_a_checkpoint() -> None:
    assert PARENT_STAGE_SEQUENCE == (
        "materialize",
        "classify_route",
        "resolve_template",
        "fan_out",
    )
    assert CHILD_STAGE_SEQUENCE == (
        "extract",
        "verify",
        "gap",
        "consensus",
        "knowledge_sink",
    )


def test_tr3_job_and_stage_statuses_follow_recoverable_fail_closed_transitions() -> None:
    parent = _parent()
    job = JobState(identity=parent, status="queued")
    running_job = job.transition("running")
    failed_job = running_job.transition("failed")
    resumed_job = failed_job.transition("running")
    succeeded_job = resumed_job.transition("succeeded")

    stage = StageState(
        identity=parent,
        stage_name="materialize",
        status="pending",
    )
    running_stage = stage.transition("running")
    failed_stage = running_stage.transition("failed")
    resumed_stage = failed_stage.transition("running")
    succeeded_stage = resumed_stage.transition("succeeded")

    assert job.status == "queued"
    assert succeeded_job.status == "succeeded"
    assert stage.status == "pending"
    assert succeeded_stage.status == "succeeded"
    with pytest.raises(RuntimeContractError, match="invalid_job_transition"):
        succeeded_job.transition("running")
    with pytest.raises(RuntimeContractError, match="invalid_stage_transition"):
        succeeded_stage.transition("running")
    with pytest.raises(RuntimeContractError, match="invalid_stage_transition"):
        stage.transition("succeeded")


def test_tr3_state_identity_derives_job_id_and_kind_without_caller_self_report() -> None:
    parent = _parent()
    route = ResolvedRouteBinding.model_validate(_route_values())
    child = ChildCompilationIdentity(parent=parent, route=route)

    parent_state = JobState(identity=parent, status="queued")
    child_state = StageState(
        identity=child,
        stage_name="extract",
        status="pending",
    )

    assert parent_state.job_id == parent.job_id
    assert parent_state.job_kind == "intake"
    assert child_state.job_id == child.job_id
    assert child_state.job_kind == "product_compilation"
    with pytest.raises(TypeError):
        JobState(  # type: ignore[call-arg]
            identity=parent,
            job_id=child.job_id,
            job_kind="product_compilation",
            status="queued",
        )


def test_tr3_succeeded_state_storage_and_identity_cannot_be_overwritten() -> None:
    parent = _parent()
    succeeded_job = JobState(identity=parent, status="succeeded")
    succeeded_stage = StageState(
        identity=parent,
        stage_name="materialize",
        status="succeeded",
    )

    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(succeeded_job, "status", "running")
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(succeeded_stage, "status", "running")

    visible_job_identity = succeeded_job.identity
    visible_stage_identity = succeeded_stage.identity
    object.__setattr__(visible_job_identity, "space_id", "space-b")
    object.__setattr__(visible_stage_identity, "space_id", "space-b")
    assert succeeded_job.status == "succeeded"
    assert succeeded_stage.status == "succeeded"

    stored_job_identity = tuple.__getitem__(succeeded_job, 0)
    stored_stage_identity = tuple.__getitem__(succeeded_stage, 0)
    object.__setattr__(stored_job_identity, "space_id", "space-b")
    object.__setattr__(stored_stage_identity, "space_id", "space-b")
    for read in (
        lambda: succeeded_job.identity,
        lambda: succeeded_job.status,
        lambda: succeeded_job.job_kind,
        lambda: succeeded_job.job_id,
        lambda: succeeded_stage.identity,
        lambda: succeeded_stage.status,
        lambda: succeeded_stage.stage_name,
        lambda: succeeded_stage.job_kind,
        lambda: succeeded_stage.job_id,
    ):
        with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
            read()


def test_tr3_state_types_cannot_be_subclassed_to_override_terminal_status() -> None:
    with pytest.raises(TypeError, match="final contract type"):

        class ForgedJobState(JobState):
            @property
            def status(self) -> Any:
                return "running"

    with pytest.raises(TypeError, match="final contract type"):

        class ForgedStageState(StageState):
            @property
            def status(self) -> Any:
                return "running"


def test_tr3_forged_tuple_state_rejects_every_public_read() -> None:
    forged = tuple.__new__(JobState, (_parent(), _digest("wrong"), "succeeded"))

    for read in (
        lambda: forged.identity,
        lambda: forged.status,
        lambda: forged.job_kind,
        lambda: forged.job_id,
    ):
        with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
            read()

def test_tr3_stage_state_rejects_stage_from_the_other_job_kind() -> None:
    with pytest.raises(RuntimeContractError, match="invalid_stage_name"):
        StageState(
            identity=_parent(),
            stage_name="extract",
            status="pending",
        )


def test_tr3_stage_plan_rejects_duplicate_plugin_names() -> None:
    bindings = (
        StageBinding(stage_name="materialize", plugin_name="shared"),
        StageBinding(stage_name="classify_route", plugin_name="shared"),
        StageBinding(stage_name="resolve_template", plugin_name="resolve"),
        StageBinding(stage_name="fan_out", plugin_name="internal-fan-out"),
    )

    with pytest.raises(RuntimeContractError, match="duplicate_plugin_name"):
        StagePlan(job_kind="intake", bindings=bindings)


def test_tr3_stage_plan_rejects_missing_reordered_or_foreign_stages() -> None:
    valid = (
        StageBinding(stage_name="materialize", plugin_name="materialize"),
        StageBinding(stage_name="classify_route", plugin_name="classify"),
        StageBinding(stage_name="resolve_template", plugin_name="resolve"),
        StageBinding(stage_name="fan_out", plugin_name="internal-fan-out"),
    )
    assert StagePlan(job_kind="intake", bindings=valid).stage_names == PARENT_STAGE_SEQUENCE

    for invalid in (valid[:-1], tuple(reversed(valid))):
        with pytest.raises(RuntimeContractError, match="invalid_stage_sequence"):
            StagePlan(job_kind="intake", bindings=invalid)


@pytest.mark.parametrize(
    ("protocol", "method_name", "parameter_types", "return_type"),
    [
        (MaterializeStage, "run", (IntakeContext,), MaterializedBatch),
        (ClassifyRouteStage, "run", (MaterializedBatch,), RoutedSections),
        (ResolveTemplateStage, "run", (RoutedSections,), ResolvedRouteSet),
        (ExtractStage, "run", (ProductCompilationInput,), CandidateFactBatch),
        (VerifyStage, "run", (CandidateFactBatch,), VerifiedFactBatch),
        (GapStage, "run", (VerifiedFactBatch,), GapResult),
        (
            ConsensusStage,
            "run",
            (VerifiedFactBatch, GapResult),
            ConsensusResult,
        ),
        (KnowledgeSink, "apply", (ConsensusResult,), GovernanceResult),
    ],
)
def test_tr3_eight_async_stage_ports_have_the_frozen_shapes(
    protocol: type[object],
    method_name: str,
    parameter_types: tuple[type[object], ...],
    return_type: type[object],
) -> None:
    method = getattr(protocol, method_name)
    hints = get_type_hints(method)
    parameters = tuple(inspect.signature(method).parameters.values())[1:]

    assert inspect.iscoroutinefunction(method)
    assert tuple(hints[parameter.name] for parameter in parameters) == parameter_types
    assert hints["return"] is return_type


def test_tr3_fan_out_is_not_an_injectable_stage_port() -> None:
    assert not hasattr(runtime_ports, "FanOutStage")


def test_tr3_contract_dtos_preserve_parent_route_template_and_provenance_binding() -> None:
    (
        context,
        materialized,
        routed,
        resolved,
        compilation,
        candidates,
        verified,
        gap,
        consensus,
    ) = _contract_flow()
    governance = GovernanceResult(
        consensus=consensus,
        governance_hash=_digest("governance"),
        outcome="proposed",
    )

    assert materialized.context == context
    assert routed.materialized == materialized
    assert resolved.routes[0].template_lock_hash == context.identity.template_lock_hash
    assert (
        resolved.routes[0].resolved_template.content.provenance[0].rights_status
        == "project-owned"
    )
    assert compilation.child_identity.parent == context.identity
    assert candidates.compilation == compilation
    assert verified.candidates == candidates
    assert gap.verified == verified
    assert consensus.verified == verified
    assert governance.consensus == consensus
    assert governance.current_release_changed is False


@pytest.mark.parametrize(
    ("field_name", "replacement", "reason_code"),
    [
        ("template_lock_hash", _digest("other-lock"), "resolved_route_lock_mismatch"),
        ("model_plan_hash", _digest("other-plan"), "resolved_route_plan_mismatch"),
    ],
)
def test_tr3_resolved_route_set_rejects_parent_binding_drift(
    field_name: str,
    replacement: object,
    reason_code: str,
) -> None:
    _, _, routed, _, _, _, _, _, _ = _contract_flow()
    values = _route_values()
    values[field_name] = replacement

    with pytest.raises(RuntimeContractError, match=reason_code):
        ResolvedRouteSet(
            routed_sections=routed,
            routes=(ResolvedRouteBinding.model_validate(values),),
        )


def test_tr3_route_and_parent_reject_cross_space_product_template_binding() -> None:
    with pytest.raises(RuntimeContractError, match="route_template_space_mismatch"):
        ResolvedRouteBinding.model_validate(
            _route_values(resolved_template=_resolved_template(space_id="space-b"))
        )

    _, _, routed, _, _, _, _, _, _ = _contract_flow()
    cross_space = ResolvedRouteBinding.model_validate(
        _route_values(
            product_route=_product_route(space_id="space-b"),
            resolved_template=_resolved_template(space_id="space-b"),
        )
    )
    with pytest.raises(RuntimeContractError, match="resolved_route_space_mismatch"):
        ResolvedRouteSet(routed_sections=routed, routes=(cross_space,))
    with pytest.raises(RuntimeContractError, match="child_space_mismatch"):
        ChildCompilationIdentity(parent=_parent(), route=cross_space)


def test_tr3_resolved_route_set_rejects_missing_extra_or_mismatched_product_routes() -> None:
    _, _, routed, _, _, _, _, _, _ = _contract_flow()
    mismatch = _route_values()
    mismatch["product_route"] = _product_route(product_version_id="product-version-b")

    with pytest.raises(RuntimeContractError, match="resolved_route_set_mismatch"):
        ResolvedRouteSet(routed_sections=routed, routes=())
    with pytest.raises(RuntimeContractError, match="resolved_route_set_mismatch"):
        ResolvedRouteSet(
            routed_sections=routed,
            routes=(ResolvedRouteBinding.model_validate(mismatch),),
        )


def test_tr3_resolved_route_set_preserves_deterministic_product_route_order() -> None:
    _, materialized, _, _, _, _, _, _, _ = _contract_flow()
    materialized = materialized.model_copy(
        update={"section_hashes": (_digest("section-a"), _digest("section-b"))}
    )
    product_route_a = _product_route(
        product_version_id="product-version-a", section_markers=("section-a",)
    )
    product_route_b = _product_route(
        product_version_id="product-version-b", section_markers=("section-b",)
    )
    routed = RoutedSections(
        materialized=materialized,
        product_routes=(product_route_b, product_route_a),
        unassigned_section_hashes=(),
    )
    route_a = ResolvedRouteBinding.model_validate(
        _route_values(product_route=product_route_a)
    )
    route_b = ResolvedRouteBinding.model_validate(
        _route_values(product_route=product_route_b)
    )

    assert routed.product_routes == (product_route_a, product_route_b)
    assert ResolvedRouteSet(routed_sections=routed, routes=(route_a, route_b))
    with pytest.raises(RuntimeContractError, match="resolved_route_set_mismatch"):
        ResolvedRouteSet(routed_sections=routed, routes=(route_b, route_a))


def test_tr3_product_compilation_input_rejects_section_or_child_rebinding() -> None:
    _, _, _, resolved, _, _, _, _, _ = _contract_flow()
    child = ChildCompilationIdentity(parent=_parent(), route=resolved.routes[0])

    compilation = ProductCompilationInput(child_identity=child)
    assert compilation.routed_input_hash == child.route.routed_section_set_hash
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProductCompilationInput.model_validate(
            {
                "child_identity": child,
                "routed_input_hash": _digest("other-sections"),
            }
        )


def test_tr3_routing_forms_one_canonical_partition_in_parent_space() -> None:
    _, materialized, _, _, _, _, _, _, _ = _contract_flow()
    section = _digest("shared-section")

    with pytest.raises(RuntimeContractError, match="section_partition_overlap"):
        RoutedSections(
            materialized=materialized,
            product_routes=(
                _product_route(product_version_id="a", section_markers=("shared-section",)),
                _product_route(product_version_id="b", section_markers=("shared-section",)),
            ),
            unassigned_section_hashes=(),
        )
    with pytest.raises(RuntimeContractError, match="section_partition_overlap"):
        ProductSectionRoute(
            product=ProductVersionBinding(
                space_id="space-a", product_version_id="product-version-a"
            ),
            section_hashes=(section, section),
        )
    with pytest.raises(RuntimeContractError, match="section_partition_overlap"):
        RoutedSections(
            materialized=materialized,
            product_routes=(
                _product_route(product_version_id="a", section_markers=("shared-section",)),
            ),
            unassigned_section_hashes=(section,),
        )
    with pytest.raises(RuntimeContractError, match="product_space_mismatch"):
        RoutedSections(
            materialized=materialized,
            product_routes=(_product_route(space_id="space-b"),),
            unassigned_section_hashes=(),
        )


def test_tr3_routing_must_exactly_partition_materialized_section_universe() -> None:
    context = IntakeContext(identity=_parent(), source_ref="sources/source-a")
    section_a = _digest("section-a")
    section_b = _digest("section-b")
    materialized = MaterializedBatch(
        context=context,
        materialized_batch_hash=_digest("materialized"),
        lineage_hash=_digest("lineage"),
        section_hashes=(section_b, section_a),
    )
    assert materialized.section_hashes == (section_a, section_b)

    with pytest.raises(RuntimeContractError, match="incomplete_section_partition"):
        RoutedSections(
            materialized=materialized,
            product_routes=(_product_route(section_markers=("section-a",)),),
            unassigned_section_hashes=(),
        )
    with pytest.raises(RuntimeContractError, match="incomplete_section_partition"):
        RoutedSections(
            materialized=materialized,
            product_routes=(_product_route(section_markers=("section-a", "extra")),),
            unassigned_section_hashes=(section_b,),
        )
    assert RoutedSections(
        materialized=materialized,
        product_routes=(_product_route(section_markers=("section-a",)),),
        unassigned_section_hashes=(section_b,),
    )


def test_tr3_mixed_document_replays_two_children_and_keeps_ambiguity_unassigned() -> None:
    context = IntakeContext(identity=_parent(), source_ref="sources/mixed")
    materialized = MaterializedBatch(
        context=context,
        materialized_batch_hash=_digest("mixed-materialized"),
        lineage_hash=_digest("mixed-lineage"),
        section_hashes=tuple(
            _digest(marker) for marker in ("product-a", "product-b", "ambiguous")
        ),
    )
    product_a = _product_route(
        product_version_id="product-a", section_markers=("product-a",)
    )
    product_b = _product_route(
        product_version_id="product-b", section_markers=("product-b",)
    )
    routed = RoutedSections(
        materialized=materialized,
        product_routes=(product_b, product_a),
        unassigned_section_hashes=(_digest("ambiguous"),),
    )
    routes = (
        ResolvedRouteBinding.model_validate(_route_values(product_route=product_a)),
        ResolvedRouteBinding.model_validate(_route_values(product_route=product_b)),
    )
    resolved = ResolvedRouteSet(routed_sections=routed, routes=routes)
    first = tuple(
        ChildCompilationIdentity(parent=_parent(), route=route).job_id
        for route in resolved.routes
    )
    replay = tuple(
        ChildCompilationIdentity(parent=_parent(), route=route.model_copy()).job_id
        for route in resolved.routes
    )

    assert len(first) == 2
    assert len(set(first)) == 2
    assert replay == first
    assert routed.unassigned_section_hashes == (_digest("ambiguous"),)

def test_tr3_consensus_rejects_a_gap_result_from_another_verified_batch() -> None:
    _, _, _, _, _, candidates, verified, _, _ = _contract_flow()
    other_verified = VerifiedFactBatch(
        candidates=candidates,
        verified_batch_hash=_digest("other-verified"),
    )
    other_gap = GapResult(
        verified=other_verified,
        gap_result_hash=_digest("other-gap"),
        exhausted=False,
    )

    with pytest.raises(RuntimeContractError, match="consensus_input_mismatch"):
        ConsensusResult(
            verified=verified,
            gap=other_gap,
            consensus_hash=_digest("consensus"),
            outcome="agreed",
        )


def test_tr7_runtime_settings_freeze_bounded_worker_attempt_time_and_token_caps() -> None:
    settings = RuntimeSettings(
        worker_count=4,
        max_attempts_per_stage=3,
        stage_timeout_seconds=90,
        max_tokens_per_attempt=4096,
        max_tokens_per_job=12288,
    )

    assert settings.worker_count == 4
    with pytest.raises(ValidationError, match="Instance is frozen"):
        settings.worker_count = 2


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("worker_count", 1),
        ("worker_count", 5),
        ("worker_count", "2"),
        ("worker_count", True),
        ("max_attempts_per_stage", 0),
        ("max_attempts_per_stage", 9),
        ("max_attempts_per_stage", "3"),
        ("stage_timeout_seconds", 0),
        ("stage_timeout_seconds", 3601),
        ("stage_timeout_seconds", 1.5),
        ("max_tokens_per_attempt", 0),
        ("max_tokens_per_attempt", 65537),
        ("max_tokens_per_attempt", "4096"),
        ("max_tokens_per_job", 0),
        ("max_tokens_per_job", 524289),
    ],
)
def test_tr7_runtime_settings_reject_unbounded_or_coercive_caps(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "worker_count": 2,
        "max_attempts_per_stage": 3,
        "stage_timeout_seconds": 90,
        "max_tokens_per_attempt": 4096,
        "max_tokens_per_job": 12288,
    }
    values[field_name] = invalid_value

    with pytest.raises(ValidationError):
        RuntimeSettings.model_validate(values)


def test_tr7_job_token_cap_cannot_be_smaller_than_one_attempt_cap() -> None:
    with pytest.raises(ValidationError, match="job token cap must cover one attempt"):
        RuntimeSettings(
            worker_count=2,
            max_attempts_per_stage=3,
            stage_timeout_seconds=90,
            max_tokens_per_attempt=4096,
            max_tokens_per_job=2048,
        )


def test_tr7_job_token_cap_cannot_exceed_all_bounded_attempts() -> None:
    with pytest.raises(ValidationError, match="job token cap exceeds attempt budget"):
        RuntimeSettings(
            worker_count=2,
            max_attempts_per_stage=2,
            stage_timeout_seconds=90,
            max_tokens_per_attempt=4096,
            max_tokens_per_job=8193,
        )


def test_tr3_derived_identity_values_are_not_caller_serialized_storage() -> None:
    parent = _parent()
    route = ResolvedRouteBinding.model_validate(_route_values())
    child = ChildCompilationIdentity(parent=parent, route=route)

    assert "job_id" not in parent.model_dump()
    assert {
        "space_id",
        "schema_version",
        "resolved_template_hash",
    }.isdisjoint(route.model_dump())
    assert {
        "job_id",
        "parent_intake_job_id",
        "space_id",
        "run_revision",
        "verified_binding_digest",
        "template_lock_hash",
        "model_plan_hash",
        "product_version_id",
        "resolved_template_hash",
    }.isdisjoint(child.model_dump())


def test_tr3_contract_model_copy_revalidates_updates_and_disables_legacy_copy() -> None:
    parent = _parent()
    route = ResolvedRouteBinding.model_validate(_route_values())

    with pytest.raises(ValidationError):
        parent.model_copy(update={"space_id": ""})
    with pytest.raises(ValidationError, match="resolved identity must not be a fallback"):
        route.model_copy(
            update={
                "product_route": _product_route(product_version_id="unknown"),
            }
        )
    with pytest.raises(TypeError, match=r"copy\(\) is disabled"):
        parent.copy(update={"space_id": "space-b"})


def test_tr3_contract_copy_and_deepcopy_revalidate_to_fresh_values() -> None:
    child = ChildCompilationIdentity(
        parent=_parent(),
        route=ResolvedRouteBinding.model_validate(_route_values()),
    )

    shallow = copy.copy(child)
    deep = copy.deepcopy(child)

    assert shallow == child and shallow is not child
    assert deep == child and deep is not child
    assert shallow.parent is not child.parent
    assert deep.route is not child.route


def test_tr3_model_construct_cannot_cross_a_nested_contract_boundary() -> None:
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _unsafe_parent(verified_binding_digest="not-a-digest")


def test_tr3_public_model_construct_is_disabled_for_every_contract_model() -> None:
    with pytest.raises(TypeError, match=r"model_construct\(\) is disabled"):
        ParentIntakeIdentity.model_construct(**_parent_values())
    with pytest.raises(TypeError, match=r"model_construct\(\) is disabled"):
        RuntimeSettings.model_construct(
            worker_count=999,
            max_attempts_per_stage=999,
            stage_timeout_seconds=999999,
            max_tokens_per_attempt=999999,
            max_tokens_per_job=999999,
        )
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        cast(Any, BaseModel.model_construct).__func__(
            ParentIntakeIdentity,
            **_parent_values(),
        )


def test_tr3_field_reads_and_serialization_reject_coordinated_mutation() -> None:
    _, _, _, _, _, _, _, _, consensus = _contract_flow()
    governance = GovernanceResult(
        consensus=consensus,
        governance_hash=_digest("governance"),
        outcome="proposed",
    )

    visible_gap = consensus.gap
    object.__setattr__(visible_gap, "exhausted", True)
    assert consensus.outcome == "agreed"
    assert consensus.model_dump()["gap"]["exhausted"] is False

    stored_gap = object.__getattribute__(consensus, "gap")
    object.__setattr__(stored_gap, "exhausted", True)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = consensus.outcome
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        consensus.model_dump()
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        consensus.model_dump_json()
    with pytest.raises(PydanticSerializationError, match="invalid_contract_dto"):
        BaseModel.model_dump(consensus)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        dict(consensus)

    stored_consensus = object.__getattribute__(governance, "consensus")
    object.__setattr__(stored_consensus, "outcome", "blocked")
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = governance.outcome
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        governance.model_dump()


def test_tr3_stale_seal_cannot_be_reissued_or_laundered_by_validation() -> None:
    parent = _parent()
    object.__setattr__(parent, "space_id", "space-b")

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        parent.model_post_init(None)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        ParentIntakeIdentity.model_validate(parent)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        IntakeContext(identity=parent, source_ref="sources/source-a")


def test_tr3_construction_integrity_cannot_be_transplanted_across_instances() -> None:
    original = _parent()
    cross_space_values = _parent_values()
    cross_space_values["space_id"] = "space-b"
    cross_space = ParentIntakeIdentity(**cross_space_values)

    original_storage = object.__getattribute__(original, "__dict__")
    original_storage["space_id"] = "space-b"
    original_fields_set = object.__getattribute__(original, "__pydantic_fields_set__")
    cross_space_fields_set = object.__getattribute__(
        cross_space, "__pydantic_fields_set__"
    )
    original_fields_set.clear()
    original_fields_set.update(cross_space_fields_set)
    original_private = object.__getattribute__(original, "__pydantic_private__")
    cross_space_private = object.__getattribute__(cross_space, "__pydantic_private__")
    if type(original_private) is dict and type(cross_space_private) is dict:
        original_private.clear()
        original_private.update(cross_space_private)

    reads = (
        lambda: original.space_id,
        lambda: original.job_id,
        lambda: original.model_dump(),
        lambda: copy.copy(original),
        lambda: copy.deepcopy(original),
        lambda: ParentIntakeIdentity.model_validate(original),
        lambda: IntakeContext(identity=original, source_ref="sources/source-a"),
        lambda: JobState(identity=original, status="queued"),
    )
    for read in reads:
        with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
            read()


def test_tr3_construction_integrity_is_not_recomputable_instance_state() -> None:
    from insurance_harness.runtime import models as runtime_models

    parent = _parent()
    object.__getattribute__(parent, "__dict__")["space_id"] = "space-b"
    seal_function = getattr(runtime_models, "_construction_seal", None)
    private = object.__getattribute__(parent, "__pydantic_private__")
    if callable(seal_function) and type(private) is dict:
        try:
            private["_construction_seal"] = seal_function(parent)
        except Exception:
            pass

    assert seal_function is None
    assert not hasattr(runtime_models, "_issue_contract_snapshot")
    assert not hasattr(runtime_models, "_CONTRACT_SNAPSHOT_ISSUER_TOKEN")
    assert not hasattr(runtime_models, "_CONSTRUCTION_SECRET")
    assert private is None
    for method in (
        runtime_models._ImmutableModel.__init__,
        runtime_models._ImmutableModel.model_validate.__func__,
        runtime_models._ImmutableModel.model_post_init,
    ):
        assert method.__defaults__ is None
        assert method.__kwdefaults__ is None
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = parent.job_id


def test_tr3_deserialized_contract_has_no_migratable_process_authority() -> None:
    restored = pickle.loads(pickle.dumps(_parent()))

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = restored.job_id
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        restored.model_dump()


@pytest.mark.parametrize("tamper", ["field", "private", "fields_set", "nested"])
def test_tr3_pickle_rejects_noncanonical_runtime_storage(tamper: str) -> None:
    if tamper == "nested":
        value: Any = IntakeContext(identity=_parent(), source_ref="sources/source-a")
        nested = object.__getattribute__(value, "identity")
        object.__getattribute__(nested, "__dict__")["space_id"] = "space-b"
    else:
        value = _parent()
        if tamper == "field":
            object.__getattribute__(value, "__dict__")["space_id"] = "space-b"
        elif tamper == "private":
            object.__setattr__(value, "__pydantic_private__", {"migrated": True})
        else:
            object.__getattribute__(value, "__pydantic_fields_set__").remove("space_id")

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        pickle.dumps(value)


@pytest.mark.parametrize("tamper", ["fields_set", "private"])
def test_tr3_hidden_pydantic_storage_must_match_the_registered_snapshot(
    tamper: str,
) -> None:
    parent = _parent()
    if tamper == "fields_set":
        object.__getattribute__(parent, "__pydantic_fields_set__").remove("space_id")
    else:
        object.__setattr__(parent, "__pydantic_private__", {"migrated": True})

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = parent.space_id
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        parent.model_dump()


def test_tr3_contract_registry_is_weak_and_concurrent_reads_are_identity_bound() -> None:
    parent = _parent()
    expected_job_id = parent.job_id

    def read_job_id(value: ParentIntakeIdentity) -> str:
        return value.job_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(read_job_id, (parent,) * 128)) == {
            expected_job_id
        }

    reference = weakref.ref(parent)
    del parent
    gc.collect()
    assert reference() is None

    replacements = tuple(_parent() for _index in range(128))
    assert all(replacement.job_id == expected_job_id for replacement in replacements)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_tr3_inherited_contract_registry_is_revoked_after_fork() -> None:
    parent = _parent()
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    result: str
    if pid == 0:  # pragma: no cover - assertions are reported through the pipe
        os.close(read_fd)
        try:
            try:
                _ = parent.job_id
            except RuntimeContractError as exc:
                result = exc.reason_code
            else:
                result = "accepted"
            os.write(write_fd, result.encode("ascii"))
        finally:
            os.close(write_fd)
            os._exit(0)

    os.close(write_fd)
    try:
        result = os.read(read_fd, 128).decode("ascii")
    finally:
        os.close(read_fd)
        _waited_pid, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert result == "invalid_contract_dto"
    assert parent.job_id == _parent().job_id


def test_tr3_derived_route_properties_revalidate_nested_mutation() -> None:
    route = ResolvedRouteBinding.model_validate(_route_values())
    visible_product = route.product_route.product
    object.__setattr__(visible_product, "product_version_id", "unknown")
    assert route.product_version_id == "product-version-a"

    stored_product_route = object.__getattribute__(route, "product_route")
    stored_product = object.__getattribute__(stored_product_route, "product")
    object.__setattr__(stored_product, "product_version_id", "unknown")

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = route.product_version_id


def test_tr3_identity_digest_revalidates_model_construct_and_mutated_storage() -> None:
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _unsafe_parent(verified_binding_digest="not-a-digest")

    child = ChildCompilationIdentity(
        parent=_parent(),
        route=ResolvedRouteBinding.model_validate(_route_values()),
    )
    visible_parent = child.parent
    object.__setattr__(visible_parent, "verified_binding_digest", "not-a-digest")
    assert child.verified_binding_digest == _digest("binding")

    stored_parent = object.__getattribute__(child, "parent")
    object.__setattr__(stored_parent, "verified_binding_digest", "not-a-digest")
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = child.job_id

    shadowed = _parent()
    object.__setattr__(
        shadowed,
        "model_dump",
        lambda *args, **kwargs: _parent_values(),
    )
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = shadowed.job_id

    nested = ChildCompilationIdentity(
        parent=_parent(),
        route=ResolvedRouteBinding.model_validate(_route_values()),
    )
    stored_route = object.__getattribute__(nested, "route")
    stored_template = object.__getattribute__(stored_route, "resolved_template")
    object.__setattr__(stored_template.request, "product_line_id", "unknown")
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        _ = nested.job_id


def test_tr3_contract_strings_reject_non_unicode_scalar_text_before_hashing() -> None:
    values = _parent_values()
    values["space_id"] = "space-\ud800"

    with pytest.raises(ValidationError):
        ParentIntakeIdentity(**values)


def test_tr3_routing_rejects_same_product_split_across_multiple_route_records() -> None:
    _, materialized, _, _, _, _, _, _, _ = _contract_flow()

    with pytest.raises(RuntimeContractError, match="duplicate_product_route"):
        RoutedSections(
            materialized=materialized,
            product_routes=(
                _product_route(section_markers=("route-a1",)),
                _product_route(section_markers=("route-a2",)),
            ),
            unassigned_section_hashes=(),
        )


def test_tr3_template_binding_digest_includes_ordered_source_identity() -> None:
    original = ResolvedRouteBinding.model_validate(_route_values())
    changed = ResolvedRouteBinding.model_validate(
        _route_values(resolved_template=_resolved_template(version_id="version-b"))
    )

    assert original.resolved_template_hash == changed.resolved_template_hash
    assert original.template_binding_digest != changed.template_binding_digest
    assert (
        ChildCompilationIdentity(parent=_parent(), route=original).job_id
        != ChildCompilationIdentity(parent=_parent(), route=changed).job_id
    )
    values = _route_values()
    values["template_binding_digest"] = original.template_binding_digest
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResolvedRouteBinding.model_validate(values)


def test_tr3_exhausted_gaps_and_conflicts_cannot_claim_successful_governance() -> None:
    _, _, _, _, _, _, verified, _, _ = _contract_flow()
    exhausted = GapResult(
        verified=verified,
        gap_result_hash=_digest("exhausted-gap"),
        exhausted=True,
    )
    with pytest.raises(RuntimeContractError, match="exhausted_gap_must_block"):
        ConsensusResult(
            verified=verified,
            gap=exhausted,
            consensus_hash=_digest("invalid-consensus"),
            outcome="agreed",
        )
    blocked = ConsensusResult(
        verified=verified,
        gap=exhausted,
        consensus_hash=_digest("blocked-consensus"),
        outcome="blocked",
    )
    conflict_gap = GapResult(
        verified=verified,
        gap_result_hash=_digest("conflict-gap"),
        exhausted=False,
    )
    conflict = ConsensusResult(
        verified=verified,
        gap=conflict_gap,
        consensus_hash=_digest("conflict-consensus"),
        outcome="conflict",
    )

    for consensus in (blocked, conflict):
        with pytest.raises(RuntimeContractError, match="governance_outcome_mismatch"):
            GovernanceResult(
                consensus=consensus,
                governance_hash=_digest("invalid-governance"),
                outcome="proposed",
            )
    assert GovernanceResult(
        consensus=blocked,
        governance_hash=_digest("blocked-governance"),
        outcome="blocked",
    )
    assert GovernanceResult(
        consensus=conflict,
        governance_hash=_digest("review-governance"),
        outcome="review",
    )


def test_tr3_runtime_public_surface_is_only_the_frozen_contract_kernel() -> None:
    assert set(runtime.__all__) == {
        "CHILD_STAGE_SEQUENCE",
        "PARENT_STAGE_SEQUENCE",
        "CandidateFactBatch",
        "ChildCompilationIdentity",
        "ClassifyRouteStage",
        "ConsensusResult",
        "ConsensusStage",
        "ExtractStage",
        "GapResult",
        "GapStage",
        "GovernanceResult",
        "IntakeContext",
        "JobState",
        "KnowledgeSink",
        "MaterializeStage",
        "MaterializedBatch",
        "ParentIntakeIdentity",
        "ProductCompilationInput",
        "ProductSectionRoute",
        "ProductVersionBinding",
        "ResolveTemplateStage",
        "ResolvedRouteBinding",
        "ResolvedRouteSet",
        "RoutedSections",
        "RuntimeContractError",
        "RuntimeSettings",
        "StageBinding",
        "StagePlan",
        "StageState",
        "VerifiedFactBatch",
        "VerifyStage",
    }


def test_tr3_runtime_contract_kernel_has_exact_owned_files_and_no_deployable_imports() -> None:
    runtime_dir = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "insurance_harness"
        / "runtime"
    )
    python_files = tuple(sorted(path.name for path in runtime_dir.glob("*.py")))

    assert python_files == ("__init__.py", "models.py", "ports.py", "settings.py")

    forbidden_imports = {
        "alembic",
        "sqlalchemy",
        "insurance_harness.compiler",
        "insurance_harness.db",
        "insurance_harness.knowledge",
        "insurance_harness.model_policy",
        "insurance_harness.structured_import",
    }
    forbidden_authority_names = {
        "GuardedModelClient",
        "IssuedModelPermit",
        "ReleaseAuthorizer",
        "VerifiedAdmission",
        "create_engine",
    }
    imported_modules: set[str] = set()
    source_text = ""
    for filename in python_files:
        source = (runtime_dir / filename).read_text(encoding="utf-8")
        source_text += source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

    assert not any(
        imported == forbidden or imported.startswith(f"{forbidden}.")
        for imported in imported_modules
        for forbidden in forbidden_imports
    )
    assert forbidden_authority_names.isdisjoint(source_text.split())


def test_tr3_stage_ports_are_protocols_not_runtime_authority_instances() -> None:
    for protocol in (
        MaterializeStage,
        ClassifyRouteStage,
        ResolveTemplateStage,
        ExtractStage,
        VerifyStage,
        GapStage,
        ConsensusStage,
        KnowledgeSink,
    ):
        assert getattr(protocol, "_is_protocol", False) is True
        with pytest.raises(TypeError, match="Protocols cannot be instantiated"):
            cast(Any, protocol)()

"""OpenSpec 058: pure incremental ChangeSet/conflict/retraction contract."""

from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from insurance_harness.compiler.material_profiles import (
    MaterialProfileCatalog,
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    load_material_profile_catalog,
    resolve_material_profile,
)
from insurance_harness.knowledge_compiler.incremental_changes import (
    ChangeSetDraftV1,
    IncrementalCompilationError,
    VerifiedFactV1,
    compile_incremental_changes,
)
from insurance_harness.knowledge_compiler.retractions import RetractionProofV1
from insurance_harness.knowledge_compiler.source_authority import (
    FactScopeV1,
    MaterialBindingReceiptV1,
    SourceAuthorityV1,
)
from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
FIELD_A = "zh_a271d96039"
FIELD_B = "zh_313cabffd8"
BROCHURE_FIELD = "zh_fd9a0b9fa3"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "material_profile_596_1_052.json"


class _MemoryTemplateCatalog:
    def __init__(self, entries: tuple[TemplateCatalogEntry, ...]) -> None:
        self.entries = {entry.version.scope: entry for entry in entries}

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self.entries.get(scope)


def _template_entry(scope: TemplateScope, marker: str) -> TemplateCatalogEntry:
    content = TemplatePackageContent(
        schema_version="v1.1+b31a411c621c",
        field_groups=(
            FieldGroup(
                group_id=f"group-{marker}",
                field_ids=(f"field-{marker}",),
                evidence_roles=("terms", "brochure", "rate_table"),
            ),
        ),
        role_prompts={"extract": f"extract-{marker}"},
        validators=(
            ValidatorRef(
                validator_id=f"validator-{marker}",
                validator_version="v1",
                config_hash=HASH_A,
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 1},
        golden_slice_ref="gs-s0q-596-v1",
        provenance=(
            ProvenanceReceipt(
                migration_id=f"MIG-058-{marker}",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="explicit material and field routing",
                rejected_behavior="filename and fuzzy product dispatch",
                python_target=("harness/src/insurance_harness/compiler/material_profiles.py"),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=("harness/tests/test_incremental_changes_058.py",),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id=f"058-{marker}-v1",
        scope=scope,
        content=content,
    )
    return TemplateCatalogEntry(
        version=version,
        approval=TemplateApproval(
            approval_id=f"approval-{marker}",
            package_id=version.package_id,
            version_id=version.version_id,
            scope=scope,
            content_hash=version.content_hash,
            state="approved",
        ),
    )


@lru_cache(maxsize=1)
def _catalog() -> MaterialProfileCatalog:
    return load_material_profile_catalog(FIXTURE_PATH)


@lru_cache(maxsize=9)
def _resolution(
    role: Literal["terms", "brochure", "rate_table"],
    space_id: str = "space-058",
) -> MaterialProfileResolution:
    catalog = _catalog()
    profile = next(item for item in catalog.profiles if item.material_role == role)
    scopes = (
        TemplateScope(space_id=space_id, level="global"),
        TemplateScope(
            space_id=space_id,
            level="product-line",
            product_line_id="medical",
        ),
        TemplateScope(
            space_id=space_id,
            level="document-type",
            product_line_id="medical",
            document_type_id=profile.document_type_id,
        ),
        TemplateScope(
            space_id=space_id,
            level="product-family",
            product_line_id="medical",
            document_type_id=profile.document_type_id,
            product_family_id="pingan-eshengbao-zunxiang-medical",
        ),
    )
    templates = _MemoryTemplateCatalog(
        tuple(_template_entry(scope, f"{role}-{index}") for index, scope in enumerate(scopes))
    )
    request = MaterialProfileResolutionRequest(
        space_id=space_id,
        product_code="596",
        product_version="596-1",
        schema_version=catalog.schema_binding.schema_version,
        schema_field_ids=catalog.schema_binding.field_ids,
        source=profile.source,
        classified_material_role=role,
    )
    return resolve_material_profile(catalog, templates, request)


def _resolutions(space_id: str = "space-058") -> tuple[MaterialProfileResolution, ...]:
    return tuple(_resolution(role, space_id) for role in ("terms", "brochure", "rate_table"))


def _scope(
    field_id: str = FIELD_A,
    *,
    space_id: str = "space-058",
    product_version_id: str = "596-1",
) -> FactScopeV1:
    return FactScopeV1(
        space_id=space_id,
        product_version_id=product_version_id,
        subject_id="product:596-1",
        field_id=field_id,
        valid_from="2026-01-01T00:00:00.000000Z",
        valid_through=None,
        region="CN",
        channel="all-approved-channels",
        population="eligible-insured",
        conditions=("plan=standard",),
    )


def _authority(
    *,
    material_role: Literal["terms", "brochure", "rate_table"] = "terms",
    source_revision_id: str = "revision-1",
    reliable_at: str = "2026-01-01T00:00:00.000000Z",
) -> SourceAuthorityV1:
    resolution = _resolution(material_role)
    binding = MaterialBindingReceiptV1(
        catalog_hash=resolution.catalog_hash,
        binding_hash=resolution.binding_hash,
        space_id=resolution.request.space_id,
        product_version_id=resolution.request.product_version,
        source_id=resolution.profile.source.sha256,
        source_revision_id=source_revision_id,
        material_role=material_role,
    )
    return SourceAuthorityV1(
        source_id=resolution.profile.source.sha256,
        source_revision_id=source_revision_id,
        material_role=material_role,
        binding=binding,
        reliable_at=reliable_at,
    )


def _fact(
    *,
    field_id: str = FIELD_A,
    value_hash: str = HASH_A,
    evidence_hashes: tuple[str, ...] = (HASH_B,),
    authority: SourceAuthorityV1 | None = None,
    supporting_source_revision_ids: tuple[str, ...] | None = None,
    state: Literal["known", "unknown"] = "known",
    space_id: str = "space-058",
    product_version_id: str = "596-1",
) -> VerifiedFactV1:
    selected_authority = authority or _authority()
    supports = (
        (selected_authority.source_revision_id,)
        if supporting_source_revision_ids is None
        else supporting_source_revision_ids
    )
    return VerifiedFactV1(
        scope=_scope(
            field_id,
            space_id=space_id,
            product_version_id=product_version_id,
        ),
        state=state,
        value_hash=value_hash if state == "known" else None,
        authority=selected_authority,
        evidence_hashes=evidence_hashes if state == "known" else (),
        supporting_source_revision_ids=supports,
    )


def _compile(
    *,
    baseline: tuple[VerifiedFactV1, ...] = (),
    candidates: tuple[VerifiedFactV1, ...] = (),
    retractions: tuple[RetractionProofV1, ...] = (),
) -> ChangeSetDraftV1:
    return compile_incremental_changes(
        space_id="space-058",
        product_version_id="596-1",
        material_profile_catalog=_catalog(),
        material_profile_resolutions=_resolutions(),
        baseline_facts=baseline,
        candidate_facts=candidates,
        retraction_proofs=retractions,
    )


def test_add_is_c0_stable_and_input_order_independent() -> None:
    first = _fact(field_id=FIELD_A, value_hash=HASH_A)
    second = _fact(
        field_id=FIELD_B,
        value_hash=HASH_C,
        authority=_authority(),
    )

    left = _compile(candidates=(first, second))
    right = _compile(candidates=(second, first))

    assert {item.action for item in left.items} == {"add"}
    assert left == right
    assert left.change_set_hash == right.change_set_hash
    with pytest.raises(ValidationError):
        left.__setattr__("items", ())


def test_equal_value_enriches_evidence_without_merging_different_values() -> None:
    baseline = _fact(value_hash=HASH_A, evidence_hashes=(HASH_B,))
    candidate = _fact(
        value_hash=HASH_A,
        evidence_hashes=(HASH_C,),
        authority=_authority(
            source_revision_id="revision-2",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
    )

    draft = _compile(baseline=(baseline,), candidates=(candidate,))

    assert len(draft.items) == 1
    assert draft.items[0].action == "enrich"
    assert draft.items[0].evidence_hashes == (HASH_B, HASH_C)
    assert draft.items[0].prior_fact_hashes == (baseline.fact_hash,)


def test_higher_or_newer_authority_supersedes_while_equal_disagreement_conflicts() -> None:
    support = _fact(
        value_hash=HASH_A,
        authority=_authority(material_role="brochure"),
    )
    primary = _fact(
        value_hash=HASH_C,
        authority=_authority(
            source_revision_id="revision-primary",
            reliable_at="2026-01-01T00:00:00.000000Z",
        ),
    )
    assert _compile(baseline=(support,), candidates=(primary,)).items[0].action == ("supersede")

    older = _fact(
        value_hash=HASH_A,
        authority=_authority(
            source_revision_id="revision-old",
            reliable_at="2026-01-01T00:00:00.000000Z",
        ),
    )
    newer = _fact(
        value_hash=HASH_C,
        authority=_authority(
            source_revision_id="revision-new",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
    )
    assert _compile(baseline=(older,), candidates=(newer,)).items[0].action == ("supersede")

    peer = _fact(
        value_hash=HASH_C,
        authority=_authority(source_revision_id="revision-peer"),
    )
    conflict = _compile(baseline=(older,), candidates=(peer,)).items[0]
    assert conflict.action == "conflict"
    assert conflict.prior_fact_hashes == (older.fact_hash,)
    assert conflict.incoming_fact_hash == peer.fact_hash


def test_mixed_same_and_lower_different_baseline_uses_authority_winner() -> None:
    same_primary = _fact(
        value_hash=HASH_C,
        authority=_authority(
            source_revision_id="revision-primary-old",
            reliable_at="2026-01-01T00:00:00.000000Z",
        ),
    )
    different_support = _fact(
        value_hash=HASH_A,
        authority=_authority(
            material_role="brochure",
            source_revision_id="revision-support",
        ),
    )
    incoming = _fact(
        value_hash=HASH_C,
        authority=_authority(
            source_revision_id="revision-primary-new",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
    )

    item = _compile(
        baseline=(same_primary, different_support),
        candidates=(incoming,),
    ).items[0]

    assert item.action == "supersede"
    assert set(item.prior_fact_hashes) == {
        same_primary.fact_hash,
        different_support.fact_hash,
    }


def test_affected_only_preserves_unmentioned_baseline_and_unknown_is_not_retract() -> None:
    affected = _fact(field_id=FIELD_A, value_hash=HASH_A)
    unaffected = _fact(
        field_id=FIELD_B,
        value_hash=HASH_B,
        authority=_authority(),
    )
    replacement = _fact(
        field_id=FIELD_A,
        value_hash=HASH_C,
        authority=_authority(
            source_revision_id="revision-2",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
    )
    unknown = _fact(
        field_id=FIELD_B,
        authority=_authority(
            source_revision_id="revision-2",
        ),
        state="unknown",
    )

    draft = _compile(
        baseline=(affected, unaffected),
        candidates=(replacement, unknown),
    )

    assert len(draft.items) == 1
    assert draft.items[0].scope.field_id == FIELD_A
    assert draft.items[0].action == "supersede"
    assert unaffected.fact_hash not in draft.items[0].prior_fact_hashes


def test_unknown_fact_requires_exact_authority_support() -> None:
    for supports in ((), ("revision-other",)):
        with pytest.raises(ValidationError, match="authority_revision_not_supported"):
            _fact(state="unknown", supporting_source_revision_ids=supports)

    valid = _fact(
        state="unknown",
        supporting_source_revision_ids=("revision-1",),
    )
    assert valid.supporting_source_revision_ids == (valid.authority.source_revision_id,)

    for supports in ((), ("revision-other",)):
        forged = valid.model_copy(update={"supporting_source_revision_ids": supports})
        with pytest.raises(IncrementalCompilationError, match="invalid_fact"):
            _compile(candidates=(forged,))


def test_retract_requires_complete_exact_exclusive_support_proof() -> None:
    old_authority = _authority(
        source_revision_id="revision-old",
        reliable_at="2026-01-01T00:00:00.000000Z",
    )
    baseline = _fact(
        authority=old_authority,
        supporting_source_revision_ids=("revision-old",),
    )
    proof = RetractionProofV1(
        scope=baseline.scope,
        old_source_revision_id="revision-old",
        replacement_authority=_authority(
            source_revision_id="revision-new",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
        complete_scope=True,
        explicitly_absent=True,
        evidence_hash=HASH_E,
        reason_code="source_revision_replaced",
    )

    item = _compile(baseline=(baseline,), retractions=(proof,)).items[0]

    assert item.action == "retract"
    assert item.prior_fact_hashes == (baseline.fact_hash,)
    assert item.retraction_proof_hash == proof.proof_hash
    assert item.incoming_fact_hash is None


def test_missing_or_nonexclusive_retraction_never_withdraws_fact() -> None:
    baseline = _fact(
        supporting_source_revision_ids=("revision-1", "revision-other"),
    )
    assert _compile(baseline=(baseline,)).items == ()

    proof = RetractionProofV1(
        scope=baseline.scope,
        old_source_revision_id="revision-1",
        replacement_authority=_authority(
            source_revision_id="revision-2",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
        complete_scope=True,
        explicitly_absent=True,
        evidence_hash=HASH_E,
        reason_code="source_revision_replaced",
    )
    with pytest.raises(
        IncrementalCompilationError,
        match="retraction_not_exclusive",
    ):
        _compile(baseline=(baseline,), retractions=(proof,))


@pytest.mark.parametrize(
    ("space_id", "product_version_id"),
    (("space-foreign", "596-1"), ("space-058", "596-2")),
)
def test_cross_scope_candidate_fails_closed(
    space_id: str,
    product_version_id: str,
) -> None:
    foreign = _fact(
        space_id=space_id,
        product_version_id=product_version_id,
    )
    with pytest.raises(IncrementalCompilationError, match="cross_scope_input"):
        _compile(candidates=(foreign,))


def test_baseline_and_retraction_cross_scope_fail_closed() -> None:
    baseline = _fact(space_id="space-foreign")
    with pytest.raises(IncrementalCompilationError, match="cross_scope_input"):
        _compile(baseline=(baseline,))

    local = _fact()
    proof = RetractionProofV1(
        scope=_scope(space_id="space-foreign"),
        old_source_revision_id=local.authority.source_revision_id,
        replacement_authority=_authority(
            source_revision_id="revision-new",
            reliable_at="2026-02-01T00:00:00.000000Z",
        ),
        complete_scope=True,
        explicitly_absent=True,
        evidence_hash=HASH_E,
        reason_code="source_revision_replaced",
    )
    with pytest.raises(IncrementalCompilationError, match="cross_scope_input"):
        _compile(baseline=(local,), retractions=(proof,))


def test_empty_scope_is_validated_and_bound_into_input_hash() -> None:
    left = compile_incremental_changes(
        space_id="space-empty-a",
        product_version_id="596-1",
        material_profile_catalog=_catalog(),
        material_profile_resolutions=_resolutions("space-empty-a"),
        baseline_facts=(),
        candidate_facts=(),
    )
    right = compile_incremental_changes(
        space_id="space-empty-b",
        product_version_id="596-1",
        material_profile_catalog=_catalog(),
        material_profile_resolutions=_resolutions("space-empty-b"),
        baseline_facts=(),
        candidate_facts=(),
    )
    assert left.input_hash != right.input_hash
    for space_id, product_version_id in (("", "596-1"), ("space-058", "*")):
        with pytest.raises(IncrementalCompilationError, match="invalid_root_scope"):
            compile_incremental_changes(
                space_id=space_id,
                product_version_id=product_version_id,
                material_profile_catalog=_catalog(),
                material_profile_resolutions=_resolutions(),
                baseline_facts=(),
                candidate_facts=(),
            )


@pytest.mark.parametrize(
    ("space_id", "product_version_id"),
    (
        ("all", "596-1"),
        ("ANY", "596-1"),
        ("Unknown", "596-1"),
        ("space-058", "all"),
        ("space-058", "ANY"),
        ("space-058", "Unknown"),
    ),
)
def test_unresolved_whole_token_root_scope_fails_closed(
    space_id: str,
    product_version_id: str,
) -> None:
    with pytest.raises(IncrementalCompilationError, match="invalid_root_scope"):
        compile_incremental_changes(
            space_id=space_id,
            product_version_id=product_version_id,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            baseline_facts=(),
            candidate_facts=(),
        )


@pytest.mark.parametrize(
    ("field_name", "token"),
    (
        ("space_id", "all"),
        ("product_version_id", "ANY"),
        ("subject_id", "Unknown"),
        ("field_id", "ALL"),
        ("region", "any"),
        ("channel", "UNKNOWN"),
        ("population", "All"),
    ),
)
def test_fact_scope_unresolved_whole_token_identity_fails_closed(
    field_name: str,
    token: str,
) -> None:
    payload = _scope().model_dump(mode="python", exclude={"scope_hash"})
    payload[field_name] = token
    with pytest.raises(ValidationError, match="unresolved_identity_forbidden"):
        FactScopeV1.model_validate(payload)

    payload = _scope().model_dump(mode="python", exclude={"scope_hash"})
    payload["conditions"] = (token,)
    with pytest.raises(ValidationError, match="unresolved_identity_forbidden"):
        FactScopeV1.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "token"),
    (("space_id", "all"), ("product_version_id", "ANY"), ("source_revision_id", "Unknown")),
)
def test_binding_unresolved_whole_token_identity_fails_closed(
    field_name: str,
    token: str,
) -> None:
    payload = _authority().binding.model_dump(
        mode="python",
        exclude={"registration_hash"},
    )
    payload[field_name] = token
    with pytest.raises(ValidationError, match="unresolved_identity_forbidden"):
        MaterialBindingReceiptV1.model_validate(payload)


@pytest.mark.parametrize("token", ("all", "ANY", "Unknown"))
def test_authority_and_support_unresolved_whole_token_revision_fails_closed(
    token: str,
) -> None:
    valid = _fact()
    binding = valid.authority.binding.model_copy(update={"source_revision_id": token})
    authority = valid.authority.model_copy(
        update={"source_revision_id": token, "binding": binding},
    )
    forged = valid.model_copy(
        update={
            "authority": authority,
            "supporting_source_revision_ids": (token,),
        },
    )
    with pytest.raises(IncrementalCompilationError, match="invalid_fact"):
        _compile(candidates=(forged,))

    payload = valid.model_dump(
        mode="python",
        exclude={
            "fact_hash": True,
            "scope": {"scope_hash": True},
            "authority": {
                "authority_hash": True,
                "binding": {"registration_hash": True},
            },
        },
    )
    payload["supporting_source_revision_ids"] = (token,)
    with pytest.raises(ValidationError, match="unresolved_identity_forbidden"):
        VerifiedFactV1.model_validate(payload)


@pytest.mark.parametrize("token", ("all", "ANY", "Unknown"))
def test_retraction_unresolved_whole_token_revision_fails_closed(token: str) -> None:
    with pytest.raises(ValidationError, match="unresolved_identity_forbidden"):
        RetractionProofV1(
            scope=_scope(),
            old_source_revision_id=token,
            replacement_authority=_authority(
                source_revision_id="revision-new",
                reliable_at="2026-02-01T00:00:00.000000Z",
            ),
            complete_scope=True,
            explicitly_absent=True,
            evidence_hash=HASH_E,
            reason_code="source_revision_replaced",
        )


def test_registered_052_binding_cannot_be_self_declared_or_cross_space() -> None:
    valid = _fact()
    wrong_role = valid.authority.model_copy(update={"material_role": "brochure"})
    forged_role = valid.model_copy(update={"authority": wrong_role})
    with pytest.raises(
        IncrementalCompilationError,
        match="invalid_fact|authority_binding_mismatch",
    ):
        _compile(candidates=(forged_role,))

    foreign_binding = valid.authority.binding.model_copy(update={"space_id": "space-foreign"})
    foreign_authority = valid.authority.model_copy(update={"binding": foreign_binding})
    forged_space = valid.model_copy(update={"authority": foreign_authority})
    with pytest.raises(IncrementalCompilationError, match="authority_binding_mismatch"):
        _compile(candidates=(forged_space,))


def test_fact_revision_must_be_registered_in_support_and_policy_cannot_drift() -> None:
    with pytest.raises(ValidationError, match="authority_revision_not_supported"):
        _fact(supporting_source_revision_ids=("revision-other",))

    valid = _fact()
    forged_binding = valid.authority.binding.model_copy(update={"catalog_hash": HASH_A})
    forged_authority = valid.authority.model_copy(update={"binding": forged_binding})
    forged = valid.model_copy(update={"authority": forged_authority})
    with pytest.raises(IncrementalCompilationError, match="authority_policy_mismatch"):
        _compile(candidates=(forged,))


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ({"value_hash": "g" * 64}, "invalid_fact"),
        ({"evidence_hashes": ("x" * 64,)}, "invalid_fact"),
    ),
)
def test_malformed_hashes_fail_closed(
    mutation: dict[str, object],
    reason: str,
) -> None:
    forged = _fact().model_copy(update=mutation)
    with pytest.raises(IncrementalCompilationError, match=reason):
        _compile(candidates=(forged,))


def test_wildcard_and_blank_source_support_identity_fail_closed() -> None:
    valid = _fact()
    wildcard_authority = valid.authority.model_copy(update={"source_revision_id": "revision-*"})
    wildcard = valid.model_copy(update={"authority": wildcard_authority})
    blank = valid.model_copy(update={"supporting_source_revision_ids": ("",)})
    for forged in (wildcard, blank):
        with pytest.raises(IncrementalCompilationError, match="invalid_fact"):
            _compile(candidates=(forged,))


def test_compile_revalidates_model_copy_bypasses() -> None:
    missing_value = _fact().model_copy(update={"value_hash": None})
    missing_support = _fact().model_copy(update={"supporting_source_revision_ids": ()})
    for forged in (missing_value, missing_support):
        with pytest.raises(IncrementalCompilationError, match="invalid_fact"):
            _compile(candidates=(forged,))


def test_isolated_incremental_import_does_not_load_platform_modules() -> None:
    script = """
import sys
import insurance_harness.knowledge_compiler.incremental_changes
for name in (
    'sqlalchemy',
    'insurance_harness.models',
    'insurance_harness.knowledge.models',
    'insurance_harness.knowledge.publisher',
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_exact_models_reject_extra_members_and_authority_field_drift() -> None:
    raw = _scope().model_dump(mode="python", exclude={"scope_hash"})
    assert FactScopeV1.model_validate({**raw, "conditions": ()}).conditions == ()
    with pytest.raises(ValidationError):
        FactScopeV1.model_validate({**raw, "release_id": "forbidden"})

    unauthorized = _fact(
        field_id=FIELD_A,
        authority=_authority(material_role="rate_table"),
    )
    with pytest.raises(IncrementalCompilationError, match="authority_policy_mismatch"):
        _compile(candidates=(unauthorized,))

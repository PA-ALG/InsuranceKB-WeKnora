"""OpenSpec 052: exact MaterialProfile to existing TemplatePackage binding."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.schemas import load_schema_registry
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

MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "insurance_harness"
    / "compiler"
    / "material_profiles.py"
)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "material_profile_596_1_052.json"
REPOSITORY_ROOT = Path(__file__).parents[2]
SCHEMA_ROOT = REPOSITORY_ROOT / "docs" / "insurance-kb" / "schema-baseline"
CATALOG_HASH = "32651266dcef2c6597b35911906b3d64408bc9c0cabe2db52472f836d519d019"
GOLDEN_IDENTITY = {
    "release_hash": "fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0",
    "artifact_hash": "83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca",
    "approval_subject": "6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b",
}
_HASH_A = "a" * 64


def _module() -> ModuleType:
    assert MODULE_PATH.is_file(), "OpenSpec 052 MaterialProfile binding is missing"
    return importlib.import_module("insurance_harness.compiler.material_profiles")


class _MemoryTemplateCatalog:
    def __init__(self, entries: tuple[TemplateCatalogEntry, ...]) -> None:
        self.entries = {entry.version.scope: entry for entry in entries}
        self.requests: list[TemplateScope] = []

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        self.requests.append(scope)
        return self.entries.get(scope)


def _content(marker: str) -> TemplatePackageContent:
    return TemplatePackageContent(
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
                config_hash=_HASH_A,
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
                migration_id=f"MIG-052-{marker}",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="explicit material and field routing",
                rejected_behavior="filename and fuzzy product dispatch",
                python_target="harness/src/insurance_harness/compiler/material_profiles.py",
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_material_profile_template_binding_052.py",
                ),
            ),
        ),
    )


def _entry(scope: TemplateScope, marker: str) -> TemplateCatalogEntry:
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id=f"052-{marker}-v1",
        scope=scope,
        content=_content(marker),
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


def _template_catalog(
    profile: Any,
    *,
    include_family: bool = True,
    include_foreign_family: bool = False,
) -> _MemoryTemplateCatalog:
    space_id = "space-052"
    scopes = [
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
    ]
    if include_family:
        scopes.append(
            TemplateScope(
                space_id=space_id,
                level="product-family",
                product_line_id="medical",
                document_type_id=profile.document_type_id,
                product_family_id="pingan-eshengbao-zunxiang-medical",
            )
        )
    if include_foreign_family:
        scopes.append(
            TemplateScope(
                space_id=space_id,
                level="product-family",
                product_line_id="medical",
                document_type_id=profile.document_type_id,
                product_family_id="foreign-family",
            )
        )
    return _MemoryTemplateCatalog(
        tuple(_entry(scope, f"{scope.level}-{index}") for index, scope in enumerate(scopes))
    )


def _catalog(module: ModuleType) -> Any:
    return module.load_material_profile_catalog(FIXTURE_PATH)


def _request(
    module: ModuleType,
    catalog: Any,
    role: str,
    **updates: object,
) -> Any:
    profile = next(item for item in catalog.profiles if item.material_role == role)
    values: dict[str, object] = {
        "space_id": "space-052",
        "product_code": "596",
        "product_version": "596-1",
        "schema_version": "v1.1+b31a411c621c",
        "schema_field_ids": catalog.schema_binding.field_ids,
        "source": profile.source,
        "classified_material_role": role,
    }
    values.update(updates)
    return module.MaterialProfileResolutionRequest.model_validate(values)


def _reason(
    module: ModuleType,
    catalog: Any,
    template_catalog: _MemoryTemplateCatalog,
    request: Any,
    reason_code: str,
) -> Any:
    with pytest.raises(module.MaterialProfileResolutionError) as caught:
        module.resolve_material_profile(catalog, template_catalog, request)
    assert caught.value.reason_code == reason_code
    assert caught.value.review_item.reason_code == reason_code
    assert caught.value.review_item.product_version == request.product_version
    return caught.value


def test_material_profile_binding_module_exists() -> None:
    assert MODULE_PATH.is_file(), "OpenSpec 052 MaterialProfile binding is missing"


def test_missing_approved_parse_policy_is_rejected() -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert all("parse_policy" in profile for profile in raw["profiles"])
    for profile in raw["profiles"]:
        profile.pop("parse_policy")

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


def test_profiles_bind_one_parser_neutral_bounded_policy_and_receipt() -> None:
    module = _module()
    catalog = _catalog(module)
    expected_triggers = (
        "required_capability_missing",
        "manifest_digest_or_count_mismatch",
        "locator_invalid_or_required_structure_missing",
        "table_grid_or_span_incomplete",
    )

    for profile in catalog.profiles:
        policy = profile.parse_policy
        assert policy.material_profile_id == profile.profile_id
        assert policy.default_parser_profile_ref == (
            "approved-parser-profile:parser-neutral-default.v1"
        )
        assert policy.bounded_upgrade_profile_ref == (
            "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
        )
        assert policy.upgrade_trigger_conditions == expected_triggers
        assert policy.max_parser_attempts == 2
        assert policy.privacy_policy_ref.startswith("privacy-policy:")
        assert policy.output_policy_ref.startswith("output-policy:")

        result = module.resolve_material_profile(
            catalog,
            _template_catalog(profile),
            _request(module, catalog, profile.material_role),
        )
        receipt = result.parse_policy_receipt
        assert receipt.material_profile_id == profile.profile_id
        assert receipt.required_parse_capabilities == (
            profile.required_parse_capabilities
        )
        assert receipt.policy_id == policy.policy_id
        assert receipt.policy_version == policy.policy_version
        assert receipt.default_parser_profile_ref == (
            policy.default_parser_profile_ref
        )
        assert receipt.bounded_upgrade_profile_ref == (
            policy.bounded_upgrade_profile_ref
        )
        assert receipt.upgrade_trigger_conditions == (
            policy.upgrade_trigger_conditions
        )
        assert receipt.max_parser_attempts == policy.max_parser_attempts
        assert receipt.privacy_policy_ref == policy.privacy_policy_ref
        assert receipt.output_policy_ref == policy.output_policy_ref

    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8").casefold()
    for candidate_name in ("pdfplumber", "mineru", "paddle", "ocr", "vlm"):
        assert candidate_name not in fixture_text


def test_parse_policy_rejects_a_third_parser_attempt() -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["profiles"][0]["parse_policy"]["max_parser_attempts"] = 3

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


def test_parse_policy_rejects_upgrade_without_mechanical_trigger() -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["profiles"][0]["parse_policy"]["upgrade_trigger_conditions"] = []

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


@pytest.mark.parametrize("missing_ref", ("privacy_policy_ref", "output_policy_ref"))
def test_parse_policy_requires_profile_level_policy_refs(missing_ref: str) -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["profiles"][0]["parse_policy"].pop(missing_ref)

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "default_parser_profile_ref",
            [
                "approved-parser-profile:parser-neutral-default.v1",
                "approved-parser-profile:parser-neutral-other.v1",
            ],
        ),
        (
            "bounded_upgrade_profile_ref",
            [
                "approved-parser-profile:parser-neutral-bounded-upgrade.v1",
                "approved-parser-profile:parser-neutral-third.v1",
            ],
        ),
    ],
)
def test_parse_policy_rejects_multiple_or_chained_parser_profiles(
    field: str,
    value: list[str],
) -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["profiles"][0]["parse_policy"][field] = value

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


@pytest.mark.parametrize(
    ("upgrade_ref", "triggers", "attempts"),
    [
        (None, [], 2),
        (None, ["required_capability_missing"], 1),
        (
            "approved-parser-profile:parser-neutral-bounded-upgrade.v1",
            ["required_capability_missing"],
            1,
        ),
    ],
)
def test_parse_policy_attempt_limit_matches_optional_upgrade(
    upgrade_ref: str | None,
    triggers: list[str],
    attempts: int,
) -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    policy = raw["profiles"][0]["parse_policy"]
    policy["bounded_upgrade_profile_ref"] = upgrade_ref
    policy["upgrade_trigger_conditions"] = triggers
    policy["max_parser_attempts"] = attempts

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


def test_parse_policy_allows_explicit_no_upgrade_with_one_attempt() -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    policy = raw["profiles"][0]["parse_policy"]
    policy["bounded_upgrade_profile_ref"] = None
    policy["upgrade_trigger_conditions"] = []
    policy["max_parser_attempts"] = 1

    catalog = module.load_material_profile_catalog_data(raw)

    parsed = catalog.profiles[0].parse_policy
    assert parsed.bounded_upgrade_profile_ref is None
    assert parsed.upgrade_trigger_conditions == ()
    assert parsed.max_parser_attempts == 1


def test_parse_policy_identity_must_match_owning_material_profile() -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw["profiles"][0]["parse_policy"]["material_profile_id"] = (
        "596-1-brochure-v1"
    )

    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)

    assert caught.value.reason_code == "invalid_parse_policy"


def test_exact_catalog_matches_three_pdf_schema_and_golden_identity() -> None:
    module = _module()
    catalog = _catalog(module)
    registry = load_schema_registry(SCHEMA_ROOT)
    medical_ids = tuple(field.field_id for field in registry.line("medical").extractable_fields)
    authority_ids = tuple(
        field_id
        for group in catalog.field_authority_groups
        for field_id in group.field_ids
    )

    assert catalog.product.product_code == "596"
    assert catalog.product.product_version == "596-1"
    assert registry.version == catalog.schema_binding.schema_version
    assert len(medical_ids) == 60
    assert catalog.schema_binding.field_ids == medical_ids
    assert len(authority_ids) == len(set(authority_ids)) == 60
    assert set(authority_ids) == set(medical_ids)
    assert {profile.material_role for profile in catalog.profiles} == {
        "terms",
        "brochure",
        "rate_table",
    }
    for profile in catalog.profiles:
        source_path = REPOSITORY_ROOT / profile.source.path
        assert source_path.is_file()
        assert source_path.stat().st_size == profile.source.size
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == profile.source.sha256
    assert {
        key: getattr(catalog.golden_identity, key) for key in GOLDEN_IDENTITY
    } == GOLDEN_IDENTITY


def test_three_sources_have_deterministic_roles_and_explicit_family_mapping() -> None:
    module = _module()
    catalog = _catalog(module)
    assert catalog.product_family_mapping.mapping_source == (
        "approved_product_version_mapping"
    )
    assert catalog.product_family_mapping.product_family_id == (
        "pingan-eshengbao-zunxiang-medical"
    )

    for role in ("terms", "brochure", "rate_table"):
        profile = next(item for item in catalog.profiles if item.material_role == role)
        template_catalog = _template_catalog(profile)
        result = module.resolve_material_profile(
            catalog,
            template_catalog,
            _request(module, catalog, role),
        )
        assert result.profile.material_role == role
        assert result.product_family_id == "pingan-eshengbao-zunxiang-medical"
        assert result.review_items == ()
        assert len(result.binding_hash) == 64


def test_field_authority_keeps_contract_and_rate_numeric_primary_sources() -> None:
    module = _module()
    catalog = _catalog(module)
    for field_id in (
        "exclusions_official",
        "pre_existing_conditions",
        "zh_09a5d9e54e",
        "zh_3a3e6520a3",
    ):
        authority = catalog.authority_for(field_id)
        assert authority.authority_class == "contract_fact"
        assert authority.primary_role == "terms"
        assert "brochure" in authority.support_roles
    feature = catalog.authority_for("zh_6a3bd6cdbf")
    assert feature.authority_class == "brochure_fact"
    assert feature.primary_role == "brochure"
    for field_id in ("zh_7fe8603c08", "zh_c588207763"):
        rate = catalog.authority_for(field_id)
        assert rate.authority_class == "rate_numeric"
        assert rate.primary_role == "rate_table"
        assert rate.primary_role not in rate.support_roles


def test_existing_four_level_chain_and_explicit_family_fallback_receipt() -> None:
    module = _module()
    catalog = _catalog(module)
    request = _request(module, catalog, "terms")
    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    full_catalog = _template_catalog(profile)
    full = module.resolve_material_profile(catalog, full_catalog, request)
    assert full.template_receipt.requested_levels == (
        "global",
        "product-line",
        "document-type",
        "product-family",
    )
    assert full.template_receipt.resolved_levels == full.template_receipt.requested_levels
    assert full.template_receipt.missing_levels == ()
    assert len(full.template_receipt.source_chain) == 4

    fallback_catalog = _template_catalog(
        profile,
        include_family=False,
        include_foreign_family=True,
    )
    fallback = module.resolve_material_profile(catalog, fallback_catalog, request)
    assert fallback.template_receipt.resolved_levels == (
        "global",
        "product-line",
        "document-type",
    )
    assert fallback.template_receipt.missing_levels == ("product-family",)
    assert all(
        item.scope.product_family_id != "foreign-family"
        for item in fallback.template_receipt.source_chain
    )
    assert fallback.resolved_template.request.product_family_id == (
        "pingan-eshengbao-zunxiang-medical"
    )


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ({"product_version": "596-2"}, "product_identity_mismatch"),
        ({"schema_version": "v1.1+drift"}, "schema_identity_mismatch"),
    ],
)
def test_identity_drift_is_typed_and_stops_before_template_lookup(
    mutation: Mapping[str, object],
    reason_code: str,
) -> None:
    module = _module()
    catalog = _catalog(module)
    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    template_catalog = _template_catalog(profile)
    request = _request(module, catalog, "terms", **mutation)
    _reason(module, catalog, template_catalog, request, reason_code)
    assert template_catalog.requests == []


def test_schema_bijection_and_source_bytes_drift_fail_closed() -> None:
    module = _module()
    catalog = _catalog(module)
    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    template_catalog = _template_catalog(profile)
    schema_request = _request(
        module,
        catalog,
        "terms",
        schema_field_ids=catalog.schema_binding.field_ids[:-1],
    )
    _reason(
        module,
        catalog,
        template_catalog,
        schema_request,
        "schema_identity_mismatch",
    )
    source_request = _request(
        module,
        catalog,
        "terms",
        source=profile.source.model_copy(update={"sha256": "0" * 64}),
    )
    _reason(
        module,
        catalog,
        template_catalog,
        source_request,
        "source_identity_mismatch",
    )
    assert template_catalog.requests == []


def test_classifier_conflict_and_filename_guess_create_review_items() -> None:
    module = _module()
    catalog = _catalog(module)
    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    template_catalog = _template_catalog(profile)
    conflict_request = _request(
        module,
        catalog,
        "terms",
        classified_material_role="brochure",
    )
    conflict = _reason(
        module,
        catalog,
        template_catalog,
        conflict_request,
        "material_role_conflict",
    )
    assert conflict.review_item.expected == "terms"
    assert conflict.review_item.observed == "brochure"

    fake = profile.source.model_copy(
        update={"path": "dataset/unregistered/保险条款.pdf"}
    )
    fake_request = _request(module, catalog, "terms", source=fake)
    _reason(
        module,
        catalog,
        template_catalog,
        fake_request,
        "source_not_registered",
    )
    assert template_catalog.requests == []


def test_resolver_inputs_exclude_family_model_and_golden_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    catalog = _catalog(module)
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "596.jsonl" not in fixture_text
    assert "review-and-approval.json" not in fixture_text
    assert set(module.MaterialProfileResolutionRequest.model_fields).isdisjoint(
        {
            "file_name",
            "model",
            "parser_metadata",
            "product_family_id",
            "golden_path",
            "golden_records",
        }
    )
    request_values = _request(module, catalog, "terms").model_dump(mode="python")
    with pytest.raises(ValidationError):
        module.MaterialProfileResolutionRequest.model_validate(
            {**request_values, "golden_path": "596.jsonl"}
        )

    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    template_catalog = _template_catalog(profile)

    def fail_read(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("resolution performed forbidden file I/O")

    monkeypatch.setattr(Path, "read_text", fail_read)
    result = module.resolve_material_profile(
        catalog,
        template_catalog,
        _request(module, catalog, "terms"),
    )
    assert result.golden_identity == catalog.golden_identity


def test_catalog_c0_hash_is_stable_and_binding_hash_covers_template_chain() -> None:
    module = _module()
    catalog = _catalog(module)
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    reordered = dict(reversed(tuple(raw.items())))
    assert module.material_profile_catalog_hash(catalog) == CATALOG_HASH
    assert (
        module.material_profile_catalog_hash(
            module.load_material_profile_catalog_data(reordered)
        )
        == CATALOG_HASH
    )

    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    full = module.resolve_material_profile(
        catalog,
        _template_catalog(profile),
        _request(module, catalog, "terms"),
    )
    fallback = module.resolve_material_profile(
        catalog,
        _template_catalog(profile, include_family=False),
        _request(module, catalog, "terms"),
    )
    assert full.binding_hash != fallback.binding_hash
    assert full.binding_hash != full.resolved_template.content_hash


def test_catalog_and_binding_c0_cover_capabilities_and_parse_policy_refs() -> None:
    module = _module()
    catalog = _catalog(module)
    profile = next(item for item in catalog.profiles if item.material_role == "terms")
    template_catalog = _template_catalog(profile)
    request = _request(module, catalog, "terms")
    original = module.resolve_material_profile(catalog, template_catalog, request)
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    capabilities_raw = json.loads(json.dumps(raw))
    capabilities_raw["profiles"][0]["required_parse_capabilities"].append(
        "reading_order_edges"
    )
    capabilities_catalog = module.load_material_profile_catalog_data(capabilities_raw)
    assert module.material_profile_catalog_hash(capabilities_catalog) != (
        original.catalog_hash
    )
    capabilities_changed = module.resolve_material_profile(
        capabilities_catalog,
        _template_catalog(profile),
        _request(module, capabilities_catalog, "terms"),
    )
    assert capabilities_changed.binding_hash != original.binding_hash
    assert capabilities_changed.parse_policy_receipt.required_parse_capabilities[-1] == (
        "reading_order_edges"
    )

    policy_raw = json.loads(json.dumps(raw))
    policy_raw["profiles"][0]["parse_policy"]["privacy_policy_ref"] = (
        "privacy-policy:source-revision-private-processing.v2"
    )
    policy_catalog = module.load_material_profile_catalog_data(policy_raw)
    changed = module.resolve_material_profile(
        policy_catalog,
        _template_catalog(profile),
        _request(module, policy_catalog, "terms"),
    )
    assert changed.catalog_hash != original.catalog_hash
    assert changed.binding_hash != original.binding_hash
    assert changed.parse_policy_receipt.privacy_policy_ref.endswith(".v2")


@pytest.mark.parametrize("mutation", ("rate_primary", "field_missing"))
def test_catalog_rejects_authority_or_bijection_drift(mutation: str) -> None:
    module = _module()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if mutation == "rate_primary":
        raw["field_authority_groups"][2]["primary_role"] = "terms"
    else:
        raw["field_authority_groups"][0]["field_ids"].pop()
    with pytest.raises(module.MaterialProfileCatalogError) as caught:
        module.load_material_profile_catalog_data(raw)
    assert caught.value.reason_code in {
        "invalid_field_authority",
        "invalid_field_bijection",
    }


def test_template_failure_is_typed_review_without_guessing_fallback() -> None:
    module = _module()
    catalog = _catalog(module)
    empty = _MemoryTemplateCatalog(())
    caught = _reason(
        module,
        catalog,
        empty,
        _request(module, catalog, "terms"),
        "template_resolution_failed",
    )
    assert caught.review_item.observed == "unresolved_scope"
    assert len(empty.requests) == 4


def test_module_stays_in_c_scope_without_b_or_runtime_platforms() -> None:
    _module()
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "ParsedDocument",
        "ParseManifest",
        "sqlalchemy",
        "httpx",
        "weknora",
        "insurance_harness.goldenset",
    ):
        assert forbidden not in source

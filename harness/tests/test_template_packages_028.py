"""OpenSpec 028a pure-domain contracts for approved template packages."""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    ResolutionRequest,
    ResolvedTemplate,
    ResolvedTemplateSource,
    TemplateApproval,
    TemplateCatalog,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateResolutionError,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
    canonical_content_hash,
    resolve_template,
)

_SOURCE_REPOSITORY = "silvielala412-lab/LLM-wiki-black"
_SOURCE_BRANCH = "feature/product-catalog-domain"
_SOURCE_COMMIT = "6a8a1d98de405b6a2837090ee2d43769b4c89be7"
_HASH_A = "a" * 64
_ScopeLevel = Literal["global", "product-line", "document-type", "product-family"]
_ApprovalState = Literal["approved", "pending", "revoked"]
_REPOSITORY_ROOT = Path(__file__).parents[2]
_PACKAGE_ROOT = (
    Path(__file__).parents[1] / "src" / "insurance_harness" / "template_packages"
)
_PYTHON_DOMAIN_ROOT = _PACKAGE_ROOT.parent


def _receipt(
    behavior: str,
    *,
    source_path: str = "frontend/src/lib/product-catalog-modules.ts",
    python_target: str = "harness/src/insurance_harness/template_packages/models.py",
) -> ProvenanceReceipt:
    return ProvenanceReceipt(
        migration_id=f"MIG-028A-{behavior}",
        source_repository=_SOURCE_REPOSITORY,
        source_branch=_SOURCE_BRANCH,
        source_commit=_SOURCE_COMMIT,
        source_path=source_path,
        source_language="typescript",
        rights_status="project-owned",
        accepted_behavior=f"{behavior}: explicit field groups and document routing facts",
        rejected_behavior=f"{behavior}: frontend runtime, fuzzy product-name dispatch, and state",
        python_target=python_target,
        translation_method="behavior_port_with_characterization_tests",
        characterization_tests=(
            "harness/tests/test_template_packages_028.py",
            "harness/tests/test_product_routing.py",
        ),
    )


def _content(
    marker: str,
    *,
    groups: tuple[FieldGroup, ...] | None = None,
    prompts: Mapping[str, str] | None = None,
    validators: tuple[ValidatorRef, ...] | None = None,
    limits: Mapping[str, int] | None = None,
    evidence_policy: EvidencePolicy | None = None,
    golden_slice_ref: str | None = None,
    provenance: tuple[ProvenanceReceipt, ...] | None = None,
) -> TemplatePackageContent:
    return TemplatePackageContent(
        schema_version="insurance-template.v1",
        field_groups=groups
        or (
            FieldGroup(
                group_id=f"group-{marker}",
                field_ids=(f"field-{marker}",),
                evidence_roles=("terms",),
            ),
        ),
        role_prompts=prompts or {"extract": f"extract-{marker}"},
        validators=validators
        or (
            ValidatorRef(
                validator_id=f"validator-{marker}",
                validator_version="v1",
                config_hash=_HASH_A,
            ),
        ),
        evidence_policy=evidence_policy
        or EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits=limits or {"extract": 1},
        golden_slice_ref=golden_slice_ref or f"golden-{marker}",
        provenance=provenance or (_receipt(marker),),
    )


def _scope(
    level: _ScopeLevel,
    *,
    space_id: str = "space-a",
    product_line_id: str | None = None,
    document_type_id: str | None = None,
    product_family_id: str | None = None,
) -> TemplateScope:
    return TemplateScope(
        space_id=space_id,
        level=level,
        product_line_id=product_line_id,
        document_type_id=document_type_id,
        product_family_id=product_family_id,
    )


def _entry(
    scope: TemplateScope,
    content: TemplatePackageContent,
    *,
    version_id: str,
    approval_state: _ApprovalState = "approved",
    approved_hash: str | None = None,
) -> TemplateCatalogEntry:
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id=version_id,
        scope=scope,
        content=content,
    )
    approval = TemplateApproval(
        approval_id=f"approval-{version_id}",
        package_id=version.package_id,
        version_id=version.version_id,
        scope=scope,
        content_hash=approved_hash or version.content_hash,
        state=approval_state,
    )
    return TemplateCatalogEntry(version=version, approval=approval)


class _MemoryCatalog:
    def __init__(self, entries: tuple[TemplateCatalogEntry, ...]) -> None:
        self._entries = {entry.version.scope: entry for entry in entries}
        self.requests: list[TemplateScope] = []

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        self.requests.append(scope)
        return self._entries.get(scope)


class _FixedCatalog:
    """Hostile adapter used to prove the resolver distrusts returned scope."""

    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self._entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self._entry


class _RequestMutatingCatalog:
    """Mutate the caller DTO after the first lookup to exercise snapshot isolation."""

    def __init__(
        self,
        request: ResolutionRequest,
        global_entry: TemplateCatalogEntry,
    ) -> None:
        self._request = request
        self._global_entry = global_entry
        self.requests: list[TemplateScope] = []

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        self.requests.append(scope)
        if len(self.requests) == 1:
            object.__setattr__(self._request, "space_id", "space-b")
            return self._global_entry
        return None


class _ScopeMutatingCatalog:
    """Coordinate mutation of the exact query DTO with a foreign result."""

    def __init__(self, foreign_entry: TemplateCatalogEntry) -> None:
        self._foreign_entry = foreign_entry
        self.requests: list[TemplateScope] = []

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        self.requests.append(scope)
        object.__setattr__(scope, "space_id", self._foreign_entry.version.scope.space_id)
        return self._foreign_entry


class _HostileScopeValueCatalog:
    """Replace a query primitive with an equality trap before returning."""

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        object.__setattr__(scope, "space_id", _ExplodingHash())
        return None


class _LookupFailingCatalog:
    def __init__(self) -> None:
        self.requests: list[TemplateScope] = []

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        self.requests.append(scope)
        raise RuntimeError("catalog unavailable")


class _DuplicateItemsMapping(dict[str, object]):
    def items(self) -> object:  # type: ignore[override]
        return (("extract", self["first"]), ("extract", self["second"]))


class _RaisingItemsMapping(dict[str, object]):
    def items(self) -> object:  # type: ignore[override]
        raise RuntimeError("hostile mapping items")


class _ResolutionRequestSubclass(ResolutionRequest):
    pass


class _TemplateCatalogEntrySubclass(TemplateCatalogEntry):
    pass


class _TemplateVersionSubclass(TemplateVersion):
    pass


class _TemplateApprovalSubclass(TemplateApproval):
    pass


class _ExplodingHash:
    def __eq__(self, other: object) -> bool:
        del other
        raise RuntimeError("hostile equality")


def _request(*, space_id: str = "space-a", family_id: str = "family-ordinary") -> ResolutionRequest:
    return ResolutionRequest(
        space_id=space_id,
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id=family_id,
    )


def _stacked_resolved() -> ResolvedTemplate:
    request = _request()
    scopes = (
        _scope("global"),
        _scope("product-line", product_line_id=request.product_line_id),
        _scope(
            "document-type",
            product_line_id=request.product_line_id,
            document_type_id=request.document_type_id,
        ),
        _scope(
            "product-family",
            product_line_id=request.product_line_id,
            document_type_id=request.document_type_id,
            product_family_id=request.product_family_id,
        ),
    )
    return resolve_template(
        _MemoryCatalog(
            tuple(
                _entry(scope, _content(f"source-{index}"), version_id=f"v{index}")
                for index, scope in enumerate(scopes)
            )
        ),
        request,
    )


def test_tr1_canonical_hash_is_stable_and_covers_every_content_byte() -> None:
    left = _content(
        "stable",
        prompts={"verify": "verify-stable", "extract": "extract-stable"},
        limits={"verify": 2, "extract": 1},
    )
    reordered = _content(
        "stable",
        prompts={"extract": "extract-stable", "verify": "verify-stable"},
        limits={"extract": 1, "verify": 2},
    )
    one_byte_changed = reordered.model_copy(
        update={"role_prompts": {"extract": "extract-stablE", "verify": "verify-stable"}}
    )

    assert canonical_content_hash(left) == canonical_content_hash(reordered)
    assert canonical_content_hash(left) != canonical_content_hash(one_byte_changed)
    assert len(canonical_content_hash(left)) == 64


def test_tr1_hash_contract_has_stable_domain_and_version_prefix() -> None:
    content = _content("domain")
    canonical_json = json.dumps(
        content.model_dump(mode="json", round_trip=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    expected = hashlib.sha256(
        b"insurancekb.template-package.content.v1\0" + canonical_json
    ).hexdigest()
    assert canonical_content_hash(content) == expected


@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
def test_tr1_content_rejects_non_unicode_scalar_text_before_hash(surrogate: str) -> None:
    with pytest.raises(ValidationError, match="Unicode scalar"):
        _content("surrogate", prompts={"extract": f"prompt-{surrogate}"})


def test_tr1_public_hash_revalidates_construct_copy_and_serialized_content() -> None:
    content = _content("hash-sink")
    expected = canonical_content_hash(content)
    serialized = TemplatePackageContent.model_validate_json(content.model_dump_json())
    constructed = TemplatePackageContent.model_construct(
        **content.model_dump(mode="python", round_trip=True)
    )

    assert canonical_content_hash(copy.copy(content)) == expected
    assert canonical_content_hash(copy.deepcopy(content)) == expected
    assert canonical_content_hash(serialized) == expected
    assert canonical_content_hash(constructed) == expected

    invalid_construct = TemplatePackageContent.model_construct(
        **{
            **content.model_dump(mode="python", round_trip=True),
            "attempt_limits": {"extract": True},
        }
    )
    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(invalid_construct)


def test_tr1_public_hash_rejects_extra_top_level_or_nested_storage() -> None:
    plain_mapping = _content("plain-mapping").model_dump(
        mode="python",
        round_trip=True,
    )
    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(plain_mapping)  # type: ignore[arg-type]

    top_level = _content("top-storage")
    object.__getattribute__(top_level, "__dict__")["unvalidated_extra"] = "ignored"
    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(top_level)

    nested = _content("nested-storage")
    object.__getattribute__(nested.field_groups[0], "__dict__")[
        "unvalidated_extra"
    ] = "ignored"
    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(nested)


def test_tr1_public_hash_normalizes_hostile_mapping_exception() -> None:
    content = _content("raising-mapping")
    poisoned = TemplatePackageContent.model_construct(
        **{
            **{
                field_name: getattr(content, field_name)
                for field_name in TemplatePackageContent.model_fields
            },
            "role_prompts": _RaisingItemsMapping(extract="prompt"),
        }
    )

    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(poisoned)


@pytest.mark.parametrize(
    "storage_name",
    ["__pydantic_extra__", "__pydantic_private__", "__pydantic_fields_set__"],
)
def test_tr1_public_hash_rejects_hidden_pydantic_storage(
    storage_name: str,
) -> None:
    top_content = _content(f"hidden-top-{storage_name}")
    nested_content = _content(f"hidden-nested-{storage_name}")
    for content, target in (
        (top_content, top_content),
        (nested_content, nested_content.field_groups[0]),
    ):
        if storage_name == "__pydantic_fields_set__":
            fields_set = set(object.__getattribute__(target, storage_name))
            fields_set.add("unhashed")
            object.__setattr__(target, storage_name, fields_set)
        else:
            object.__setattr__(target, storage_name, {"unhashed": "authority"})
        with pytest.raises(ValueError, match="invalid_template_content"):
            canonical_content_hash(content)


def test_tr1_public_hash_rejects_empty_fields_set_top_level_or_nested() -> None:
    top_content = _content("empty-fields-top")
    object.__setattr__(top_content, "__pydantic_fields_set__", set())
    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(top_content)

    nested_content = _content("empty-fields-nested")
    object.__setattr__(
        nested_content.field_groups[0],
        "__pydantic_fields_set__",
        set(),
    )
    with pytest.raises(ValueError, match="invalid_template_content"):
        canonical_content_hash(nested_content)


@pytest.mark.parametrize(
    "changed_prompt",
    ["extract-stable ", " extract-stable", "extract-stable\n"],
)
def test_tr1_prompt_whitespace_bytes_are_preserved_in_full_hash(
    changed_prompt: str,
) -> None:
    original = _content("stable", prompts={"extract": "extract-stable"})
    changed = original.model_copy(update={"role_prompts": {"extract": changed_prompt}})

    assert changed.role_prompts["extract"] == changed_prompt
    assert canonical_content_hash(original) != canonical_content_hash(changed)


def test_tr1_full_hash_accepts_representative_multisection_prompt() -> None:
    prompt = "system\n" + ("evidence-first extraction instructions\n" * 40)
    content = _content("long-prompt", prompts={"extract": prompt})

    assert len(prompt) > 512
    assert content.role_prompts["extract"] == prompt
    assert len(canonical_content_hash(content)) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role_prompts", {" extract": "prompt", "extract": "other"}),
        ("attempt_limits", {" extract": 1, "extract": 2}),
    ],
)
def test_tr1_mapping_keys_must_arrive_in_canonical_form(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _content("canonical-keys").model_copy(update={field: value})


@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_tr1_attempt_limits_require_strict_positive_integers(value: object) -> None:
    with pytest.raises(ValidationError):
        _content("strict-attempts").model_copy(
            update={"attempt_limits": {"extract": value}}
        )


@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_tr1_evidence_minimum_sources_requires_strict_positive_integer(
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "role_prompts",
            _DuplicateItemsMapping(first="prompt-one", second="prompt-two"),
        ),
        ("attempt_limits", _DuplicateItemsMapping(first=1, second=2)),
        ("role_prompts", [("extract", "prompt")]),
        ("attempt_limits", [("extract", 1)]),
    ],
)
def test_tr1_mapping_inputs_reject_duplicate_or_iterable_ambiguity(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match="mapping"):
        _content("ambiguous-mapping").model_copy(update={field: value})


def test_tr1_content_is_deeply_immutable() -> None:
    content = _content("immutable")

    with pytest.raises(ValidationError):
        content.schema_version = "tampered"
    with pytest.raises(TypeError):
        content.role_prompts["extract"] = "tampered"  # type: ignore[index]
    with pytest.raises(TypeError):
        content.attempt_limits["extract"] = 99  # type: ignore[index]


@pytest.mark.parametrize("approval_state", ["pending", "revoked"])
def test_tr1_unapproved_template_fails_closed(approval_state: _ApprovalState) -> None:
    global_scope = _scope("global")
    catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("unapproved"),
                version_id="global-v1",
                approval_state=approval_state,
            ),
        )
    )

    with pytest.raises(TemplateResolutionError, match="unapproved") as exc_info:
        resolve_template(catalog, _request())

    assert exc_info.value.reason_code == "unapproved"


def test_tr1_old_approval_does_not_authorize_changed_full_content() -> None:
    global_scope = _scope("global")
    original = _entry(global_scope, _content("before"), version_id="global-v1")
    changed = _entry(
        global_scope,
        _content("after"),
        version_id="global-v2",
        approved_hash=original.version.content_hash,
    )

    with pytest.raises(TemplateResolutionError, match="approval_hash_mismatch") as exc_info:
        resolve_template(_MemoryCatalog((changed,)), _request())

    assert exc_info.value.reason_code == "approval_hash_mismatch"


def test_tr1_old_approval_does_not_authorize_prompt_whitespace_change() -> None:
    global_scope = _scope("global")
    original = _entry(
        global_scope,
        _content("before", prompts={"extract": "exact prompt"}),
        version_id="global-v1",
    )
    changed = _entry(
        global_scope,
        _content("after", prompts={"extract": "exact prompt\n"}),
        version_id="global-v2",
        approved_hash=original.version.content_hash,
    )

    with pytest.raises(TemplateResolutionError, match="approval_hash_mismatch"):
        resolve_template(_MemoryCatalog((changed,)), _request())


@pytest.mark.parametrize(
    ("approval_field", "wrong_value"),
    [
        ("package_id", "other-package"),
        ("version_id", "other-version"),
        ("scope", _scope("global", space_id="space-b")),
    ],
)
def test_tr1_approval_must_bind_exact_package_version_and_scope(
    approval_field: str,
    wrong_value: object,
) -> None:
    global_scope = _scope("global")
    valid = _entry(global_scope, _content("binding"), version_id="global-v1")
    mismatched = TemplateCatalogEntry(
        version=valid.version,
        approval=valid.approval.model_copy(update={approval_field: wrong_value}),
    )

    with pytest.raises(TemplateResolutionError, match="approval_binding_mismatch") as exc_info:
        resolve_template(_MemoryCatalog((mismatched,)), _request())

    assert exc_info.value.reason_code == "approval_binding_mismatch"


def test_tr1_corrupt_persisted_full_hash_is_recomputed_at_resolver_boundary() -> None:
    global_scope = _scope("global")
    valid = _entry(global_scope, _content("valid"), version_id="global-v1")
    corrupt_version = TemplateVersion.model_construct(
        package_id=valid.version.package_id,
        version_id=valid.version.version_id,
        scope=valid.version.scope,
        content=valid.version.content,
        content_hash="0" * 64,
    )
    corrupt = TemplateCatalogEntry.model_construct(
        version=corrupt_version,
        approval=valid.approval,
    )

    with pytest.raises(TemplateResolutionError, match="content_hash_mismatch") as exc_info:
        resolve_template(_MemoryCatalog((corrupt,)), _request())

    assert exc_info.value.reason_code == "content_hash_mismatch"


def test_tr1_partial_catalog_dtos_fail_with_typed_boundary_error() -> None:
    global_scope = _scope("global")
    valid = _entry(global_scope, _content("partial"), version_id="global-v1")
    partial_version = TemplateVersion.model_construct(content=valid.version.content)
    partial_approval = TemplateApproval.model_construct(state="approved")
    hostile_hash_version = TemplateVersion.model_construct(
        **{
            **{
                field_name: getattr(valid.version, field_name)
                for field_name in TemplateVersion.model_fields
            },
            "content_hash": _ExplodingHash(),
        }
    )
    subclassed_version = _TemplateVersionSubclass.model_validate(
        valid.version.model_dump(mode="python", round_trip=True)
    )
    subclassed_approval = _TemplateApprovalSubclass.model_validate(
        valid.approval.model_dump(mode="python", round_trip=True)
    )
    candidates = (
        TemplateCatalogEntry.model_construct(
            version=partial_version,
            approval=valid.approval,
        ),
        TemplateCatalogEntry.model_construct(
            version=valid.version,
            approval=partial_approval,
        ),
        _TemplateCatalogEntrySubclass(
            version=valid.version,
            approval=valid.approval,
        ),
        TemplateCatalogEntry.model_construct(
            version=hostile_hash_version,
            approval=valid.approval,
        ),
        TemplateCatalogEntry.model_construct(
            version=subclassed_version,
            approval=valid.approval,
        ),
        TemplateCatalogEntry.model_construct(
            version=valid.version,
            approval=subclassed_approval,
        ),
    )

    for candidate in candidates:
        with pytest.raises(
            TemplateResolutionError,
            match="invalid_catalog_entry",
        ) as exc_info:
            resolve_template(_FixedCatalog(candidate), _request())
        assert exc_info.value.reason_code == "invalid_catalog_entry"


@pytest.mark.parametrize("invalid_part", ["package", "version", "scope", "approval"])
def test_tr1_invalid_catalog_structure_precedes_wrong_but_well_formed_hash(
    invalid_part: str,
) -> None:
    global_scope = _scope("global")
    valid = _entry(global_scope, _content("invalid-structure"), version_id="global-v1")
    version_values = {
        field_name: getattr(valid.version, field_name)
        for field_name in TemplateVersion.model_fields
    }
    approval_values = {
        field_name: getattr(valid.approval, field_name)
        for field_name in TemplateApproval.model_fields
    }
    version_values["content_hash"] = "0" * 64
    if invalid_part == "package":
        version_values["package_id"] = ""
    elif invalid_part == "version":
        version_values["version_id"] = ""
    elif invalid_part == "scope":
        version_values["scope"] = TemplateScope.model_construct(
            space_id="space-a",
            level="global",
            product_line_id="unexpected",
        )
    else:
        approval_values["approval_id"] = ""
    candidate = TemplateCatalogEntry.model_construct(
        version=TemplateVersion.model_construct(**version_values),
        approval=TemplateApproval.model_construct(**approval_values),
    )

    with pytest.raises(
        TemplateResolutionError,
        match="invalid_catalog_entry",
    ) as exc_info:
        resolve_template(_FixedCatalog(candidate), _request())
    assert exc_info.value.reason_code == "invalid_catalog_entry"


def test_tr1_cross_space_catalog_result_fails_closed() -> None:
    foreign_scope = _scope("global", space_id="space-b")
    foreign = _entry(foreign_scope, _content("foreign"), version_id="global-b-v1")

    with pytest.raises(TemplateResolutionError, match="scope_mismatch") as exc_info:
        resolve_template(_FixedCatalog(foreign), _request(space_id="space-a"))

    assert exc_info.value.reason_code == "scope_mismatch"


def test_tr1_catalog_cannot_mutate_query_scope_into_foreign_authority() -> None:
    foreign_scope = _scope("global", space_id="space-b")
    foreign = _entry(foreign_scope, _content("foreign"), version_id="global-b-v1")
    catalog = _ScopeMutatingCatalog(foreign)

    with pytest.raises(TemplateResolutionError, match="catalog_scope_mutation") as exc_info:
        resolve_template(catalog, _request(space_id="space-a"))

    assert exc_info.value.reason_code == "catalog_scope_mutation"


def test_tr1_catalog_query_equality_trap_is_typed_scope_mutation() -> None:
    with pytest.raises(
        TemplateResolutionError,
        match="catalog_scope_mutation",
    ) as exc_info:
        resolve_template(_HostileScopeValueCatalog(), _request())

    assert exc_info.value.reason_code == "catalog_scope_mutation"


def test_tr1_catalog_lookup_failure_is_typed_and_stops_later_scopes() -> None:
    catalog = _LookupFailingCatalog()

    with pytest.raises(
        TemplateResolutionError,
        match="catalog_lookup_failed",
    ) as exc_info:
        resolve_template(catalog, _request())

    assert exc_info.value.reason_code == "catalog_lookup_failed"
    assert [scope.level for scope in catalog.requests] == ["global"]


def test_tr1_duplicate_field_group_must_be_identical_or_fail_closed() -> None:
    global_scope = _scope("global")
    family_scope = _scope(
        "product-family",
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id="family-ordinary",
    )
    global_group = FieldGroup(
        group_id="benefits",
        field_ids=("benefit-a", "benefit-b"),
        evidence_roles=("terms", "regulator"),
    )
    identical_catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("group-global", groups=(global_group,)),
                version_id="global-v1",
            ),
            _entry(
                family_scope,
                _content("group-family", groups=(global_group,)),
                version_id="family-v1",
            ),
        )
    )
    assert resolve_template(identical_catalog, _request()).content.field_groups == (
        global_group,
    )

    weakened_group = FieldGroup(
        group_id="benefits",
        field_ids=("benefit-a",),
        evidence_roles=("marketing",),
    )
    conflicting_catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("group-global", groups=(global_group,)),
                version_id="global-v1",
            ),
            _entry(
                family_scope,
                _content("group-family", groups=(weakened_group,)),
                version_id="family-v2",
            ),
        )
    )
    with pytest.raises(TemplateResolutionError, match="field_group_conflict") as exc_info:
        resolve_template(conflicting_catalog, _request())
    assert exc_info.value.reason_code == "field_group_conflict"


def test_tr1_field_ids_must_be_unique_across_groups_in_one_content() -> None:
    with pytest.raises(ValidationError, match="field_ids.*across field_groups"):
        _content(
            "duplicate-field-owner",
            groups=(
                FieldGroup(
                    group_id="benefits",
                    field_ids=("benefit-a",),
                    evidence_roles=("terms", "regulator"),
                ),
                FieldGroup(
                    group_id="benefits-shadow",
                    field_ids=("benefit-a",),
                    evidence_roles=("marketing",),
                ),
            ),
        )


@pytest.mark.parametrize("strict_group_is_global", [True, False])
def test_tr1_overlay_cannot_reuse_field_id_under_a_new_group(
    strict_group_is_global: bool,
) -> None:
    global_scope = _scope("global")
    family_scope = _scope(
        "product-family",
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id="family-ordinary",
    )
    strict_group = FieldGroup(
        group_id="benefits",
        field_ids=("benefit-a",),
        evidence_roles=("terms", "regulator"),
    )
    shadow_group = FieldGroup(
        group_id="benefits-shadow",
        field_ids=("benefit-a",),
        evidence_roles=("marketing",),
    )
    first, second = (
        (strict_group, shadow_group)
        if strict_group_is_global
        else (shadow_group, strict_group)
    )
    catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("field-owner-global", groups=(first,)),
                version_id="global-v1",
            ),
            _entry(
                family_scope,
                _content("field-owner-family", groups=(second,)),
                version_id="family-v1",
            ),
        )
    )

    with pytest.raises(TemplateResolutionError, match="field_group_conflict") as exc_info:
        resolve_template(catalog, _request())
    assert exc_info.value.reason_code == "field_group_conflict"


def test_tr1_evidence_policy_can_only_tighten_across_scope_overlay() -> None:
    global_scope = _scope("global")
    family_scope = _scope(
        "product-family",
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id="family-ordinary",
    )
    strict_global = EvidencePolicy(
        require_quote=True,
        require_locator=True,
        minimum_sources=3,
    )
    weak_family = EvidencePolicy(
        require_quote=False,
        require_locator=False,
        minimum_sources=1,
    )
    catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("strict-global", evidence_policy=strict_global),
                version_id="global-v1",
            ),
            _entry(
                family_scope,
                _content("weak-family", evidence_policy=weak_family),
                version_id="family-v1",
            ),
        )
    )

    resolved = resolve_template(catalog, _request())

    assert resolved.content.evidence_policy == strict_global


def test_tr1_duplicate_validator_must_be_identical_or_fail_closed() -> None:
    global_scope = _scope("global")
    family_scope = _scope(
        "product-family",
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id="family-ordinary",
    )
    validator = ValidatorRef(
        validator_id="evidence-validator",
        validator_version="v1",
        config_hash="1" * 64,
    )
    identical_catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("validator-global", validators=(validator,)),
                version_id="global-v1",
            ),
            _entry(
                family_scope,
                _content("validator-family", validators=(validator,)),
                version_id="family-v1",
            ),
        )
    )
    assert resolve_template(identical_catalog, _request()).content.validators == (validator,)

    conflicting = validator.model_copy(update={"config_hash": "2" * 64})
    conflicting_catalog = _MemoryCatalog(
        (
            _entry(
                global_scope,
                _content("validator-global", validators=(validator,)),
                version_id="global-v1",
            ),
            _entry(
                family_scope,
                _content("validator-family", validators=(conflicting,)),
                version_id="family-v2",
            ),
        )
    )
    with pytest.raises(TemplateResolutionError, match="validator_conflict") as exc_info:
        resolve_template(conflicting_catalog, _request())
    assert exc_info.value.reason_code == "validator_conflict"


def test_tr2_unresolved_applicability_fails_closed() -> None:
    with pytest.raises(TemplateResolutionError, match="unresolved_scope") as exc_info:
        resolve_template(_MemoryCatalog(()), _request())

    assert exc_info.value.reason_code == "unresolved_scope"


@pytest.mark.parametrize(
    "invalid_request",
    [
        ResolutionRequest.model_construct(space_id="space-a"),
        _ResolutionRequestSubclass(
            space_id="space-a",
            product_line_id="line-life",
            document_type_id="document-terms",
            product_family_id="family-ordinary",
        ),
    ],
)
def test_tr2_invalid_or_subclassed_request_is_typed_and_has_zero_catalog_calls(
    invalid_request: ResolutionRequest,
) -> None:
    catalog = _MemoryCatalog(())

    with pytest.raises(TemplateResolutionError, match="invalid_request") as exc_info:
        resolve_template(catalog, invalid_request)

    assert exc_info.value.reason_code == "invalid_request"
    assert catalog.requests == []


def test_tr2_shadowed_request_method_is_typed_and_has_zero_catalog_calls() -> None:
    request = _request()
    catalog = _MemoryCatalog(())

    def exploding_dump(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("hostile request dump")

    object.__setattr__(request, "model_dump", exploding_dump)

    with pytest.raises(TemplateResolutionError, match="invalid_request") as exc_info:
        resolve_template(catalog, request)

    assert exc_info.value.reason_code == "invalid_request"
    assert catalog.requests == []


def test_tr2_request_hidden_extra_storage_is_typed_and_has_zero_catalog_calls() -> None:
    request = _request()
    object.__setattr__(request, "__pydantic_extra__", {"unhashed": "authority"})
    catalog = _MemoryCatalog(())

    with pytest.raises(TemplateResolutionError, match="invalid_request") as exc_info:
        resolve_template(catalog, request)

    assert exc_info.value.reason_code == "invalid_request"
    assert catalog.requests == []


def test_tr2_request_empty_fields_set_is_typed_and_has_zero_catalog_calls() -> None:
    request = _request()
    object.__setattr__(request, "__pydantic_fields_set__", set())
    catalog = _MemoryCatalog(())

    with pytest.raises(TemplateResolutionError, match="invalid_request") as exc_info:
        resolve_template(catalog, request)

    assert exc_info.value.reason_code == "invalid_request"
    assert catalog.requests == []


def test_tr2_catalog_hidden_extra_storage_is_typed_invalid_entry() -> None:
    entry = _entry(_scope("global"), _content("hidden-entry"), version_id="v1")
    object.__setattr__(entry.version, "__pydantic_extra__", {"unhashed": "authority"})

    with pytest.raises(
        TemplateResolutionError,
        match="invalid_catalog_entry",
    ) as exc_info:
        resolve_template(_FixedCatalog(entry), _request())

    assert exc_info.value.reason_code == "invalid_catalog_entry"


@pytest.mark.parametrize(
    "hidden_target",
    ["content-field-group", "version-scope", "approval-scope"],
)
def test_tr2_catalog_nested_hidden_storage_is_typed_invalid_entry(
    hidden_target: str,
) -> None:
    entry = _entry(
        _scope("global"),
        _content(f"hidden-{hidden_target}"),
        version_id="v1",
    )
    if hidden_target == "content-field-group":
        object.__setattr__(
            entry.version.content.field_groups[0],
            "__pydantic_private__",
            {"unhashed": "authority"},
        )
    else:
        scope = entry.version.scope if hidden_target == "version-scope" else entry.approval.scope
        object.__setattr__(scope, "__pydantic_fields_set__", set())

    with pytest.raises(
        TemplateResolutionError,
        match="invalid_catalog_entry",
    ) as exc_info:
        resolve_template(_FixedCatalog(entry), _request())

    assert exc_info.value.reason_code == "invalid_catalog_entry"


def test_tr2_catalog_accepts_natural_scope_fields_set_at_all_levels() -> None:
    scopes = (
        TemplateScope(space_id="space-a", level="global"),
        TemplateScope(
            space_id="space-a",
            level="product-line",
            product_line_id="line-life",
        ),
        TemplateScope(
            space_id="space-a",
            level="document-type",
            product_line_id="line-life",
            document_type_id="document-terms",
        ),
        TemplateScope(
            space_id="space-a",
            level="product-family",
            product_line_id="line-life",
            document_type_id="document-terms",
            product_family_id="family-ordinary",
        ),
    )
    catalog = _MemoryCatalog(
        tuple(
            _entry(
                scope,
                _content(f"natural-scope-{index}"),
                version_id=f"v{index}",
            )
            for index, scope in enumerate(scopes)
        )
    )

    resolved = resolve_template(catalog, _request())

    assert [source.scope.level for source in resolved.source_chain] == [
        "global",
        "product-line",
        "document-type",
        "product-family",
    ]


def test_tr2_catalog_scope_fields_set_cannot_omit_non_none_identity() -> None:
    scope = TemplateScope(
        space_id="space-a",
        level="product-line",
        product_line_id="line-life",
    )
    entry = _entry(scope, _content("scope-fields-omitted"), version_id="v1")
    for bound_scope in (entry.version.scope, entry.approval.scope):
        object.__setattr__(
            bound_scope,
            "__pydantic_fields_set__",
            {"space_id", "level"},
        )

    with pytest.raises(
        TemplateResolutionError,
        match="invalid_catalog_entry",
    ) as exc_info:
        resolve_template(_FixedCatalog(entry), _request())

    assert exc_info.value.reason_code == "invalid_catalog_entry"


def test_tr2_resolver_uses_one_canonical_request_snapshot() -> None:
    request = _request(space_id="space-a")
    global_scope = _scope("global", space_id="space-a")
    entry = _entry(global_scope, _content("snapshot"), version_id="global-v1")
    catalog = _RequestMutatingCatalog(request, entry)

    resolved = resolve_template(catalog, request)

    assert request.space_id == "space-b"
    assert resolved.request.space_id == "space-a"
    assert {scope.space_id for scope in catalog.requests} == {"space-a"}
    assert {source.scope.space_id for source in resolved.source_chain} == {"space-a"}


def test_tr2_resolved_source_chain_carries_hashable_content_facts() -> None:
    resolved = _stacked_resolved()

    assert "content" in ResolvedTemplateSource.model_fields
    assert all(
        source.content_hash == canonical_content_hash(source.content)
        for source in resolved.source_chain
    )


def test_tr2_ordinary_constructor_rejects_cross_space_duplicate_or_unordered_lineage() -> None:
    resolved = _stacked_resolved()
    sources = resolved.source_chain
    foreign_global = sources[0].model_copy(
        update={"scope": _scope("global", space_id="space-b")}
    )
    unrelated_line = sources[1].model_copy(
        update={"scope": _scope("product-line", product_line_id="line-other")}
    )
    bad_chains = (
        (sources[0], sources[0]),
        tuple(reversed(sources)),
        (foreign_global,) + sources[1:],
        (sources[0], unrelated_line) + sources[2:],
    )

    for source_chain in bad_chains:
        with pytest.raises(ValidationError, match="source_chain"):
            ResolvedTemplate(
                request=resolved.request,
                content=resolved.content,
                content_hash=resolved.content_hash,
                source_chain=source_chain,
            )


def test_tr2_ordinary_constructor_rejects_source_or_final_content_mismatch() -> None:
    resolved = _stacked_resolved()
    first = resolved.source_chain[0]
    corrupt_source = ResolvedTemplateSource.model_construct(
        scope=first.scope,
        package_id=first.package_id,
        version_id=first.version_id,
        content=first.content,
        content_hash="0" * 64,
    )
    with pytest.raises(ValidationError, match="content_hash_mismatch"):
        ResolvedTemplate(
            request=resolved.request,
            content=resolved.content,
            content_hash=resolved.content_hash,
            source_chain=(corrupt_source,) + resolved.source_chain[1:],
        )

    unrelated_content = _content("unrelated-final")
    with pytest.raises(ValidationError, match="resolved_content_mismatch"):
        ResolvedTemplate(
            request=resolved.request,
            content=unrelated_content,
            content_hash=canonical_content_hash(unrelated_content),
            source_chain=resolved.source_chain,
        )


def test_tr2_valid_resolved_template_survives_serialization_round_trip() -> None:
    resolved = _stacked_resolved()

    restored = ResolvedTemplate.model_validate_json(resolved.model_dump_json())

    assert restored == resolved


def test_tr2_resolver_applies_stable_order_and_returns_full_source_chain() -> None:
    request = _request()
    scopes = (
        _scope("global"),
        _scope("product-line", product_line_id=request.product_line_id),
        _scope(
            "document-type",
            product_line_id=request.product_line_id,
            document_type_id=request.document_type_id,
        ),
        _scope(
            "product-family",
            product_line_id=request.product_line_id,
            document_type_id=request.document_type_id,
            product_family_id=request.product_family_id,
        ),
    )
    shared = FieldGroup(
        group_id="shared",
        field_ids=("global-field",),
        evidence_roles=("terms",),
    )
    entries = (
        _entry(
            scopes[0],
            _content(
                "global",
                groups=(shared,),
                prompts={"extract": "global-extract", "verify": "global-verify"},
                limits={"extract": 1},
            ),
            version_id="global-v1",
        ),
        _entry(
            scopes[1],
            _content(
                "line",
                groups=(
                    shared,
                    FieldGroup(
                        group_id="line-only",
                        field_ids=("line-only-field",),
                        evidence_roles=("brochure",),
                    ),
                ),
                prompts={"extract": "line-extract"},
                limits={"verify": 2},
            ),
            version_id="line-v1",
        ),
        _entry(
            scopes[2],
            _content(
                "document",
                prompts={"verify": "document-verify"},
                limits={"gap": 1},
            ),
            version_id="document-v1",
        ),
        _entry(
            scopes[3],
            _content(
                "family",
                prompts={"extract": "family-extract"},
                limits={"extract": 2},
                golden_slice_ref="golden-family-final",
            ),
            version_id="family-v1",
        ),
    )
    catalog = _MemoryCatalog(entries)

    resolved = resolve_template(catalog, request)

    assert catalog.requests == list(scopes)
    assert [source.scope.level for source in resolved.source_chain] == [
        "global",
        "product-line",
        "document-type",
        "product-family",
    ]
    assert [source.version_id for source in resolved.source_chain] == [
        "global-v1",
        "line-v1",
        "document-v1",
        "family-v1",
    ]
    assert [group.group_id for group in resolved.content.field_groups] == [
        "shared",
        "line-only",
        "group-document",
        "group-family",
    ]
    assert resolved.content.field_groups[0].field_ids == ("global-field",)
    assert dict(resolved.content.role_prompts) == {
        "extract": "family-extract",
        "verify": "document-verify",
    }
    assert dict(resolved.content.attempt_limits) == {
        "extract": 2,
        "verify": 2,
        "gap": 1,
    }
    assert resolved.content.golden_slice_ref == "golden-family-final"
    assert resolved.content_hash == canonical_content_hash(resolved.content)


def test_tr2_similar_ordinary_and_participating_families_never_share_overlay() -> None:
    global_scope = _scope("global")
    ordinary_scope = _scope(
        "product-family",
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id="family-ordinary",
    )
    participating_scope = _scope(
        "product-family",
        product_line_id="line-life",
        document_type_id="document-terms",
        product_family_id="family-participating",
    )
    catalog = _MemoryCatalog(
        (
            _entry(global_scope, _content("global"), version_id="global-v1"),
            _entry(
                ordinary_scope,
                _content("ordinary", prompts={"extract": "ordinary-only"}),
                version_id="ordinary-v1",
            ),
            _entry(
                participating_scope,
                _content("participating", prompts={"extract": "participating-only"}),
                version_id="participating-v1",
            ),
        )
    )

    ordinary = resolve_template(catalog, _request(family_id="family-ordinary"))
    participating = resolve_template(catalog, _request(family_id="family-participating"))

    assert ordinary.content.role_prompts["extract"] == "ordinary-only"
    assert participating.content.role_prompts["extract"] == "participating-only"
    assert ordinary.content_hash != participating.content_hash
    assert "product_name" not in ResolutionRequest.model_fields
    assert "product_name" not in inspect.getsource(resolve_template)


def test_tr0_provenance_is_exact_metadata_not_a_typescript_runtime_bridge() -> None:
    receipt = _receipt(
        "document-routing",
        source_path="frontend/src/lib/__tests__/product-catalog-document-routing.test.ts",
        python_target="harness/src/insurance_harness/template_packages/resolver.py",
    )

    assert receipt.source_repository == _SOURCE_REPOSITORY
    assert receipt.source_branch == _SOURCE_BRANCH
    assert receipt.source_commit == _SOURCE_COMMIT
    assert receipt.source_path.endswith(".ts")
    assert receipt.python_target.endswith(".py")
    assert receipt.source_language == "typescript"
    assert (_REPOSITORY_ROOT / receipt.python_target).is_file()
    with pytest.raises(ValidationError):
        receipt.model_copy(update={"python_target": "runtime/template-resolver.ts"})


@pytest.mark.parametrize(
    ("field", "noncanonical_path"),
    [
        ("source_path", r"C:\repo\source.ts"),
        ("source_path", "C:/repo/source.ts"),
        ("source_path", "frontend/src/../source.ts"),
        ("source_path", "frontend//source.ts"),
        ("source_path", "frontend/source\x00.ts"),
        ("python_target", r"harness\src\target.py"),
        ("python_target", "/harness/src/target.py"),
        ("characterization_tests", ("harness/tests/../test_escape.py",)),
        ("characterization_tests", ("harness//tests/test_duplicate.py",)),
    ],
)
def test_tr0_provenance_paths_require_canonical_repository_relative_posix_form(
    field: str,
    noncanonical_path: object,
) -> None:
    with pytest.raises(ValidationError):
        _receipt("canonical-path").model_copy(update={field: noncanonical_path})


def test_tr0_package_has_one_read_only_port_and_no_orm_or_node_runtime_surface() -> None:
    expected_files = {"__init__.py", "models.py", "ports.py", "resolver.py"}
    assert {path.name for path in _PACKAGE_ROOT.iterdir() if path.is_file()} == expected_files
    assert not tuple(_PYTHON_DOMAIN_ROOT.rglob("*.ts"))
    assert not tuple(_PYTHON_DOMAIN_ROOT.rglob("*.tsx"))
    assert not tuple(_PYTHON_DOMAIN_ROOT.rglob("package.json"))

    public_protocol_methods = {
        name
        for name, value in vars(TemplateCatalog).items()
        if not name.startswith("_") and callable(value)
    }
    assert public_protocol_methods == {"get_approved"}

    banned_import_roots = {"sqlalchemy", "subprocess", "node", "nodejs", "typescript"}
    for path in sorted(_PACKAGE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert imported_roots.isdisjoint(banned_import_roots), path

    node_executables = {"node", "nodejs", "npm", "npx", "ts-node", "deno", "bun"}
    for path in sorted(_PYTHON_DOMAIN_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
            ):
                continue
            command_literals = {
                child.value.strip().rsplit("/", 1)[-1]
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            assert command_literals.isdisjoint(node_executables), path

    resolver_source = (_PACKAGE_ROOT / "resolver.py").read_text(encoding="utf-8")
    assert "普通终身寿险" not in resolver_source
    assert "分红型" not in resolver_source
    assert ".ts" not in resolver_source

"""OpenSpec 027 PWB2/PWB3 production-entrypoint closure tests."""

from __future__ import annotations

import ast
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.compiler import cli as compiler_cli
from insurance_harness.compiler import llm as llm_module
from insurance_harness.compiler import pipeline as pipeline_module
from insurance_harness.compiler.attempts import SqliteAttemptLedger
from insurance_harness.compiler.extract import call_and_parse
from insurance_harness.compiler.judge import JUDGE_SYSTEM, JudgeDispatcher
from insurance_harness.compiler.models import (
    DeadLetter,
    DocPayload,
    FieldCandidate,
    JudgeRequest,
    RunManifest,
)
from insurance_harness.compiler.pipeline import ExtractionPipeline, PipelineConfig
from insurance_harness.compiler.prompts import EXTRACTION_SYSTEM, PROMPT_VERSION
from insurance_harness.compiler.routing_data import group_of_field
from insurance_harness.compiler.sections import DocSection
from insurance_harness.config import HarnessSettings
from insurance_harness.db import Base, make_engine
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import KnowledgeScope, load_scope
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import Evidence
from insurance_harness.model_policy import (
    AdmissionBinding,
    AdmissionPolicyDenied,
    ModelCallFacts,
    ModelCallRequest,
    ModelIdentity,
    ModelPolicyDenied,
    ModelRole,
    PolicyReceipt,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
)
from insurance_harness.model_policy import composition as composition_module
from insurance_harness.model_policy import gateway as gateway_module
from insurance_harness.model_policy.admission import _issue_verified_admission
from insurance_harness.model_policy.composition import _build_production_model_composition
from insurance_harness.schemas import (
    FieldSpec,
    ProductLineSchema,
    SchemaRegistry,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_INVENTORY_PATH = (
    _REPOSITORY_ROOT
    / "openspec/changes/027-production-weak-model-boundary/artifacts/entrypoint-inventory.md"
)


@dataclass(frozen=True, slots=True)
class _InventoryEntry:
    path: str
    callable: str
    classification: str
    required_guard: str


def _inventory_entries() -> tuple[_InventoryEntry, ...]:
    headings: tuple[str, ...] | None = None
    entries: list[_InventoryEntry] = []
    for raw_line in _INVENTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not raw_line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in raw_line.strip().strip("|").split("|"))
        if cells[:3] == ("Path", "Callable / export", "Classification"):
            headings = cells
            continue
        if headings is None or len(cells) != len(headings) or set(cells[0]) == {"-"}:
            continue
        values = dict(zip(headings, cells, strict=True))
        entries.append(
            _InventoryEntry(
                path=values["Path"],
                callable=values["Callable / export"],
                classification=values["Classification"],
                required_guard=values["Required guard"],
            )
        )
    assert headings is not None, "inventory table header is missing"
    assert entries, "inventory table contains no machine-enumerable entrypoints"
    return tuple(entries)


def _source_path(markdown_path: str) -> Path:
    first_path = markdown_path.split(";")[0].strip().strip("`")
    return _REPOSITORY_ROOT / first_path


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(matches) == 1, f"expected one callable named {name!r}, got {len(matches)}"
    return matches[0]


def _called_names(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Call):
            continue
        if isinstance(candidate.func, ast.Name):
            names.add(candidate.func.id)
        elif isinstance(candidate.func, ast.Attribute):
            names.add(candidate.func.attr)
    return frozenset(names)


def test_pwb2_inventory_drives_real_compiler_entrypoint_closure() -> None:
    """Every production root has code-owned sealed construction and no raw client."""

    entries = _inventory_entries()
    production = tuple(
        entry
        for entry in entries
        if entry.classification.lower().startswith("production")
        and "/compiler/" in entry.path
    )
    assert production, "inventory classifies no compiler production roots"

    proof_rules = {
        "harness/src/insurance_harness/compiler/cli.py": (
            "_cmd_extract",
            "_build_production_compiler_client",
        ),
        "harness/src/insurance_harness/compiler/pipeline.py": (
            "__init__",
            "_require_production_compiler_client",
        ),
    }
    forbidden_raw_constructors = {
        "LiteLLMClient",
        "OpenAICompatClient",
        "ReplayClient",
        "build_client",
    }
    failures: list[str] = []
    covered: set[str] = set()
    for entry in production:
        path = str(_source_path(entry.path).relative_to(_REPOSITORY_ROOT))
        rule = proof_rules.get(path)
        if rule is None:
            failures.append(f"{path}: inventoried production root has no construction proof")
            continue
        callable_name, required = rule
        tree = ast.parse(_source_path(entry.path).read_text(encoding="utf-8"))
        called = _called_names(_find_function(tree, callable_name))
        if required not in called:
            failures.append(f"{path}:{callable_name} does not call {required}")
        leaked = forbidden_raw_constructors.intersection(called)
        if leaked:
            failures.append(
                f"{path}:{callable_name} constructs raw clients: {sorted(leaked)}"
            )
        if path.endswith("compiler/cli.py"):
            factory_calls = _called_names(
                _find_function(tree, "_build_production_compiler_client")
            )
            if "_build_production_model_composition" not in factory_calls:
                failures.append(
                    f"{path}: production factory skips canonical composition"
                )
            factory_leaks = forbidden_raw_constructors.intersection(factory_calls)
            if factory_leaks:
                failures.append(
                    f"{path}: production factory constructs raw clients: "
                    f"{sorted(factory_leaks)}"
                )
        covered.add(path)

    assert covered == set(proof_rules), "inventory and production-root proofs diverged"
    assert not failures, "\n".join(failures)


def test_pwb2_inventory_keeps_library_model_primitives_outside_production_exports() -> None:
    """Raw library calls stay non-production; sealed roots may use their guarded chain."""

    entries = _inventory_entries()
    primitive_rules = {
        "harness/src/insurance_harness/compiler/extract.py": (
            "call_and_parse",
            "_complete_reserved_model_call",
        ),
        "harness/src/insurance_harness/compiler/gapfill.py": (
            "gapfill_field",
            "call_and_parse",
        ),
        "harness/src/insurance_harness/compiler/voting.py": (
            "vote_field",
            "call_and_parse",
        ),
        "harness/src/insurance_harness/compiler/judge.py": (
            "dispatch_audited",
            "call_and_parse",
        ),
    }
    classified = {
        str(_source_path(entry.path).relative_to(_REPOSITORY_ROOT)): entry
        for entry in entries
        if entry.classification.startswith("Library/transport primitive")
        and "/compiler/" in entry.path
    }

    assert set(classified) == set(primitive_rules)
    for path, (callable_name, required) in primitive_rules.items():
        entry = classified[path]
        assert "offline/non-production" in entry.classification
        tree = ast.parse(_source_path(entry.path).read_text(encoding="utf-8"))
        assert required in _called_names(_find_function(tree, callable_name))

    package_tree = ast.parse(
        (
            _REPOSITORY_ROOT
            / "harness/src/insurance_harness/compiler/__init__.py"
        ).read_text(encoding="utf-8")
    )
    package_exports = next(
        ast.literal_eval(node.value)
        for node in package_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    assert {
        "JudgeDispatcher",
        "call_and_parse",
        "gapfill_field",
        "vote_field",
    }.isdisjoint(package_exports)


def test_pwb2_product_cli_classification_remains_deterministic_zero_model() -> None:
    """The product CLI must not opt into the explicitly offline raw-client lane."""

    source = _REPOSITORY_ROOT / "harness/src/insurance_harness/product/cli.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    command = _find_function(tree, "cmd_classify")
    calls = [
        node
        for node in ast.walk(command)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "classify_document"
    ]

    assert len(calls) == 1
    assert len(calls[0].args) == 2
    assert calls[0].keywords == []


_EXPECTED_POLICY_FIELDS = (
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


def _production_settings(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "weknora_base_url": "https://weknora.invalid",
        "weknora_api_key": "weknora-secret",
        "model_profile": "production",
        "production_model_provider": "bailian",
        "production_model_deployment_id": "qwen3-prod-20260722-sha256-a1",
        "production_model_family": "qwen",
        "production_model_policy_version": "pwb-v1",
        "judge_mode": "guarded",
        "llm_base_url": "https://provider.invalid/compatible-mode/v1",
        "llm_api_key": "provider-secret",
    }
    for index, field in enumerate(_EXPECTED_POLICY_FIELDS, start=1):
        if field in {
            "purpose",
            "run_schema_version",
            "run_id",
            "run_revision",
            "space_id",
            "admission_artifact_ref",
        }:
            values[f"production_expected_{field}"] = f"expected-{field}"
        elif field == "clean_integration_sha":
            values[f"production_expected_{field}"] = "d" * 40
        else:
            values[f"production_expected_{field}"] = f"{index:x}"[-1] * 64
    values.update(updates)
    return values


@pytest.mark.parametrize(
    "missing",
    [
        "production_model_provider",
        "production_model_deployment_id",
        "production_model_family",
        "production_model_policy_version",
        "production_expected_purpose",
        "production_expected_run_schema_version",
        "production_expected_space_id",
        "production_expected_run_id",
        "production_expected_run_revision",
        "production_expected_admission_artifact_ref",
        "production_expected_admission_artifact_digest",
        "production_expected_model_plan_hash",
    ],
)
def test_pwb1_production_profile_requires_independent_frozen_policy_inputs(
    missing: str,
) -> None:
    values = _production_settings()
    values.pop(missing)

    with pytest.raises(ValidationError):
        HarnessSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"judge_mode": "gateway"}, "legacy gateway judge"),
        ({"judge_mode": "claude-session"}, "Claude session judge"),
        ({"llm_model_judge_fallback": "deepseek-v4-pro"}, "strong fallback"),
        ({"production_model_provider": "unknown"}, "unknown provider"),
        ({"production_model_deployment_id": "qwen-latest"}, "rolling identity"),
        ({"production_model_deployment_id": "claude-opus"}, "strong identity"),
        ({"production_model_deployment_id": "unknown"}, "unknown identity"),
    ],
)
def test_pwb1_production_profile_rejects_legacy_or_unfrozen_model_routes(
    updates: dict[str, object],
    reason: str,
) -> None:
    del reason
    with pytest.raises(ValidationError):
        HarnessSettings(**_production_settings(**updates))  # type: ignore[arg-type]


def test_pwb4_global_config_has_no_caller_authority_or_runtime_override_fields() -> None:
    forbidden = {
        "admission_binding",
        "admission_state",
        "admission_verifier",
        "model_policy",
        "permit",
        "permit_issuer",
        "guard",
        "call_scope_hash",
        "worker_id",
        "lease_token",
        "mcp_token",
        "mcp_host",
        "mcp_port",
    }

    assert forbidden.isdisjoint(HarnessSettings.model_fields)


class _ReceiptCollector:
    def __init__(self) -> None:
        self.receipts: list[PolicyReceipt] = []

    def record(self, receipt: PolicyReceipt, /) -> None:
        self.receipts.append(receipt)


def _reserved_call_authority(
    *, template_hash: str, schema_hash: str | None = None
) -> tuple[VerifiedAdmission, ModelIdentity, StrictAdmissionRequestBinding]:
    identity = ModelIdentity(
        provider="bailian",
        deployment_id="qwen3-prod-20260722-sha256-a1",
        family="qwen",
        role="extract",
        policy_version="pwb-v1",
    )
    setting_values = _production_settings(
        **(
            {}
            if schema_hash is None
            else {"production_expected_schema_hash": schema_hash}
        )
    )
    request_values = {
        name: value
        for name, value in setting_values.items()
        if name.startswith("production_expected_")
    }
    request = StrictAdmissionRequestBinding.model_validate(
        {
            name.removeprefix("production_"): value
            for name, value in request_values.items()
        }
    )
    binding = AdmissionBinding.model_validate(
        {
            **{
                f"actual_{name.removeprefix('expected_')}": value
                for name, value in request.model_dump().items()
            },
            "actual_state": "READY",
            "actual_expires_at": datetime(2099, 8, 1, tzinfo=UTC),
            "approved_identities": (identity,),
            "approved_template_hashes": (template_hash,),
        }
    )
    verified = _issue_verified_admission(
        request,
        binding,
        verifier_id="027-entrypoint-test",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    return verified, identity, request


def _guarded_test_client(
    *,
    template_hash: str,
    schema_hash: str,
    transport_mode: str | None = None,
) -> tuple[
    object,
    object,
    _ReceiptCollector,
    VerifiedAdmission,
    ModelIdentity,
    StrictAdmissionRequestBinding,
]:
    verified, identity, request = _reserved_call_authority(
        template_hash=template_hash,
        schema_hash=schema_hash,
    )
    composition = _build_production_model_composition(
        approved_identity_keys={identity.identity_key}
    )
    if transport_mode is None:
        target = gateway_module._build_stateful_model_client_target_for_test(
            endpoint="https://provider.invalid",
            model=identity.deployment_id,
            credential="provider-secret",
            result='[{"field_id":"x","value":null,"tri_state":"unknown","evidence":[]}]',
        )
        executor = gateway_module._issue_stateful_model_client_executor_for_test(
            composition=composition,
            transport_identity=identity,
            target=target,
        )
    else:
        executor = gateway_module._issue_test_model_executor_for_test(
            composition=composition,
            transport_identity=identity,
            mode=transport_mode,
        )
        target = executor
    sink = _ReceiptCollector()
    guard = gateway_module._build_guarded_model_client_for_test(
        composition=composition,
        executor=executor,
        receipt_sink=sink,
    )
    client = llm_module._build_production_compiler_client_for_test(
        guarded_clients={"extract": guard},
        verified_admission=verified,
        retained_resources=(target, sink),
    )
    return client, target, sink, verified, identity, request


def _guarded_role_test_client(
    *,
    schema_hash: str,
    role: ModelRole,
    stage: str,
    prompt_version: str,
    system: str,
    transport_mode: str,
) -> tuple[object, object, StrictAdmissionRequestBinding, ModelIdentity]:
    """Build an explicit test-only production client with extract + one model role."""

    extract_identity = ModelIdentity(
        provider="bailian",
        deployment_id="qwen3-prod-20260722-sha256-a1",
        family="qwen",
        role="extract",
        policy_version="pwb-v1",
    )
    role_identity = extract_identity.model_copy(update={"role": role})
    setting_values = _production_settings(production_expected_schema_hash=schema_hash)
    request = StrictAdmissionRequestBinding.model_validate(
        {
            name.removeprefix("production_"): value
            for name, value in setting_values.items()
            if name.startswith("production_expected_")
        }
    )
    extract_template_hash = llm_module._compiler_template_hash(
        stage="extract",
        prompt_version=f"baseline@{PROMPT_VERSION}",
        system=EXTRACTION_SYSTEM,
    )
    role_template_hash = llm_module._compiler_template_hash(
        stage=stage,
        prompt_version=prompt_version,
        system=system,
    )
    binding = AdmissionBinding.model_validate(
        {
            **{
                f"actual_{name.removeprefix('expected_')}": value
                for name, value in request.model_dump().items()
            },
            "actual_state": "READY",
            "actual_expires_at": datetime(2099, 8, 1, tzinfo=UTC),
            "approved_identities": (extract_identity, role_identity),
            "approved_template_hashes": (extract_template_hash, role_template_hash),
        }
    )
    verified = _issue_verified_admission(
        request,
        binding,
        verifier_id="027-entrypoint-role-test",
        verifier_version="v1",
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )
    composition = _build_production_model_composition(
        approved_identity_keys={extract_identity.identity_key, role_identity.identity_key}
    )
    extract_executor = gateway_module._issue_test_model_executor_for_test(
        composition=composition,
        transport_identity=extract_identity,
    )
    role_executor = gateway_module._issue_test_model_executor_for_test(
        composition=composition,
        transport_identity=role_identity,
        mode=transport_mode,
    )
    sink = _ReceiptCollector()
    extract_guard = gateway_module._build_guarded_model_client_for_test(
        composition=composition,
        executor=extract_executor,
        receipt_sink=sink,
    )
    role_guard = gateway_module._build_guarded_model_client_for_test(
        composition=composition,
        executor=role_executor,
        receipt_sink=sink,
    )
    client = llm_module._build_production_compiler_client_for_test(
        guarded_clients={"extract": extract_guard, role: role_guard},
        verified_admission=verified,
        retained_resources=(extract_executor, role_executor, sink),
    )
    return client, role_executor, request, extract_identity


def _production_role_pipeline_fixture(
    tmp_path: Path,
    *,
    role: ModelRole,
    stage: str,
    prompt_version: str,
    system: str,
) -> tuple[
    ExtractionPipeline,
    dict[str, object],
    object,
    StrictAdmissionRequestBinding,
]:
    field = FieldSpec(
        name="等待期",
        field_id="x",
        source_sheet="test",
        risk_level="high",
    )
    registry = SchemaRegistry(
        version="canonical-registry",
        lines={
            "t": ProductLineSchema(
                line_key="t",
                sheet_name="test",
                fields=(field,),
            )
        },
        glossary=(),
    )
    schema_hash = pipeline_module._compiler_schema_hash(registry)
    client, role_executor, request, identity = _guarded_role_test_client(
        schema_hash=schema_hash,
        role=role,
        stage=stage,
        prompt_version=prompt_version,
        system=system,
        transport_mode="failure",
    )
    engine = make_engine(f"sqlite:///{tmp_path}/scope.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            KnowledgeSpace(
                id=request.expected_space_id,
                name="Canonical",
                tenant_id="tenant-canonical",
                raw_kb_id="raw-canonical",
                wiki_kb_id="wiki-canonical",
                binding_status="bound",
            )
        )
        session.commit()
        scope = load_scope(session, request.expected_space_id)
    pipeline = ExtractionPipeline(
        client=client,  # type: ignore[arg-type]
        registry=registry,
        model_id=identity.deployment_id,
        source=object(),  # type: ignore[arg-type]
        config=PipelineConfig(
            model_profile="production",
            judge_mode="guarded",
            transport_attempts=2,
            backoff_base_s=0.0,
        ),
        scope=scope,
    )
    pipeline._test_scope_engine = engine  # type: ignore[attr-defined]  # noqa: SLF001
    page = PageText(page_no=1, text="本合同等待期为90天。")
    payload = DocPayload(
        doc="policy.pdf",
        pages=[page],
        sections=[],
        by_group={},
    )
    state: dict[str, object] = {
        "run_id": request.expected_run_id,
        "run_dir": str(tmp_path),
        "line_key": "t",
        "product_id": "product-1",
        "product_name": "Canonical product",
        "docs": [payload.model_dump(mode="json")],
        "dead_letters": [],
        "judge_queue": [],
        "manifest": RunManifest(
            run_id=request.expected_run_id,
            product_dir="",
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
        ).model_dump(mode="json"),
    }
    return pipeline, state, role_executor, request


def _production_pipeline_fixture(
    tmp_path: Path,
    *,
    transport_mode: str | None = None,
    transport_attempts: int = 3,
) -> tuple[
    ExtractionPipeline,
    dict[str, object],
    object,
    ModelIdentity,
    StrictAdmissionRequestBinding,
    SchemaRegistry,
]:
    field = FieldSpec(name="等待期", field_id="x", source_sheet="test")
    line = ProductLineSchema(line_key="t", sheet_name="test", fields=(field,))
    registry = SchemaRegistry(
        version="canonical-registry",
        lines={"t": line},
        glossary=(),
    )
    schema_hash = pipeline_module._compiler_schema_hash(registry)
    template_hash = llm_module._compiler_template_hash(
        stage="extract",
        prompt_version=f"baseline@{PROMPT_VERSION}",
        system=EXTRACTION_SYSTEM,
    )
    client, target, _sink, _verified, identity, request = _guarded_test_client(
        template_hash=template_hash,
        schema_hash=schema_hash,
        transport_mode=transport_mode,
    )
    engine = make_engine(f"sqlite:///{tmp_path}/scope.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            KnowledgeSpace(
                id=request.expected_space_id,
                name="Canonical",
                tenant_id="tenant-canonical",
                raw_kb_id="raw-canonical",
                wiki_kb_id="wiki-canonical",
                binding_status="bound",
            )
        )
        session.commit()
        scope = load_scope(session, request.expected_space_id)
    pipeline = ExtractionPipeline(
        client=client,  # type: ignore[arg-type]
        registry=registry,
        model_id=identity.deployment_id,
        source=object(),  # type: ignore[arg-type]
        config=PipelineConfig(
            model_profile="production",
            judge_mode="guarded",
            transport_attempts=transport_attempts,
            backoff_base_s=0.0,
        ),
        scope=scope,
    )
    pipeline._test_scope_engine = engine  # type: ignore[attr-defined]  # noqa: SLF001
    page = PageText(page_no=1, text="本合同等待期为90天。")
    section = DocSection(
        section_id="section-1",
        title="等待期",
        headings=("等待期",),
        fragments=(page,),
    )
    payload = DocPayload(
        doc="policy.pdf",
        pages=[page],
        sections=[section],
        by_group={group_of_field(field.name): [section.section_id]},
    )
    state: dict[str, object] = {
        "run_id": request.expected_run_id,
        "run_dir": str(tmp_path),
        "line_key": "t",
        "product_name": "Canonical product",
        "docs": [payload.model_dump(mode="json")],
        "dead_letters": [],
        "manifest": RunManifest(
            run_id=request.expected_run_id,
            product_dir="",
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
        ).model_dump(mode="json"),
    }
    return pipeline, state, target, identity, request, registry


def test_pwb2_reserved_attempt_builds_canonical_guarded_call_facts(
    tmp_path: Path,
) -> None:
    system = "approved extraction system"
    user = "input-content-secret-sentinel"
    stage = "extract"
    prompt_version = "baseline@ep-v1.0"
    schema_registry = SchemaRegistry(
        version="not-the-run-schema-version", lines={}, glossary=()
    )
    assert hasattr(pipeline_module, "_compiler_schema_hash")
    schema_hash = pipeline_module._compiler_schema_hash(schema_registry)
    assert hasattr(llm_module, "_compiler_template_hash")
    template_hash = llm_module._compiler_template_hash(
        stage=stage,
        prompt_version=prompt_version,
        system=system,
    )
    client, target, sink, verified, identity, request = _guarded_test_client(
        template_hash=template_hash,
        schema_hash=schema_hash,
    )
    with pytest.raises(llm_module.ProductionEntrypointDenied):
        llm_module._require_production_compiler_client(
            client,
            schema_hash=schema_hash,
            model_id=identity.deployment_id,
            space_id=None,
        )
    assert (
        llm_module._require_production_compiler_client(
            client,
            schema_hash=schema_hash,
            model_id=identity.deployment_id,
            space_id=request.expected_space_id,
        )
        is client
    )
    with pytest.raises(llm_module.ProductionEntrypointDenied):
        llm_module._require_production_compiler_client(
            client,
            schema_hash="0" * 64,
            model_id=identity.deployment_id,
            space_id=request.expected_space_id,
        )
    ledger = SqliteAttemptLedger(tmp_path / "attempts.sqlite", run_id=request.expected_run_id)

    parsed = asyncio.run(
        call_and_parse(
            client,
            system,
            user,
            ledger=ledger,
            field_ids=("x",),
            stage=stage,
            prompt_version=prompt_version,
        )
    )

    assert parsed.producing_attempt_id is not None
    assert len(sink.receipts) == 1
    assert hasattr(llm_module, "_compiler_input_digest")
    call_request = ModelCallRequest(
        content=user.encode("utf-8"),
        rendered_prompt=system.encode("utf-8"),
    )
    input_digest = llm_module._compiler_input_digest(
        run_id=request.expected_run_id,
        call_stage=stage,
        attempt_id=parsed.producing_attempt_id,
        field_ids=("x",),
        reserved_request_key=hashlib.sha256(
            (system + "\x00" + user).encode("utf-8")
        ).hexdigest()[:16],
    )
    expected_facts = ModelCallFacts(
        job_id=request.expected_run_id,
        stage=stage,
        attempt=1,
        input_digest=input_digest,
        content_digest=hashlib.sha256(call_request.content).hexdigest(),
        rendered_prompt_digest=hashlib.sha256(call_request.rendered_prompt).hexdigest(),
        purpose=request.expected_purpose,
        run_schema_version=request.expected_run_schema_version,
        space_id=request.expected_space_id,
        run_id=request.expected_run_id,
        run_revision=request.expected_run_revision,
        admission_artifact_digest=request.expected_admission_artifact_digest,
        template_hash=template_hash,
        model_plan_hash=request.expected_model_plan_hash,
        identity=identity,
        role="extract",
    )
    receipt = sink.receipts[0]
    assert receipt.call_scope_hash == gateway_module._derive_call_scope_hash(
        expected_facts,
        request.request_digest,
        verified.binding.binding_digest,
        verified.verified_binding_digest,
    )
    assert input_digest != expected_facts.content_digest
    assert user not in receipt.model_dump_json()
    assert gateway_module._test_stateful_target_calls(target) == ((system, user),)


def test_pwb2_production_pipeline_rejects_raw_model_client_before_default_judge() -> None:
    transport_calls: list[tuple[str, str]] = []

    class _RawClient:
        async def complete(self, system: str, user: str) -> str:
            transport_calls.append((system, user))
            raise AssertionError("raw model transport must not be observed")

    registry = SchemaRegistry(version="expected-run_schema_version", lines={}, glossary=())

    with pytest.raises(llm_module.ProductionEntrypointDenied) as denied:
        ExtractionPipeline(
            client=_RawClient(),
            registry=registry,
            model_id="caller-model",
            source=object(),  # type: ignore[arg-type]
            config=PipelineConfig(model_profile="production", judge_mode="guarded"),
        )

    assert denied.value.reason_code == "invalid_production_client"
    assert transport_calls == []


@pytest.mark.parametrize("judge_mode", ["gateway", "claude-session"])
def test_pwb3_production_pipeline_rejects_legacy_judge_mode(judge_mode: str) -> None:
    registry = SchemaRegistry(version="not-run-schema", lines={}, glossary=())
    schema_hash = pipeline_module._compiler_schema_hash(registry)
    template_hash = llm_module._compiler_template_hash(
        stage="extract",
        prompt_version="baseline@ep-v1.0",
        system="approved extraction system",
    )
    client, _target, _sink, _verified, identity, request = _guarded_test_client(
        template_hash=template_hash,
        schema_hash=schema_hash,
    )
    del request

    with pytest.raises(llm_module.ProductionEntrypointDenied) as denied:
        ExtractionPipeline(
            client=client,  # type: ignore[arg-type]
            registry=registry,
            model_id=identity.deployment_id,
            source=object(),  # type: ignore[arg-type]
            config=PipelineConfig(
                model_profile="production",
                judge_mode=judge_mode,
            ),
            scope=None,
        )

    assert denied.value.reason_code == "invalid_production_judge"


def test_pwb2_pipeline_model_profile_defaults_disabled_and_raw_model_fails_closed() -> None:
    class _RawClient:
        async def complete(self, system: str, user: str) -> str:
            del system, user
            return "[]"

    config = PipelineConfig()
    assert config.model_profile == "disabled"

    with pytest.raises(llm_module.ProductionEntrypointDenied):
        ExtractionPipeline(
            client=_RawClient(),
            registry=SchemaRegistry(version="offline-schema", lines={}, glossary=()),
            model_id="raw-model",
            source=object(),  # type: ignore[arg-type]
            config=config,
        )


def test_pwb2_production_pipeline_ignores_post_construction_raw_client_replacement(
    tmp_path: Path,
) -> None:
    pipeline, state, target, _identity, _request, _registry = (
        _production_pipeline_fixture(tmp_path)
    )
    raw_calls: list[tuple[str, str]] = []

    class _RawClient:
        async def complete(self, system: str, user: str) -> str:
            raw_calls.append((system, user))
            return '[{"field_id":"x","value":null,"tri_state":"unknown","evidence":[]}]'

    pipeline._client = _RawClient()  # noqa: SLF001 - coordinated bypass probe

    asyncio.run(pipeline._node_extract(state))  # type: ignore[arg-type]  # noqa: SLF001

    assert raw_calls == []
    assert len(gateway_module._test_stateful_target_calls(target)) == 1


def test_pwb2_production_pipeline_ignores_post_construction_raw_judge_replacement(
    tmp_path: Path,
) -> None:
    pipeline, _state, _target, _identity, request, _registry = (
        _production_pipeline_fixture(tmp_path)
    )
    raw_calls: list[tuple[str, str]] = []

    class _RawClient:
        async def complete(self, system: str, user: str) -> str:
            raw_calls.append((system, user))
            return '[{"field_id":"x","value":null,"tri_state":"unknown","evidence":[]}]'

    pipeline._judge = JudgeDispatcher(  # noqa: SLF001 - coordinated bypass probe
        mode="gateway",
        client=_RawClient(),
    )
    judge_request = JudgeRequest(
        product_id="product-1",
        product_name="Canonical product",
        doc="policy.pdf",
        field_id="x",
        field_name="等待期",
        reason="vote_disagreement",
        candidates=[],
        context_excerpt="",
    )

    with pytest.raises(llm_module.ProductionEntrypointDenied) as denied:
        asyncio.run(
            pipeline._judge.dispatch_audited(  # noqa: SLF001
                judge_request,
                ledger=SqliteAttemptLedger(
                    tmp_path / "judge-attempts.sqlite",
                    run_id=request.expected_run_id,
                ),
            )
        )

    assert denied.value.reason_code == "role_not_admitted"
    assert raw_calls == []


def test_pwb2_production_pipeline_uses_canonical_identity_snapshot_after_replacement(
    tmp_path: Path,
) -> None:
    pipeline, state, target, identity, request, registry = (
        _production_pipeline_fixture(tmp_path)
    )
    pipeline._registry = SchemaRegistry(  # noqa: SLF001 - coordinated bypass probe
        version="attacker-registry",
        lines={},
        glossary=(),
    )
    pipeline._scope = KnowledgeScope(  # noqa: SLF001 - coordinated bypass probe
        space_id="attacker-space",
        tenant_id="attacker-tenant",
        raw_kb_id="attacker-raw",
        wiki_kb_id="attacker-wiki",
    )
    pipeline._model_id = "claude-opus"  # noqa: SLF001 - coordinated bypass probe
    pipeline._cfg = PipelineConfig(  # noqa: SLF001 - coordinated bypass probe
        model_profile="offline-eval"
    )

    resolved = pipeline._resolve_run_identity(  # noqa: SLF001
        run_dir=tmp_path / "resolved-run",
        checkpoint_path=None,
        product_dir=None,
        product_id="product-1",
        product_name="Canonical product",
        line_key="t",
        thread_id=request.expected_run_id,
    )
    asyncio.run(pipeline._node_extract(state))  # type: ignore[arg-type]  # noqa: SLF001

    assert resolved.model_id == identity.deployment_id
    assert resolved.schema_version == registry.version
    assert pipeline._cfg.model_profile == "production"  # noqa: SLF001
    assert pipeline._scope.space_id == request.expected_space_id  # noqa: SLF001
    assert len(gateway_module._test_stateful_target_calls(target)) == 1


def test_pwb3_weak_transport_exhaustion_stays_blocked_without_fallback_or_promotion(
    tmp_path: Path,
) -> None:
    pipeline, state, executor, _identity, _request, _registry = (
        _production_pipeline_fixture(
            tmp_path,
            transport_mode="failure",
            transport_attempts=2,
        )
    )
    strong_or_offline_calls: list[tuple[str, str]] = []

    class _ForbiddenFallback:
        async def complete(self, system: str, user: str) -> str:
            strong_or_offline_calls.append((system, user))
            return "[]"

    pipeline._judge = JudgeDispatcher(  # noqa: SLF001 - fallback observation probe
        mode="gateway",
        client=_ForbiddenFallback(),
    )

    result = asyncio.run(pipeline._node_extract(state))  # type: ignore[arg-type]  # noqa: SLF001
    candidates = [FieldCandidate.model_validate(raw) for raw in result["candidates"]]
    dead_letters = [DeadLetter.model_validate(raw) for raw in result["dead_letters"]]

    assert len(gateway_module._test_executor_terminal_observations(executor)) == 2
    assert strong_or_offline_calls == []
    assert len(candidates) == 1
    assert candidates[0].tri_state == "unknown"
    assert candidates[0].unknown_reason == "dead_letter"
    assert len(dead_letters) == 1
    assert dead_letters[0].attempts == 2
    assert set(result) == {"candidates", "dead_letters", "manifest"}


def test_pwb3_guarded_judge_exhaustion_retries_then_blocks_field(
    tmp_path: Path,
) -> None:
    pipeline, state, executor, _request = _production_role_pipeline_fixture(
        tmp_path,
        role="consensus",
        stage="judge",
        prompt_version=f"judge@{PROMPT_VERSION}",
        system=JUDGE_SYSTEM,
    )
    fallback_calls: list[tuple[str, str]] = []

    class _ForbiddenFallback:
        async def complete(self, system: str, user: str) -> str:
            fallback_calls.append((system, user))
            return "[]"

    pipeline._judge = JudgeDispatcher(  # noqa: SLF001 - fallback observation probe
        mode="gateway",
        client=_ForbiddenFallback(),
    )
    state["candidates"] = [
        FieldCandidate(
            field_id="x",
            field_name="等待期",
            group=group_of_field("等待期"),
            doc="policy.pdf",
            tri_state="unknown",
            unknown_reason="quote_mismatch",
            metadata={
                "rejected_value": "90天",
                "rejected_evidence": [{"page": 1, "quote": "等待期为90天"}],
            },
        ).model_dump(mode="json")
    ]

    result = asyncio.run(pipeline._node_vote(state))  # type: ignore[arg-type]  # noqa: SLF001
    candidates = [FieldCandidate.model_validate(raw) for raw in result["candidates"]]
    dead_letters = [DeadLetter.model_validate(raw) for raw in result["dead_letters"]]

    assert len(gateway_module._test_executor_terminal_observations(executor)) == 2
    assert len(candidates) == 1
    assert candidates[0].tri_state == "unknown"
    assert candidates[0].unknown_reason == "dead_letter"
    assert candidates[0].pending_judge is False
    assert len(dead_letters) == 1
    assert dead_letters[0].attempts == 2
    assert result["judge_queue"] == []
    assert fallback_calls == []
    assert "changeset" not in result


def test_pwb3_guarded_vote_exhaustion_cannot_leave_old_high_candidate_promotable(
    tmp_path: Path,
) -> None:
    pipeline, state, executor, _request = _production_role_pipeline_fixture(
        tmp_path,
        role="verify",
        stage="vote",
        prompt_version=f"vote@{PROMPT_VERSION}",
        system=EXTRACTION_SYSTEM,
    )
    fallback_calls: list[tuple[str, str]] = []

    class _ForbiddenFallback:
        async def complete(self, system: str, user: str) -> str:
            fallback_calls.append((system, user))
            return "[]"

    pipeline._judge = JudgeDispatcher(  # noqa: SLF001 - fallback observation probe
        mode="gateway",
        client=_ForbiddenFallback(),
    )
    state["candidates"] = [
        FieldCandidate(
            field_id="x",
            field_name="等待期",
            group=group_of_field("等待期"),
            doc="policy.pdf",
            value="90天",
            tri_state="present",
            evidence=[Evidence(page=1, quote="本合同等待期为90天。")],
            confidence="high",
        ).model_dump(mode="json")
    ]

    result = asyncio.run(pipeline._node_vote(state))  # type: ignore[arg-type]  # noqa: SLF001
    candidates = [FieldCandidate.model_validate(raw) for raw in result["candidates"]]
    dead_letters = [DeadLetter.model_validate(raw) for raw in result["dead_letters"]]

    assert len(gateway_module._test_executor_terminal_observations(executor)) == 2
    assert len(candidates) == 1
    assert candidates[0].tri_state == "unknown"
    assert candidates[0].unknown_reason == "dead_letter"
    assert candidates[0].confidence == "low"
    assert candidates[0].pending_judge is False
    assert len(dead_letters) == 1
    assert dead_letters[0].attempts == 2
    assert result["judge_queue"] == []
    assert fallback_calls == []
    assert "changeset" not in result


@pytest.mark.parametrize("model_profile", ["offline-eval", "replay"])
def test_pwb2_pipeline_runs_test_double_only_with_explicit_offline_profile(
    model_profile: str,
) -> None:
    class _OfflineClient:
        async def complete(self, system: str, user: str) -> str:
            del system, user
            return "[]"

    pipeline = ExtractionPipeline(
        client=_OfflineClient(),
        registry=SchemaRegistry(version="offline-schema", lines={}, glossary=()),
        model_id="offline-fixture",
        source=object(),  # type: ignore[arg-type]
        config=PipelineConfig.model_validate({"model_profile": model_profile}),
    )

    assert pipeline._cfg.model_profile == model_profile  # noqa: SLF001


def test_pwb2_cli_production_builder_uses_canonical_verifier_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HarnessSettings(**_production_settings())  # type: ignore[arg-type]
    transports: list[object] = []

    def reject_transport(**kwargs: object) -> object:
        transports.append(kwargs)
        pytest.fail("provider transport must not be constructed before canonical admission")

    monkeypatch.setattr(compiler_cli, "OpenAICompatClient", reject_transport)

    with pytest.raises(AdmissionPolicyDenied) as denied:
        compiler_cli._build_production_compiler_client(
            settings,
            schema_hash=settings.production_expected_schema_hash,
            space_id=settings.production_expected_space_id,
        )

    assert denied.value.reason_code == "canonical_verifier_unavailable"
    assert transports == []


def test_pwb2_cli_production_builder_fails_closed_without_028_adapter_after_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HarnessSettings(**_production_settings())  # type: ignore[arg-type]
    verified, _identity, request = _reserved_call_authority(
        template_hash="a" * 64,
        schema_hash=settings.production_expected_schema_hash,
    )
    verifier_calls: list[StrictAdmissionRequestBinding] = []
    transport_builds: list[object] = []

    class _CanonicalVerifier:
        def verify(
            self,
            current: StrictAdmissionRequestBinding,
            /,
        ) -> object:
            verifier_calls.append(current)
            return verified

    class _CanonicalModule:
        @staticmethod
        def select_canonical_admission_verifier(
            purpose: str,
            run_schema_version: str,
        ) -> _CanonicalVerifier:
            assert (purpose, run_schema_version) == (
                request.expected_purpose,
                request.expected_run_schema_version,
            )
            return _CanonicalVerifier()

    monkeypatch.setattr(
        composition_module,
        "import_module",
        lambda name: _CanonicalModule,
    )
    monkeypatch.setattr(
        compiler_cli,
        "OpenAICompatClient",
        lambda **kwargs: transport_builds.append(kwargs),
    )

    with pytest.raises(llm_module.ProductionEntrypointDenied) as denied:
        compiler_cli._build_production_compiler_client(
            settings,
            schema_hash=settings.production_expected_schema_hash,
            space_id=settings.production_expected_space_id,
        )

    assert denied.value.reason_code == "canonical_adapter_unavailable"
    assert verifier_calls == [request]
    assert transport_builds == []


def test_pwb2_replay_entrypoint_rejects_disabled_profile_before_client_or_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_builds: list[object] = []
    schema_reads: list[object] = []
    transport_builds: list[object] = []
    settings = HarnessSettings(
        weknora_base_url="https://unused.invalid",
        weknora_api_key="unused",
    )
    monkeypatch.setattr(compiler_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        compiler_cli,
        "build_client",
        lambda *args: client_builds.append(args),
    )
    monkeypatch.setattr(
        compiler_cli,
        "load_schema_registry",
        lambda path: schema_reads.append(path),
    )
    monkeypatch.setattr(
        compiler_cli,
        "OpenAICompatClient",
        lambda **kwargs: transport_builds.append(kwargs),
    )
    args = type(
        "ReplayArgs",
        (),
        {
            "replay_dir": tmp_path / "fixtures",
            "model": None,
            "schema_dir": tmp_path / "schema",
        },
    )()

    with pytest.raises(llm_module.ProductionEntrypointDenied) as denied:
        asyncio.run(compiler_cli._cmd_extract_replay(args))

    assert denied.value.reason_code == "invalid_model_profile"
    assert client_builds == []
    assert schema_reads == []
    assert transport_builds == []


def test_pwb2_production_entrypoint_rejects_disabled_profile_before_client_or_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_reads: list[object] = []
    client_builds: list[object] = []
    transport_builds: list[object] = []
    settings = HarnessSettings(
        weknora_base_url="https://unused.invalid",
        weknora_api_key="unused",
    )
    monkeypatch.setattr(compiler_cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(
        compiler_cli,
        "load_schema_registry",
        lambda path: schema_reads.append(path),
    )
    monkeypatch.setattr(
        compiler_cli,
        "_build_production_compiler_client",
        lambda *args, **kwargs: client_builds.append((args, kwargs)),
    )
    monkeypatch.setattr(
        compiler_cli,
        "OpenAICompatClient",
        lambda **kwargs: transport_builds.append(kwargs),
    )
    args = type(
        "ProductionArgs",
        (),
        {
            "space_id": "space-1",
            "schema_dir": tmp_path / "schema",
        },
    )()

    with pytest.raises(llm_module.ProductionEntrypointDenied) as denied:
        asyncio.run(compiler_cli._cmd_extract(args))

    assert denied.value.reason_code == "invalid_model_profile"
    assert schema_reads == []
    assert client_builds == []
    assert transport_builds == []


@pytest.mark.parametrize(
    "updates",
    [
        {"judge_mode": "gateway"},
        {"judge_mode": "claude-session"},
        {"llm_model_judge_fallback": "deepseek-v4-pro"},
    ],
)
def test_pwb3_legacy_or_strong_production_config_denies_before_all_io(
    updates: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_reads: list[object] = []
    client_builds: list[object] = []
    transport_builds: list[object] = []

    def load_invalid_settings(**kwargs: object) -> HarnessSettings:
        del kwargs
        return HarnessSettings.model_validate(_production_settings(**updates))

    monkeypatch.setattr(compiler_cli, "load_settings", load_invalid_settings)
    monkeypatch.setattr(
        compiler_cli,
        "load_schema_registry",
        lambda path: schema_reads.append(path),
    )
    monkeypatch.setattr(
        compiler_cli,
        "_build_production_compiler_client",
        lambda *args, **kwargs: client_builds.append((args, kwargs)),
    )
    monkeypatch.setattr(
        compiler_cli,
        "OpenAICompatClient",
        lambda **kwargs: transport_builds.append(kwargs),
    )
    args = type(
        "ProductionArgs",
        (),
        {
            "space_id": "expected-space_id",
            "schema_dir": tmp_path / "schema",
        },
    )()

    with pytest.raises(ValidationError):
        asyncio.run(compiler_cli._cmd_extract(args))

    assert schema_reads == []
    assert client_builds == []
    assert transport_builds == []


@pytest.mark.parametrize(
    ("model_profile", "replay_dir"),
    [
        ("offline-eval", None),
        ("replay", "fixtures"),
    ],
)
def test_pwb2_replay_entrypoint_requires_explicit_nonproduction_profile(
    model_profile: str,
    replay_dir: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExpectedStop(RuntimeError):
        pass

    settings = HarnessSettings(
        weknora_base_url="https://unused.invalid",
        weknora_api_key="unused",
        model_profile=model_profile,  # type: ignore[arg-type]
    )
    builds: list[tuple[object, object, object]] = []

    def record_build(
        current: object,
        fixture: object,
        model: object,
    ) -> tuple[object, str]:
        builds.append((current, fixture, model))
        return object(), "fixture-model"

    monkeypatch.setattr(compiler_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(compiler_cli, "build_client", record_build)
    monkeypatch.setattr(
        compiler_cli,
        "load_schema_registry",
        lambda _: (_ for _ in ()).throw(_ExpectedStop),
    )
    fixture_path = None if replay_dir is None else tmp_path / replay_dir
    args = type(
        "ReplayArgs",
        (),
        {
            "replay_dir": fixture_path,
            "model": None,
            "schema_dir": tmp_path / "schema",
        },
    )()

    with pytest.raises(_ExpectedStop):
        asyncio.run(compiler_cli._cmd_extract_replay(args))

    assert builds == [(settings, fixture_path, None)]


def test_pwb3_reserved_entrypoint_template_mismatch_denies_before_transport(
    tmp_path: Path,
) -> None:
    system = "actual code-owned extraction template"
    prompt_version = "baseline@ep-v1.0"
    client, target, sink, _verified, _identity, request = _guarded_test_client(
        template_hash="a" * 64,
        schema_hash="b" * 64,
    )
    ledger = SqliteAttemptLedger(
        tmp_path / "attempts.sqlite",
        run_id=request.expected_run_id,
    )

    with pytest.raises(ModelPolicyDenied) as denied:
        asyncio.run(
            call_and_parse(
                client,  # type: ignore[arg-type]
                system,
                "input-content",
                ledger=ledger,
                field_ids=("x",),
                stage="extract",
                prompt_version=prompt_version,
            )
        )

    assert denied.value.reason_code == "template_not_approved"
    assert gateway_module._test_stateful_target_calls(target) == ()
    assert [receipt.decision for receipt in sink.receipts] == ["DENY"]

"""OpenSpec 020 D1.5: production baseline uses only admitted inputs."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from insurance_harness.compiler import pipeline as compiler_pipeline
from insurance_harness.compiler.judge import JudgeDispatcher
from insurance_harness.compiler.models import BaselineAdmissionIdentity, RunManifest
from insurance_harness.compiler.pipeline import (
    ExtractionPipeline as CompilerExtractionPipeline,
)
from insurance_harness.compiler.pipeline import (
    PipelineConfig,
    RunArtifactCommitCandidate,
    RunResult,
)
from insurance_harness.compiler.templates import TemplateRegistry
from insurance_harness.goldenset import execution_artifacts_020, run_020
from insurance_harness.goldenset.admission import (
    RunAdmissionDocument,
    execution_plan_hash,
)
from insurance_harness.goldenset.admission_identity import (
    IdentityInspectionRequest,
    identity_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    ModelRolePlan,
    PendingProductInputPlan,
    ProductInputPlan,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
)
from insurance_harness.goldenset.admission_runtime import (
    AdmissionPausedError,
    AdmittedModelClient,
)
from insurance_harness.schemas import SchemaRegistry
from insurance_harness.schemas.models import ProductLineSchema
from insurance_harness.sources.directory import DirectorySourceRequest

_PRODUCT_NAME = "平安爱满分（2026）两全保险"
_OTHER_PRODUCT = "平安附加（2026）意外伤害保险"
_PLAN_CODE = "1818"
_LINE_KEY = "endowment"
_SOURCE_ROOT = "inputs/source"
_GOLDEN_ROOT = "inputs/golden"
_TERMS = "保险条款.pdf"
_BROCHURE = "产品说明书.pdf"
_SCHEMA_VERSION = "v1.1+020baseline"
_EXTRACTOR_MODEL = "approved-weak-extractor-deployment"
_JUDGE_MODEL = "approved-judge-deployment"
_PARSER_FINGERPRINT = "1" * 64
_TARGET_DOMAIN = b"insurancekb.run-admission.baseline-target.v1\0"


class _ProductionBaselineExecutor(Protocol):
    async def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        product_id: str,
        extractor_client: AdmittedModelClient,
        judge_client: AdmittedModelClient,
        configuration: object,
    ) -> RunResult: ...


@dataclass(slots=True)
class _Configuration:
    repo_root: Path
    run_root: Path
    ledger_path: Path


@dataclass(slots=True)
class _Context:
    configuration: _Configuration
    document: RunAdmissionDocument
    extractor_client: AdmittedModelClient
    judge_client: AdmittedModelClient
    product_dir: Path
    golden_product_dir: Path
    registry: SchemaRegistry
    templates: TemplateRegistry
    table_provider: object


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _target_digest(product_id: str) -> str:
    return hashlib.sha256(_TARGET_DOMAIN + b"baseline\0" + product_id.encode("utf-8")).hexdigest()


def _roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id={
                "annotator": "approved-annotator-deployment",
                "weak_extractor": _EXTRACTOR_MODEL,
                "judge": _JUDGE_MODEL,
            }[role],
            expected_model_revision="2026-07-20T00:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _identity(
    *,
    pdf_digests: Mapping[str, str],
    product_meta_digest: str | None,
    fields_digest: str | None,
    consumed_input_digests: Mapping[str, str],
    source_products_root: str = _SOURCE_ROOT,
    pending: bool = False,
    shared_input_digests: Mapping[str, str] | None = None,
) -> IdentityInspectionRequest:
    if pending:
        product: ProductInputPlan | PendingProductInputPlan = PendingProductInputPlan(
            input_status="pending_required_input",
            product_id=_PRODUCT_NAME,
            line_key=_LINE_KEY,
            pdf_digests=pdf_digests,
            product_meta_digest=product_meta_digest,
            fields_digest=fields_digest,
            consumed_input_digests=consumed_input_digests,
        )
    else:
        assert product_meta_digest is not None
        assert fields_digest is not None
        product = ProductInputPlan(
            product_id=_PRODUCT_NAME,
            line_key=_LINE_KEY,
            pdf_digests=pdf_digests,
            product_meta_digest=product_meta_digest,
            fields_digest=fields_digest,
            consumed_input_digests=consumed_input_digests,
        )
    return IdentityInspectionRequest(
        required_dependency_revisions={},
        source_products_root=source_products_root,
        golden_products_root=_GOLDEN_ROOT,
        products=(product,),
        shared_input_digests=shared_input_digests or {},
        execution_surface_digests={},
        historical_product_ids=(),
        historical_provenance=(),
    )


def _document(identity: IdentityInspectionRequest) -> RunAdmissionDocument:
    payload = RunAdmissionPlanPayload(
        run_identity="020-production-baseline-contract",
        purpose="gs-v0.1-product-baseline",
        model_roles=_roles(),
        identity_contract_hash=identity_contract_hash(identity),
        budget_contract_hash=None,
    )
    return RunAdmissionDocument(
        plan=RunAdmissionPlan(payload=payload),
        identity_request=identity,
        budget_contract=None,
    )


def _context(tmp_path: Path) -> _Context:
    repo_root = tmp_path / "repo"
    product_dir = repo_root / _SOURCE_ROOT / _PRODUCT_NAME
    golden_product_dir = repo_root / _GOLDEN_ROOT / _PRODUCT_NAME
    product_dir.mkdir(parents=True)
    golden_product_dir.mkdir(parents=True)
    (repo_root / "docs/insurance-kb/schema-baseline").mkdir(parents=True)
    (repo_root / "dataset/templates").mkdir(parents=True)
    schema_file = repo_root / "docs/insurance-kb/schema-baseline/base.yaml"
    template_file = repo_root / "dataset/templates/sample.yaml"
    schema_file.write_bytes(b"admitted schema bytes")
    template_file.write_bytes(b"admitted template bytes")

    pdf_bytes = {
        _TERMS: b"admitted baseline terms bytes",
        _BROCHURE: b"admitted baseline brochure bytes",
    }
    for name, value in pdf_bytes.items():
        (product_dir / name).write_bytes(value)
    meta_bytes = json.dumps(
        {"planCode": _PLAN_CODE, "clauseName": _PRODUCT_NAME},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    fields_bytes = json.dumps(
        {"line_key": _LINE_KEY, "schema_version": _SCHEMA_VERSION},
        separators=(",", ":"),
    ).encode()
    prompt_bytes = b"admitted baseline prompt bytes"
    (product_dir / "product_meta.json").write_bytes(meta_bytes)
    (golden_product_dir / "fields.json").write_bytes(fields_bytes)
    (golden_product_dir / "prompt.txt").write_bytes(prompt_bytes)

    identity = _identity(
        pdf_digests={name: _sha256(value) for name, value in pdf_bytes.items()},
        product_meta_digest=_sha256(meta_bytes),
        fields_digest=_sha256(fields_bytes),
        consumed_input_digests={"prompt.txt": _sha256(prompt_bytes)},
        shared_input_digests={
            schema_file.relative_to(repo_root).as_posix(): _sha256(
                schema_file.read_bytes()
            ),
            template_file.relative_to(repo_root).as_posix(): _sha256(
                template_file.read_bytes()
            ),
        },
    )
    registry = SchemaRegistry(
        version=_SCHEMA_VERSION,
        lines={
            _LINE_KEY: ProductLineSchema(
                line_key=_LINE_KEY,
                sheet_name="两全保险",
                fields=(),
            )
        },
        glossary=(),
    )
    run_root = tmp_path / "protected-run-root"
    run_root.mkdir(mode=0o700)
    run_root.chmod(0o700)
    return _Context(
        configuration=_Configuration(
            repo_root=repo_root,
            run_root=run_root,
            ledger_path=tmp_path / "budget.sqlite3",
        ),
        document=_document(identity),
        extractor_client=object.__new__(AdmittedModelClient),
        judge_client=object.__new__(AdmittedModelClient),
        product_dir=product_dir,
        golden_product_dir=golden_product_dir,
        registry=registry,
        templates=TemplateRegistry(version="tpl-v1+020baseline", templates=()),
        table_provider=object(),
    )


def _executor(value: object) -> _ProductionBaselineExecutor:
    parameters = inspect.signature(cast(Callable[..., object], value)).parameters
    if "document" not in parameters:
        pytest.skip("D1.5 baseline executor document seam is the current RED")
    return cast(_ProductionBaselineExecutor, value)


def _expected_run_dir(context: _Context) -> Path:
    return (
        context.configuration.run_root
        / execution_plan_hash(context.document)
        / _target_digest(_PRODUCT_NAME)
    )


def _write_pipeline_checkpoint(
    path: Path,
    *,
    thread_id: str,
    values: Mapping[str, object],
) -> None:
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            SqliteSaver(connection).put(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
                {
                    "v": 1,
                    "id": "00000000-0000-0000-0000-000000000001",
                    "ts": "2026-07-20T00:00:00+00:00",
                    "channel_values": dict(values),
                    "channel_versions": {},
                    "versions_seen": {},
                    "updated_channels": list(values),
                },
                {"source": "input", "step": 0},
                {},
            )
    path.chmod(0o600)


def _checkpoint_identity_values(context: _Context) -> dict[str, object]:
    inputs = run_020._revalidate_baseline_inputs(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )
    plan_hash = execution_plan_hash(context.document)
    snapshot = run_020._private_baseline_snapshot(
        configuration=context.configuration,
        inputs=inputs,
        plan_hash=plan_hash,
    )
    run_dir = _expected_run_dir(context)
    return {
        "run_id": _target_digest(_PRODUCT_NAME),
        "run_dir": str(run_dir),
        "checkpoint_path": str(run_dir / "checkpoint.sqlite3"),
        "product_dir": str(snapshot.product_dir),
        "product_id": _PLAN_CODE,
        "product_name": _PRODUCT_NAME,
        "line_key": _LINE_KEY,
        "schema_version": _SCHEMA_VERSION,
        "model_id": _EXTRACTOR_MODEL,
        "judge_mode": "gateway",
    }


def _raw_result(context: _Context) -> RunResult:
    run_dir = _expected_run_dir(context)
    return RunResult(
        manifest=RunManifest(
            run_id=_target_digest(_PRODUCT_NAME),
            product_dir=str(context.product_dir),
            run_dir=str(run_dir),
            checkpoint_path=str(run_dir / "checkpoint.sqlite3"),
            product_id=_PLAN_CODE,
            product_name=_PRODUCT_NAME,
            line_key=_LINE_KEY,
            schema_version=_SCHEMA_VERSION,
            model_id=_EXTRACTOR_MODEL,
            judge_mode="gateway",
            started_at=datetime(2026, 7, 20, tzinfo=UTC),
        ),
        records=[],
        pred_path=run_dir / "pred.jsonl",
        manifest_path=run_dir / "manifest.json",
        judge_queue_path=run_dir / "judge-queue.jsonl",
    )


def _install_success_seams(
    context: _Context,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RunResult, RunResult, dict[str, object]]:
    captured: dict[str, object] = {}
    raw_result = _raw_result(context)
    verified_result = raw_result.model_copy()

    def parser_fingerprint(
        *,
        document: object,
        configuration: object,
        installed_version: Callable[[str], str],
    ) -> str:
        assert document is context.document
        assert configuration is context.configuration
        assert installed_version.__module__ == "importlib.metadata"
        assert installed_version("pydantic")
        captured["parser_fingerprint"] = _PARSER_FINGERPRINT
        return _PARSER_FINGERPRINT

    def load_registry(path: Path) -> SchemaRegistry:
        captured["schema_path"] = path
        return context.registry

    def load_templates(path: Path) -> TemplateRegistry:
        captured["template_path"] = path
        return context.templates

    def select_provider(name: str) -> object:
        captured["table_provider_name"] = name
        return context.table_provider

    class CapturedSource:
        def __init__(
            self,
            *,
            replay_identity: str,
            parser_fingerprint: str,
        ) -> None:
            captured["source_replay_identity"] = replay_identity
            captured["source_parser_fingerprint"] = parser_fingerprint

    class CapturedPipeline:
        def __init__(
            self,
            *,
            client: object,
            registry: SchemaRegistry,
            model_id: str,
            source: object,
            config: PipelineConfig,
            judge: JudgeDispatcher,
            template_registry: TemplateRegistry,
            table_provider: object,
            baseline_admission_identity: BaselineAdmissionIdentity,
            precommit_validator: Callable[[RunArtifactCommitCandidate], None],
        ) -> None:
            assert client is context.extractor_client
            assert registry is context.registry
            assert model_id == _EXTRACTOR_MODEL
            assert isinstance(source, CapturedSource)
            assert config.judge_mode == "gateway"
            assert judge.mode == "gateway"
            assert judge._client is context.judge_client  # noqa: SLF001
            assert template_registry is context.templates
            assert table_provider is context.table_provider
            captured["baseline_admission_identity"] = baseline_admission_identity
            captured["precommit_validator"] = precommit_validator
            captured["pipeline_constructed"] = True

        async def run(self, **values: object) -> RunResult:
            captured["pipeline_run"] = values
            return raw_result

    def validate(**values: object) -> RunResult:
        captured["validator"] = values
        return verified_result

    monkeypatch.setattr(
        execution_artifacts_020,
        "directory_parser_fingerprint",
        parser_fingerprint,
    )
    monkeypatch.setattr(
        execution_artifacts_020,
        "validate_baseline_result",
        validate,
    )
    monkeypatch.setattr(
        run_020,
        "directory_parser_fingerprint",
        parser_fingerprint,
        raising=False,
    )
    monkeypatch.setattr(
        run_020,
        "validate_baseline_result",
        validate,
        raising=False,
    )
    monkeypatch.setattr(run_020, "load_schema_registry", load_registry, raising=False)
    monkeypatch.setattr(run_020, "load_template_registry", load_templates, raising=False)
    monkeypatch.setattr(run_020, "select_table_provider", select_provider, raising=False)
    monkeypatch.setattr(run_020, "DirectoryDocumentSource", CapturedSource, raising=False)
    monkeypatch.setattr(run_020, "ExtractionPipeline", CapturedPipeline, raising=False)
    return raw_result, verified_result, captured


def test_d1_5_production_baseline_executor_requires_admission_document() -> None:
    assert tuple(inspect.signature(run_020._execute_baseline).parameters) == (
        "document",
        "product_id",
        "extractor_client",
        "judge_client",
        "configuration",
    )


def test_d1_5_pipeline_rejects_admission_receipt_without_precommit_gate(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    product = context.document.identity_request.products[0]
    assert type(product) is ProductInputPlan
    identity = BaselineAdmissionIdentity(
        format="insurancekb.baseline-admission-identity.v1",
        execution_plan_hash=execution_plan_hash(context.document),
        parser_fingerprint=_PARSER_FINGERPRINT,
        pdf_digests=product.pdf_digests,
        product_meta_digest=product.product_meta_digest,
        fields_digest=product.fields_digest,
        consumed_input_digests=product.consumed_input_digests,
        shared_input_digests=context.document.identity_request.shared_input_digests,
        extractor_model_id=_EXTRACTOR_MODEL,
        judge_model_id=_JUDGE_MODEL,
        schema_version=_SCHEMA_VERSION,
        template_registry_version=context.templates.version,
    )

    with pytest.raises(ValueError, match="precommit"):
        CompilerExtractionPipeline(
            client=context.extractor_client,
            registry=context.registry,
            model_id=_EXTRACTOR_MODEL,
            source=cast(Any, object()),
            baseline_admission_identity=identity,
        )


@pytest.mark.asyncio
async def test_d1_5_production_baseline_wires_exact_admitted_pipeline_and_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    raw_result, verified_result, captured = _install_success_seams(
        context,
        monkeypatch,
    )
    plan = context.document.identity_request.products[0]
    assert type(plan) is ProductInputPlan

    result = await _executor(run_020._execute_baseline)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )

    run_dir = _expected_run_dir(context)
    checkpoint_path = run_dir / "checkpoint.sqlite3"
    schema_path = cast(Path, captured["schema_path"])
    snapshot_root = schema_path.parent
    snapshot_product_dir = snapshot_root / "product"
    assert result is verified_result
    admission_identity = cast(
        BaselineAdmissionIdentity,
        captured.pop("baseline_admission_identity"),
    )
    precommit_validator = captured.pop("precommit_validator")
    assert callable(precommit_validator)
    assert admission_identity.execution_plan_hash == execution_plan_hash(context.document)
    assert admission_identity.parser_fingerprint == _PARSER_FINGERPRINT
    assert admission_identity.pdf_digests == plan.pdf_digests
    assert admission_identity.extractor_model_id == _EXTRACTOR_MODEL
    assert admission_identity.judge_model_id == _JUDGE_MODEL
    assert captured == {
        "parser_fingerprint": _PARSER_FINGERPRINT,
        "schema_path": snapshot_root / "schema",
        "template_path": snapshot_root / "templates",
        "table_provider_name": "pdfplumber",
        "source_replay_identity": (
            f"run-admission-020/{execution_plan_hash(context.document)}/"
            f"{_target_digest(_PRODUCT_NAME)}"
        ),
        "source_parser_fingerprint": _PARSER_FINGERPRINT,
        "pipeline_constructed": True,
        "pipeline_run": {
            "run_dir": run_dir,
            "source_request": DirectorySourceRequest(product_dir=snapshot_product_dir),
            "product_dir": snapshot_product_dir,
            "product_id": _PLAN_CODE,
            "product_name": _PRODUCT_NAME,
            "line_key": _LINE_KEY,
            "thread_id": _target_digest(_PRODUCT_NAME),
            "checkpoint_path": checkpoint_path,
            "resume": False,
        },
        "validator": {
            "result": raw_result,
            "run_root": context.configuration.run_root,
            "expected_source_root": snapshot_root,
            "expected_product_dir": snapshot_product_dir,
            "expected_run_id": _target_digest(_PRODUCT_NAME),
            "expected_run_dir": run_dir,
            "expected_product_id": _PLAN_CODE,
            "expected_product_name": _PRODUCT_NAME,
            "expected_line_key": _LINE_KEY,
            "expected_schema_version": _SCHEMA_VERSION,
            "expected_model_id": _EXTRACTOR_MODEL,
            "expected_judge_mode": "gateway",
            "expected_admission_identity": admission_identity,
        },
    }
    assert snapshot_root.is_relative_to(context.configuration.run_root)
    assert context.product_dir.parent == (context.configuration.repo_root / _SOURCE_ROOT)
    assert context.product_dir.name == _PRODUCT_NAME


@pytest.mark.asyncio
async def test_d1_5_baseline_pipeline_reads_private_verified_snapshot_and_rejects_repo_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    schema_file = context.configuration.repo_root / run_020._SCHEMA_BASELINE / "base.yaml"
    template_file = context.configuration.repo_root / run_020._TEMPLATE_BASELINE / "sample.yaml"
    schema_bytes = schema_file.read_bytes()
    template_bytes = template_file.read_bytes()
    original_pdf = (context.product_dir / _TERMS).read_bytes()
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)

    def mutate_after_verification(**_values: object) -> str:
        (context.product_dir / _TERMS).write_bytes(b"swapped repo pdf")
        schema_file.write_bytes(b"swapped repo schema")
        template_file.write_bytes(b"swapped repo template")
        captured["parser_fingerprint"] = _PARSER_FINGERPRINT
        return _PARSER_FINGERPRINT

    def load_registry(path: Path) -> SchemaRegistry:
        captured["schema_path"] = path
        captured["schema_bytes_seen"] = (path / schema_file.name).read_bytes()
        return context.registry

    def load_templates(path: Path) -> TemplateRegistry:
        captured["template_path"] = path
        captured["template_bytes_seen"] = (path / template_file.name).read_bytes()
        return context.templates

    monkeypatch.setattr(run_020, "directory_parser_fingerprint", mutate_after_verification)
    monkeypatch.setattr(run_020, "load_schema_registry", load_registry)
    monkeypatch.setattr(run_020, "load_template_registry", load_templates)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_identity_mismatch"
    pipeline_run = cast(dict[str, object], captured["pipeline_run"])
    source_request = cast(DirectorySourceRequest, pipeline_run["source_request"])
    assert source_request.product_dir == pipeline_run["product_dir"]
    assert source_request.product_dir != context.product_dir
    assert source_request.product_dir.is_relative_to(context.configuration.run_root)
    assert (source_request.product_dir / _TERMS).read_bytes() == original_pdf
    assert captured["schema_bytes_seen"] == schema_bytes
    assert captured["template_bytes_seen"] == template_bytes


@pytest.mark.asyncio
async def test_d1_5_repo_drift_precommit_leaves_no_manifest_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    await _executor(run_020._execute_baseline)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )
    (context.product_dir / _TERMS).write_bytes(b"repo drift before commit")
    precommit = cast(
        Callable[[RunArtifactCommitCandidate], None],
        captured["precommit_validator"],
    )
    run_dir = _expected_run_dir(context)

    with pytest.raises(AdmissionPausedError) as caught:
        compiler_pipeline._commit_run_artifacts(
            run_dir=run_dir,
            pred_text="not-admitted\n",
            manifest_text="not-admitted",
            judge_requests=[],
            dead_letter_text="",
            precommit_validator=precommit,
        )

    assert caught.value.code == "baseline_identity_mismatch"
    assert not (run_dir / "manifest.json").exists()


def _replace_identity(
    context: _Context,
    *,
    pending: bool = False,
    source_products_root: str = _SOURCE_ROOT,
    product_meta_digest: str | None | object = ...,  # noqa: PYI051
    fields_digest: str | None | object = ...,  # noqa: PYI051
) -> None:
    current = context.document.identity_request.products[0]
    meta_digest = (
        current.product_meta_digest
        if product_meta_digest is ...
        else cast(str | None, product_meta_digest)
    )
    admitted_fields_digest = (
        current.fields_digest
        if fields_digest is ...
        else cast(str | None, fields_digest)
    )
    identity = _identity(
        pdf_digests=current.pdf_digests,
        product_meta_digest=meta_digest,
        fields_digest=admitted_fields_digest,
        consumed_input_digests=current.consumed_input_digests,
        source_products_root=source_products_root,
        pending=pending,
        shared_input_digests=context.document.identity_request.shared_input_digests,
    )
    context.document = _document(identity)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ("line-missing", "line-wrong", "schema-missing", "schema-wrong"),
)
async def test_d1_5_baseline_rejects_fields_semantic_identity_pre_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context(tmp_path)
    fields: dict[str, str] = {
        "line_key": _LINE_KEY,
        "schema_version": _SCHEMA_VERSION,
    }
    field, mutation = failure.split("-", maxsplit=1)
    key = "line_key" if field == "line" else "schema_version"
    if mutation == "missing":
        fields.pop(key)
    else:
        fields[key] = "wrong-value"
    fields_bytes = json.dumps(fields, separators=(",", ":")).encode()
    (context.golden_product_dir / "fields.json").write_bytes(fields_bytes)
    _replace_identity(context, fields_digest=_sha256(fields_bytes))
    calls: list[str] = []
    _install_pre_io_guards(monkeypatch, calls)
    monkeypatch.setattr(run_020, "load_schema_registry", lambda _path: context.registry)
    monkeypatch.setattr(run_020, "load_template_registry", lambda _path: context.templates)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_identity_mismatch"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_kind", ("schema", "template"))
async def test_d1_5_baseline_rejects_signed_shared_input_drift_pre_parser_or_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shared_kind: str,
) -> None:
    context = _context(tmp_path)
    relative = {
        "schema": "docs/insurance-kb/schema-baseline/base.yaml",
        "template": "dataset/templates/sample.yaml",
    }[shared_kind]
    (context.configuration.repo_root / relative).write_bytes(b"unsigned shared drift")
    calls: list[str] = []
    _install_pre_io_guards(monkeypatch, calls)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_identity_mismatch"
    assert calls == []


def _install_pre_io_guards(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        calls.append("forbidden_io")
        raise AssertionError("identity drift must reject before source/pipeline/model I/O")

    monkeypatch.setattr(
        execution_artifacts_020,
        "directory_parser_fingerprint",
        forbidden,
    )
    monkeypatch.setattr(
        run_020,
        "directory_parser_fingerprint",
        forbidden,
        raising=False,
    )
    for name in (
        "load_schema_registry",
        "load_template_registry",
        "select_table_provider",
        "DirectoryDocumentSource",
        "ExtractionPipeline",
    ):
        monkeypatch.setattr(run_020, name, forbidden, raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    (
        "pending-product",
        "wrong-requested-product",
        "source-root-traversal",
        "source-root-absolute",
        "source-directory-symlink",
        "source-directory-missing",
        "pdf-digest",
        "meta-digest",
        "fields-digest",
        "consumed-digest",
        "meta-invalid",
        "plan-code-missing",
        "clause-name-drift",
        "run-root-symlink",
    ),
)
async def test_d1_5_production_baseline_rejects_identity_path_or_digest_pre_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context(tmp_path)
    requested_product = _PRODUCT_NAME
    if failure == "pending-product":
        _replace_identity(context, pending=True, product_meta_digest=None)
    elif failure == "wrong-requested-product":
        requested_product = _OTHER_PRODUCT
    elif failure == "source-root-traversal":
        _replace_identity(context, source_products_root="inputs/source/../source")
    elif failure == "source-root-absolute":
        _replace_identity(context, source_products_root=str(context.product_dir.parent))
    elif failure == "source-directory-symlink":
        target = tmp_path / "outside-product"
        context.product_dir.rename(target)
        context.product_dir.symlink_to(target, target_is_directory=True)
    elif failure == "source-directory-missing":
        context.product_dir.rename(tmp_path / "missing-product")
    elif failure.endswith("-digest"):
        path = {
            "pdf-digest": context.product_dir / _TERMS,
            "meta-digest": context.product_dir / "product_meta.json",
            "fields-digest": context.golden_product_dir / "fields.json",
            "consumed-digest": context.golden_product_dir / "prompt.txt",
        }[failure]
        path.write_bytes(path.read_bytes() + b" unsigned drift")
    elif failure in {"meta-invalid", "plan-code-missing", "clause-name-drift"}:
        if failure == "meta-invalid":
            meta_bytes = b"not-json"
        else:
            meta = (
                {"clauseName": _PRODUCT_NAME}
                if failure == "plan-code-missing"
                else {"planCode": _PLAN_CODE, "clauseName": _OTHER_PRODUCT}
            )
            meta_bytes = json.dumps(
                meta,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        (context.product_dir / "product_meta.json").write_bytes(meta_bytes)
        _replace_identity(context, product_meta_digest=_sha256(meta_bytes))
    else:
        real_root = context.configuration.run_root
        alias = tmp_path / "run-root-alias"
        real_root.rename(alias)
        real_root.symlink_to(alias, target_is_directory=True)

    calls: list[str] = []
    _install_pre_io_guards(monkeypatch, calls)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=requested_product,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_identity_mismatch"
    assert calls == []


@pytest.mark.asyncio
async def test_d1_5_production_baseline_parser_drift_is_pre_source_and_model_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    calls: list[str] = []
    parser_error = AdmissionPausedError("baseline_parser_identity_mismatch")

    def parser_drift(**_values: object) -> str:
        calls.append("parser_fingerprint")
        raise parser_error

    def forbidden(*_args: object, **_kwargs: object) -> object:
        calls.append("forbidden_io")
        raise AssertionError("parser drift must reject before source/pipeline/model I/O")

    monkeypatch.setattr(
        execution_artifacts_020,
        "directory_parser_fingerprint",
        parser_drift,
    )
    monkeypatch.setattr(
        run_020,
        "directory_parser_fingerprint",
        parser_drift,
        raising=False,
    )
    for name in ("DirectoryDocumentSource", "ExtractionPipeline"):
        monkeypatch.setattr(run_020, name, forbidden, raising=False)
    monkeypatch.setattr(run_020, "load_schema_registry", lambda _path: context.registry)
    monkeypatch.setattr(run_020, "load_template_registry", lambda _path: context.templates)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value is parser_error
    assert calls == ["parser_fingerprint"]


@pytest.mark.asyncio
async def test_d1_5_empty_private_checkpoint_is_not_a_resume_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    checkpoint.write_bytes(b"")
    checkpoint.chmod(0o600)

    await _executor(run_020._execute_baseline)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )

    pipeline_run = cast(dict[str, object], captured["pipeline_run"])
    assert pipeline_run["resume"] is False


@pytest.mark.asyncio
async def test_d1_5_uninitialized_sqlite_checkpoint_is_not_a_resume_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    with closing(sqlite3.connect(checkpoint)) as connection:
        SqliteSaver(connection).setup()
    checkpoint.chmod(0o600)

    await _executor(run_020._execute_baseline)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )

    pipeline_run = cast(dict[str, object], captured["pipeline_run"])
    assert pipeline_run["resume"] is False


@pytest.mark.asyncio
async def test_d1_5_checkpoint_for_exact_thread_with_wrong_pipeline_identity_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    values = _checkpoint_identity_values(context)
    values["product_id"] = "forged-product-id"
    _write_pipeline_checkpoint(
        checkpoint,
        thread_id=_target_digest(_PRODUCT_NAME),
        values=values,
    )

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_resume_state_unsafe"
    assert "pipeline_run" not in captured


@pytest.mark.asyncio
async def test_d1_5_valid_pipeline_checkpoint_from_fresh_crash_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    raw_result, verified_result, captured = _install_success_seams(
        context,
        monkeypatch,
    )
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    _write_pipeline_checkpoint(
        checkpoint,
        thread_id=_target_digest(_PRODUCT_NAME),
        values=_checkpoint_identity_values(context),
    )

    result = await _executor(run_020._execute_baseline)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )

    assert result is verified_result
    pipeline_run = cast(dict[str, object], captured["pipeline_run"])
    assert pipeline_run["run_dir"] == run_dir
    assert pipeline_run["checkpoint_path"] == checkpoint
    assert pipeline_run["thread_id"] == _target_digest(_PRODUCT_NAME)
    assert pipeline_run["resume"] is True


@pytest.mark.asyncio
async def test_d1_5_resume_queries_only_the_verified_in_memory_checkpoint_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    _write_pipeline_checkpoint(
        checkpoint,
        thread_id=_target_digest(_PRODUCT_NAME),
        values=_checkpoint_identity_values(context),
    )
    real_connect = sqlite3.connect
    opened: list[str] = []

    def connect(database: str) -> sqlite3.Connection:
        opened.append(database)
        assert database == ":memory:"
        return real_connect(database)

    monkeypatch.setattr(sqlite3, "connect", connect)

    await _executor(run_020._execute_baseline)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        extractor_client=context.extractor_client,
        judge_client=context.judge_client,
        configuration=context.configuration,
    )

    assert opened == [":memory:", ":memory:"]
    assert cast(dict[str, object], captured["pipeline_run"])["resume"] is True


@pytest.mark.asyncio
async def test_d1_5_resume_serde_failure_is_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    _write_pipeline_checkpoint(
        checkpoint,
        thread_id=_target_digest(_PRODUCT_NAME),
        values=_checkpoint_identity_values(context),
    )
    sensitive = "provider-secret-must-not-escape"

    class _Serde:
        def loads_typed(self, _value: object) -> object:
            raise ValueError(sensitive)

    monkeypatch.setattr(
        run_020,
        "SqliteSaver",
        lambda _connection: SimpleNamespace(serde=_Serde()),
    )

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_resume_state_unsafe"
    assert sensitive not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "pipeline_run" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("corrupt", "schema-missing"))
async def test_d1_5_nonempty_invalid_checkpoint_is_ambiguous_not_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    if failure == "corrupt":
        checkpoint.write_bytes(b"not a sqlite checkpoint")
    else:
        with sqlite3.connect(checkpoint) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
    checkpoint.chmod(0o600)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_resume_state_unsafe"
    assert "pipeline_run" not in captured


@pytest.mark.asyncio
async def test_d1_5_checkpoint_for_another_thread_is_ambiguous_not_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    _write_pipeline_checkpoint(
        checkpoint,
        thread_id="another-admitted-run",
        values=_checkpoint_identity_values(context),
    )

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_resume_state_unsafe"
    assert "pipeline_run" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    (
        "checkpoint-symlink",
        "checkpoint-directory",
        "checkpoint-public-mode",
        "checkpoint-hardlink",
        "checkpoint-wal",
        "checkpoint-shm",
        "checkpoint-alias",
        "manifest-without-checkpoint",
        "manifest-mismatch",
        "manifest-symlink",
        "run-lock-symlink",
        "run-lock-directory",
        "run-lock-public-mode",
        "run-lock-hardlink",
    ),
)
async def test_d1_5_production_baseline_rejects_unsafe_resume_state_pre_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context(tmp_path)
    run_dir = _expected_run_dir(context)
    run_dir.mkdir(parents=True, mode=0o700)
    checkpoint = run_dir / "checkpoint.sqlite3"
    manifest = run_dir / "manifest.json"
    raw_result = _raw_result(context)
    if failure == "checkpoint-symlink":
        outside = tmp_path / "outside-checkpoint.sqlite3"
        outside.write_bytes(b"outside")
        checkpoint.symlink_to(outside)
    elif failure == "checkpoint-directory":
        checkpoint.mkdir()
    elif failure == "checkpoint-public-mode":
        checkpoint.write_bytes(b"checkpoint")
        checkpoint.chmod(0o644)
    elif failure == "checkpoint-hardlink":
        outside = tmp_path / "outside-checkpoint.sqlite3"
        outside.write_bytes(b"checkpoint")
        outside.chmod(0o600)
        os.link(outside, checkpoint)
    elif failure in {"checkpoint-wal", "checkpoint-shm"}:
        checkpoint.write_bytes(b"")
        checkpoint.chmod(0o600)
        suffix = "-wal" if failure == "checkpoint-wal" else "-shm"
        (run_dir / f"checkpoint.sqlite3{suffix}").write_bytes(b"sidecar")
    elif failure == "checkpoint-alias":
        (run_dir / "alternate-checkpoint.sqlite3").write_bytes(b"alias")
    elif failure == "manifest-without-checkpoint":
        manifest.write_text(raw_result.manifest.model_dump_json(), encoding="utf-8")
    elif failure == "manifest-mismatch":
        checkpoint.write_bytes(b"checkpoint")
        checkpoint.chmod(0o600)
        changed = raw_result.manifest.model_copy(update={"run_id": "wrong-run"})
        manifest.write_text(changed.model_dump_json(), encoding="utf-8")
    elif failure == "manifest-symlink":
        checkpoint.write_bytes(b"checkpoint")
        checkpoint.chmod(0o600)
        outside = tmp_path / "outside-manifest.json"
        outside.write_text(raw_result.manifest.model_dump_json(), encoding="utf-8")
        manifest.symlink_to(outside)
    elif failure == "run-lock-symlink":
        outside = tmp_path / "outside-run-lock"
        outside.write_bytes(b"outside")
        outside.chmod(0o600)
        (run_dir / ".run.lock").symlink_to(outside)
    elif failure == "run-lock-directory":
        (run_dir / ".run.lock").mkdir(mode=0o700)
    elif failure == "run-lock-public-mode":
        lock_path = run_dir / ".run.lock"
        lock_path.write_bytes(b"lock")
        lock_path.chmod(0o644)
    else:
        outside = tmp_path / "outside-run-lock"
        outside.write_bytes(b"outside")
        outside.chmod(0o600)
        os.link(outside, run_dir / ".run.lock")

    calls: list[str] = []

    class ForbiddenPipeline:
        def __init__(self, **_values: object) -> None:
            calls.append("pipeline")

    monkeypatch.setattr(run_020, "ExtractionPipeline", ForbiddenPipeline, raising=False)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value.code == "baseline_resume_state_unsafe"
    assert calls == []


@pytest.mark.asyncio
async def test_d1_5_production_baseline_never_returns_unvalidated_pipeline_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _raw, _verified, captured = _install_success_seams(context, monkeypatch)
    validator_error = AdmissionPausedError("baseline_artifact_content_mismatch")

    def reject_result(**values: object) -> RunResult:
        captured["rejected_validator"] = values
        raise validator_error

    monkeypatch.setattr(
        execution_artifacts_020,
        "validate_baseline_result",
        reject_result,
    )
    monkeypatch.setattr(
        run_020,
        "validate_baseline_result",
        reject_result,
        raising=False,
    )

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_baseline)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            extractor_client=context.extractor_client,
            judge_client=context.judge_client,
            configuration=context.configuration,
        )

    assert caught.value is validator_error
    assert "rejected_validator" in captured


def test_d1_5_production_dependencies_expose_real_baseline_executor() -> None:
    dependencies = run_020._production_ready_dependencies()
    assert dependencies.baseline_executor is run_020._execute_baseline

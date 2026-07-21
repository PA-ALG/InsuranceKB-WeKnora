"""OpenSpec 020 D1.5: production annotation execution uses admitted inputs."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import pytest

from insurance_harness.goldenset import execution_artifacts_020, run_020, runner
from insurance_harness.goldenset.admission import (
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission import (
    execution_plan_hash as compute_execution_plan_hash,
)
from insurance_harness.goldenset.admission_artifacts import CanaryArtifactBundle
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
from insurance_harness.goldenset.annotator import GoldenAnnotator
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import Evidence, GoldenRecord
from insurance_harness.schemas import SchemaRegistry
from insurance_harness.schemas.models import ProductLineSchema

_PRODUCT_NAME = "平安爱满分（2026）两全保险"
_PLAN_CODE = "1818"
_LINE_KEY = "endowment"
_SOURCE_ROOT = "inputs/source"
_GOLDEN_ROOT = "inputs/golden"
_TERMS = "保险条款.pdf"
_BROCHURE = "产品说明书.pdf"
_SCHEMA_VERSION = "v1.1+020annotation"
_ANNOTATOR_MODEL = "approved-annotator-deployment"
_CREATED_AT = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)


class _ProductionAnnotationExecutor(Protocol):
    async def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        product_id: str,
        client: AdmittedModelClient,
        configuration: object,
    ) -> CanaryArtifactBundle: ...


@dataclass(slots=True)
class _Configuration:
    repo_root: Path
    run_root: Path
    ledger_path: Path


@dataclass(slots=True)
class _Context:
    configuration: _Configuration
    document: RunAdmissionDocument
    client: AdmittedModelClient
    product_dir: Path
    golden_product_dir: Path
    schema_root: Path
    registry: SchemaRegistry
    pdf_pages: Mapping[str, list[PageText]]
    source_bytes: Mapping[str, bytes]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id=(
                _ANNOTATOR_MODEL if role == "annotator" else f"approved-{role}"
            ),
            expected_model_revision="2026-07-20T00:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _document(identity: IdentityInspectionRequest) -> RunAdmissionDocument:
    payload = RunAdmissionPlanPayload(
        run_identity="020-production-annotation-contract",
        purpose="gs-v0.1-canary-annotation",
        model_roles=_roles(),
        identity_contract_hash=identity_contract_hash(identity),
        budget_contract_hash=None,
    )
    return RunAdmissionDocument(
        plan=RunAdmissionPlan(payload=payload),
        identity_request=identity,
        budget_contract=None,
    )


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


def _context(tmp_path: Path) -> _Context:
    repo_root = tmp_path / "repo"
    product_dir = repo_root / _SOURCE_ROOT / _PRODUCT_NAME
    golden_product_dir = repo_root / _GOLDEN_ROOT / _PRODUCT_NAME
    schema_root = repo_root / "docs/insurance-kb/schema-baseline"
    product_dir.mkdir(parents=True)
    golden_product_dir.mkdir(parents=True)
    schema_root.mkdir(parents=True)

    pdf_bytes = {
        _TERMS: b"real admitted terms pdf bytes",
        _BROCHURE: b"real admitted brochure pdf bytes",
    }
    for name, content in pdf_bytes.items():
        (product_dir / name).write_bytes(content)
    meta_bytes = json.dumps(
        {"planCode": _PLAN_CODE, "clauseName": _PRODUCT_NAME},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    fields_bytes = json.dumps(
        {"line_key": _LINE_KEY, "schema_version": _SCHEMA_VERSION},
        separators=(",", ":"),
    ).encode()
    prompt_bytes = b"admitted annotation prompt bytes"
    schema_bytes = b"admitted annotation schema bytes"
    (product_dir / "product_meta.json").write_bytes(meta_bytes)
    (golden_product_dir / "fields.json").write_bytes(fields_bytes)
    (golden_product_dir / "prompt.txt").write_bytes(prompt_bytes)
    schema_file = schema_root / "base.yaml"
    schema_file.write_bytes(schema_bytes)

    identity = _identity(
        pdf_digests={name: _sha256(content) for name, content in pdf_bytes.items()},
        product_meta_digest=_sha256(meta_bytes),
        fields_digest=_sha256(fields_bytes),
        consumed_input_digests={"prompt.txt": _sha256(prompt_bytes)},
        shared_input_digests={
            schema_file.relative_to(repo_root).as_posix(): _sha256(schema_bytes),
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
        client=object.__new__(AdmittedModelClient),
        product_dir=product_dir,
        golden_product_dir=golden_product_dir,
        schema_root=schema_root,
        registry=registry,
        pdf_pages={
            _TERMS: [PageText(page_no=1, text="等待期为九十日。")],
            _BROCHURE: [PageText(page_no=1, text="保险期间为二十年。")],
        },
        source_bytes={**pdf_bytes, "product_meta.json": meta_bytes},
    )


def _executor(value: object) -> _ProductionAnnotationExecutor:
    return cast(_ProductionAnnotationExecutor, value)


def _install_success_seams(
    context: _Context,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate_repo_after_snapshot: bool = False,
    mutate_schema_after_snapshot: bool = False,
) -> tuple[CanaryArtifactBundle, dict[str, object]]:
    captured: dict[str, object] = {"page_loader_payloads": []}
    expected_bundle = CanaryArtifactBundle(
        checkpoint=b"real-checkpoint",
        manifest=b"real-manifest",
        golden=b"real-golden",
        quote_verification=b"real-quote-verification",
        disputed_quality=b"real-disputed-quality",
        disputed_count=0,
        record_count=2,
        quality_threshold_version="golden-v0.1-thresholds-v1",
    )
    real_annotator_init = GoldenAnnotator.__init__

    def load_registry(path: Path) -> SchemaRegistry:
        captured["schema_root"] = path
        return context.registry

    def track_annotator_init(
        self: GoldenAnnotator,
        model_client: object,
        registry: SchemaRegistry,
        annotator_model: str,
        doc_char_budget: int = 30_000,
    ) -> None:
        captured["annotator_client"] = model_client
        captured["annotator_registry"] = registry
        captured["annotator_model"] = annotator_model
        real_annotator_init(
            self,
            cast(AdmittedModelClient, model_client),
            registry,
            annotator_model,
            doc_char_budget,
        )

    async def annotate(
        product_dir: Path,
        registry: SchemaRegistry,
        annotator: GoldenAnnotator,
        cache_dir: Path,
        line_key: str | None = None,
    ) -> list[GoldenRecord]:
        assert product_dir != context.product_dir
        plan_snapshot_root = (
            context.configuration.run_root
            / "annotation-input-snapshots"
            / compute_execution_plan_hash(context.document)
        )
        snapshot_root = product_dir.parent.parent
        assert snapshot_root.parent == plan_snapshot_root
        assert len(snapshot_root.name) == 64
        assert all(character in "0123456789abcdef" for character in snapshot_root.name)
        assert product_dir == snapshot_root / "product" / _PRODUCT_NAME
        assert captured["schema_root"] == snapshot_root / "schema"
        assert product_dir.stat().st_uid == os.geteuid()
        assert product_dir.stat().st_mode & 0o777 == 0o700
        assert not product_dir.is_symlink()
        assert set(path.name for path in product_dir.iterdir()) == set(
            context.source_bytes
        )
        for name, expected_bytes in context.source_bytes.items():
            snapshot_file = product_dir / name
            metadata = snapshot_file.stat(follow_symlinks=False)
            assert not snapshot_file.is_symlink()
            assert metadata.st_uid == os.geteuid()
            assert metadata.st_mode & 0o777 in {0o400, 0o600}
            assert snapshot_file.read_bytes() == expected_bytes
        assert registry is context.registry
        assert isinstance(annotator, GoldenAnnotator)
        assert line_key == _LINE_KEY
        captured["cache_dir"] = cache_dir
        captured["snapshot_dir"] = product_dir
        captured["snapshot_terms_bytes"] = (product_dir / _TERMS).read_bytes()
        if mutate_repo_after_snapshot:
            (context.product_dir / _TERMS).write_bytes(b"raced repository bytes")
        if mutate_schema_after_snapshot:
            (context.schema_root / "base.yaml").write_bytes(
                b"unsigned schema drift with unchanged registry version"
            )
        records = [
            GoldenRecord(
                product_id=_PLAN_CODE,
                product_name=_PRODUCT_NAME,
                doc=_TERMS,
                field_id="waiting_period",
                field_name="等待期",
                value="90日",
                tri_state="present",
                evidence=[Evidence(page=1, quote="等待期为九十日")],
                annotator_model=_ANNOTATOR_MODEL,
                schema_version=registry.version,
                created_at=_CREATED_AT,
            ),
            GoldenRecord(
                product_id=_PLAN_CODE,
                product_name=_PRODUCT_NAME,
                doc=_BROCHURE,
                field_id="insurance_period",
                field_name="保险期间",
                value="20年",
                tri_state="present",
                evidence=[Evidence(page=1, quote="保险期间为二十年")],
                annotator_model=_ANNOTATOR_MODEL,
                schema_version=registry.version,
                created_at=_CREATED_AT,
            ),
        ]
        suffix = registry.version.split("+")[-1]
        for record in records:
            path = cache_dir / _PRODUCT_NAME / f"{record.doc}.{suffix}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(record.model_dump_json().encode() + b"\n")
        captured["records"] = tuple(records)
        return records

    def load_pages(pdf_bytes: bytes, *, source_name: str) -> list[PageText]:
        assert pdf_bytes == context.source_bytes[source_name]
        cast(list[tuple[str, bytes]], captured["page_loader_payloads"]).append(
            (source_name, pdf_bytes)
        )
        return list(context.pdf_pages[source_name])

    def render(
        *,
        document: object,
        configuration: object,
        product_id: str,
        records: Sequence[GoldenRecord],
        cache_dir: Path,
        page_loader: Callable[[str, bytes], list[PageText]],
        started_at: datetime,
        finished_at: datetime,
        execution_plan_hash: str,
    ) -> CanaryArtifactBundle:
        assert document is context.document
        assert configuration is context.configuration
        assert product_id == _PRODUCT_NAME
        assert tuple(records) == captured["records"]
        assert cache_dir == captured["cache_dir"]
        assert cache_dir.resolve().is_relative_to(context.configuration.run_root.resolve())
        assert not cache_dir.resolve().is_relative_to(
            context.configuration.repo_root.resolve()
        )
        assert context.configuration.run_root.stat().st_mode & 0o777 == 0o700
        cache_files = sorted(cache_dir.rglob("*.jsonl"))
        assert len(cache_files) == 2
        assert all(path.read_bytes() for path in cache_files)
        signature = inspect.signature(page_loader)
        assert tuple(signature.parameters) == ("doc", "verified_bytes")
        assert all(
            parameter.default is inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )
        captured["page_loader"] = page_loader
        for record in records:
            pages = page_loader(record.doc, context.source_bytes[record.doc])
            assert record.evidence[0].quote in pages[0].text
        assert started_at.tzinfo is UTC
        assert finished_at.tzinfo is UTC
        assert started_at <= finished_at
        assert execution_plan_hash == compute_execution_plan_hash(context.document)
        captured["renderer_called"] = True
        return expected_bundle

    def forbid_line_inference(_product_name: str) -> str:
        raise AssertionError("production annotation must use admitted line_key")

    monkeypatch.setattr(GoldenAnnotator, "__init__", track_annotator_init)
    monkeypatch.setattr(run_020, "load_schema_registry", load_registry, raising=False)
    monkeypatch.setattr(run_020, "annotate_product", annotate, raising=False)
    monkeypatch.setattr(runner, "annotate_product", annotate)
    monkeypatch.setattr(run_020, "extract_pages_bytes", load_pages, raising=False)
    monkeypatch.setattr(run_020, "infer_line_key", forbid_line_inference, raising=False)
    monkeypatch.setattr(runner, "infer_line_key", forbid_line_inference)
    monkeypatch.setattr(
        run_020,
        "render_annotation_artifacts",
        render,
        raising=False,
    )
    monkeypatch.setattr(execution_artifacts_020, "render_annotation_artifacts", render)
    return expected_bundle, captured


@pytest.mark.asyncio
async def test_d1_5_production_annotation_executor_uses_exact_admitted_inputs_and_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    expected, captured = _install_success_seams(context, monkeypatch)
    effective_uid = os.geteuid()
    monkeypatch.setattr(os, "getuid", lambda: effective_uid + 1)
    monkeypatch.setattr(os, "geteuid", lambda: effective_uid)

    result = await _executor(run_020._execute_annotation)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )
    repeated = await _executor(run_020._execute_annotation)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )

    assert result is expected
    assert repeated is expected
    assert captured["schema_root"] != context.schema_root
    assert cast(Path, captured["schema_root"]).name == "schema"
    assert captured["annotator_client"] is context.client
    assert captured["annotator_registry"] is context.registry
    assert captured["annotator_model"] == _ANNOTATOR_MODEL
    assert captured["renderer_called"] is True
    assert captured["snapshot_terms_bytes"] == context.source_bytes[_TERMS]
    assert len(cast(list[tuple[str, bytes]], captured["page_loader_payloads"])) == 4


@pytest.mark.asyncio
async def test_d1_5_annotation_schema_drift_with_unchanged_version_blocks_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _expected, captured = _install_success_seams(
        context,
        monkeypatch,
        mutate_schema_after_snapshot=True,
    )

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_annotation)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            client=context.client,
            configuration=context.configuration,
        )

    assert caught.value.code == "annotation_identity_mismatch"
    assert captured["annotator_registry"] is context.registry
    assert captured["renderer_called"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("signed_schema", ["missing", "wrong-path"])
async def test_d1_5_annotation_rejects_unsigned_or_mispathed_schema_pre_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signed_schema: str,
) -> None:
    context = _context(tmp_path)
    product = context.document.identity_request.products[0]
    assert isinstance(product, ProductInputPlan)
    schema_digest = _sha256((context.schema_root / "base.yaml").read_bytes())
    shared = (
        {}
        if signed_schema == "missing"
        else {"docs/insurance-kb/wrong-schema/base.yaml": schema_digest}
    )
    context.document = _document(
        _identity(
            pdf_digests=product.pdf_digests,
            product_meta_digest=product.product_meta_digest,
            fields_digest=product.fields_digest,
            consumed_input_digests=product.consumed_input_digests,
            shared_input_digests=shared,
        )
    )
    _expected, captured = _install_success_seams(context, monkeypatch)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_annotation)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            client=context.client,
            configuration=context.configuration,
        )

    assert caught.value.code == "annotation_identity_mismatch"
    assert "records" not in captured


@pytest.mark.asyncio
async def test_d1_5_annotation_loads_schema_only_from_private_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    expected, captured = _install_success_seams(context, monkeypatch)

    result = await _executor(run_020._execute_annotation)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )

    schema_root = cast(Path, captured["schema_root"])
    assert result is expected
    assert schema_root != context.schema_root
    assert schema_root.name == "schema"
    assert schema_root.resolve().is_relative_to(
        (
            context.configuration.run_root
            / "annotation-input-snapshots"
            / compute_execution_plan_hash(context.document)
        ).resolve()
    )
    assert {path.name: path.read_bytes() for path in schema_root.iterdir()} == {
        "base.yaml": (context.schema_root / "base.yaml").read_bytes()
    }


@pytest.mark.parametrize("drift", ("repo", "snapshot", "verified-bytes"))
@pytest.mark.asyncio
async def test_d1_5_annotation_page_loader_rejects_any_verified_byte_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    context = _context(tmp_path)
    _expected, captured = _install_success_seams(context, monkeypatch)
    await _executor(run_020._execute_annotation)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )
    loader = cast(Callable[[str, bytes], list[PageText]], captured["page_loader"])
    verified_bytes = context.source_bytes[_TERMS]
    if drift == "repo":
        (context.product_dir / _TERMS).write_bytes(b"drifted repository PDF")
    elif drift == "snapshot":
        (cast(Path, captured["snapshot_dir"]) / _TERMS).chmod(0o600)
        (cast(Path, captured["snapshot_dir"]) / _TERMS).write_bytes(
            b"drifted snapshot PDF"
        )
    else:
        verified_bytes = b"unverified caller bytes"
    calls_before = len(
        cast(list[tuple[str, bytes]], captured["page_loader_payloads"])
    )

    with pytest.raises(AdmissionPausedError) as caught:
        loader(_TERMS, verified_bytes)

    assert caught.value.code == "annotation_quote_verification_failed"
    assert (
        len(cast(list[tuple[str, bytes]], captured["page_loader_payloads"]))
        == calls_before
    )


@pytest.mark.asyncio
async def test_d1_5_annotation_page_loader_rejects_legacy_path_single_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _expected, captured = _install_success_seams(context, monkeypatch)
    await _executor(run_020._execute_annotation)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )
    loader = cast(Callable[..., list[PageText]], captured["page_loader"])

    with pytest.raises(TypeError):
        loader(context.product_dir / _TERMS)


@pytest.mark.asyncio
async def test_d1_5_repository_race_uses_snapshot_but_blocks_artifact_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    real_renderer = execution_artifacts_020.render_annotation_artifacts
    _expected, captured = _install_success_seams(
        context,
        monkeypatch,
        mutate_repo_after_snapshot=True,
    )
    monkeypatch.setattr(run_020, "render_annotation_artifacts", real_renderer)

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_annotation)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            client=context.client,
            configuration=context.configuration,
        )

    assert caught.value.code == "annotation_identity_mismatch"
    assert captured["snapshot_terms_bytes"] == context.source_bytes[_TERMS]
    assert (context.product_dir / _TERMS).read_bytes() == b"raced repository bytes"
    assert "renderer_called" not in captured


@pytest.mark.parametrize(
    "failure",
    (
        "snapshot-symlink",
        "snapshot-public-mode",
        "snapshot-different-bytes",
        "snapshot-hardlink",
    ),
)
@pytest.mark.asyncio
async def test_d1_5_snapshot_is_private_exact_and_fail_closed_before_model_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context(tmp_path)
    snapshot_root = context.configuration.run_root / "annotation-input-snapshots"
    plan_dir = snapshot_root / compute_execution_plan_hash(context.document)
    admitted_inputs = run_020._revalidate_annotation_inputs(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )
    content_dir = plan_dir / run_020._annotation_snapshot_digest(admitted_inputs)
    product_group = content_dir / "product"
    snapshot_product = product_group / _PRODUCT_NAME
    snapshot_root.mkdir(mode=0o700)
    snapshot_root.chmod(0o700)
    if failure == "snapshot-symlink":
        attacker = tmp_path / "attacker-snapshot"
        attacker.mkdir(mode=0o700)
        plan_dir.symlink_to(attacker, target_is_directory=True)
    else:
        plan_dir.mkdir(mode=0o700)
        plan_dir.chmod(0o700)
        content_dir.mkdir(mode=0o700)
        content_dir.chmod(0o700)
        product_group.mkdir(mode=0o700)
        product_group.chmod(0o700)
        snapshot_product.mkdir(mode=0o755 if failure == "snapshot-public-mode" else 0o700)
        snapshot_product.chmod(
            0o755 if failure == "snapshot-public-mode" else 0o700
        )
        if failure in {"snapshot-different-bytes", "snapshot-hardlink"}:
            for name, value in context.source_bytes.items():
                path = snapshot_product / name
                if failure == "snapshot-hardlink" and name == _TERMS:
                    attacker = tmp_path / "linked-snapshot.pdf"
                    attacker.write_bytes(value)
                    os.link(attacker, path)
                else:
                    path.write_bytes(b"different" if name == _TERMS else value)
                path.chmod(0o400)

    calls: list[str] = []

    async def forbidden_annotate(*_args: object, **_kwargs: object) -> list[GoldenRecord]:
        calls.append("model")
        return []

    monkeypatch.setattr(run_020, "annotate_product", forbidden_annotate)
    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_annotation)(
            document=context.document,
            product_id=_PRODUCT_NAME,
            client=context.client,
            configuration=context.configuration,
        )

    assert caught.value.code == "annotation_snapshot_invalid"
    assert calls == []


@pytest.mark.parametrize(
    "failure",
    (
        "pending-product",
        "wrong-requested-product",
        "source-root-traversal",
        "pdf-symlink",
        "pdf-digest",
        "meta-digest",
        "fields-digest",
        "consumed-digest",
        "schema-version-drift",
        "plan-code-missing",
        "plan-code-drift",
        "clause-name-drift",
    ),
)
@pytest.mark.asyncio
async def test_d1_5_production_annotation_revalidates_identity_before_model_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context(tmp_path)
    product = context.document.identity_request.products[0]
    requested_product = _PRODUCT_NAME
    identity = context.document.identity_request
    loaded_registry: SchemaRegistry | None = None
    if failure == "pending-product":
        identity = _identity(
            pdf_digests=product.pdf_digests,
            product_meta_digest=None,
            fields_digest=product.fields_digest,
            consumed_input_digests=product.consumed_input_digests,
            pending=True,
            shared_input_digests=identity.shared_input_digests,
        )
    elif failure == "wrong-requested-product":
        requested_product = "另一个产品"
    elif failure == "source-root-traversal":
        identity = _identity(
            pdf_digests=product.pdf_digests,
            product_meta_digest=product.product_meta_digest,
            fields_digest=product.fields_digest,
            consumed_input_digests=product.consumed_input_digests,
            source_products_root="inputs/source/../source",
            shared_input_digests=identity.shared_input_digests,
        )
    elif failure == "pdf-symlink":
        pdf_path = context.product_dir / _TERMS
        attacker_path = tmp_path / "attacker.pdf"
        attacker_path.write_bytes(pdf_path.read_bytes())
        pdf_path.unlink()
        pdf_path.symlink_to(attacker_path)
    elif failure.endswith("-digest"):
        paths = {
            "pdf-digest": context.product_dir / _TERMS,
            "meta-digest": context.product_dir / "product_meta.json",
            "fields-digest": context.golden_product_dir / "fields.json",
            "consumed-digest": context.golden_product_dir / "prompt.txt",
        }
        path = paths[failure]
        path.write_bytes(path.read_bytes() + b"unsigned drift")
    elif failure == "schema-version-drift":
        loaded_registry = SchemaRegistry(
            version="v1.1+different-schema",
            lines=context.registry.lines,
            glossary=context.registry.glossary,
        )
    else:
        if failure == "plan-code-missing":
            meta = {"clauseName": _PRODUCT_NAME}
        elif failure == "plan-code-drift":
            meta = {"planCode": "9999", "clauseName": _PRODUCT_NAME}
        else:
            meta = {"planCode": _PLAN_CODE, "clauseName": "另一个产品"}
        meta_bytes = json.dumps(
            meta,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        (context.product_dir / "product_meta.json").write_bytes(meta_bytes)
        identity = _identity(
            pdf_digests=product.pdf_digests,
            product_meta_digest=_sha256(meta_bytes),
            fields_digest=product.fields_digest,
            consumed_input_digests=product.consumed_input_digests,
            shared_input_digests=identity.shared_input_digests,
        )
    if identity is not context.document.identity_request:
        context.document = _document(identity)

    calls: list[str] = []

    async def forbidden_annotate(*_args: object, **_kwargs: object) -> list[GoldenRecord]:
        calls.append("model")
        return []

    monkeypatch.setattr(run_020, "annotate_product", forbidden_annotate, raising=False)
    monkeypatch.setattr(runner, "annotate_product", forbidden_annotate)
    if loaded_registry is not None:
        monkeypatch.setattr(
            run_020,
            "load_schema_registry",
            lambda _path: loaded_registry,
        )

    with pytest.raises(AdmissionPausedError) as caught:
        await _executor(run_020._execute_annotation)(
            document=context.document,
            product_id=requested_product,
            client=context.client,
            configuration=context.configuration,
        )

    assert caught.value.code == "annotation_identity_mismatch"
    assert calls == []


@pytest.mark.asyncio
async def test_d1_5_production_dependencies_expose_the_real_annotation_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    expected, captured = _install_success_seams(context, monkeypatch)
    dependencies = run_020._production_ready_dependencies()

    assert dependencies.annotation_executor is run_020._execute_annotation
    result = await _executor(dependencies.annotation_executor)(
        document=context.document,
        product_id=_PRODUCT_NAME,
        client=context.client,
        configuration=context.configuration,
    )

    assert result is expected
    assert captured["renderer_called"] is True

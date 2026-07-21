"""OpenSpec 020 D1.5: real annotation bytes and evidence coverage."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict

from insurance_harness.goldenset.admission_artifacts import CanaryArtifactBundle
from insurance_harness.goldenset.admission_runtime import AdmissionPausedError
from insurance_harness.goldenset.annotator import GoldenAnnotator
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import Evidence, GoldenRecord, TriState
from insurance_harness.goldenset.runner import annotate_product, write_annotation_cache
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from tests.run_admission_execution_contract_020 import (
    ExecutionArtifacts020,
    execution_artifact_module_exists,
    execution_artifacts_or_skip,
)

_FIRST = "平安爱满分（2026）两全保险"
_PLAN_CODE = "1818"
_MODEL = "approved-annotator-v1"
_SCHEMA = "schema-v1+abcdef"
_LINE = "endowment"
_TERMS = "保险条款.pdf"
_BROCHURE = "产品说明书.pdf"
_RATE_TABLE = "产品费率表.pdf"
_TERMS_QUOTE = "等待期为九十日"
_BROCHURE_QUOTE = "保险期间为二十年"
_STARTED = datetime(2026, 7, 20, 1, 2, 3, tzinfo=UTC)
_FINISHED = _STARTED + timedelta(seconds=7)
_PLAN_HASH = "c" * 64


class _VersionedArtifact(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class _CacheFileV1(_VersionedArtifact):
    path: str
    sha256: str
    record_count: int


class _CheckpointV1(_VersionedArtifact):
    format: Literal["insurancekb.annotation-checkpoint.v1"]
    complete: Literal[True]
    cache_files: tuple[_CacheFileV1, ...]


class _VerifiedEvidenceV1(_VersionedArtifact):
    page: int
    quote_sha256: str
    matched: Literal[True]


class _VerifiedRecordV1(_VersionedArtifact):
    doc: str
    field_id: str
    evidence: tuple[_VerifiedEvidenceV1, ...]
    complete: Literal[True]


class _DocumentCoverageV1(_VersionedArtifact):
    doc: str
    pdf_sha256: str
    complete: Literal[True]


class _QuoteVerificationV1(_VersionedArtifact):
    format: Literal["insurancekb.quote-verification.v1"]
    documents: tuple[_DocumentCoverageV1, ...]
    records: tuple[_VerifiedRecordV1, ...]
    complete: Literal[True]


class _DisputedQualityV1(_VersionedArtifact):
    format: Literal["insurancekb.disputed-quality.v1"]
    quality_threshold_version: str
    record_count: int
    disputed_count: int
    reasons: dict[str, int]


class _InputDigestsV1(_VersionedArtifact):
    pdf_digests: dict[str, str]
    product_meta_digest: str
    fields_digest: str
    consumed_input_digests: dict[str, str]
    shared_input_digests: dict[str, str]


class _AnnotationIdentityV1(_VersionedArtifact):
    admission_product_name: str
    plan_code: str
    line_key: str
    schema_version: str
    annotator_model: str


class _AnnotationManifestV1(_VersionedArtifact):
    format: Literal["insurancekb.annotation-manifest.v1"]
    identity: _AnnotationIdentityV1
    execution_plan_hash: str
    started_at: datetime
    finished_at: datetime
    input_digests: _InputDigestsV1
    artifact_digests: dict[str, str]


@dataclass(slots=True)
class _AnnotationContext:
    document: object
    configuration: object
    cache_root: Path
    product_dir: Path
    golden_product_dir: Path
    records: tuple[GoldenRecord, ...]
    cache_files: tuple[Path, ...]
    verified_pdf_bytes: dict[str, bytes]
    page_texts: dict[str, list[PageText]]
    page_loads: list[str]

    def load_pages(self, doc: str, verified_bytes: bytes) -> list[PageText]:
        assert verified_bytes == self.verified_pdf_bytes[doc]
        self.page_loads.append(doc)
        return self.page_texts[doc]


@pytest.fixture
def artifact_contract() -> ExecutionArtifacts020:
    contract, _module = execution_artifacts_or_skip()
    return contract


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record(
    *,
    doc: str,
    field_id: str,
    field_name: str,
    value: str | None,
    quote: str | None,
    page: int = 1,
    tri_state: TriState = "present",
    disputed: bool = False,
    product_id: str = _PLAN_CODE,
    product_name: str = _FIRST,
    model: str = _MODEL,
    schema: str = _SCHEMA,
) -> GoldenRecord:
    return GoldenRecord(
        product_id=product_id,
        product_name=product_name,
        doc=doc,
        field_id=field_id,
        field_name=field_name,
        value=value,
        tri_state=tri_state,
        evidence=[] if quote is None else [Evidence(page=page, quote=quote)],
        disputed=disputed,
        disputed_reason="meta_mismatch" if disputed else None,
        annotator_model=model,
        schema_version=schema,
        created_at=_STARTED,
    )


def _records() -> tuple[GoldenRecord, GoldenRecord]:
    return (
        _record(
            doc=_TERMS,
            field_id="waiting_period",
            field_name="等待期",
            value="90日",
            quote=_TERMS_QUOTE,
            disputed=True,
        ),
        _record(
            doc=_BROCHURE,
            field_id="insurance_period",
            field_name="保险期间",
            value="20年",
            quote=_BROCHURE_QUOTE,
        ),
    )


def _write_cache(
    cache_root: Path,
    doc: str,
    records: Sequence[GoldenRecord],
    *,
    suffix: bytes = b"\n",
    schema_version: str = _SCHEMA,
) -> Path:
    schema_hash = schema_version.split("+")[-1]
    path = cache_root / _FIRST / f"{doc}.{schema_hash}.jsonl"
    if path.exists():
        path.unlink()
    path = write_annotation_cache(
        cache_root,
        _FIRST,
        doc,
        schema_version,
        list(records),
    )
    if suffix != b"\n":
        path.write_bytes(path.read_bytes().removesuffix(b"\n") + suffix)
    return path


def _context(tmp_path: Path) -> _AnnotationContext:
    repo_root = tmp_path / "repo"
    product_dir = repo_root / "dataset" / _FIRST
    golden_product_dir = repo_root / "golden" / _FIRST
    product_dir.mkdir(parents=True)
    golden_product_dir.mkdir(parents=True)
    pdf_bytes = {
        _TERMS: b"real-terms-pdf-input",
        _BROCHURE: b"real-brochure-pdf-input",
    }
    for name, value in pdf_bytes.items():
        (product_dir / name).write_bytes(value)
    meta_bytes = json.dumps(
        {"planCode": _PLAN_CODE, "clauseName": _FIRST},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    fields_bytes = json.dumps(
        {"line_key": _LINE, "schema_version": _SCHEMA},
        separators=(",", ":"),
    ).encode("utf-8")
    prompt_bytes = b"approved annotation prompt v1"
    (product_dir / "product_meta.json").write_bytes(meta_bytes)
    (golden_product_dir / "fields.json").write_bytes(fields_bytes)
    (golden_product_dir / "prompt.txt").write_bytes(prompt_bytes)

    records = _records()
    protected_run_root = tmp_path / "protected-run"
    protected_run_root.mkdir(mode=0o700)
    cache_root = protected_run_root / "annotation-cache"
    cache_files = (
        _write_cache(cache_root, records[0].doc, (records[0],)),
        # Preserve non-canonical whitespace so the checkpoint must hash actual bytes.
        _write_cache(cache_root, records[1].doc, (records[1],), suffix=b" \n"),
    )
    product = SimpleNamespace(
        product_id=_FIRST,
        line_key=_LINE,
        pdf_digests={name: _sha256(value) for name, value in pdf_bytes.items()},
        product_meta_path="product_meta.json",
        product_meta_digest=_sha256(meta_bytes),
        fields_digest=_sha256(fields_bytes),
        consumed_input_digests={"prompt.txt": _sha256(prompt_bytes)},
    )
    document = SimpleNamespace(
        identity_request=SimpleNamespace(
            source_products_root="dataset",
            golden_products_root="golden",
            products=(product,),
            shared_input_digests={},
            execution_surface_digests={},
        ),
        plan=SimpleNamespace(
            payload=SimpleNamespace(
                model_roles={"annotator": SimpleNamespace(model_id=_MODEL)}
            )
        ),
    )
    return _AnnotationContext(
        document=document,
        configuration=SimpleNamespace(
            repo_root=repo_root,
            run_root=protected_run_root,
        ),
        cache_root=cache_root,
        product_dir=product_dir,
        golden_product_dir=golden_product_dir,
        records=records,
        cache_files=cache_files,
        verified_pdf_bytes=pdf_bytes,
        page_texts={
            _TERMS: [PageText(page_no=1, text=f"条款原文：{_TERMS_QUOTE}。")],
            _BROCHURE: [
                PageText(page_no=1, text=f"说明书原文：{_BROCHURE_QUOTE}。")
            ],
        },
        page_loads=[],
    )


def _render(
    contract: ExecutionArtifacts020,
    context: _AnnotationContext,
    *,
    records: tuple[GoldenRecord, ...] | list[GoldenRecord] | None = None,
) -> CanaryArtifactBundle:
    return contract.render_annotation_artifacts(
        document=context.document,
        configuration=context.configuration,
        product_id=_FIRST,
        records=context.records if records is None else records,
        cache_dir=context.cache_root,
        page_loader=context.load_pages,
        started_at=_STARTED,
        finished_at=_FINISHED,
        execution_plan_hash=_PLAN_HASH,
    )


def _validate_annotation_bundle(
    contract: ExecutionArtifacts020,
    context: _AnnotationContext,
    bundle: CanaryArtifactBundle,
) -> CanaryArtifactBundle:
    return contract.validate_annotation_bundle(
        document=context.document,
        configuration=context.configuration,
        product_id=_FIRST,
        bundle=bundle,
        cache_dir=context.cache_root,
        page_loader=context.load_pages,
        execution_plan_hash=_PLAN_HASH,
    )


def test_d1_5_annotation_precommit_accepts_only_exact_rendered_bundle(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    bundle = _render(artifact_contract, context)
    monkeypatch.setattr(
        "insurance_harness.goldenset.execution_artifacts_020.extract_pages",
        lambda path: context.page_texts[path.name],
        raising=False,
    )

    assert _validate_annotation_bundle(artifact_contract, context, bundle) is bundle


def test_d1_5_annotation_precommit_rejects_nonempty_placeholder_bundle(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    placeholder = CanaryArtifactBundle(
        checkpoint=b"checkpoint",
        manifest=b"manifest",
        golden=b"golden",
        quote_verification=b"quote-verification",
        disputed_quality=b"disputed-quality",
        disputed_count=0,
        record_count=1,
        quality_threshold_version="golden-v0.1-thresholds-v1",
    )

    with pytest.raises(
        AdmissionPausedError,
        match="^canary_artifact_commit_invalid$",
    ):
        _validate_annotation_bundle(artifact_contract, context, placeholder)


@pytest.mark.parametrize("drift", ["repo-pdf", "cache", "manifest"])
def test_d1_5_annotation_precommit_rejects_post_render_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    context = _context(tmp_path)
    bundle = _render(artifact_contract, context)
    monkeypatch.setattr(
        "insurance_harness.goldenset.execution_artifacts_020.extract_pages",
        lambda path: context.page_texts[path.name],
        raising=False,
    )
    if drift == "repo-pdf":
        (context.product_dir / _TERMS).write_bytes(b"post-render-drift")
    elif drift == "cache":
        context.cache_files[0].write_bytes(b"post-render-drift")
    else:
        bundle = CanaryArtifactBundle(
            checkpoint=bundle.checkpoint,
            manifest=bundle.manifest + b" ",
            golden=bundle.golden,
            quote_verification=bundle.quote_verification,
            disputed_quality=bundle.disputed_quality,
            disputed_count=bundle.disputed_count,
            record_count=bundle.record_count,
            quality_threshold_version=bundle.quality_threshold_version,
        )

    with pytest.raises(
        AdmissionPausedError,
        match="^canary_artifact_commit_invalid$",
    ):
        _validate_annotation_bundle(artifact_contract, context, bundle)


class _FixtureAnnotator:
    def __init__(self, records: Sequence[GoldenRecord]) -> None:
        self._records = records

    async def annotate_document(
        self,
        product_id: str,
        product_name: str,
        doc_name: str,
        pages: list[PageText],
        line: ProductLineSchema,
        created_at: datetime | None = None,
    ) -> list[GoldenRecord]:
        del line, created_at
        assert product_id == _PLAN_CODE
        assert product_name == _FIRST
        assert pages
        return [
            record.model_copy(deep=True)
            for record in self._records
            if record.doc == doc_name
        ]


def test_d1_5_versioned_execution_artifact_contract_exists() -> None:
    assert execution_artifact_module_exists(), (
        "D1.5 requires the public execution_artifacts_020 contract before production "
        "annotation or baseline execution can replace placeholders"
    )


async def test_d1_5_real_runner_cache_is_directly_accepted_by_renderer(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    for cache_file in context.cache_files:
        cache_file.unlink()
    monkeypatch.setattr(
        "insurance_harness.goldenset.runner.extract_pages",
        lambda path: context.page_texts[path.name],
    )
    registry = SchemaRegistry(
        version=_SCHEMA,
        lines={
            _LINE: ProductLineSchema(
                line_key=_LINE,
                sheet_name="两全保险",
                fields=(
                    FieldSpec(
                        name="等待期",
                        field_id="waiting_period",
                        source_sheet="两全保险",
                    ),
                    FieldSpec(
                        name="保险期间",
                        field_id="insurance_period",
                        source_sheet="两全保险",
                    ),
                ),
            )
        },
        glossary=(),
    )

    records = await annotate_product(
        context.product_dir,
        registry,
        cast(GoldenAnnotator, _FixtureAnnotator(context.records)),
        context.cache_root,
        line_key=_LINE,
    )
    context.cache_files = tuple(
        sorted((context.cache_root / _FIRST).glob("*.jsonl"))
    )
    bundle = _render(artifact_contract, context, records=tuple(records))

    assert bundle.record_count == len(context.records)
    assert len(context.cache_files) == 2
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in context.cache_files)


def test_d1_5_annotation_artifacts_bind_exact_cache_bytes_all_pdfs_and_dual_identity(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    product = context.document.identity_request.products[0]  # type: ignore[attr-defined]
    assert {path.name for path in context.product_dir.iterdir()} == {
        _TERMS,
        _BROCHURE,
        "product_meta.json",
    }
    assert {path.name for path in context.golden_product_dir.iterdir()} == {
        "fields.json",
        "prompt.txt",
    }
    assert product.pdf_digests == {
        name: _sha256((context.product_dir / name).read_bytes())
        for name in (_TERMS, _BROCHURE)
    }
    assert product.product_meta_digest == _sha256(
        (context.product_dir / "product_meta.json").read_bytes()
    )
    assert product.fields_digest == _sha256(
        (context.golden_product_dir / "fields.json").read_bytes()
    )
    assert product.consumed_input_digests == {
        "prompt.txt": _sha256(
            (context.golden_product_dir / "prompt.txt").read_bytes()
        )
    }
    assert context.cache_root.parent.parent == tmp_path
    assert context.cache_root.parent != context.configuration.repo_root  # type: ignore[attr-defined]
    assert context.cache_root.parent.stat().st_mode & 0o077 == 0

    bundle = _render(artifact_contract, context)

    rendered_records = tuple(
        GoldenRecord.model_validate_json(line)
        for line in bundle.golden.decode("utf-8").splitlines()
    )
    assert sorted(rendered_records, key=lambda item: item.doc) == sorted(
        context.records, key=lambda item: item.doc
    )

    checkpoint = _CheckpointV1.model_validate_json(bundle.checkpoint)
    expected_cache = {
        path.relative_to(context.cache_root).as_posix(): (
            _sha256(path.read_bytes()),
            1,
        )
        for path in context.cache_files
    }
    assert {
        item.path: (item.sha256, item.record_count) for item in checkpoint.cache_files
    } == expected_cache
    assert {item.path for item in checkpoint.cache_files} == {
        f"{_FIRST}/{_TERMS}.abcdef.jsonl",
        f"{_FIRST}/{_BROCHURE}.abcdef.jsonl",
    }

    quote_report = _QuoteVerificationV1.model_validate_json(bundle.quote_verification)
    assert {item.doc: item.pdf_sha256 for item in quote_report.documents} == dict(
        product.pdf_digests
    )
    assert {(item.doc, item.field_id) for item in quote_report.records} == {
        (record.doc, record.field_id) for record in context.records
    }
    assert sorted(context.page_loads) == sorted(product.pdf_digests)
    for item in quote_report.records:
        source = next(
            record
            for record in context.records
            if (record.doc, record.field_id) == (item.doc, item.field_id)
        )
        assert tuple(evidence.quote_sha256 for evidence in item.evidence) == tuple(
            _sha256(evidence.quote.encode("utf-8")) for evidence in source.evidence
        )

    quality = _DisputedQualityV1.model_validate_json(bundle.disputed_quality)
    assert (quality.record_count, quality.disputed_count) == (2, 1)
    assert quality.reasons == {"meta_mismatch": 1}
    assert quality.quality_threshold_version == "golden-v0.1-thresholds-v1"
    assert bundle.quality_threshold_version == quality.quality_threshold_version

    manifest = _AnnotationManifestV1.model_validate_json(bundle.manifest)
    assert manifest.identity == _AnnotationIdentityV1(
        admission_product_name=_FIRST,
        plan_code=_PLAN_CODE,
        line_key=_LINE,
        schema_version=_SCHEMA,
        annotator_model=_MODEL,
    )
    assert manifest.execution_plan_hash == _PLAN_HASH
    assert (manifest.started_at, manifest.finished_at) == (_STARTED, _FINISHED)
    assert manifest.input_digests == _InputDigestsV1(
        pdf_digests=dict(product.pdf_digests),
        product_meta_digest=product.product_meta_digest,
            fields_digest=product.fields_digest,
            consumed_input_digests=dict(product.consumed_input_digests),
            shared_input_digests={},
        )
    assert manifest.artifact_digests == {
        "checkpoint": _sha256(bundle.checkpoint),
        "golden": _sha256(bundle.golden),
        "quote_verification": _sha256(bundle.quote_verification),
        "disputed_quality": _sha256(bundle.disputed_quality),
    }
    assert (bundle.record_count, bundle.disputed_count) == (2, 1)


def test_d1_5_annotation_checkpoint_requires_empty_cache_for_zero_record_pdf(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    product = context.document.identity_request.products[0]  # type: ignore[attr-defined]
    rate_bytes = b"real-rate-table-pdf-input"
    (context.product_dir / _RATE_TABLE).write_bytes(rate_bytes)
    product.pdf_digests[_RATE_TABLE] = _sha256(rate_bytes)
    context.verified_pdf_bytes[_RATE_TABLE] = rate_bytes
    context.page_texts[_RATE_TABLE] = [PageText(page_no=1, text="费率表无目标字段")]
    empty_cache = _write_cache(
        context.cache_root,
        _RATE_TABLE,
        (),
        schema_version=_SCHEMA,
    )

    bundle = _render(artifact_contract, context)

    checkpoint = _CheckpointV1.model_validate_json(bundle.checkpoint)
    by_path = {item.path: item for item in checkpoint.cache_files}
    empty_item = by_path[f"{_FIRST}/{_RATE_TABLE}.abcdef.jsonl"]
    assert empty_cache.read_bytes() == b""
    assert empty_item.sha256 == _sha256(b"")
    assert empty_item.record_count == 0
    report = _QuoteVerificationV1.model_validate_json(bundle.quote_verification)
    assert {item.doc for item in report.documents} == {_TERMS, _BROCHURE, _RATE_TABLE}
    assert all(item.complete is True for item in report.documents)


def test_d1_5_annotation_rejects_missing_empty_cache_for_zero_record_pdf(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    product = context.document.identity_request.products[0]  # type: ignore[attr-defined]
    rate_bytes = b"real-rate-table-pdf-input"
    (context.product_dir / _RATE_TABLE).write_bytes(rate_bytes)
    product.pdf_digests[_RATE_TABLE] = _sha256(rate_bytes)
    context.verified_pdf_bytes[_RATE_TABLE] = rate_bytes
    context.page_texts[_RATE_TABLE] = [PageText(page_no=1, text="费率表无目标字段")]

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context)

    assert error.value.code == "annotation_cache_invalid"
    assert context.page_loads == []


@pytest.mark.parametrize(
    "failure",
    (
        "pdf-missing",
        "pdf-drift",
        "meta-missing",
        "meta-drift",
        "fields-missing",
        "fields-drift",
        "consumed-missing",
        "consumed-drift",
        "extra-pdf",
        "no-pdf",
    ),
)
def test_d1_5_annotation_revalidates_declared_input_bytes_before_page_loader(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    context = _context(tmp_path)
    paths = {
        "pdf": context.product_dir / _TERMS,
        "meta": context.product_dir / "product_meta.json",
        "fields": context.golden_product_dir / "fields.json",
        "consumed": context.golden_product_dir / "prompt.txt",
    }
    if failure == "extra-pdf":
        (context.product_dir / "未声明附件.pdf").write_bytes(b"unsigned-pdf")
    elif failure == "no-pdf":
        for name in (_TERMS, _BROCHURE):
            (context.product_dir / name).unlink()
    else:
        kind, mutation = failure.split("-", maxsplit=1)
        path = paths[kind]
        if mutation == "missing":
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b"unsigned-drift")

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context)

    assert error.value.code == "annotation_identity_mismatch"
    assert context.page_loads == []


def test_d1_5_annotation_loader_window_repo_pdf_swap_is_rejected(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    calls: list[tuple[str, bytes]] = []

    def swapping_loader(doc: str, verified_bytes: bytes) -> list[PageText]:
        assert verified_bytes == context.verified_pdf_bytes[doc]
        calls.append((doc, verified_bytes))
        if len(calls) == 1:
            (context.product_dir / doc).write_bytes(b"swapped-after-verification")
        return context.page_texts[doc]

    with pytest.raises(AdmissionPausedError) as error:
        artifact_contract.render_annotation_artifacts(
            document=context.document,
            configuration=context.configuration,
            product_id=_FIRST,
            records=context.records,
            cache_dir=context.cache_root,
            page_loader=swapping_loader,
            started_at=_STARTED,
            finished_at=_FINISHED,
            execution_plan_hash=_PLAN_HASH,
        )

    assert error.value.code == "annotation_identity_mismatch"
    assert calls


def test_d1_5_annotation_rejects_detached_pages_for_another_verified_document(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    def detached_loader(doc: str, verified_bytes: bytes) -> list[PageText]:
        assert verified_bytes == context.verified_pdf_bytes[doc]
        other = _BROCHURE if doc == _TERMS else _TERMS
        return context.page_texts[other]

    with pytest.raises(AdmissionPausedError) as error:
        artifact_contract.render_annotation_artifacts(
            document=context.document,
            configuration=context.configuration,
            product_id=_FIRST,
            records=context.records,
            cache_dir=context.cache_root,
            page_loader=detached_loader,
            started_at=_STARTED,
            finished_at=_FINISHED,
            execution_plan_hash=_PLAN_HASH,
        )

    assert error.value.code == "annotation_quote_verification_failed"


def test_d1_5_annotation_failure_does_not_expose_nested_exception_context(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    (context.product_dir / _TERMS).unlink()

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context)

    assert str(error.value) == "annotation_identity_mismatch"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_d1_5_annotation_render_is_canonical_for_same_fixed_inputs_and_times(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    first_context = _context(tmp_path / "first")
    second_context = _context(tmp_path / "second")

    # Re-create every enumerated input set in reverse order.  The renderer must
    # canonicalize semantic inputs, never inherit filesystem or caller ordering.
    for directory in (
        second_context.product_dir,
        second_context.golden_product_dir,
        second_context.cache_root / _FIRST,
    ):
        entries = [
            (path.name, path.read_bytes(), path.stat().st_mode & 0o777)
            for path in directory.iterdir()
        ]
        for path in directory.iterdir():
            path.unlink()
        for name, payload, mode in reversed(entries):
            recreated = directory / name
            recreated.write_bytes(payload)
            recreated.chmod(mode)

    first = _render(artifact_contract, first_context)
    second = _render(
        artifact_contract,
        second_context,
        records=list(reversed(second_context.records)),
    )

    assert second == first
    assert (
        second.checkpoint,
        second.manifest,
        second.golden,
        second.quote_verification,
        second.disputed_quality,
    ) == (
        first.checkpoint,
        first.manifest,
        first.golden,
        first.quote_verification,
        first.disputed_quality,
    )


def test_d1_5_annotation_cache_ownership_uses_effective_process_uid(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    effective_uid = os.geteuid()
    monkeypatch.setattr(os, "getuid", lambda: effective_uid + 1)
    monkeypatch.setattr(os, "geteuid", lambda: effective_uid)

    bundle = _render(artifact_contract, context)

    assert bundle.record_count == len(context.records)


def test_d1_5_annotation_unknown_and_absent_have_distinct_complete_evidence_rules(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    absent_quote = "本产品未约定满期自动续保责任"
    unknown = _record(
        doc=_TERMS,
        field_id="unresolved_rider",
        field_name="未决附加责任",
        value=None,
        quote=None,
        tri_state="unknown",
    )
    absent = _record(
        doc=_BROCHURE,
        field_id="automatic_renewal",
        field_name="自动续保",
        value=None,
        quote=absent_quote,
        tri_state="absent_explicitly",
    )
    records = (*context.records, unknown, absent)
    _write_cache(
        context.cache_root,
        _TERMS,
        (context.records[0], unknown),
    )
    _write_cache(
        context.cache_root,
        _BROCHURE,
        (context.records[1], absent),
    )
    brochure_page = context.page_texts[_BROCHURE][0]
    context.page_texts[_BROCHURE] = [
        PageText(page_no=brochure_page.page_no, text=f"{brochure_page.text}。{absent_quote}")
    ]

    bundle = _render(artifact_contract, context, records=list(records))
    report = _QuoteVerificationV1.model_validate_json(bundle.quote_verification)
    by_field = {record.field_id: record for record in report.records}

    assert unknown.evidence == []
    assert by_field[unknown.field_id].complete is True
    assert by_field[unknown.field_id].evidence == ()
    assert absent.evidence == [Evidence(page=1, quote=absent_quote)]
    assert by_field[absent.field_id].complete is True
    assert tuple(item.quote_sha256 for item in by_field[absent.field_id].evidence) == (
        _sha256(absent_quote.encode("utf-8")),
    )


@pytest.mark.parametrize("failure", ("unknown-with-evidence", "absent-without-evidence"))
def test_d1_5_annotation_rejects_illegal_tri_state_evidence_combinations(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    context = _context(tmp_path)
    records = list(context.records)
    if failure == "unknown-with-evidence":
        records[0] = records[0].model_copy(
            update={"tri_state": "unknown", "value": None}
        )
    else:
        records[0] = records[0].model_copy(
            update={"tri_state": "absent_explicitly", "value": None, "evidence": []}
        )
    _write_cache(context.cache_root, records[0].doc, (records[0],))

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context, records=records)

    assert error.value.code == "annotation_quote_verification_failed"


def test_d1_5_annotation_empty_records_has_distinct_blocker(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context, records=[])

    assert error.value.code == "annotation_records_empty"


@pytest.mark.parametrize("failure", ("drift", "missing", "extra", "missing-record"))
def test_d1_5_annotation_cache_set_and_content_must_exactly_match_records(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    context = _context(tmp_path)
    records: tuple[GoldenRecord, ...] | list[GoldenRecord] = context.records
    if failure == "drift":
        changed = context.records[0].model_copy(update={"value": "180日"})
        context.cache_files[0].write_text(changed.model_dump_json() + "\n")
    elif failure == "missing":
        context.cache_files[1].unlink()
    elif failure == "extra":
        extra = context.cache_root / _FIRST / "orphan.jsonl"
        extra.write_text(context.records[0].model_dump_json() + "\n")
    else:
        records = context.records[:1]

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context, records=records)

    assert error.value.code == "annotation_cache_invalid"


@pytest.mark.parametrize("failure", ("quote-drift", "cross-document", "wrong-page"))
def test_d1_5_annotation_quote_verification_is_per_document_and_not_inferred(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    context = _context(tmp_path)
    records = list(context.records)
    if failure == "quote-drift":
        # The affected record is undisputed; disputed=false must not imply verified=true.
        context.page_texts[_BROCHURE] = [PageText(page_no=1, text="无对应引文")]
    elif failure == "cross-document":
        context.page_texts[_TERMS], context.page_texts[_BROCHURE] = (
            context.page_texts[_BROCHURE],
            context.page_texts[_TERMS],
        )
    else:
        records[0] = context.records[0].model_copy(
            update={"evidence": [Evidence(page=2, quote=_TERMS_QUOTE)]}
        )
        _write_cache(context.cache_root, records[0].doc, (records[0],))

    with pytest.raises(AdmissionPausedError) as error:
        _render(artifact_contract, context, records=records)

    assert error.value.code == "annotation_quote_verification_failed"


@pytest.mark.parametrize(
    "failure",
    (
        "admission-product",
        "record-product-name",
        "plan-code",
        "clause-name",
        "line",
        "schema",
        "model",
        "record-doc",
        "extra-source-pdf",
    ),
)
def test_d1_5_annotation_identity_drift_has_distinct_blocker(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    context = _context(tmp_path)
    records = list(context.records)
    product = context.document.identity_request.products[0]  # type: ignore[attr-defined]
    product_id = _FIRST
    if failure == "admission-product":
        product_id = "另一个产品"
    elif failure == "record-product-name":
        records[0] = records[0].model_copy(update={"product_name": "错误产品名"})
        _write_cache(context.cache_root, records[0].doc, (records[0],))
    elif failure == "plan-code":
        meta = json.dumps(
            {"planCode": "9999", "clauseName": _FIRST},
            ensure_ascii=False,
        ).encode("utf-8")
        (context.product_dir / "product_meta.json").write_bytes(meta)
        product.product_meta_digest = _sha256(meta)
    elif failure == "clause-name":
        meta = json.dumps(
            {"planCode": _PLAN_CODE, "clauseName": "错误产品名"},
            ensure_ascii=False,
        ).encode("utf-8")
        (context.product_dir / "product_meta.json").write_bytes(meta)
        product.product_meta_digest = _sha256(meta)
    elif failure == "line":
        product.line_key = "health"
    elif failure == "schema":
        records[0] = records[0].model_copy(update={"schema_version": "schema-v2"})
        _write_cache(context.cache_root, records[0].doc, (records[0],))
    elif failure == "model":
        records[0] = records[0].model_copy(update={"annotator_model": "other-model"})
        _write_cache(context.cache_root, records[0].doc, (records[0],))
    elif failure == "record-doc":
        records[0] = records[0].model_copy(update={"doc": "未知附件.pdf"})
        _write_cache(context.cache_root, records[0].doc, (records[0],))
        context.cache_files[0].unlink()
    else:
        (context.product_dir / "未签名附件.pdf").write_bytes(b"extra-pdf")

    with pytest.raises(AdmissionPausedError) as error:
        artifact_contract.render_annotation_artifacts(
            document=context.document,
            configuration=context.configuration,
            product_id=product_id,
            records=records,
            cache_dir=context.cache_root,
            page_loader=context.load_pages,
            started_at=_STARTED,
            finished_at=_FINISHED,
            execution_plan_hash=_PLAN_HASH,
        )

    assert error.value.code == "annotation_identity_mismatch"

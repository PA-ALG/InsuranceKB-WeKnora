"""OpenSpec 061: offline pdfplumber baseline artifact capture."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import stat
import traceback
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from insurance_harness.compiler.material_profiles import (
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    load_material_profile_catalog,
    resolve_material_profile,
)
from insurance_harness.compiler.native_pdfplumber import NativePdfplumberFacts
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    build_parse_manifest,
    evaluate_parse_quality,
)
from insurance_harness.sources.models import GenerationOrdering, SourceRevision
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

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "harness/scripts/capture_596_1_pdfplumber_artifacts_061.py"
CATALOG = ROOT / "harness/tests/fixtures/material_profile_596_1_052.json"
PRODUCT_DIR = ROOT / "dataset/shouxian_product/平安e生保（尊享版）医疗保险"
SOURCE_PATHS = {
    "terms": PRODUCT_DIR / "保险条款.pdf",
    "brochure": PRODUCT_DIR / "产品说明书.pdf",
    "rate_table": PRODUCT_DIR / "费率表.pdf",
}
SOURCE_SHA256 = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}
ROLES = ("terms", "brochure", "rate_table")
CONFIG_HASH = "a" * 64


class _TemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self._entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self._entry if scope == self._entry.version.scope else None


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_596_1_pdfplumber_artifacts_061", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _template_catalog() -> _TemplateCatalog:
    catalog = load_material_profile_catalog(CATALOG)
    scope = TemplateScope(space_id="space-061", level="global")
    content = TemplatePackageContent(
        schema_version=catalog.schema_binding.schema_version,
        field_groups=(
            FieldGroup(
                group_id="group-061",
                field_ids=(catalog.schema_binding.field_ids[0],),
                evidence_roles=("terms",),
            ),
        ),
        role_prompts={"extract": "extract-061"},
        validators=(
            ValidatorRef(
                validator_id="validator-061",
                validator_version="v1",
                config_hash="1" * 64,
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
                migration_id="MIG-061-test",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="task-local baseline capture",
                rejected_behavior="runtime identity invention",
                python_target=str(SCRIPT.relative_to(ROOT)),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(str(Path(__file__).relative_to(ROOT)),),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id="061-test-v1",
        scope=scope,
        content=content,
    )
    return _TemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="approval-061",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )


def _resolutions() -> dict[str, MaterialProfileResolution]:
    catalog = load_material_profile_catalog(CATALOG)
    templates = _template_catalog()
    return {
        profile.material_role: resolve_material_profile(
            catalog,
            templates,
            MaterialProfileResolutionRequest(
                space_id="space-061",
                product_code=catalog.product.product_code,
                product_version=catalog.product.product_version,
                schema_version=catalog.schema_binding.schema_version,
                schema_field_ids=catalog.schema_binding.field_ids,
                source=profile.source,
                classified_material_role=profile.material_role,
            ),
        )
        for profile in catalog.profiles
    }


def _parser_fingerprint(parser: ParserIdentityV1) -> str:
    return _sha(parser.model_dump(mode="json"))


def _request() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for role, resolution in _resolutions().items():
        parser = ParserIdentityV1(
            parser_id="pdfplumber",
            parser_profile_ref=(resolution.parse_policy_receipt.default_parser_profile_ref),
            parser_build_id="pdfplumber-test-build-v1",
            parser_config_hash=CONFIG_HASH,
        )
        source_revision = SourceRevision(
            file_hash=resolution.profile.source.sha256,
            ordering=GenerationOrdering(value=1),
            parser_fingerprint=_parser_fingerprint(parser),
        )
        subject = ParseSubjectV1(
            space_id="space-061",
            source_id=f"source-061-{role}",
            source_revision_id=source_revision.value,
            product_version_id=resolution.request.product_version,
            material_profile_id=resolution.profile.profile_id,
            material_profile_binding_hash=resolution.binding_hash,
            source_sha256=resolution.profile.source.sha256,
            raw_artifact_hash=_sha({"role": role, "kind": "raw"}),
            canonical_envelope_hash=_sha({"role": role, "kind": "envelope"}),
        )
        entries.append(
            {
                "material_role": role,
                "source_revision": source_revision.model_dump(mode="json"),
                "attempt_state": "completed",
                "parse_policy_receipt": (resolution.parse_policy_receipt.model_dump(mode="json")),
                "subject": subject.model_dump(mode="json"),
                "parser": parser.model_dump(mode="json"),
                "attempt": ParseAttemptV1(
                    attempt_id=f"parse-attempt-061-{role}",
                    attempt_number=1,
                    attempt_role="default",
                    generation=1,
                ).model_dump(mode="json"),
                "snapshot": ParseSnapshotV1(
                    snapshot_id=f"snapshot-061-{role}",
                    snapshot_generation=1,
                    pagination_complete=True,
                    concurrent_mutation_fence_hash=_sha({"role": role, "kind": "fence"}),
                ).model_dump(mode="json"),
                "output_facts": ParseOutputFactsV1(
                    privacy_policy_ref=(resolution.parse_policy_receipt.privacy_policy_ref),
                    output_policy_ref=(resolution.parse_policy_receipt.output_policy_ref),
                    body_text_included=False,
                    secrets_included=False,
                    absolute_paths_included=False,
                    unknown_vendor_fields_included=False,
                ).model_dump(mode="json"),
                "material_profile_resolution": resolution.model_dump(mode="json"),
            }
        )
    return {
        "contract": "pdfplumber-baseline-capture-request.v1",
        "product_version": "596-1",
        "materials": entries,
    }


def _pdf_bytes() -> dict[str, bytes]:
    payloads = {role: path.read_bytes() for role, path in SOURCE_PATHS.items()}
    assert {
        role: hashlib.sha256(payload).hexdigest() for role, payload in payloads.items()
    } == SOURCE_SHA256
    return payloads


def _admitted_contract(
    *,
    subject: ParseSubjectV1,
    parser: ParserIdentityV1,
    attempt: ParseAttemptV1,
    snapshot: ParseSnapshotV1,
    output_facts: ParseOutputFactsV1,
    resolution: MaterialProfileResolution,
    salt: str = "stable",
) -> tuple[ParsedDocumentV1, Any, ParseQualityDecisionV1]:
    prefix = resolution.profile.material_role
    page_ids = (f"{prefix}-page-1", f"{prefix}-page-2")
    block_ids = (f"{prefix}-block-1", f"{prefix}-block-2")
    table_ids = (f"{prefix}-table-1", f"{prefix}-table-2")
    cell_ids = (f"{prefix}-cell-1", f"{prefix}-cell-2")
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output_facts,
        pages=tuple(
            ParsePageV1(
                page_id=page_id,
                order_index=index,
                locator=PageLocatorV1(page_number=index + 1),
                content_hash=_sha({"page": page_id, "salt": salt}),
                structure_hash=_sha({"page": page_id, "structure": 1}),
            )
            for index, page_id in enumerate(page_ids)
        ),
        blocks=tuple(
            ParseBlockV1(
                block_id=block_id,
                order_index=index,
                locator=BlockLocatorV1(
                    page_number=index + 1,
                    block_index=0,
                    bbox=(Decimal(0), Decimal(0), Decimal(10), Decimal(10)),
                ),
                content_hash=_sha({"block": block_id}),
                structure_hash=_sha({"block": block_id, "structure": 1}),
            )
            for index, block_id in enumerate(block_ids)
        ),
        tables=(
            ParseTableV1(
                table_id=table_ids[0],
                order_index=0,
                locator=TableLocatorV1(
                    page_number=1,
                    table_index=0,
                    bbox=(Decimal(0), Decimal(0), Decimal(10), Decimal(20)),
                ),
                content_hash=_sha({"table": table_ids[0]}),
                structure_hash=_sha({"table": table_ids[0], "structure": 1}),
                row_count=2,
                column_count=1,
                header_cell_ids=(cell_ids[0],),
                continuation_table_ids=(table_ids[1],),
            ),
            ParseTableV1(
                table_id=table_ids[1],
                order_index=1,
                locator=TableLocatorV1(
                    page_number=2,
                    table_index=0,
                    bbox=(Decimal(0), Decimal(0), Decimal(10), Decimal(10)),
                ),
                content_hash=_sha({"table": table_ids[1]}),
                structure_hash=_sha({"table": table_ids[1], "structure": 1}),
                row_count=1,
                column_count=1,
                header_cell_ids=(cell_ids[1],),
                continuation_table_ids=(),
            ),
        ),
        cells=(
            ParseCellV1(
                cell_id=cell_ids[0],
                order_index=0,
                table_id=table_ids[0],
                locator=CellLocatorV1(
                    page_number=1,
                    table_id=table_ids[0],
                    row_index=0,
                    column_index=0,
                    row_span=2,
                    column_span=1,
                    bbox=(Decimal(0), Decimal(0), Decimal(10), Decimal(20)),
                ),
                content_hash=_sha({"cell": cell_ids[0]}),
                structure_hash=_sha({"cell": cell_ids[0], "structure": 1}),
            ),
            ParseCellV1(
                cell_id=cell_ids[1],
                order_index=1,
                table_id=table_ids[1],
                locator=CellLocatorV1(
                    page_number=2,
                    table_id=table_ids[1],
                    row_index=0,
                    column_index=0,
                    row_span=1,
                    column_span=1,
                    bbox=(Decimal(0), Decimal(0), Decimal(10), Decimal(10)),
                ),
                content_hash=_sha({"cell": cell_ids[1]}),
                structure_hash=_sha({"cell": cell_ids[1], "structure": 1}),
            ),
        ),
        capability_evidence=(
            CapabilityEvidenceV1(capability="ordered_pages", subject_refs=page_ids),
            CapabilityEvidenceV1(capability="block_locators", subject_refs=block_ids),
            CapabilityEvidenceV1(capability="cross_page_sections", subject_refs=block_ids),
            CapabilityEvidenceV1(capability="table_grid", subject_refs=table_ids + cell_ids),
            CapabilityEvidenceV1(capability="cell_locators", subject_refs=cell_ids),
            CapabilityEvidenceV1(capability="header_hierarchy", subject_refs=table_ids + cell_ids),
            CapabilityEvidenceV1(capability="row_column_indices", subject_refs=cell_ids),
            CapabilityEvidenceV1(capability="merged_cells", subject_refs=(cell_ids[0],)),
            CapabilityEvidenceV1(capability="cross_page_tables", subject_refs=table_ids),
        ),
        warnings=(),
        unsupported=(),
    )
    manifest = build_parse_manifest(document, resolution.profile)
    decision = evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=resolution,
    )
    assert decision.decision == "ADMIT"
    return document, manifest, decision


def _install_admitting_adapter(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    salt_for_call: Callable[[int], str] | None = None,
) -> list[str]:
    calls: list[str] = []

    def extract(
        pdf_bytes: bytes,
        *,
        expected_source_sha256: str,
        parser_build_id: str,
        parser_config_hash: str,
    ) -> NativePdfplumberFacts:
        assert hashlib.sha256(pdf_bytes).hexdigest() == expected_source_sha256
        assert parser_build_id == "pdfplumber-test-build-v1"
        assert parser_config_hash == CONFIG_HASH
        calls.append(expected_source_sha256)
        return NativePdfplumberFacts(
            parser_engine="pdfplumber",
            parser_build_id=parser_build_id,
            parser_config_hash=parser_config_hash,
            source_sha256=expected_source_sha256,
            pages=(),
            capability_evidence=(),
            supported_capabilities=(),
            unsupported_capabilities=(),
        )

    def bridge(
        facts: NativePdfplumberFacts,
        *,
        subject: ParseSubjectV1,
        parser: ParserIdentityV1,
        attempt: ParseAttemptV1,
        snapshot: ParseSnapshotV1,
        output_facts: ParseOutputFactsV1,
        material_profile_resolution: MaterialProfileResolution,
    ) -> tuple[ParsedDocumentV1, Any, ParseQualityDecisionV1]:
        salt = salt_for_call(len(calls)) if salt_for_call is not None else "stable"
        assert facts.source_sha256 == subject.source_sha256
        return _admitted_contract(
            subject=subject,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output_facts,
            resolution=material_profile_resolution,
            salt=salt,
        )

    monkeypatch.setattr(module.native_pdfplumber, "extract_native_pdfplumber_facts", extract)
    monkeypatch.setattr(module.native_pdfplumber, "build_parsed_document_v1", bridge)
    return calls


def _capture_error(module: ModuleType, _reason_code: str) -> type[Any]:
    return cast(type[Any], module.BaselineArtifactCaptureError)


def _production_exception_graph_reaches(
    error: BaseException,
    needle: str | bytes,
) -> bool:
    seen: set[int] = set()

    def reaches(value: object) -> bool:
        identity = id(value)
        if identity in seen:
            return False
        seen.add(identity)
        if isinstance(needle, bytes):
            if isinstance(value, bytes):
                return value == needle
        elif isinstance(value, (str, Path)):
            return needle in str(value)
        if isinstance(value, Mapping):
            return any(reaches(key) or reaches(item) for key, item in value.items())
        if isinstance(value, (tuple, list, set, frozenset)):
            return any(reaches(item) for item in value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return reaches(model_dump(mode="python"))
        return False

    pending: list[BaseException] = [error]
    while pending:
        current_error = pending.pop()
        if reaches(str(current_error)) or reaches(repr(current_error)):
            return True
        if current_error.__cause__ is not None:
            pending.append(current_error.__cause__)
        if current_error.__context__ is not None:
            pending.append(current_error.__context__)
        current_traceback = current_error.__traceback__
        while current_traceback is not None:
            if Path(current_traceback.tb_frame.f_code.co_filename) == SCRIPT and reaches(
                current_traceback.tb_frame.f_locals
            ):
                return True
            current_traceback = current_traceback.tb_next
    return False


def test_061_capture_freezes_three_deterministic_private_artifacts(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_admitting_adapter(mod, monkeypatch)
    outputs = (tmp_path / "capture-a", tmp_path / "capture-b")
    results = [
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), output) for output in outputs
    ]

    assert len(calls) == 12  # three materials, two deterministic passes, two captures
    assert results[0].artifact_hashes == results[1].artifact_hashes
    expected_files = {
        "terms.json",
        "brochure.json",
        "rate-table.json",
        "capture-manifest.json",
    }
    for output in outputs:
        assert stat.S_IMODE(output.stat().st_mode) == 0o700
        assert {item.name for item in output.iterdir()} == expected_files
        assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in output.iterdir())
    assert {name: (outputs[0] / name).read_bytes() for name in expected_files} == {
        name: (outputs[1] / name).read_bytes() for name in expected_files
    }
    raw = b"".join((outputs[0] / name).read_bytes() for name in expected_files)
    assert b"%PDF" not in raw
    assert b"/" + b"Users/" not in raw
    assert b"/" + b"private/" not in raw
    assert b"must-not-survive" not in raw
    manifest = json.loads((outputs[0] / "capture-manifest.json").read_text())
    assert manifest["material_roles"] == list(ROLES)
    assert manifest["files"] == {
        name: hashlib.sha256((outputs[0] / name).read_bytes()).hexdigest()
        for name in ("terms.json", "brochure.json", "rate-table.json")
    }


def test_061_publication_enforces_modes_under_restrictive_umask(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_admitting_adapter(mod, monkeypatch)
    output = tmp_path / "capture"
    previous = os.umask(0o700)
    try:
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), output)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(item.stat().st_mode) == 0o600 for item in output.iterdir()
    )


def test_061_real_pdfplumber_blocks_exact_terms_without_persistent_artifact(
    mod: ModuleType,
    tmp_path: Path,
) -> None:
    output = tmp_path / "capture"

    with pytest.raises(_capture_error(mod, "BASELINE_PARSE_QUALITY_BLOCKED")) as caught:
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), output)

    assert caught.value.reason_code == "BASELINE_PARSE_QUALITY_BLOCKED"
    assert caught.value.diagnostic.material_role == "terms"
    assert "table_grid_or_span_incomplete" in caught.value.diagnostic.reason_codes
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    (
        (lambda request: request["materials"][0].pop("source_revision"), "INVALID_CAPTURE_REQUEST"),
        (
            lambda request: request["materials"][0].update({"attempt_state": "processing"}),
            "ATTEMPT_NOT_COMPLETED",
        ),
        (
            lambda request: request["materials"][0]["parser"].update(
                {"parser_id": "not-pdfplumber"}
            ),
            "PARSER_POLICY_DRIFT",
        ),
        (
            lambda request: request["materials"][0]["parse_policy_receipt"].update(
                {"policy_version": "drifted"}
            ),
            "PARSER_POLICY_DRIFT",
        ),
        (
            lambda request: request["materials"][0]["subject"].update(
                {"source_revision_id": "wrong-revision"}
            ),
            "SOURCE_IDENTITY_MISMATCH",
        ),
    ),
)
def test_061_authority_drift_fails_before_parser_and_output(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], object],
    reason_code: str,
) -> None:
    calls = _install_admitting_adapter(mod, monkeypatch)
    request = cast(dict[str, Any], copy.deepcopy(_request()))
    mutate(request)
    output = tmp_path / "capture"

    with pytest.raises(_capture_error(mod, reason_code)) as caught:
        mod.capture_pdfplumber_artifacts(request, _pdf_bytes(), output)
    assert caught.value.reason_code == reason_code
    assert calls == [] and not output.exists()


def test_061_output_policy_and_unknown_secret_fail_before_parser(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_admitting_adapter(mod, monkeypatch)
    unsafe = cast(dict[str, Any], copy.deepcopy(_request()))
    unsafe["materials"][0]["output_facts"]["body_text_included"] = True
    unsafe_path = cast(dict[str, Any], copy.deepcopy(_request()))
    unsafe_path["materials"][0]["subject"]["source_id"] = "/" + "private/source"
    extra_secret = cast(dict[str, Any], copy.deepcopy(_request()))
    extra_secret["api_key"] = "must-not-survive"

    for request, reason in (
        (unsafe, "OUTPUT_POLICY_VIOLATION"),
        (unsafe_path, "UNSAFE_CAPTURE_INPUT"),
        (extra_secret, "INVALID_CAPTURE_REQUEST"),
    ):
        output = tmp_path / reason
        with pytest.raises(_capture_error(mod, reason)) as caught:
            mod.capture_pdfplumber_artifacts(request, _pdf_bytes(), output)
        assert caught.value.reason_code == reason
        assert not output.exists()
    assert calls == []


def test_061_invalid_wire_error_drops_sensitive_exception_chain_and_frames(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_admitting_adapter(mod, monkeypatch)
    request = cast(dict[str, Any], copy.deepcopy(_request()))
    sensitive = (
        "must-not-survive-secret-061",
        "must-not-survive-body-061",
        "/" + "private/must-not-survive-path-061",
    )
    request["untrusted"] = {
        "api_key": sensitive[0],
        "body": sensitive[1],
        "path": sensitive[2],
    }
    output = tmp_path / "capture"

    with pytest.raises(_capture_error(mod, "INVALID_CAPTURE_REQUEST")) as caught:
        mod.capture_pdfplumber_artifacts(request, _pdf_bytes(), output)

    error = caught.value
    assert error.reason_code == "INVALID_CAPTURE_REQUEST"
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = "".join(traceback.format_exception(error))
    production_locals: list[str] = []
    current = error.__traceback__
    while current is not None:
        if Path(current.tb_frame.f_code.co_filename) == SCRIPT:
            production_locals.append(repr(current.tb_frame.f_locals))
        current = current.tb_next
    observed = "\n".join((str(error), repr(error), rendered, *production_locals))
    assert all(value not in observed for value in sensitive)
    assert calls == [] and not output.exists()


def test_061_semantic_wire_error_clears_parsed_request_from_public_traceback(
    mod: ModuleType,
    tmp_path: Path,
) -> None:
    request = cast(dict[str, Any], copy.deepcopy(_request()))
    sensitive = (
        "semantic-secret-must-not-survive-061",
        "semantic-body-must-not-survive-061",
        "/" + "private/semantic-path-must-not-survive-061",
    )
    request["contract"] = "|".join(sensitive)
    pdf_bytes = _pdf_bytes()
    output = tmp_path / "semantic-sensitive-output"

    with pytest.raises(_capture_error(mod, "INVALID_CAPTURE_REQUEST")) as caught:
        mod.capture_pdfplumber_artifacts(request, pdf_bytes, output)

    error = caught.value
    assert error.reason_code == "INVALID_CAPTURE_REQUEST"
    assert error.__cause__ is None and error.__context__ is None
    assert all(
        not _production_exception_graph_reaches(error, value) for value in sensitive
    )
    assert not _production_exception_graph_reaches(error, str(output.resolve()))
    assert all(
        not _production_exception_graph_reaches(error, payload)
        for payload in pdf_bytes.values()
    )
    assert not output.exists()


@pytest.mark.parametrize("failure_kind", ("value_error", "validation_error"))
def test_061_native_failure_clears_exception_and_pdf_bytes_from_public_traceback(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    sensitive = (
        "native-secret-must-not-survive-061",
        "native-body-must-not-survive-061",
        "/" + "private/native-path-must-not-survive-061",
    )
    pdf_bytes = _pdf_bytes()
    output = tmp_path / f"native-sensitive-output-{failure_kind}"

    if failure_kind == "value_error":

        def fail_extract(*args: object, **kwargs: object) -> object:
            raise ValueError("|".join(sensitive))

        monkeypatch.setattr(
            mod.native_pdfplumber,
            "extract_native_pdfplumber_facts",
            fail_extract,
        )
    else:
        _install_admitting_adapter(mod, monkeypatch)

        def fail_bridge(*args: object, **kwargs: object) -> object:
            mod.CaptureRequestV1.model_validate(
                {"untrusted": {"secret": sensitive[0], "body": sensitive[1], "path": sensitive[2]}}
            )
            raise AssertionError("unreachable")

        monkeypatch.setattr(
            mod.native_pdfplumber,
            "build_parsed_document_v1",
            fail_bridge,
        )

    with pytest.raises(_capture_error(mod, "BASELINE_PARSE_QUALITY_BLOCKED")) as caught:
        mod.capture_pdfplumber_artifacts(_request(), pdf_bytes, output)

    error = caught.value
    assert error.reason_code == "BASELINE_PARSE_QUALITY_BLOCKED"
    assert error.diagnostic.reason_codes == ("native_pdfplumber_contract_invalid",)
    assert error.__cause__ is None and error.__context__ is None
    assert all(
        not _production_exception_graph_reaches(error, value) for value in sensitive
    )
    assert not _production_exception_graph_reaches(error, str(output.resolve()))
    assert all(
        not _production_exception_graph_reaches(error, payload)
        for payload in pdf_bytes.values()
    )
    assert not output.exists()


def test_061_nondeterministic_parser_fails_with_zero_output(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_admitting_adapter(
        mod,
        monkeypatch,
        salt_for_call=lambda call: "first" if call <= 3 else "second",
    )
    output = tmp_path / "capture"
    with pytest.raises(_capture_error(mod, "NONDETERMINISTIC_BASELINE_PARSE")) as caught:
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), output)
    assert caught.value.reason_code == "NONDETERMINISTIC_BASELINE_PARSE"
    assert not output.exists()


def test_061_quality_block_returns_immutable_diagnostic_without_output(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_admitting_adapter(mod, monkeypatch)
    original = mod.native_pdfplumber.build_parsed_document_v1

    def blocked(*args: object, **kwargs: object) -> tuple[object, object, object]:
        document, manifest, decision = original(*args, **kwargs)
        resolution = cast(MaterialProfileResolution, kwargs["material_profile_resolution"])
        return (
            document,
            manifest,
            decision.model_copy(
                update={
                    "decision": "ESCALATE",
                    "reason_codes": ("locator_invalid_or_required_structure_missing",),
                    "admitted_attempt_id": None,
                    "next_parser_profile_ref": (
                        resolution.parse_policy_receipt.bounded_upgrade_profile_ref
                    ),
                    "review_item": None,
                }
            ),
        )

    monkeypatch.setattr(mod.native_pdfplumber, "build_parsed_document_v1", blocked)
    output = tmp_path / "capture"
    with pytest.raises(_capture_error(mod, "BASELINE_PARSE_QUALITY_BLOCKED")) as caught:
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), output)
    assert caught.value.reason_code == "BASELINE_PARSE_QUALITY_BLOCKED"
    assert caught.value.diagnostic.material_role in ROLES
    assert len(caught.value.diagnostic.diagnostic_sha256) == 64
    assert not output.exists()


def test_061_atomic_no_replace_preserves_existing_and_raced_target(
    mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_admitting_adapter(mod, monkeypatch)
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "sentinel"
    sentinel.write_bytes(b"keep")
    with pytest.raises(_capture_error(mod, "OUTPUT_ALREADY_EXISTS")):
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), existing)
    assert sentinel.read_bytes() == b"keep" and list(existing.iterdir()) == [sentinel]

    raced = tmp_path / "raced"
    original = mod._publish_no_replace

    def race(source: Path, target: Path) -> None:
        target.mkdir(mode=0o700)
        (target / "foreign").write_bytes(b"foreign")
        original(source, target)

    monkeypatch.setattr(mod, "_publish_no_replace", race)
    with pytest.raises(_capture_error(mod, "OUTPUT_ALREADY_EXISTS")):
        mod.capture_pdfplumber_artifacts(_request(), _pdf_bytes(), raced)
    assert (raced / "foreign").read_bytes() == b"foreign"
    assert list(raced.iterdir()) == [raced / "foreign"]


def test_061_source_has_no_external_runtime_imports() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"httpx", "requests", "socket", "urllib", "goldenset", "openai"})

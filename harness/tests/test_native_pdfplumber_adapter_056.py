"""OpenSpec 056: native pdfplumber facts and formal OpenSpec 053 bridge."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

import pdfplumber
import pytest

from insurance_harness.compiler import native_pdfplumber as native
from insurance_harness.compiler.material_profiles import (
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    load_material_profile_catalog_data,
    resolve_material_profile,
)
from insurance_harness.compiler.parsed_documents import (
    ParseAttemptV1,
    ParseOutputFactsV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
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

FIXTURE = Path(__file__).parent / "fixtures/native_pdfplumber_page_056.json"
MATERIAL_PROFILE_FIXTURE = (
    Path(__file__).parent / "fixtures/material_profile_596_1_052.json"
)
CONFIG_HASH = "a" * 64
DEFAULT_PARSER = "approved-parser-profile:parser-neutral-default.v1"
UPGRADE_PARSER = "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
PRIVACY_POLICY = "privacy-policy:source-revision-private-processing.v1"
OUTPUT_POLICY = "output-policy:parsed-artifact-internal-only.v1"


class _OneEntryTemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self._entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self._entry if scope == self._entry.version.scope else None


class _FakeTable:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.bbox = tuple(payload["bbox"])
        self.rows = [
            type("Row", (), {"cells": tuple(row)})() for row in payload["rows"]
        ]
        self._values = cast(list[list[str]], payload["values"])

    def extract(self) -> list[list[str]]:
        return self._values


class _FakePage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.width = payload["width"]
        self.height = payload["height"]
        self.bbox = tuple(payload.get("bbox", (0, 0, self.width, self.height)))
        self._words = cast(list[dict[str, Any]], payload["words"])
        self._tables = [_FakeTable(table) for table in payload["tables"]]

    def extract_words(self) -> list[dict[str, Any]]:
        return self._words

    def find_tables(self) -> list[_FakeTable]:
        return self._tables


class _FakePdf:
    def __init__(self, page: _FakePage) -> None:
        self.pages = [page]

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE.read_text(encoding="utf-8")))


def _extract(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_bytes: bytes | None = None,
) -> native.NativePdfplumberFacts:
    payload = _fixture()
    exact_source_bytes = source_bytes or payload["source_bytes"].encode()
    opened: list[bytes] = []

    def _open(stream: BytesIO) -> _FakePdf:
        opened.append(stream.getvalue())
        return _FakePdf(_FakePage(payload["page"]))

    monkeypatch.setattr(pdfplumber, "open", _open)
    facts = native.extract_native_pdfplumber_facts(
        exact_source_bytes,
        expected_source_sha256=hashlib.sha256(exact_source_bytes).hexdigest(),
        parser_build_id="pdfplumber-test-build-v1",
        parser_config_hash=CONFIG_HASH,
    )
    assert opened == [exact_source_bytes]
    return facts


def _bridge_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_upgrade: bool,
    capabilities: tuple[str, ...] = (
        "ordered_pages",
        "block_locators",
        "table_grid",
    ),
) -> tuple[
    native.NativePdfplumberFacts,
    ParseSubjectV1,
    ParserIdentityV1,
    ParseAttemptV1,
    ParseSnapshotV1,
    ParseOutputFactsV1,
    MaterialProfileResolution,
]:
    raw = json.loads(MATERIAL_PROFILE_FIXTURE.read_text(encoding="utf-8"))
    terms = raw["profiles"][0]
    terms["required_parse_capabilities"] = list(capabilities)
    if not with_upgrade:
        policy = terms["parse_policy"]
        policy["bounded_upgrade_profile_ref"] = None
        policy["upgrade_trigger_conditions"] = []
        policy["max_parser_attempts"] = 1
    catalog = load_material_profile_catalog_data(raw)
    profile = catalog.profiles[0]
    source_path = Path(__file__).parents[2] / profile.source.path
    facts = _extract(monkeypatch, source_bytes=source_path.read_bytes())
    scope = TemplateScope(space_id="space-056", level="global")
    content = TemplatePackageContent(
        schema_version=catalog.schema_binding.schema_version,
        field_groups=(
            FieldGroup(
                group_id="group-056",
                field_ids=(catalog.schema_binding.field_ids[0],),
                evidence_roles=("terms",),
            ),
        ),
        role_prompts={"extract": "extract-056"},
        validators=(
            ValidatorRef(
                validator_id="validator-056",
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
                migration_id="MIG-056-test",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="native pdfplumber facts bridge",
                rejected_behavior="word locators as block locators",
                python_target=(
                    "harness/src/insurance_harness/compiler/native_pdfplumber.py"
                ),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_native_pdfplumber_adapter_056.py",
                ),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id="056-test-v1",
        scope=scope,
        content=content,
    )
    template_catalog = _OneEntryTemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="approval-056",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )
    resolution = resolve_material_profile(
        catalog,
        template_catalog,
        MaterialProfileResolutionRequest(
            space_id="space-056",
            product_code=catalog.product.product_code,
            product_version=catalog.product.product_version,
            schema_version=catalog.schema_binding.schema_version,
            schema_field_ids=catalog.schema_binding.field_ids,
            source=profile.source,
            classified_material_role="terms",
        ),
    )
    return (
        facts,
        ParseSubjectV1(
            space_id="space-056",
            source_id="source-056",
            source_revision_id="source-revision-056",
            product_version_id=resolution.request.product_version,
            material_profile_id=resolution.profile.profile_id,
            material_profile_binding_hash=resolution.binding_hash,
            source_sha256=facts.source_sha256,
            raw_artifact_hash="c" * 64,
            canonical_envelope_hash="d" * 64,
        ),
        ParserIdentityV1(
            parser_id="pdfplumber",
            parser_profile_ref=DEFAULT_PARSER,
            parser_build_id=facts.parser_build_id,
            parser_config_hash=facts.parser_config_hash,
        ),
        ParseAttemptV1(
            attempt_id="parse-attempt-056",
            attempt_number=1,
            attempt_role="default",
            generation=1,
        ),
        ParseSnapshotV1(
            snapshot_id="snapshot-056",
            snapshot_generation=1,
            pagination_complete=True,
            concurrent_mutation_fence_hash="e" * 64,
        ),
        ParseOutputFactsV1(
            privacy_policy_ref=PRIVACY_POLICY,
            output_policy_ref=OUTPUT_POLICY,
            body_text_included=False,
            secrets_included=False,
            absolute_paths_included=False,
            unknown_vendor_fields_included=False,
        ),
        resolution,
    )


def test_056_native_facts_preserve_only_proven_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _extract(monkeypatch)

    assert facts.parser_engine == "pdfplumber"
    assert len(facts.pages) == 1
    assert [word.word_index for word in facts.pages[0].words] == [0, 1]
    assert [(cell.row_index, cell.column_index) for cell in facts.pages[0].tables[0].cells] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]
    assert [(cell.row_index, cell.column_index) for cell in facts.pages[0].tables[1].cells] == [
        (0, 0)
    ]
    assert "sensitive synthetic content" not in repr(facts)
    assert "must-not-survive" not in repr(facts)
    assert "/synthetic/absolute/path.pdf" not in repr(facts)
    assert facts.supported_capabilities == (
        "ordered_pages",
        "word_locators",
        "table_grid",
    )
    assert tuple(item.capability for item in facts.capability_evidence) == (
        "ordered_pages",
        "word_locators",
        "table_grid",
    )
    assert facts.unsupported_capabilities == (
        "block_locators",
        "cell_locators",
        "header_hierarchy",
        "merged_cells",
        "row_column_indices",
        "cross_page_sections",
        "cross_page_tables",
    )


def test_056_page_bbox_preserves_nonzero_native_crop_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture()
    payload["page"]["bbox"] = [10, 20, 110, 220]
    source_bytes = payload["source_bytes"].encode()

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: _FakePdf(_FakePage(payload["page"])),
    )
    facts = native.extract_native_pdfplumber_facts(
        source_bytes,
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        parser_build_id="pdfplumber-test-build-v1",
        parser_config_hash=CONFIG_HASH,
    )
    assert facts.pages[0].bbox == ("10", "20", "110", "220")


def test_056_words_do_not_claim_block_locator_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _extract(monkeypatch)
    assert facts.pages[0].words
    assert "block_locators" not in facts.supported_capabilities
    assert "block_locators" in facts.unsupported_capabilities
    assert all(
        evidence.capability != "block_locators"
        for evidence in facts.capability_evidence
    )


def test_056_source_digest_fails_before_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _open(_: BytesIO) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(pdfplumber, "open", _open)
    with pytest.raises(native.NativePdfplumberError, match="source_digest_mismatch"):
        native.extract_native_pdfplumber_facts(
            b"bytes",
            expected_source_sha256="0" * 64,
            parser_build_id="pdfplumber-test-build-v1",
            parser_config_hash=CONFIG_HASH,
        )
    assert calls == 0


def test_056_invalid_native_bbox_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _fixture()
    payload["page"]["words"][0]["x1"] = 10
    source_bytes = payload["source_bytes"].encode()

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: _FakePdf(_FakePage(payload["page"])),
    )
    with pytest.raises(native.NativePdfplumberError, match="invalid_native_bbox"):
        native.extract_native_pdfplumber_facts(
            source_bytes,
            expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            parser_build_id="pdfplumber-test-build-v1",
            parser_config_hash=CONFIG_HASH,
        )


def test_056_irregular_native_table_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture()
    payload["page"]["tables"][0]["values"][1].pop()
    source_bytes = payload["source_bytes"].encode()

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: _FakePdf(_FakePage(payload["page"])),
    )
    with pytest.raises(native.NativePdfplumberError, match="native_table_shape_mismatch"):
        native.extract_native_pdfplumber_facts(
            source_bytes,
            expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            parser_build_id="pdfplumber-test-build-v1",
            parser_config_hash=CONFIG_HASH,
        )


def test_056_missing_words_are_explicitly_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture()
    payload["page"]["words"] = []
    source_bytes = payload["source_bytes"].encode()

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _: _FakePdf(_FakePage(payload["page"])),
    )
    facts = native.extract_native_pdfplumber_facts(
        source_bytes,
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        parser_build_id="pdfplumber-test-build-v1",
        parser_config_hash=CONFIG_HASH,
    )
    assert "word_locators" not in facts.supported_capabilities
    assert "block_locators" not in facts.supported_capabilities
    assert "word_locators" in facts.unsupported_capabilities
    assert "block_locators" in facts.unsupported_capabilities


@pytest.mark.parametrize(
    ("with_upgrade", "expected_decision"),
    ((True, "ESCALATE"), (False, "BLOCK")),
)
def test_056_bridge_delegates_missing_block_capability_to_053_quality_gate(
    monkeypatch: pytest.MonkeyPatch,
    with_upgrade: bool,
    expected_decision: str,
) -> None:
    (
        facts,
        subject,
        parser,
        attempt,
        snapshot,
        output,
        resolution,
    ) = _bridge_context(
        monkeypatch,
        with_upgrade=with_upgrade,
        capabilities=("block_locators",),
    )

    document, manifest, decision = native.build_parsed_document_v1(
        facts,
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert document.contract == "parsed-document.v1"
    assert document.blocks == ()
    assert "block_locators" in manifest.unsatisfied_capabilities
    assert decision.decision == expected_decision
    assert decision.reason_codes == ("locator_invalid_or_required_structure_missing",)
    assert (decision.review_item is not None) is (expected_decision == "BLOCK")


@pytest.mark.parametrize(
    ("with_upgrade", "expected_decision"),
    ((True, "ESCALATE"), (False, "BLOCK")),
)
def test_056_bridge_does_not_invent_cells_or_spans_for_ambiguous_native_table(
    monkeypatch: pytest.MonkeyPatch,
    with_upgrade: bool,
    expected_decision: str,
) -> None:
    (
        facts,
        subject,
        parser,
        attempt,
        snapshot,
        output,
        resolution,
    ) = _bridge_context(
        monkeypatch,
        with_upgrade=with_upgrade,
        capabilities=("table_grid",),
    )

    document, manifest, decision = native.build_parsed_document_v1(
        facts,
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    complete_table_id = facts.pages[0].tables[0].table_id
    ambiguous_table_id = facts.pages[0].tables[1].table_id
    complete_cells = tuple(
        cell for cell in document.cells if cell.table_id == complete_table_id
    )

    assert complete_cells
    assert all(
        cell.locator.row_span == 1 and cell.locator.column_span == 1
        for cell in complete_cells
    )
    assert not any(cell.table_id == ambiguous_table_id for cell in document.cells)
    assert "table_grid" in manifest.unsatisfied_capabilities
    assert decision.decision == expected_decision
    assert decision.reason_codes == ("table_grid_or_span_incomplete",)
    assert (decision.review_item is not None) is (expected_decision == "BLOCK")


def test_056_bridge_rejects_caller_subject_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        facts,
        subject,
        parser,
        attempt,
        snapshot,
        output,
        resolution,
    ) = _bridge_context(monkeypatch, with_upgrade=True)
    drifted = subject.model_copy(update={"source_sha256": "f" * 64})

    with pytest.raises(native.NativePdfplumberError, match="bridge_identity_mismatch"):
        native.build_parsed_document_v1(
            facts,
            subject=drifted,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output,
            material_profile_resolution=resolution,
        )

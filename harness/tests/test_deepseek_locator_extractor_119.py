"""Mission 119: code-owned locator selection plus DeepSeek extraction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from inspect import getsource, signature
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import SecretStr

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import evidence_verifier as evidence_verifier_module
from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
    RepairResolutionV1,
)
from insurance_harness.compiler.extraction_receipts import build_initial_attempt
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionInputRefsV1,
    MaterialRole,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.llm import openai_compat_request_bytes
from insurance_harness.compiler.material_profiles import (
    MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
    ApprovedParsePolicy,
    FieldAuthority,
    MaterialProfile,
    MaterialProfileResolution,
    ParsePolicyReceipt,
    SourceDocumentIdentity,
)
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParsedDocumentV1,
    ParseElementCountsV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
)
from insurance_harness.knowledge_compiler import deepseek_locator_extractor_596_1 as deepseek
from insurance_harness.knowledge_compiler import semantic_input_binding as semantic
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    DEEPSEEK_EXECUTION_IDENTITY_SHA256,
    DEEPSEEK_MODEL_IDENTITY,
    SCHEMA67_APPROVED_BY,
    SCHEMA67_WORKBOOK_SHA256,
    CanonicalLocatorInputV1,
    DeepSeekCompilerError,
    DeepSeekFieldPromptInputV1,
    DeepSeekRepairRequestV1,
    Schema67BatchBudgetV1,
    Schema67CapturedContentV1,
    Schema67ExecutionPlanV1,
    Schema67PreparedTaskV1,
    Schema67RoleTaskInputV1,
    _run_deepseek_task,
    _run_schema67_deepseek_batch,
    _schema67_binding_ports,
    _Schema67EvidenceBindingPort,
    _select_deepseek_execution_identity,
    build_schema67_batch_receipt,
    build_schema67_execution_plan,
    compile_schema67_deepseek_task,
    prepare_schema67_deepseek_tasks,
    prepare_schema67_real_execution_inputs,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    RelationBoundAdmissionResultV1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_BY,
    APPROVED_ORDERED_FIELD_IDS_SHA256,
    APPROVED_PRODUCT_VERSION_ID,
    APPROVED_REVIEW_PACKAGE_ID,
    APPROVED_SCHEMA_ID,
    APPROVED_WORKBOOK_SHA256,
    EXACT_APPROVAL_AUTHORITY_REF,
    ApprovedSchemaSnapshotV1,
    FieldContractSetV1,
    approved_schema_rows,
    approved_schema_snapshot_sha256,
    compile_schema_contracts,
    schema_rows_sha256,
)
from insurance_harness.knowledge_compiler.semantic_input_binding import (
    SemanticExecutionIdentityV1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
    VerticalFalsificationAdmission,
)
from insurance_harness.live_env.config import ModelProfile
from insurance_harness.model_policy import ProductionModelPolicy


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _mineru_hash(domain: str, value: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"mineru-060:{domain}".encode())
    digest.update(b"\0")
    digest.update(value.encode())
    return digest.hexdigest()


def _bound(task_id: str = "task-119") -> semantic.BoundSemanticAttemptV1:
    payload = semantic._bound_attempt_payload(
        task_id=task_id,
        composition_hash="1" * 64,
        model_id="deepseek-v4-flash",
        model_identity_sha256=DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        arm_blueprint_hash="3" * 64,
        normalizer_identity_sha256="4" * 64,
        receipt_chain=None,
        evidence_receipts=(),
        verification=None,
    )
    return semantic.BoundSemanticAttemptV1(
        task_id=task_id,
        composition_hash="1" * 64,
        model_id="deepseek-v4-flash",
        model_identity_sha256=DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        arm_blueprint_hash="3" * 64,
        normalizer_identity_sha256="4" * 64,
        receipt_chain=None,
        evidence_receipts=(),
        verification=None,
        bound_attempt_hash=canonical_hash(semantic.BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE, payload),
    )


def _profile() -> ModelProfile:
    return ModelProfile(
        base_url="https://api.deepseek.com/v1",
        api_key=SecretStr("test-secret-never-serialize"),
        model="deepseek-v4-flash",
        provider="deepseek",
        protocol="openai_compatible",
    )


def _policy() -> ProductionModelPolicy:
    return ProductionModelPolicy({DEEPSEEK_MODEL_IDENTITY.identity_key})


def _extractor_response(*, attempt_hash: str = "5" * 64) -> str:
    del attempt_hash
    return _unknown_fields_response(("product_code",))


def _unknown_fields_response(field_ids: tuple[str, ...]) -> str:
    return json.dumps(
        {
            "fields": [
                {
                    "field_id": field_id,
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": [],
                }
                for field_id in field_ids
            ],
        },
        separators=(",", ":"),
    )


def _shape_invalid_response(
    field_ids: tuple[str, ...],
    *,
    sentinel: str = "RAW_RESPONSE_MUST_NOT_REAPPEAR",
) -> str:
    return json.dumps(
        {
            "fields": [
                {
                    "field_id": field_id,
                    "state": "unknown",
                    "diagnostic_sentinel": sentinel,
                }
                for field_id in field_ids
            ],
        },
        separators=(",", ":"),
    )


class _FakeTransport:
    def __init__(self, outputs: Sequence[str | Exception]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class _UnknownExtractorTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        selected_field_ids = set(payload.get("field_ids", ()))
        field_ids = [
            item["field_id"]
            for item in payload["field_contracts"]
            if not selected_field_ids or item["field_id"] in selected_field_ids
        ]
        return json.dumps(
            {
                "fields": [
                    {
                        "field_id": field_id,
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                    for field_id in field_ids
                ],
            },
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class _FakePort:
    task_id: str = "task-119"
    attempt_hash: str = "5" * 64
    field_ids: tuple[str, ...] = ("product_code",)
    arm_blueprint_hash: str = "3" * 64
    model_identity_sha256: str = DEEPSEEK_EXECUTION_IDENTITY_SHA256
    normalizer_identity_sha256: str = "4" * 64
    repair: bool = False
    expected_locator_refs: tuple[str, ...] = ("block-1",)

    def validate_locators(self, locators: tuple[CanonicalLocatorInputV1, ...]) -> None:
        assert tuple(item.locator_ref for item in locators) == self.expected_locator_refs

    def hydrate_extractor_outputs(
        self,
        *,
        selections: tuple[deepseek._ExtractorFieldSelectionV1, ...],
        contracts: tuple[DeepSeekFieldPromptInputV1, ...],
        locators: tuple[CanonicalLocatorInputV1, ...],
    ) -> tuple[FreeformFieldOutputV1, ...]:
        locator_by_ref = {item.locator_ref: item for item in locators}
        outputs: list[FreeformFieldOutputV1] = []
        for selection, contract in zip(selections, contracts, strict=True):
            evidence = tuple(
                FreeformEvidenceV1(
                    field_id=selection.field_id,
                    source_sha256="9" * 64,
                    source_revision_id="source-revision-119",
                    parse_attempt_id="parse-attempt-119",
                    parsed_document_hash="a" * 64,
                    parse_manifest_hash="b" * 64,
                    page_number=locator_by_ref[item.locator_ref].page_number,
                    block_id=item.locator_ref,
                    locator=evidence_verifier_module.EvidenceLocatorSnapshotV1(
                        subject_type="block",
                        subject_ref=item.locator_ref,
                        page_number=locator_by_ref[item.locator_ref].page_number,
                        parent_refs=locator_by_ref[item.locator_ref].parent_refs,
                        content_snapshot=locator_by_ref[item.locator_ref].content_snapshot,
                        content_snapshot_sha256=locator_by_ref[
                            item.locator_ref
                        ].content_snapshot_sha256,
                    ),
                    quote_snapshot=item.quote_snapshot,
                    quote_snapshot_sha256=_sha(item.quote_snapshot),
                )
                for item in selection.evidence
            )
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=contract.field_id,
                    state=selection.state,
                    value_snapshot=selection.value_snapshot,
                    evidence=evidence,
                )
            )
        return tuple(outputs)

    def bind_initial(self, response_json: bytes) -> semantic.BoundSemanticAttemptV1:
        assert json.loads(response_json)["attempt_hash"] == self.attempt_hash
        return _bound(self.task_id)

    def prepare_repair(
        self,
        initial: semantic.BoundSemanticAttemptV1 | deepseek.Schema67BoundAttemptV1,
        locator_refs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> DeepSeekRepairRequestV1 | None:
        assert initial.task_id == self.task_id
        if not self.repair:
            return None
        field_id = self.field_ids[0]
        approved = dict(locator_refs).get(field_id, ())
        repair_plan = evidence_verifier_module.TargetedRepairPlanV1(
            contract="targeted-repair-plan.v1",
            parent_verification_hash="7" * 64,
            repair_number=1,
            field_ids=(field_id,),
            approved_locators=(
                evidence_verifier_module.ApprovedLocatorSetV1(
                    field_id=field_id,
                    locator_refs=approved,
                ),
            ),
        )
        return DeepSeekRepairRequestV1(
            attempt_hash="6" * 64,
            repair_plan_hash=repair_plan.plan_hash,
            parent_bound_attempt_hash=initial.bound_attempt_hash,
            field_ids=(field_id,),
            approved_locators=((field_id, approved),),
        )

    def bind_repair(
        self,
        response_json: bytes,
        request: DeepSeekRepairRequestV1,
    ) -> RepairResolutionV1:
        assert json.loads(response_json)["attempt_hash"] == request.attempt_hash
        return RepairResolutionV1(
            contract="targeted-repair-resolution.v1",
            parent_verification_hash="7" * 64,
            repair_plan_hash=request.repair_plan_hash,
            results=(
                evidence_verifier_module.FieldVerificationV1(
                    field_id=request.field_ids[0],
                    status="PASS",
                    reason_codes=(),
                    candidate_snapshot_hash="8" * 64,
                ),
            ),
            gaps=(),
            review_items=(),
        )


def _inputs() -> tuple[tuple[DeepSeekFieldPromptInputV1, ...], tuple[CanonicalLocatorInputV1, ...]]:
    contract = _schema67_contract_set().contracts[0]
    prompt_payload = {
        "field_id": contract.field_id,
        "description": contract.description,
        "value_shape": contract.value_shape,
        "formation_modes": contract.formation_modes,
        "source_roles": contract.source_roles,
        "evidence_required": contract.evidence_required,
        "output_state_policy": contract.output_state_policy,
        "hardness": contract.hardness.model_dump(mode="python"),
        "field_contract_sha256": contract.field_contract_sha256,
    }
    prompt = DeepSeekFieldPromptInputV1(
        contract=contract,
        prompt_payload_sha256=canonical_hash("schema67-deepseek-field-prompt.v1", prompt_payload),
        allowed_locator_refs=("block-1",),
        source_locator_refs=(("terms", ("block-1",)),),
    )
    locator = CanonicalLocatorInputV1(
        locator_ref="block-1",
        locator_kind="block",
        page_number=1,
        parent_refs=("page-1",),
        content_snapshot="保险责任以条款约定为准。",
        content_snapshot_sha256=_sha("保险责任以条款约定为准。"),
    )
    return (prompt,), (locator,)


def _slot_authority(
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
    *,
    port: deepseek.Schema67EvidenceBindingPort | None = None,
) -> deepseek._LocatorSlotAuthorityV1:
    return deepseek._build_locator_slot_authority(
        port=_FakePort() if port is None else port,
        contracts=contracts,
        locators=locators,
    )


def _absent_extractor_response(quote: str, *, attempt_hash: str = "5" * 64) -> str:
    del attempt_hash
    evidence = {
        "source_role": "terms",
        "locator_slot": "slot-0001",
        "quote_snapshot": quote,
    }
    payload = json.loads(_extractor_response())
    payload["fields"] = [
        {
            "field_id": "product_code",
            "state": "absent_explicitly",
            "value_snapshot": "模型原始不适用陈述",
            "evidence": [evidence],
        }
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.asyncio
async def test_119_exact_authority_and_locator_extractor_happy_path() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport([_extractor_response()])

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )

    assert result.initial.bound_attempt_hash == _bound().bound_attempt_hash
    assert result.response_contract_repair is None
    assert result.evidence_repair is None
    assert result.receipt.total_calls == 1
    assert result.receipt.locator_calls == 0
    assert result.receipt.extractor_calls == 1
    assert result.receipt.transport_retries == 0
    assert result.receipt.response_contract_repairs == 0
    assert result.receipt.evidence_repairs == 0
    assert result.receipt.execution_identity_sha256 == DEEPSEEK_EXECUTION_IDENTITY_SHA256
    assert len(transport.calls) == 1
    extractor_system, extractor_user = transport.calls[0]
    assert "extractor" in extractor_system.casefold()
    assert "deepseek locator" not in extractor_system.casefold()
    extractor_payload = json.loads(extractor_user)
    assert extractor_payload["response_contract"]["output_contract"] == (
        "schema67-semantic-field-selection.v2"
    )
    assert extractor_payload["response_contract"]["fields"]["field_order"] == ["product_code"]
    assert extractor_payload["response_contract"]["response_skeleton"] == {
        "fields": [
            {
                "field_id": "product_code",
                "state": "unknown",
                "value_snapshot": None,
                "evidence": [],
            }
        ]
    }
    assert extractor_payload["locator_slot_catalog"] == [
        {
            "slot": "slot-0001",
            "locator_kind": "block",
            "page_number": 1,
            "content_snapshot": locators[0].content_snapshot,
            "content_snapshot_sha256": locators[0].content_snapshot_sha256,
        }
    ]
    assert extractor_payload["field_locator_slots"] == [
        {
            "field_id": "product_code",
            "sources": [
                {"source_role": "terms", "allowed_slots": ["slot-0001"]}
            ],
        }
    ]
    assert "locator_ref" not in extractor_payload
    assert result.receipt.locator_selection_policy_sha256 == canonical_hash(
        "schema67-deterministic-locator-selection-policy.v1",
        {
            "source": "field-contract-plus-mineru-locators",
            "contract_terms": ("field_name", "description", "category"),
            "algorithm_version": "schema67-contract-lexical-locator-v2",
            "normalization": "str.casefold",
            "unicode_sequence_regex": r"[\u3400-\u9fff]+",
            "whole_sequence_min_chars": 2,
            "whole_sequence_max_chars": 12,
            "ngram_widths": (2, 3, 4),
            "ascii_token_regex": r"[a-z0-9_]{3,}",
            "stoplist": (
                "产品",
                "信息",
                "内容",
                "相关",
                "情况",
                "是否",
                "说明",
                "要求",
                "规则",
                "保险",
            ),
            "score": ("term_length_squared", "field_name_exact_bonus:100"),
            "tie_break": ("score_desc", "input_ordinal_asc"),
            "input_order": "mineru_canonical_ordinal",
            "output_order": "locator_ref_lexicographic",
            "all_locators_threshold": 24,
            "ranked_match_limit": 8,
            "neighbor_offsets": (-1, 0, 1),
            "fallback_max_content_chars": 40,
            "fallback_max_locators": 24,
            "golden_reads": 0,
            "model_calls": 0,
        },
    )
    assert result.receipt.locator_authority_sha256 == canonical_hash(
        "schema67-deterministic-locator-authority.v1",
        {
            "task_id": "task-119",
            "attempt_hash": "5" * 64,
            "field_contracts": (
                {
                    "field_id": "product_code",
                    "field_contract_sha256": contracts[0].contract.field_contract_sha256,
                    "prompt_payload_sha256": contracts[0].prompt_payload_sha256,
                    "source_locator_refs": (("terms", ("block-1",)),),
                    "requires_unknown_review": False,
                },
            ),
            "canonical_locators": (
                {
                    "ordinal": 0,
                    "locator_ref": "block-1",
                    "locator_kind": "block",
                    "page_number": 1,
                    "parent_refs": ("page-1",),
                    "content_snapshot_sha256": locators[0].content_snapshot_sha256,
                },
            ),
        },
    )
    assert result.receipt.locator_selection_sha256 == canonical_hash(
        "schema67-deterministic-locator-selection.v1",
        {
            "policy_sha256": result.receipt.locator_selection_policy_sha256,
            "authority_sha256": result.receipt.locator_authority_sha256,
            "selection": (("product_code", ("block-1",)),),
        },
    )
    assert (
        result.receipt.extractor_request_sha256
        == hashlib.sha256(
            openai_compat_request_bytes(
                model=deepseek.DEEPSEEK_MODEL,
                temperature=deepseek.DEEPSEEK_TEMPERATURE,
                max_tokens=deepseek.DEEPSEEK_MAX_TOKENS,
                system=extractor_system,
                user=extractor_user,
                thinking=deepseek.DEEPSEEK_THINKING,
                response_format=deepseek.DEEPSEEK_RESPONSE_FORMAT,
            )
        ).hexdigest()
    )
    assert "保险责任" not in repr(result)
    assert "test-secret-never-serialize" not in repr(result)


@pytest.mark.asyncio
async def test_119_extractor_response_contract_is_isomorphic_to_validator() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport([_unknown_fields_response(("product_code",))])

    await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )

    system, user = transport.calls[0]
    response_contract = json.loads(user)["response_contract"]
    assert response_contract["output_contract"] == ("schema67-semantic-field-selection.v2")
    assert response_contract["top_level"] == {
        "required_keys": ["fields"],
        "additional_properties": False,
    }
    assert response_contract["fields"]["exact_count"] == 1
    assert response_contract["fields"]["field_order"] == ["product_code"]
    assert response_contract["fields"]["items"] == {
        "required_keys": ["field_id", "state", "value_snapshot", "evidence"],
        "additional_properties": False,
        "field_id": {
            "type": "nonblank_string",
            "min_length": 1,
            "max_length": 512,
            "single_line": True,
            "allow_crlf": False,
            "allow_leading_or_trailing_whitespace": False,
        },
        "state_enum": ["present", "absent_explicitly", "unknown"],
        "state_rules": {
            "unknown": {"value_snapshot": None, "evidence": []},
            "present_or_absent_explicitly": {
                "value_snapshot": {
                    "type": "nonblank_string",
                    "min_length": 1,
                    "max_length": 512,
                    "single_line": True,
                    "allow_crlf": False,
                    "allow_leading_or_trailing_whitespace": False,
                },
                "evidence": "nonempty_unique_array",
            },
        },
    }
    assert response_contract["evidence"] == {
        "required_keys": ["source_role", "locator_slot", "quote_snapshot"],
        "additional_properties": False,
        "source_role": {
            "constraint": "exact_member_of_field_source_roles",
            "type": "nonblank_string",
            "min_length": 1,
            "max_length": 512,
            "single_line": True,
            "allow_crlf": False,
            "allow_leading_or_trailing_whitespace": False,
        },
        "locator_slot": {
            "constraint": "exact_member_of_field_role_allowed_slots",
            "type": "nonblank_string",
            "min_length": 1,
            "max_length": 512,
            "single_line": True,
            "allow_crlf": False,
            "allow_leading_or_trailing_whitespace": False,
        },
        "quote_snapshot": {
            "constraint": ("nonblank_literal_substring_after_exact_057_normalization"),
            "type": "nonblank_string",
            "min_length": 1,
            "max_length": 512,
            "single_line": True,
            "allow_crlf": False,
            "allow_leading_or_trailing_whitespace": False,
        },
        "uniqueness": "unique_source_role_locator_slot_quote_snapshot_triples",
    }
    assert response_contract["present_value_057_support"] == {
        "state": "present",
        "normalization": "existing_057_nfkc_whitespace_punctuation_case",
        "value_quote_relation": (
            "value_snapshot_normalized_equals_at_least_one_complete_quote_snapshot"
        ),
        "required_source_roles": "all_contract_required_roles",
        "locator_authority": "same_field_field_locator_slots_only",
        "quote_authority": "literal_replay_not_semantic_paraphrase",
    }
    assert "field_source_locator_refs" not in response_contract
    assert response_contract["forced_unknown_field_ids"] == []
    assert response_contract["response_skeleton"] == {
        "fields": [
            {
                "field_id": "product_code",
                "state": "unknown",
                "value_snapshot": None,
                "evidence": [],
            }
        ]
    }
    assert "only the JSON object" in system
    assert "null" in system
    assert "literal substring" in system
    assert "present value_snapshot" in system
    assert "at least one quote_snapshot" in system
    assert "exactly equal after the same 057 normalization" in system
    assert evidence_verifier_module._quote_occurs("保险 责任。", "保险责任.")
    assert not evidence_verifier_module._quote_occurs("保险免责", "保险责任.")


@pytest.mark.asyncio
async def test_119_extractor_string_limits_are_visible_and_exact() -> None:
    contracts, locators = _inputs()
    boundary = "甲" * 512

    def extractor_payload(*, field_name: str, value: str) -> object:
        return {
            "fields": [
                {
                    "field_id": value if field_name == "field_id" else "product_code",
                    "state": "present",
                    "value_snapshot": value if field_name == "value_snapshot" else boundary,
                    "evidence": [
                        {
                            "source_role": value if field_name == "source_role" else "terms",
                            "locator_slot": (
                                value if field_name == "locator_slot" else "slot-0001"
                            ),
                            "quote_snapshot": (
                                value if field_name == "quote_snapshot" else boundary
                            ),
                        }
                    ],
                }
            ]
        }

    accepted = deepseek._require_extractor_envelope(
        extractor_payload(field_name="value_snapshot", value=boundary),
        contracts=contracts,
        slot_authority=_slot_authority(contracts, locators),
    )
    assert len(accepted[0].value_snapshot or "") == 512
    assert len(accepted[0].evidence[0].quote_snapshot) == 512

    invalid_strings = ("", " 甲", "甲 ", "甲\r乙", "甲\n乙", "甲" * 513)
    for field_name in (
        "field_id",
        "value_snapshot",
        "source_role",
        "locator_slot",
        "quote_snapshot",
    ):
        for invalid in invalid_strings:
            with pytest.raises(DeepSeekCompilerError) as caught:
                deepseek._require_extractor_envelope(
                    extractor_payload(field_name=field_name, value=invalid),
                    contracts=contracts,
                    slot_authority=_slot_authority(contracts, locators),
                )
            assert caught.value.reason_code == "EXTRACTOR_STRING_CONSTRAINT_INVALID"

    transport = _FakeTransport([_unknown_fields_response(("product_code",))])
    await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )
    system, user = transport.calls[0]
    response_contract = json.loads(user)["response_contract"]
    field_items = response_contract["fields"]["items"]
    visible_string_constraint = {
        "type": "nonblank_string",
        "min_length": 1,
        "max_length": 512,
        "single_line": True,
        "allow_crlf": False,
        "allow_leading_or_trailing_whitespace": False,
    }
    assert field_items["field_id"] == visible_string_constraint
    assert (
        field_items["state_rules"]["present_or_absent_explicitly"]["value_snapshot"]
        == visible_string_constraint
    )
    assert response_contract["evidence"]["source_role"] == {
        "constraint": "exact_member_of_field_source_roles",
        **visible_string_constraint,
    }
    assert response_contract["evidence"]["locator_slot"] == {
        "constraint": "exact_member_of_field_role_allowed_slots",
        **visible_string_constraint,
    }
    assert response_contract["evidence"]["quote_snapshot"] == {
        "constraint": ("nonblank_literal_substring_after_exact_057_normalization"),
        **visible_string_constraint,
    }
    assert "between 1 and 512 characters" in system
    assert "single line" in system
    assert "must not contain CR or LF" in system
    assert "must not have leading or trailing whitespace" in system


@pytest.mark.asyncio
async def test_119_prompt_discloses_required_unknown_null_and_empty_evidence() -> None:
    contracts, locators = _inputs()
    invalid_response = json.dumps(
        {
            "fields": [
                {
                    "field_id": "product_code",
                    "state": "unknown",
                }
            ]
        },
        separators=(",", ":"),
    )
    transport = _FakeTransport([invalid_response, invalid_response])

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )

    assert caught.value.reason_code == "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID"
    assert len(transport.calls) == 2
    response_contract = json.loads(transport.calls[0][1])["response_contract"]
    field_rules = response_contract.get("fields", {}).get("items", {})
    assert field_rules.get("required_keys") == [
        "field_id",
        "state",
        "value_snapshot",
        "evidence",
    ]
    assert field_rules.get("state_rules", {}).get("unknown") == {
        "value_snapshot": None,
        "evidence": [],
    }
    assert response_contract.get("response_skeleton") == {
        "fields": [
            {
                "field_id": "product_code",
                "state": "unknown",
                "value_snapshot": None,
                "evidence": [],
            }
        ]
    }


def test_119_only_public_transport_entrypoint_owns_full_schema67_authority() -> None:
    assert not hasattr(deepseek, "compile_596_1_deepseek_task")
    assert "compile_596_1_deepseek_task" not in deepseek.__all__
    assert "transport" not in signature(compile_schema67_deepseek_task).parameters
    assert tuple(
        name for name in deepseek.__all__ if name.startswith("compile_") and "deepseek" in name
    ) == ("compile_schema67_deepseek_task",)
    source = getsource(compile_schema67_deepseek_task)
    assert "temperature=DEEPSEEK_TEMPERATURE" in source
    assert "max_tokens=DEEPSEEK_MAX_TOKENS" in source
    assert "timeout_s=DEEPSEEK_TIMEOUT_S" in source
    assert "thinking=DEEPSEEK_THINKING" in source
    assert "response_format=DEEPSEEK_RESPONSE_FORMAT" in source
    assert "4096" not in source

    schema_parameters = signature(compile_schema67_deepseek_task).parameters
    assert "prepared" not in schema_parameters
    assert "batch_budget" not in schema_parameters
    assert {
        "field_contracts",
        "execution_plan",
        "relation_admission",
        "captured_contents",
    }.issubset(schema_parameters)
    assert "role_inputs" not in schema_parameters
    assert "locators_by_task" not in schema_parameters
    assert "binding_ports" not in schema_parameters


@pytest.mark.asyncio
async def test_119_preflight_rejects_authority_or_contract_drift_before_call() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport([])
    wrong = _profile()
    wrong = ModelProfile(
        base_url=wrong.base_url,
        api_key=wrong.api_key,
        model="deepseek-v4-pro",
        provider=wrong.provider,
        protocol=wrong.protocol,
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=wrong,
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )
    assert caught.value.reason_code == "MODEL_AUTHORITY_MISMATCH"
    assert transport.calls == []

    mixed_provider = _profile()
    mixed_provider = ModelProfile(
        base_url=mixed_provider.base_url,
        api_key=mixed_provider.api_key,
        model=mixed_provider.model,
        provider="aliyun",
        protocol=mixed_provider.protocol,
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=mixed_provider,
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )
    assert caught.value.reason_code == "MODEL_AUTHORITY_MISMATCH"
    assert transport.calls == []

    for wrong_base_url in (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://api.deepseek.com/compatible-mode/v1",
        "https://example.invalid/v1",
    ):
        exact_profile = _profile()
        wrong_host = ModelProfile(
            base_url=wrong_base_url,
            api_key=exact_profile.api_key,
            model=exact_profile.model,
            provider=exact_profile.provider,
            protocol=exact_profile.protocol,
        )
        with pytest.raises(DeepSeekCompilerError) as caught:
            await _run_deepseek_task(
                profile=wrong_host,
                policy=_policy(),
                transport=transport,
                port=_FakePort(),
                field_contracts=contracts,
                locators=locators,
            )
        assert caught.value.reason_code == "MODEL_AUTHORITY_MISMATCH"
        assert transport.calls == []

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(model_identity_sha256="f" * 64),
            field_contracts=contracts,
            locators=locators,
        )
    assert caught.value.reason_code == "MODEL_AUTHORITY_MISMATCH"
    assert transport.calls == []

    forged = contracts[0].model_copy(
        update={
            "allowed_locator_refs": ("missing",),
            "source_locator_refs": (("terms", ("missing",)),),
        }
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=(forged,),
            locators=locators,
        )
    assert caught.value.reason_code == "LOCATOR_AUTHORITY_MISMATCH"
    assert transport.calls == []

    forged_contract = contracts[0].contract.model_copy(
        update={"description": "caller-forged-description"}
    )
    forged_authority = contracts[0].model_copy(update={"contract": forged_contract})
    forged_transport = _FakeTransport([_extractor_response()])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=forged_transport,
            port=_FakePort(),
            field_contracts=(forged_authority,),
            locators=locators,
        )
    assert caught.value.reason_code == "FIELD_CONTRACT_MISMATCH"
    assert forged_transport.calls == []


@pytest.mark.asyncio
async def test_119_absent_has_no_expected_state_or_golden_oracle_in_prompt() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport([_absent_extractor_response("本合同为不保证续保合同。")])
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )
    assert result.receipt.schema_workbook_sha256 == SCHEMA67_WORKBOOK_SHA256
    assert result.receipt.approved_by == SCHEMA67_APPROVED_BY
    serialized_prompts = "\n".join(value for call in transport.calls for value in call)
    assert "explicit_absence_markers" not in serialized_prompts
    assert "expected_state" not in serialized_prompts
    assert "guaranteed_renewal_period" not in serialized_prompts
    assert "不保证续保" not in serialized_prompts
    assert "golden" not in serialized_prompts.casefold()

    with pytest.raises(ValueError):
        DeepSeekFieldPromptInputV1.model_validate(
            {**contracts[0].model_dump(mode="python"), "expected_state": "absent"}
        )


def _execution_identity(identity_sha256: str) -> SemanticExecutionIdentityV1:
    return SemanticExecutionIdentityV1(
        model_id="deepseek-v4-flash",
        model_identity_sha256=identity_sha256,
        prompt_contract_id="schema67-locator-extractor.v1",
        prompt_template_sha256="6" * 64,
        budget_identity_sha256="7" * 64,
        normalizer_identity_sha256="4" * 64,
        output_contract_id="freeform-arm-evidence-binding-receipt.v1",
        output_contract_identity_sha256="8" * 64,
    )


def test_119_execution_identity_is_exact_and_unique_before_provider() -> None:
    repair_policy_sha256 = canonical_hash(
        "schema67-response-contract-repair-policy.v2",
        {
            "failed_field_ids": "code_owned_contract_order_unique",
            "failed_field_content": "field_id_only",
            "forbidden_failure_content": (
                "locator_ref",
                "quote_snapshot",
                "raw_response",
            ),
            "repair_authority": "unchanged",
            "max_repairs": 1,
        },
    )
    slot_policy_sha256 = canonical_hash(
        "schema67-locator-slot-policy.v1",
        {
            "scope": "task_global",
            "slot_format": "slot-%04d",
            "catalog_order": "locator_ref_lexicographic",
            "catalog_content": "single_copy",
            "field_role_membership": "exact",
            "collision_policy": "reject",
            "model_visible_authority": "slot_only",
            "code_owned_mapping": "field_role_slot_to_locator_ref",
        },
    )
    expected = canonical_hash(
        "schema67-deepseek-execution-identity.v1",
        {
            "provider": "deepseek",
            "protocol": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
            "family": "deepseek",
            "role": "extract",
            "policy_version": "schema67-deepseek-v1",
            "temperature": "0.0",
            "max_tokens": 8192,
            "timeout_s": "180.0",
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "response_contract_repair_policy_sha256": repair_policy_sha256,
            "locator_slot_policy_sha256": slot_policy_sha256,
            "fixed_dual_repair_policy": {
                "max_shared_extra_calls": 2,
                "max_transport_retries": 1,
                "max_response_contract_repairs": 1,
                "max_evidence_repairs": 1,
                "allowed_pairs": (
                    "retry+response_contract_repair",
                    "retry+evidence_repair",
                    "response_contract_repair+evidence_repair",
                ),
            },
        },
    )
    assert DEEPSEEK_EXECUTION_IDENTITY_SHA256 == expected
    exact_identity_payload = {
        "provider": "deepseek",
        "protocol": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "family": "deepseek",
        "role": "extract",
        "policy_version": "schema67-deepseek-v1",
        "temperature": "0.0",
        "max_tokens": 8192,
        "timeout_s": "180.0",
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "response_contract_repair_policy_sha256": repair_policy_sha256,
        "locator_slot_policy_sha256": slot_policy_sha256,
    }
    for key, drifted in (
        ("temperature", "0.1"),
        ("max_tokens", 4096),
        ("timeout_s", "179.0"),
        ("thinking", {"type": "enabled"}),
        ("response_format", {"type": "text"}),
        ("response_contract_repair_policy_sha256", "f" * 64),
        ("locator_slot_policy_sha256", "e" * 64),
    ):
        assert (
            canonical_hash(
                "schema67-deepseek-execution-identity.v1",
                {**exact_identity_payload, key: drifted},
            )
            != DEEPSEEK_EXECUTION_IDENTITY_SHA256
        )
    exact = _execution_identity(expected)
    assert _select_deepseek_execution_identity((exact,)) == exact

    for candidates in (
        (_execution_identity("f" * 64),),
        (exact, exact),
    ):
        with pytest.raises(DeepSeekCompilerError) as caught:
            _select_deepseek_execution_identity(candidates)
        assert caught.value.reason_code == "SEMANTIC_EXECUTION_IDENTITY_MISMATCH"


def _schema67_contract_set() -> FieldContractSetV1:
    rows = approved_schema_rows()
    schema_hash = schema_rows_sha256(rows)
    snapshot_hash = approved_schema_snapshot_sha256(
        product_version_id=APPROVED_PRODUCT_VERSION_ID,
        review_package_id=APPROVED_REVIEW_PACKAGE_ID,
        schema_id=APPROVED_SCHEMA_ID,
        workbook_sha256=APPROVED_WORKBOOK_SHA256,
        approval_status="EXPERT_APPROVED_NO_CHANGES",
        approved_by=APPROVED_BY,
        authority_ref=EXACT_APPROVAL_AUTHORITY_REF,
        schema_rows_sha256_value=schema_hash,
        ordered_field_ids_sha256_value=APPROVED_ORDERED_FIELD_IDS_SHA256,
    )
    return compile_schema_contracts(
        ApprovedSchemaSnapshotV1(
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            review_package_id=APPROVED_REVIEW_PACKAGE_ID,
            schema_id=APPROVED_SCHEMA_ID,
            workbook_sha256=APPROVED_WORKBOOK_SHA256,
            approval_status="EXPERT_APPROVED_NO_CHANGES",
            approved_by=APPROVED_BY,
            authority_ref="user-message:019fda9b-schema67-approved-no-changes",
            fields=rows,
            schema_rows_sha256=schema_hash,
            ordered_field_ids_sha256=APPROVED_ORDERED_FIELD_IDS_SHA256,
            snapshot_sha256=snapshot_hash,
        )
    )


def _execution_plan(contracts: FieldContractSetV1) -> Schema67ExecutionPlanV1:
    return build_schema67_execution_plan(contracts)


def _schema67_role_inputs(
    contracts: FieldContractSetV1,
    plan: Schema67ExecutionPlanV1,
) -> tuple[Schema67RoleTaskInputV1, ...]:
    inputs: list[Schema67RoleTaskInputV1] = []
    for task_slice in plan.task_slices:
        for role in task_slice.material_roles:
            field_ids = tuple(
                field_id
                for field_id in task_slice.field_ids
                if role
                in next(
                    item.source_roles for item in contracts.contracts if item.field_id == field_id
                )
            )
            inputs.append(
                _schema67_role_input(
                    contracts=contracts,
                    task_key=task_slice.task_key,
                    role=role,
                    field_ids=field_ids,
                )
            )
    return tuple(inputs)


def _schema67_role_input(
    *,
    contracts: FieldContractSetV1,
    task_key: str,
    role: MaterialRole,
    field_ids: tuple[str, ...],
) -> Schema67RoleTaskInputV1:
    field_ids = tuple(sorted(field_ids))
    profile_id = f"596-1-{role}-v1"
    parse_policy = ApprovedParsePolicy(
        policy_id=f"596-1-{role}-approved-parse-policy",
        policy_version="v1",
        material_profile_id=profile_id,
        default_parser_profile_ref=("approved-parser-profile:parser-neutral-default.v1"),
        bounded_upgrade_profile_ref=("approved-parser-profile:parser-neutral-bounded.v1"),
        upgrade_trigger_conditions=("required_capability_missing",),
        max_parser_attempts=2,
        privacy_policy_ref="privacy-policy:private.v1",
        output_policy_ref="output-policy:internal.v1",
    )
    material = MaterialProfile(
        profile_id=profile_id,
        material_role=role,
        source=SourceDocumentIdentity(
            name=f"{role}.pdf",
            path=f"dataset/596-1/{role}.pdf",
            size=1024,
            sha256="a" * 64,
        ),
        document_type_id=f"596-1-{role}",
        required_parse_capabilities=("ordered_pages", "block_locators"),
        parse_policy=parse_policy,
    )
    receipt = ParsePolicyReceipt.model_validate(
        {
            **parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": material.required_parse_capabilities,
        }
    )
    profile = build_extraction_task_profile(
        material_profile=material,
        material_profile_binding_hash="b" * 64,
        parse_policy_receipt=receipt,
        field_authority=FieldAuthority(
            authority_class=(
                "contract_fact"
                if role == "terms"
                else "brochure_fact"
                if role == "brochure"
                else "rate_numeric"
            ),
            primary_role=role,
            support_roles=(),
            field_ids=field_ids,
        ),
        attempt_budget=AttemptBudgetV1(
            max_fields=len(field_ids),
            max_total_attempts=2,
            max_targeted_repairs=1,
        ),
    )
    refs = ExtractionInputRefsV1(
        source_revision=ArtifactRefV1(object_type="source-revision.v1", artifact_hash="a" * 64),
        material_profile=ArtifactRefV1(
            object_type=MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
            artifact_hash="b" * 64,
        ),
        resolved_template=ArtifactRefV1(object_type="resolved-template.v1", artifact_hash="c" * 64),
        schema_contract=ArtifactRefV1(
            object_type="schema67-field-contract-set.v1",
            artifact_hash=contracts.contract_set_sha256,
        ),
        parsed_document=ArtifactRefV1(object_type="parsed-document.v1", artifact_hash="d" * 64),
        parse_manifest=ArtifactRefV1(object_type="parse-manifest.v1", artifact_hash="e" * 64),
        parse_quality_decision=ArtifactRefV1(
            object_type="parse-quality-decision.v1", artifact_hash="f" * 64
        ),
    )
    return Schema67RoleTaskInputV1(
        task_key=task_key,
        material_role=role,
        space_id="space-119",
        product_version_id="596-1",
        source_revision_id=f"revision-{role}-119",
        module_id=f"schema67-{task_key}-{role}",
        risk_partition_id=f"schema67-{task_key}-{role}-risk",
        allowed_locator_refs=tuple(
            (field_id, (f"block-{role}-{field_id}",)) for field_id in field_ids
        ),
        input_refs=refs,
        task_profile=profile,
    )


def _admitted_source_for_prepared(
    prepared: Schema67PreparedTaskV1,
    *,
    source_index: int = 0,
) -> tuple[
    Schema67PreparedTaskV1,
    AdmittedParseArtifactV1,
    tuple[CanonicalLocatorInputV1, ...],
]:
    source_task = prepared.source_tasks[source_index]
    role = source_task.material_role
    locator_refs = tuple(
        ref
        for prompt in prepared.field_prompts
        for source_role, refs in prompt.source_locator_refs
        if source_role == role
        for ref in refs
    )
    document_locator_refs = locator_refs or (f"block-{role}-unassigned",)
    page = ParsePageV1(
        page_id=f"page-{role}",
        order_index=0,
        locator=PageLocatorV1(page_number=1),
        content_hash=_sha(f"page-{role}"),
        structure_hash="1" * 64,
    )
    blocks = tuple(
        ParseBlockV1(
            block_id=ref,
            order_index=index,
            locator=BlockLocatorV1(
                page_number=1,
                block_index=index,
                bbox=(Decimal(index), Decimal(0), Decimal(index + 1), Decimal(1)),
            ),
            content_hash=_sha(f"content-{ref}"),
            structure_hash=_sha(f"structure-{ref}"),
        )
        for index, ref in enumerate(document_locator_refs)
    )
    subject = ParseSubjectV1(
        space_id=source_task.space_id,
        source_id=f"source-{role}",
        source_revision_id=source_task.source_revision_id,
        product_version_id=source_task.product_version_id,
        material_profile_id=source_task.task_profile.material_profile.profile_id,
        material_profile_binding_hash=source_task.task_profile.material_profile_binding_hash,
        source_sha256=source_task.task_profile.material_profile.source.sha256,
        raw_artifact_hash="2" * 64,
        canonical_envelope_hash="3" * 64,
    )
    parser = ParserIdentityV1(
        parser_id="parser-neutral-fixture",
        parser_profile_ref=source_task.task_profile.parse_policy_receipt.default_parser_profile_ref,
        parser_build_id="build-119",
        parser_config_hash="4" * 64,
    )
    attempt = ParseAttemptV1(
        attempt_id=f"parse-attempt-{role}",
        attempt_number=1,
        attempt_role="default",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id=f"snapshot-{role}",
        snapshot_generation=0,
        pagination_complete=True,
        concurrent_mutation_fence_hash="5" * 64,
    )
    output_facts = ParseOutputFactsV1(
        privacy_policy_ref=source_task.task_profile.parse_policy_receipt.privacy_policy_ref,
        output_policy_ref=source_task.task_profile.parse_policy_receipt.output_policy_ref,
        body_text_included=False,
        secrets_included=False,
        absolute_paths_included=False,
        unknown_vendor_fields_included=False,
    )
    capabilities = (
        CapabilityEvidenceV1(capability="ordered_pages", subject_refs=(page.page_id,)),
        CapabilityEvidenceV1(
            capability="block_locators",
            subject_refs=tuple(item.block_id for item in blocks),
        ),
    )
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output_facts,
        pages=(page,),
        blocks=blocks,
        tables=(),
        cells=(),
        capability_evidence=capabilities,
        warnings=(),
        unsupported=(),
    )
    manifest = ParseManifestV1(
        contract="parse-manifest.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output_facts,
        document_hash=document.document_hash,
        ordered_page_ids=(page.page_id,),
        ordered_block_ids=tuple(item.block_id for item in blocks),
        ordered_table_ids=(),
        ordered_cell_ids=(),
        element_counts=ParseElementCountsV1(pages=1, blocks=len(blocks), tables=0, cells=0),
        required_capabilities=("ordered_pages", "block_locators"),
        satisfied_capabilities=("ordered_pages", "block_locators"),
        unsatisfied_capabilities=(),
        capability_evidence=capabilities,
        warnings=(),
        unsupported=(),
    )
    decision = ParseQualityDecisionV1(
        contract="parse-quality-decision.v1",
        subject=subject,
        manifest_hash=manifest.manifest_hash,
        parse_policy_receipt=source_task.task_profile.parse_policy_receipt,
        measured_facts=ParseQualityMeasuredFactsV1(
            threshold_version="parse-quality-structural.v1",
            required_capabilities=("ordered_pages", "block_locators"),
            satisfied_capabilities=("ordered_pages", "block_locators"),
            unsatisfied_capabilities=(),
            trigger_conditions=(),
            attempts_exhausted=False,
        ),
        decision="ADMIT",
        reason_codes=(),
        admitted_attempt_id=attempt.attempt_id,
        next_parser_profile_ref=None,
        review_item=None,
    )
    admitted = AdmittedParseArtifactV1(
        role=role,
        source_sha256=subject.source_sha256,
        artifact_sha256=document.document_hash,
        document=document,
        manifest=manifest,
        decision=decision,
        manifest_sha256=manifest.manifest_hash,
        decision_sha256=decision.decision_hash,
    )
    refs = source_task.input_refs.model_copy(
        update={
            "parsed_document": ArtifactRefV1(
                object_type="parsed-document.v1", artifact_hash=document.document_hash
            ),
            "parse_manifest": ArtifactRefV1(
                object_type="parse-manifest.v1", artifact_hash=manifest.manifest_hash
            ),
            "parse_quality_decision": ArtifactRefV1(
                object_type="parse-quality-decision.v1",
                artifact_hash=decision.decision_hash,
            ),
        }
    )
    source_task = build_extraction_task(
        space_id=source_task.space_id,
        product_version_id=source_task.product_version_id,
        source_revision_id=source_task.source_revision_id,
        material_role=source_task.material_role,
        module_id=source_task.module_id,
        risk_partition_id=source_task.risk_partition_id,
        field_ids=source_task.field_ids,
        input_refs=refs,
        budget=source_task.budget,
        task_profile=source_task.task_profile,
    )
    source_tasks = tuple(
        source_task if index == source_index else item
        for index, item in enumerate(prepared.source_tasks)
    )
    initial_attempts = tuple(build_initial_attempt(item) for item in source_tasks)
    provider_task_sha256 = canonical_hash(
        "schema67-deepseek-provider-task.v1",
        {
            "execution_plan_sha256": prepared.execution_plan_sha256,
            "task_slice_sha256": prepared.task_slice_sha256,
            "source_task_hashes": tuple(item.task_hash for item in source_tasks),
            "locator_selection_policy_sha256": deepseek.LOCATOR_SELECTION_POLICY_SHA256,
            "field_prompt_authorities": tuple(
                item.model_dump(mode="python") for item in prepared.field_prompts
            ),
        },
    )
    prepared = replace(
        prepared,
        source_tasks=source_tasks,
        initial_attempts=initial_attempts,
        provider_task_sha256=provider_task_sha256,
        provider_attempt_sha256=canonical_hash(
            "schema67-deepseek-provider-attempt.v1",
            {
                "provider_task_sha256": provider_task_sha256,
                "source_attempt_hashes": tuple(
                    item.attempt_hash for item in initial_attempts
                ),
            },
        ),
    )
    locators = tuple(
        CanonicalLocatorInputV1(
            locator_ref=ref,
            locator_kind="block",
            page_number=1,
            parent_refs=(page.page_id,),
            content_snapshot=f"content-{ref}",
            content_snapshot_sha256=_sha(f"content-{ref}"),
        )
        for ref in locator_refs
    )
    return prepared, admitted, locators


@pytest.mark.asyncio
async def test_119_lane_a_role_subsets_build_exact_054_tasks_before_fake_run() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )
    assert len(prepared) == 8
    assert all(len(item.field_prompts) <= 8 for item in prepared)
    assert sum(len(item.field_prompts) for item in prepared) == 46
    assert tuple(item.task_kind for item in prepared).count("synthesis") == 1
    synthesis = next(item for item in prepared if item.task_kind == "synthesis")
    assert len(synthesis.field_prompts) == 6
    assert {item.material_role for item in synthesis.source_tasks} == {
        "terms",
        "brochure",
        "rate_table",
    }
    assert len(plan.deferred_unknown_field_ids) == 21
    assert all(len(item.field_prompts) <= 8 for item in prepared)
    assert all(
        field_id not in {prompt.field_id for prompt in item.field_prompts}
        for field_id in plan.deferred_unknown_field_ids
        for item in prepared
    )
    assert all(
        attempt.task_hash == task.task_hash
        for item in prepared
        for task, attempt in zip(item.source_tasks, item.initial_attempts, strict=True)
    )

    first = prepared[0]
    locators = tuple(
        CanonicalLocatorInputV1(
            locator_ref=contract.allowed_locator_refs[0],
            locator_kind="block",
            page_number=1,
            parent_refs=("page-1",),
            content_snapshot=f"source content for {contract.field_id}",
            content_snapshot_sha256=_sha(f"source content for {contract.field_id}"),
        )
        for contract in first.field_prompts
    )
    extractor_response = json.dumps(
        {
            "fields": [
                {
                    "field_id": contract.field_id,
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": [],
                }
                for contract in first.field_prompts
            ],
        },
        separators=(",", ":"),
    )
    transport = _FakeTransport([extractor_response, extractor_response])
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(
            task_id=first.provider_task_sha256,
            attempt_hash=first.provider_attempt_sha256,
            field_ids=tuple(item.field_id for item in first.field_prompts),
            expected_locator_refs=tuple(item.locator_ref for item in locators),
        ),
        field_contracts=first.field_prompts,
        locators=locators,
    )
    assert result.receipt.task_id == first.provider_task_sha256
    assert result.receipt.attempt_hash == first.provider_attempt_sha256
    assert len(transport.calls) == 1
    prompt_bytes = "\n".join(value for call in transport.calls for value in call)
    assert all(field_id not in prompt_bytes for field_id in plan.deferred_unknown_field_ids)


def test_119_concrete_schema67_binding_consumes_admitted_artifact_and_keeps_receipts() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(
        prepared=prepared,
        admitted_sources=(admitted,),
    )
    port.validate_locators(locators)
    response = json.dumps(
        {
            "task_id": prepared.provider_task_sha256,
            "attempt_hash": prepared.provider_attempt_sha256,
            "arm_blueprint_hash": prepared.task_slice_sha256,
            "model_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
            "fields": [
                {
                    "product_version_id": "596-1",
                    "field_id": prompt.field_id,
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": [],
                }
                for prompt in prepared.field_prompts
            ],
        },
        separators=(",", ":"),
    ).encode()
    bound = port.bind_initial(response)
    assert tuple(item.field_id for item in bound.outputs) == port.field_ids
    assert tuple(item.field_id for item in bound.evidence_receipts) == port.field_ids
    assert len(bound.verification_batches) == len(prepared.source_tasks) == 1
    assert len(bound.receipt_chains) == 1
    assert all(item.state == "unknown" for item in bound.outputs)

    selected = tuple((item.field_id, item.allowed_locator_refs) for item in prepared.field_prompts)
    request = port.prepare_repair(bound, selected)
    assert request is not None
    prompt_by_field = {item.field_id: item for item in prepared.field_prompts}
    repair_fields = []
    for field_id in request.field_ids:
        locator_ref = prompt_by_field[field_id].allowed_locator_refs[0]
        quote = f"content-{locator_ref}"
        repair_fields.append(
            {
                "product_version_id": "596-1",
                "field_id": field_id,
                "state": "present",
                "value_snapshot": quote,
                "evidence": [
                    {
                        "field_id": field_id,
                        "source_sha256": admitted.source_sha256,
                        "source_revision_id": admitted.document.subject.source_revision_id,
                        "parse_attempt_id": admitted.document.attempt.attempt_id,
                        "parsed_document_hash": admitted.document.document_hash,
                        "parse_manifest_hash": admitted.manifest.manifest_hash,
                        "page_number": 1,
                        "block_id": locator_ref,
                        "locator": {
                            "subject_type": "block",
                            "subject_ref": locator_ref,
                            "page_number": 1,
                            "parent_refs": ["page-terms"],
                            "content_snapshot": quote,
                            "content_snapshot_sha256": _sha(quote),
                        },
                        "quote_snapshot": quote,
                        "quote_snapshot_sha256": _sha(quote),
                    }
                ],
            }
        )
    repaired = port.bind_repair(
        json.dumps({"fields": repair_fields}, separators=(",", ":")).encode(),
        request,
    )
    assert all(item.state == "present" for item in repaired.outputs)
    assert tuple(item.field_id for item in repaired.evidence_receipts) == request.field_ids
    assert len(repaired.receipt_chains[0].receipts) == 2


def test_119_concrete_binding_accepts_exact_mineru_domain_hash_snapshot() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    parser = admitted.document.parser.model_copy(
        update={
            "parser_id": "mineru-cloud-pipeline",
            "parser_build_id": "NewMinerUCloudReader/mineru-native-structure.v1",
        }
    )
    content_by_ref = {item.locator_ref: item.content_snapshot for item in locators}
    document = ParsedDocumentV1.model_validate(
        {
            **admitted.document.model_dump(mode="python", exclude={"document_hash"}),
            "parser": parser,
            "blocks": tuple(
                block.model_copy(
                    update={
                        "content_hash": _mineru_hash(
                            "block-content", content_by_ref[block.block_id]
                        )
                    }
                )
                for block in admitted.document.blocks
            ),
        }
    )
    manifest = ParseManifestV1.model_validate(
        {
            **admitted.manifest.model_dump(mode="python", exclude={"manifest_hash"}),
            "parser": parser,
            "document_hash": document.document_hash,
        }
    )
    decision = ParseQualityDecisionV1.model_validate(
        {
            **admitted.decision.model_dump(mode="python", exclude={"decision_hash"}),
            "manifest_hash": manifest.manifest_hash,
        }
    )
    mineru_admitted = AdmittedParseArtifactV1(
        role=admitted.role,
        source_sha256=admitted.source_sha256,
        artifact_sha256=document.document_hash,
        document=document,
        manifest=manifest,
        decision=decision,
        manifest_sha256=manifest.manifest_hash,
        decision_sha256=decision.decision_hash,
    )

    _Schema67EvidenceBindingPort(
        prepared=prepared,
        admitted_sources=(mineru_admitted,),
    ).validate_locators(locators)


def test_119_real_mineru_snapshot_recovers_only_exact_single_line_block_preimages() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    exact_contents = tuple(item.content_snapshot for item in locators)
    parser = admitted.document.parser.model_copy(
        update={
            "parser_id": "mineru-cloud-pipeline",
            "parser_build_id": "NewMinerUCloudReader/mineru-native-structure.v1",
        }
    )
    blocks = tuple(
        block.model_copy(
            update={"content_hash": _mineru_hash("block-content", exact_contents[index])}
        )
        for index, block in enumerate(admitted.document.blocks)
    )
    document = ParsedDocumentV1.model_validate(
        {
            **admitted.document.model_dump(mode="python", exclude={"document_hash"}),
            "parser": parser,
            "blocks": blocks,
        }
    )
    mineru_admitted = replace(admitted, document=document)
    snapshot = "\n\n".join(f"## {value}" for value in exact_contents)

    recovered = deepseek.recover_exact_mineru_block_locators(
        admitted_source=mineru_admitted,
        content_snapshot=snapshot,
    )

    assert tuple(item.locator_ref for item in recovered) == tuple(
        item.locator_ref for item in locators
    )
    assert tuple(item.content_snapshot for item in recovered) == exact_contents
    assert all("\n" not in item.content_snapshot for item in recovered)


def test_119_cropped_capture_snapshot_is_rejected_before_execution_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    role_inputs = _schema67_role_inputs(contracts, plan)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=role_inputs,
    )
    selected = tuple(
        next(
            item
            for item in prepared
            if item.task_kind == "material" and item.source_tasks[0].material_role == role
        )
        for role in ("terms", "brochure", "rate_table")
    )
    built = tuple(_admitted_source_for_prepared(item) for item in selected)
    admitted: list[AdmittedParseArtifactV1] = []
    captures: list[Schema67CapturedContentV1] = []
    for index, (_task, source, locators) in enumerate(built):
        whole_snapshot = "\n".join(item.content_snapshot for item in locators)
        whole_hash = _sha(whole_snapshot)
        capture_identity = _sha(f"capture-{index}:{whole_hash}")
        raw_hash = _sha(f"raw-{index}")
        sanitized_hash = _sha(f"sanitized-{index}")
        admitted.append(
            replace(
                source,
                capture_identity_sha256=capture_identity,
                content_snapshot_sha256=whole_hash,
                raw_structure_sha256=raw_hash,
                sanitized_structure_sha256=sanitized_hash,
            )
        )
        supplied_snapshot = locators[0].content_snapshot if index == 0 else whole_snapshot
        captures.append(
            Schema67CapturedContentV1(
                role=source.role,
                source_sha256=source.source_sha256,
                capture_identity_sha256=capture_identity,
                raw_structure_sha256=raw_hash,
                sanitized_structure_sha256=sanitized_hash,
                content_snapshot=supplied_snapshot,
                content_snapshot_sha256=_sha(supplied_snapshot),
            )
        )

    original_admission = VerticalFalsificationAdmission(
        status="READY_FOR_QUALITY_FALSIFICATION",
        missing_contracts=(),
        receipt_digest_sha256="f" * 64,
    )
    relation_admission = RelationBoundAdmissionResultV1(
        status="READY_FOR_QUALITY_FALSIFICATION",
        admitted_parse_artifacts=tuple(admitted),
        admission=original_admission,
        intake_bundle_digest_sha256="e" * 64,
        integration_digest_sha256="d" * 64,
    )
    monkeypatch.setattr(
        deepseek,
        "admit_596_1_vertical_falsification",
        lambda **_: VerticalFalsificationAdmission(
            status="READY_FOR_QUALITY_FALSIFICATION",
            missing_contracts=(),
            receipt_digest_sha256="a" * 64,
        ),
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        prepare_schema67_real_execution_inputs(
            field_contracts=contracts,
            execution_plan=plan,
            relation_admission=relation_admission,
            captured_contents=tuple(captures),
        )

    assert caught.value.reason_code == "SCHEMA67_RELATION_ADMISSION_INVALID"


def test_119_field_contract_locator_narrowing_is_deterministic_and_contract_only() -> None:
    contract = _schema67_contract_set().contracts[0]
    locators = tuple(
        CanonicalLocatorInputV1(
            locator_ref=f"block-{index:03d}",
            locator_kind="block",
            page_number=1,
            parent_refs=("page-1",),
            content_snapshot=(
                f"{contract.field_name} 对应原始材料" if index == 50 else f"普通条款 {index}"
            ),
            content_snapshot_sha256=_sha(
                f"{contract.field_name} 对应原始材料" if index == 50 else f"普通条款 {index}"
            ),
        )
        for index in range(100)
    )

    first = deepseek.select_contract_locator_refs(contract=contract, locators=locators)
    second = deepseek.select_contract_locator_refs(contract=contract, locators=locators)

    assert first == second
    assert "block-050" in first
    assert set(first).issubset({item.locator_ref for item in locators})
    assert len(first) <= 24


@pytest.mark.asyncio
async def test_119_oversized_http_envelope_fails_before_transport() -> None:
    contracts, base_locators = _inputs()
    transport = _FakeTransport([_extractor_response()])
    escaped_content = "\\u4fdd" * 80
    extra_locators = tuple(
        CanonicalLocatorInputV1(
            locator_ref=f"oversized-block-{index:03d}",
            locator_kind="block",
            page_number=1,
            parent_refs=("page-1",),
            content_snapshot=escaped_content,
            content_snapshot_sha256=_sha(escaped_content),
        )
        for index in range(200)
    )
    locators = (*base_locators, *extra_locators)
    allowed_refs = tuple(sorted(item.locator_ref for item in locators))
    exact_contracts = (
        contracts[0].model_copy(
            update={
                "allowed_locator_refs": allowed_refs,
                "source_locator_refs": (("terms", allowed_refs),),
            }
        ),
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(expected_locator_refs=tuple(item.locator_ref for item in locators)),
            field_contracts=exact_contracts,
            locators=locators,
        )

    assert caught.value.reason_code == "MODEL_REQUEST_TOO_LARGE"
    assert transport.calls == []


def test_119_request_size_boundary_counts_exact_thinking_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deepseek,
        "_deepseek_request_bytes",
        lambda **_kwargs: b"x" * deepseek.DEEPSEEK_MAX_REQUEST_BYTES,
    )
    deepseek._require_request_size(system="sys", user="user")

    monkeypatch.setattr(
        deepseek,
        "_deepseek_request_bytes",
        lambda **_kwargs: b"x" * (deepseek.DEEPSEEK_MAX_REQUEST_BYTES + 1),
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        deepseek._require_request_size(system="sys", user="user")
    assert caught.value.reason_code == "MODEL_REQUEST_TOO_LARGE"


def test_119_all_request_stages_share_json_object_serializer() -> None:
    calls = (
        ("initial-system", "initial-user"),
        ("repair-system", "repair-user"),
        ("repair-system", "repair-user"),
    )
    bodies = tuple(
        deepseek._deepseek_request_bytes(system=system, user=user)
        for system, user in calls
    )
    decoded = tuple(json.loads(body) for body in bodies)
    assert all(
        item["response_format"] == {"type": "json_object"}
        for item in decoded
    )
    assert bodies[1] == bodies[2]
    assert max(len(body) for body in bodies) < deepseek.DEEPSEEK_MAX_REQUEST_BYTES


def test_119_concrete_factory_owns_three_admitted_source_ports() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    role_inputs = _schema67_role_inputs(contracts, plan)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=role_inputs,
    )
    selected = tuple(
        next(
            item
            for item in prepared
            if item.task_kind == "material" and item.source_tasks[0].material_role == role
        )
        for role in ("terms", "brochure", "rate_table")
    )
    corrected: list[Schema67PreparedTaskV1] = []
    admitted: list[AdmittedParseArtifactV1] = []
    corrected_inputs: list[Schema67RoleTaskInputV1] = []
    for item in selected:
        exact_item, source, _ = _admitted_source_for_prepared(item)
        corrected.append(exact_item)
        admitted.append(source)
        original = next(
            value
            for value in role_inputs
            if value.task_key == item.task_key
            and value.material_role == item.source_tasks[0].material_role
        )
        corrected_inputs.append(replace(original, input_refs=exact_item.source_tasks[0].input_refs))
    ports = _schema67_binding_ports(
        prepared_tasks=tuple(corrected),
        role_inputs=tuple(corrected_inputs),
        admitted_sources=tuple(admitted),
    )
    assert len(ports) == 3
    assert tuple(item.admitted_sources[0].role for item in ports) == (
        "terms",
        "brochure",
        "rate_table",
    )


@pytest.mark.asyncio
async def test_119_fake_transport_runs_through_production_concrete_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    role_inputs = _schema67_role_inputs(contracts, plan)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=role_inputs,
    )
    selected = tuple(
        next(
            item
            for item in prepared
            if item.task_kind == "material" and item.source_tasks[0].material_role == role
        )
        for role in ("terms", "brochure", "rate_table")
    )
    corrected = tuple(_admitted_source_for_prepared(item) for item in selected)
    task, terms, locators = corrected[0]
    admitted = tuple(item[1] for item in corrected)
    original_input = next(
        item
        for item in role_inputs
        if item.task_key == task.task_key and item.material_role == "terms"
    )
    exact_input = replace(original_input, input_refs=task.source_tasks[0].input_refs)
    monkeypatch.setattr(
        deepseek,
        "prepare_schema67_deepseek_tasks",
        lambda **_: (task,),
    )
    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "prepare_repair",
        lambda *_args, **_kwargs: None,
    )
    transport = _UnknownExtractorTransport()
    result = await _run_schema67_deepseek_batch(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=(exact_input,),
        admitted_sources=admitted,
        locators_by_task=(locators,),
    )
    assert terms.role == "terms"
    assert result.receipt.task_count == 1
    assert result.receipt.locator_calls == 0
    assert result.receipt.provider_calls == len(transport.calls)
    assert result.executions[0].final_outputs == result.executions[0].initial_outputs
    assert len(result.executions[0].evidence_receipts) == len(task.field_prompts)


def test_119_lane_a_partition_drift_blocks_before_any_task_or_provider() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    forged_payload = {
        "contract_set_sha256": plan.contract_set_sha256,
        "task_slices": tuple(item.model_dump(mode="python") for item in plan.task_slices),
        "deferred_unknown_field_ids": plan.deferred_unknown_field_ids[1:],
        "batch_budget": plan.batch_budget.model_dump(mode="python"),
    }
    forged = Schema67ExecutionPlanV1.model_validate(
        {
            **forged_payload,
            "execution_plan_sha256": canonical_hash(
                "schema67-deepseek-execution-plan.v2", forged_payload
            ),
        }
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=forged,
            role_inputs=_schema67_role_inputs(contracts, plan),
        )
    assert caught.value.reason_code == "SCHEMA67_FIELD_PARTITION_INVALID"

    changed_contract = contracts.contracts[0].model_copy(
        update={"description": "forged A contract"}
    )
    changed_set = contracts.model_copy(
        update={"contracts": (changed_contract, *contracts.contracts[1:])}
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        prepare_schema67_deepseek_tasks(
            field_contracts=changed_set,
            execution_plan=plan,
            role_inputs=_schema67_role_inputs(contracts, plan),
        )
    assert caught.value.reason_code == "SCHEMA67_CONTRACT_SET_INVALID"


def test_119_rejects_giant_or_single_source_multisource_plans() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    first = plan.task_slices[0]
    giant = first.model_copy(
        update={"field_ids": tuple(item.field_id for item in contracts.contracts[:35])}
    )
    forged = plan.model_copy(update={"task_slices": (giant, *plan.task_slices[1:])})
    with pytest.raises(DeepSeekCompilerError) as caught:
        prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=forged,
            role_inputs=_schema67_role_inputs(contracts, plan),
        )
    assert caught.value.reason_code == "SCHEMA67_FIELD_PARTITION_INVALID"

    synthesis = next(item for item in plan.task_slices if item.task_kind == "synthesis")
    single_role = synthesis.model_copy(update={"material_roles": ("terms",)})
    forged = plan.model_copy(
        update={
            "task_slices": tuple(
                single_role if item.task_key == synthesis.task_key else item
                for item in plan.task_slices
            )
        }
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=forged,
            role_inputs=_schema67_role_inputs(contracts, plan),
        )
    assert caught.value.reason_code == "SCHEMA67_FIELD_PARTITION_INVALID"


@pytest.mark.asyncio
async def test_119_shape_invalid_gets_one_response_contract_repair() -> None:
    contracts, locators = _inputs()
    sentinel = "RAW_RESPONSE_MUST_NOT_REAPPEAR"
    transport = _FakeTransport(
        [
            _shape_invalid_response(("product_code",), sentinel=sentinel),
            _unknown_fields_response(("product_code",)),
        ]
    )

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )

    assert len(transport.calls) == 2
    assert result.receipt.response_contract_repairs == 1
    assert result.receipt.evidence_repairs == 0
    assert result.receipt.transport_retries == 0
    assert result.receipt.repair_calls == 1
    assert result.response_contract_repair is not None
    assert result.response_contract_repair.failure_code == "FIELD_ITEM_SHAPE"
    assert result.response_contract_repair.failed_field_ids == ()
    assert result.response_contract_repair.invalid_response_sha256 == _sha(
        _shape_invalid_response(("product_code",), sentinel=sentinel)
    )
    repair_payload = json.loads(transport.calls[1][1])
    assert repair_payload["repair_kind"] == "response_contract"
    assert repair_payload["reason_code"] == "FIELD_ITEM_SHAPE"
    assert repair_payload["failed_field_ids"] == []
    assert repair_payload["parent_extractor_request_sha256"] == (
        result.receipt.extractor_request_sha256
    )
    assert sentinel not in transport.calls[1][1]
    assert repair_payload["field_contracts"] == json.loads(transport.calls[0][1])["field_contracts"]
    assert repair_payload["locator_slot_catalog"] == json.loads(
        transport.calls[0][1]
    )["locator_slot_catalog"]
    assert repair_payload["field_locator_slots"] == json.loads(
        transport.calls[0][1]
    )["field_locator_slots"]
    assert (
        repair_payload["response_contract"]
        == json.loads(transport.calls[0][1])["response_contract"]
    )
    forged = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    assert isinstance(forged["response_contract_repair"], dict)
    forged["response_contract_repair"]["failure_code"] = (
        "CODE_OWNED_AUTHORITY_MISMATCH"
    )
    with pytest.raises(ValueError):
        deepseek.DeepSeekExecutionReceiptV1.model_validate(
            {
                **forged,
                "receipt_hash": canonical_hash("deepseek-evidence-compiler-596-1.v2", forged),
            }
        )


@pytest.mark.asyncio
async def test_119_locator_membership_repair_binds_only_failed_field_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(
        prepared=prepared,
        admitted_sources=(admitted,),
    )
    target_a, target_b = prepared.field_prompts[:2]
    ref_a = target_a.allowed_locator_refs[0]
    ref_b = target_b.allowed_locator_refs[0]
    quote_a = f"content-{ref_a}"
    quote_b = f"content-{ref_b}"
    slot_authority = _slot_authority(
        prepared.field_prompts, locators, port=port
    )
    slot_by_ref = {
        locator_ref: slot
        for _field_id, _role, slot, locator_ref in slot_authority.code_mapping
    }
    invalid_fields: list[dict[str, object]] = [
        {
            "field_id": prompt.field_id,
            "state": "unknown",
            "value_snapshot": None,
            "evidence": [],
        }
        for prompt in prepared.field_prompts
    ]
    invalid_fields[0] = {
        "field_id": target_a.field_id,
        "state": "present",
        "value_snapshot": "candidate-a",
        "evidence": [
            {
                "source_role": "terms",
                "locator_slot": slot_by_ref[ref_b],
                "quote_snapshot": quote_b,
            }
        ],
    }
    invalid_fields[1] = {
        "field_id": target_b.field_id,
        "state": "present",
        "value_snapshot": "candidate-b",
        "evidence": [
            {
                "source_role": "terms",
                "locator_slot": slot_by_ref[ref_a],
                "quote_snapshot": quote_a,
            }
        ],
    }
    invalid_response = json.dumps(
        {"fields": invalid_fields}, ensure_ascii=False, separators=(",", ":")
    )
    expected_failed = (target_a.field_id, target_b.field_id)
    with pytest.raises(DeepSeekCompilerError) as caught:
        deepseek._require_extractor_envelope(
            json.loads(invalid_response),
            contracts=prepared.field_prompts,
            slot_authority=slot_authority,
        )
    assert caught.value.reason_code == "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID"
    assert isinstance(caught.value, deepseek._LocatorMembershipFailure)
    assert caught.value.failed_field_ids == expected_failed
    assert ref_a not in repr(caught.value)
    assert ref_b not in repr(caught.value)
    assert quote_a not in repr(caught.value)
    assert quote_b not in repr(caught.value)

    repaired_response = _unknown_fields_response(
        tuple(prompt.field_id for prompt in prepared.field_prompts)
    )

    class _FailedFieldAwareTransport(_FakeTransport):
        async def complete(self, system: str, user: str) -> str:
            self.calls.append((system, user))
            payload = json.loads(user)
            if payload.get("failed_field_ids") == list(expected_failed):
                return repaired_response
            return invalid_response

    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "prepare_repair",
        lambda *_args, **_kwargs: None,
    )
    transport = _FailedFieldAwareTransport(())
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=port,
        field_contracts=prepared.field_prompts,
        locators=locators,
        execution_plan_sha256=plan.execution_plan_sha256,
        task_slice_sha256=prepared.task_slice_sha256,
    )

    assert len(transport.calls) == 2
    initial_payload = json.loads(transport.calls[0][1])
    repair_payload = json.loads(transport.calls[1][1])
    assert repair_payload["failed_field_ids"] == list(expected_failed)
    assert set(repair_payload).isdisjoint(
        {"failed_locator_refs", "failed_quotes", "raw_response"}
    )
    for key in (
        "field_contracts",
        "locator_authority_sha256",
        "locator_selection_sha256",
        "locator_slot_policy_sha256",
        "locator_slot_authority_sha256",
        "locator_slot_catalog",
        "field_locator_slots",
        "response_contract",
    ):
        assert repair_payload[key] == initial_payload[key]
    assert result.receipt.field_ids == tuple(
        prompt.field_id for prompt in prepared.field_prompts
    )
    assert result.response_contract_repair is not None
    assert result.response_contract_repair.failed_field_ids == expected_failed
    assert isinstance(
        result.response_contract_repair, deepseek.ResponseContractRepairResolutionV2
    )
    assert result.response_contract_repair.field_ids == result.receipt.field_ids
    assert result.response_contract_repair.response_contract_repair_policy_sha256 == (
        result.receipt.response_contract_repair_policy_sha256
    )

    for forged_failed in (
        tuple(reversed(expected_failed)),
        (*expected_failed, "outside-contract-field"),
    ):
        forged = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
        assert isinstance(forged["response_contract_repair"], dict)
        resolution_values = {
            **forged["response_contract_repair"],
            "response_contract_repair_policy_sha256": (
                forged["response_contract_repair_policy_sha256"]
            ),
            "field_ids": forged["field_ids"],
            "failed_field_ids": forged_failed,
            "parent_extractor_request_sha256": forged["extractor_request_sha256"],
        }
        resolution_values.pop("resolution_hash")
        forged["response_contract_repair"] = {
            **resolution_values,
            "resolution_hash": canonical_hash(
                "schema67-response-contract-repair-resolution.v2",
                resolution_values,
            ),
        }
        with pytest.raises(ValueError):
            deepseek.DeepSeekExecutionReceiptV1.model_validate(
                {
                    **forged,
                    "receipt_hash": canonical_hash(
                        "deepseek-evidence-compiler-596-1.v2", forged
                    ),
                }
            )
@pytest.mark.asyncio
async def test_119_locator_membership_repair_stays_fail_closed_after_exact_two_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(prepared=prepared, admitted_sources=(admitted,))
    target, foreign = prepared.field_prompts[:2]
    foreign_ref = foreign.allowed_locator_refs[0]
    slot_authority = _slot_authority(prepared.field_prompts, locators, port=port)
    foreign_slot = next(
        slot
        for _field_id, _role, slot, locator_ref in slot_authority.code_mapping
        if locator_ref == foreign_ref
    )
    quote = f"content-{foreign_ref}"
    response_fields: list[dict[str, object]] = [
        {
            "field_id": prompt.field_id,
            "state": "unknown",
            "value_snapshot": None,
            "evidence": [],
        }
        for prompt in prepared.field_prompts
    ]
    response_fields[0] = {
        "field_id": target.field_id,
        "state": "present",
        "value_snapshot": "candidate",
        "evidence": [
            {
                "source_role": "terms",
                "locator_slot": foreign_slot,
                "quote_snapshot": quote,
            }
        ],
    }
    foreign_response = json.dumps(
        {"fields": response_fields}, ensure_ascii=False, separators=(",", ":")
    )
    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "prepare_repair",
        lambda *_args, **_kwargs: None,
    )
    transport = _FakeTransport([foreign_response, foreign_response])

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=port,
            field_contracts=prepared.field_prompts,
            locators=locators,
        )
    assert caught.value.reason_code == "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID"
    assert isinstance(caught.value, deepseek._LocatorMembershipFailure)
    assert caught.value.failed_field_ids == (target.field_id,)
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_119_field_local_slots_make_foreign_locator_unrepresentable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(prepared=prepared, admitted_sources=(admitted,))
    target, foreign = prepared.field_prompts[:2]
    target_ref = target.allowed_locator_refs[0]
    foreign_ref = foreign.allowed_locator_refs[0]
    assert target_ref != foreign_ref

    class _SlotAwareTransport(_FakeTransport):
        async def complete(self, system: str, user: str) -> str:
            self.calls.append((system, user))
            payload = json.loads(user)
            assert "selected_locators" not in payload
            assert "deterministic_locator_selection" not in payload
            assert "locator_ref" not in json.dumps(tuple(payload.keys()))
            slot_rows = {
                row["field_id"]: row for row in payload["field_locator_slots"]
            }
            target_role = slot_rows[target.field_id]["sources"][0]
            foreign_role = slot_rows[foreign.field_id]["sources"][0]
            assert target_role["source_role"] == foreign_role["source_role"] == "terms"
            target_slot = target_role["allowed_slots"][0]
            foreign_slot = foreign_role["allowed_slots"][0]
            assert target_slot != foreign_slot
            catalog_slots = [row["slot"] for row in payload["locator_slot_catalog"]]
            assert len(catalog_slots) == len(set(catalog_slots))
            attempted_slot = target_slot if len(self.calls) == 2 else foreign_slot
            fields: list[dict[str, object]] = [
                {
                    "field_id": prompt.field_id,
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": [],
                }
                for prompt in prepared.field_prompts
            ]
            fields[0] = {
                "field_id": target.field_id,
                "state": "present",
                "value_snapshot": "candidate",
                "evidence": [
                        {
                            "source_role": "terms",
                            "locator_slot": attempted_slot,
                            "quote_snapshot": f"content-{target_ref}",
                    }
                ],
            }
            return json.dumps({"fields": fields}, ensure_ascii=False, separators=(",", ":"))

    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "prepare_repair",
        lambda *_args, **_kwargs: None,
    )
    transport = _SlotAwareTransport(())
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=port,
        field_contracts=prepared.field_prompts,
        locators=locators,
        execution_plan_sha256=plan.execution_plan_sha256,
        task_slice_sha256=prepared.task_slice_sha256,
    )

    output = result.final_outputs[0]
    assert output.field_id == target.field_id
    assert output.evidence[0].locator.subject_ref == target_ref
    assert output.evidence[0].locator.subject_ref != foreign_ref
    assert len(transport.calls) == 2
    assert result.receipt.locator_slot_authority_sha256 == (
        json.loads(transport.calls[0][1])["locator_slot_authority_sha256"]
    )
    forged = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    forged["locator_slot_policy_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        deepseek.DeepSeekExecutionReceiptV1.model_validate(
            {
                **forged,
                "receipt_hash": canonical_hash(
                    "deepseek-evidence-compiler-596-1.v2", forged
                ),
            }
        )
    with pytest.raises(ValueError):
        deepseek.DeepSeekExecutionReceiptV1.model_validate(
            result.receipt.model_copy(
                update={"locator_slot_authority_sha256": "e" * 64}
            ).model_dump(mode="python")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_role", "locator_slot"),
    (("terms", "slot-9999"), ("brochure", "slot-0001")),
)
async def test_119_invalid_slot_or_role_gets_one_repair_then_stops(
    source_role: str,
    locator_slot: str,
) -> None:
    contracts, locators = _inputs()
    response = json.dumps(
        {
            "fields": [
                {
                    "field_id": "product_code",
                    "state": "present",
                    "value_snapshot": "candidate",
                    "evidence": [
                        {
                            "source_role": source_role,
                            "locator_slot": locator_slot,
                            "quote_snapshot": "保险责任以条款约定为准。",
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    transport = _FakeTransport((response, response))
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )
    assert caught.value.reason_code == "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID"
    assert isinstance(caught.value, deepseek._LocatorMembershipFailure)
    assert caught.value.failed_field_ids == ("product_code",)
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_119_slot_mapping_mutation_is_rejected_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts, locators = _inputs()
    port = _FakePort()
    authority = _slot_authority(contracts, locators, port=port)
    forged = replace(
        authority,
        code_mapping=(("product_code", "terms", "slot-0001", "foreign-ref"),),
    )
    monkeypatch.setattr(deepseek, "_build_locator_slot_authority", lambda **_kwargs: forged)
    transport = _FakeTransport((_unknown_fields_response(("product_code",)),))
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=port,
            field_contracts=contracts,
            locators=locators,
        )
    assert caught.value.reason_code == "LOCATOR_SLOT_AUTHORITY_INVALID"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_119_self_consistent_slot_reordering_is_rejected_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set().contracts[:2]
    prompts: list[DeepSeekFieldPromptInputV1] = []
    locators: list[CanonicalLocatorInputV1] = []
    for ordinal, contract in enumerate(contracts, start=1):
        ref = f"block-{ordinal}"
        prompt_payload = {
            "field_id": contract.field_id,
            "description": contract.description,
            "value_shape": contract.value_shape,
            "formation_modes": contract.formation_modes,
            "source_roles": contract.source_roles,
            "evidence_required": contract.evidence_required,
            "output_state_policy": contract.output_state_policy,
            "hardness": contract.hardness.model_dump(mode="python"),
            "field_contract_sha256": contract.field_contract_sha256,
        }
        prompts.append(
            DeepSeekFieldPromptInputV1(
                contract=contract,
                prompt_payload_sha256=canonical_hash(
                    "schema67-deepseek-field-prompt.v1", prompt_payload
                ),
                allowed_locator_refs=(ref,),
                source_locator_refs=(("terms", (ref,)),),
            )
        )
        content = f"canonical content {ordinal}"
        locators.append(
            CanonicalLocatorInputV1(
                locator_ref=ref,
                locator_kind="block",
                page_number=ordinal,
                parent_refs=(f"page-{ordinal}",),
                content_snapshot=content,
                content_snapshot_sha256=_sha(content),
            )
        )
    exact_prompts = tuple(prompts)
    exact_locators = tuple(locators)
    port = _FakePort(
        field_ids=tuple(item.field_id for item in exact_prompts),
        expected_locator_refs=tuple(item.locator_ref for item in exact_locators),
    )
    authority = _slot_authority(exact_prompts, exact_locators, port=port)
    first_catalog, second_catalog = authority.catalog
    swapped_catalog = (
        first_catalog.model_copy(
            update={
                "locator_kind": second_catalog.locator_kind,
                "page_number": second_catalog.page_number,
                "content_snapshot": second_catalog.content_snapshot,
                "content_snapshot_sha256": second_catalog.content_snapshot_sha256,
            }
        ),
        second_catalog.model_copy(
            update={
                "locator_kind": first_catalog.locator_kind,
                "page_number": first_catalog.page_number,
                "content_snapshot": first_catalog.content_snapshot,
                "content_snapshot_sha256": first_catalog.content_snapshot_sha256,
            }
        ),
    )
    first_row, second_row = authority.field_locator_slots
    swapped_rows = (
        first_row.model_copy(
            update={
                "sources": (
                    first_row.sources[0].model_copy(
                        update={"allowed_slots": ("slot-0002",)}
                    ),
                )
            }
        ),
        second_row.model_copy(
            update={
                "sources": (
                    second_row.sources[0].model_copy(
                        update={"allowed_slots": ("slot-0001",)}
                    ),
                )
            }
        ),
    )
    swapped_mapping = (
        (
            authority.code_mapping[0][0],
            authority.code_mapping[0][1],
            "slot-0002",
            authority.code_mapping[0][3],
        ),
        (
            authority.code_mapping[1][0],
            authority.code_mapping[1][1],
            "slot-0001",
            authority.code_mapping[1][3],
        ),
    )
    authority_payload = {
        "task_id": authority.task_id,
        "attempt_hash": authority.attempt_hash,
        "policy_sha256": deepseek.LOCATOR_SLOT_POLICY_SHA256,
        "catalog": tuple(item.model_dump(mode="python") for item in swapped_catalog),
        "field_locator_slots": tuple(
            item.model_dump(mode="python") for item in swapped_rows
        ),
        "code_mapping": swapped_mapping,
    }
    forged = replace(
        authority,
        catalog=swapped_catalog,
        field_locator_slots=swapped_rows,
        code_mapping=swapped_mapping,
        authority_sha256=canonical_hash(
            "schema67-locator-slot-authority.v1", authority_payload
        ),
    )
    monkeypatch.setattr(
        deepseek, "_build_locator_slot_authority", lambda **_kwargs: forged
    )
    transport = _FakeTransport(
        [_unknown_fields_response(tuple(item.field_id for item in exact_prompts))]
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=port,
            field_contracts=exact_prompts,
            locators=exact_locators,
        )

    assert caught.value.reason_code == "LOCATOR_SLOT_AUTHORITY_INVALID"
    assert transport.calls == []


def test_119_multisource_known_output_requires_each_exact_role_slot() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    synthesis = next(
        item
        for item in prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=plan,
            role_inputs=_schema67_role_inputs(contracts, plan),
        )
        if item.task_kind == "synthesis"
    )
    prompt = next(
        item
        for item in synthesis.field_prompts
        if len(tuple((role, refs) for role, refs in item.source_locator_refs if refs)) > 1
    )
    refs = tuple(ref for _role, values in prompt.source_locator_refs for ref in values)
    locators = tuple(
        CanonicalLocatorInputV1(
            locator_ref=ref,
            locator_kind="block",
            page_number=1,
            parent_refs=("page-1",),
            content_snapshot=f"content-{ref}",
            content_snapshot_sha256=_sha(f"content-{ref}"),
        )
        for ref in refs
    )
    port = _FakePort(
        task_id=synthesis.provider_task_sha256,
        attempt_hash=synthesis.provider_attempt_sha256,
        field_ids=(prompt.field_id,),
        expected_locator_refs=refs,
    )
    authority = _slot_authority((prompt,), locators, port=port)
    first_role = authority.field_locator_slots[0].sources[0]
    payload = {
        "fields": [
            {
                "field_id": prompt.field_id,
                "state": "present",
                "value_snapshot": "candidate",
                "evidence": [
                    {
                        "source_role": first_role.source_role,
                        "locator_slot": first_role.allowed_slots[0],
                        "quote_snapshot": next(
                            item.content_snapshot
                            for item in authority.catalog
                            if item.slot == first_role.allowed_slots[0]
                        ),
                    }
                ],
            }
        ]
    }
    with pytest.raises(DeepSeekCompilerError) as caught:
        deepseek._require_extractor_envelope(
            payload, contracts=(prompt,), slot_authority=authority
        )
    assert caught.value.reason_code == "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID"
    assert isinstance(caught.value, deepseek._LocatorMembershipFailure)
    assert caught.value.failed_field_ids == (prompt.field_id,)


@pytest.mark.asyncio
async def test_119_second_shape_invalid_fails_closed_without_third_call() -> None:
    contracts, locators = _inputs()
    sentinel = "RAW_RESPONSE_MUST_NOT_REAPPEAR"
    transport = _FakeTransport(
        [
            _shape_invalid_response(("product_code",), sentinel=sentinel),
            _shape_invalid_response(("product_code",), sentinel="SECOND_RAW_SENTINEL"),
        ]
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )

    assert caught.value.reason_code == "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID"
    assert len(transport.calls) == 2
    assert sentinel not in transport.calls[1][1]
    assert "SECOND_RAW_SENTINEL" not in str(caught.value)


@pytest.mark.asyncio
async def test_119_contract_repair_can_use_the_one_identical_content_retry() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        [
            _shape_invalid_response(("product_code",)),
            "not-json",
            _unknown_fields_response(("product_code",)),
        ]
    )

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )

    assert len(transport.calls) == 3
    assert transport.calls[1] == transport.calls[2]
    assert result.receipt.response_contract_repairs == 1
    assert result.receipt.evidence_repairs == 0
    assert result.receipt.transport_retries == 1
    assert result.receipt.repair_calls == 2
    assert result.receipt.total_calls == 3


@pytest.mark.asyncio
async def test_119_code_owned_authority_failure_never_claims_contract_repair() -> None:
    contracts, locators = _inputs()
    batch = Schema67BatchBudgetV1()

    @dataclass(frozen=True)
    class _CodeAuthorityFailPort(_FakePort):
        def hydrate_extractor_outputs(
            self,
            *,
            selections: tuple[deepseek._ExtractorFieldSelectionV1, ...],
            contracts: tuple[DeepSeekFieldPromptInputV1, ...],
            locators: tuple[CanonicalLocatorInputV1, ...],
        ) -> tuple[FreeformFieldOutputV1, ...]:
            del selections, contracts, locators
            raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")

    transport = _FakeTransport([_unknown_fields_response(("product_code",))])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_CodeAuthorityFailPort(),
            field_contracts=contracts,
            locators=locators,
            batch_budget=batch,
        )

    assert caught.value.reason_code == ("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
    assert len(transport.calls) == 1
    assert batch.response_contract_repairs == 0
    assert batch.evidence_repairs == 0


@pytest.mark.asyncio
async def test_119_response_contract_and_evidence_repairs_share_two_extra_calls() -> None:
    contracts, locators = _inputs()
    batch = Schema67BatchBudgetV1()
    first_transport = _FakeTransport(
        [
            _shape_invalid_response(("product_code",)),
            _unknown_fields_response(("product_code",)),
        ]
    )

    first = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=first_transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
        batch_budget=batch,
    )
    assert first.receipt.response_contract_repairs == 1
    assert batch.response_contract_repairs == 1

    second_transport = _FakeTransport(
        [
            _unknown_fields_response(("product_code",)),
            _extractor_response(attempt_hash="6" * 64),
        ]
    )
    second = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=second_transport,
        port=_FakePort(repair=True),
        field_contracts=contracts,
        locators=locators,
        batch_budget=batch,
    )
    assert second.receipt.evidence_repairs == 1
    assert batch.evidence_repairs == 1
    assert batch.extra_calls == 2
    assert len(second_transport.calls) == 2


@pytest.mark.asyncio
async def test_119_response_contract_then_evidence_repair_retains_both_typed_slots() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        [
            _shape_invalid_response(("product_code",)),
            _unknown_fields_response(("product_code",)),
            _absent_extractor_response("保险责任以条款约定为准。"),
        ]
    )

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(repair=True),
        field_contracts=contracts,
        locators=locators,
    )

    assert len(transport.calls) == 3
    assert result.receipt.total_calls == 3
    assert result.receipt.transport_retries == 0
    assert result.receipt.response_contract_repairs == 1
    assert result.receipt.evidence_repairs == 1
    assert result.response_contract_repair is not None
    assert result.response_contract_repair.kind == "response_contract_repair"
    assert result.response_contract_repair.failed_field_ids == ()
    assert result.response_contract_repair.parent_extractor_request_sha256 == (
        result.receipt.extractor_request_sha256
    )
    assert result.evidence_repair is not None
    assert result.evidence_repair.kind == "evidence_repair"
    assert result.evidence_repair.parent_bound_attempt_hash == (
        result.receipt.initial_bound_attempt_hash
    )
    assert result.receipt.response_contract_repair == result.response_contract_repair
    assert result.receipt.evidence_repair_summary == deepseek._evidence_repair_summary(
        result.evidence_repair
    )
    assert result.receipt.evidence_repair_summary.trace_hash == (
        result.evidence_repair.trace_hash
    )

    private_fragments = (
        "保险责任以条款约定为准。",
        "block-1",
        "slot-0001",
        "/private/input.pdf",
    )
    receipt_wire = json.dumps(
        result.receipt.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )
    assert all(fragment not in receipt_wire for fragment in private_fragments)

    impossible = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    impossible.update(
        {
            "extractor_calls": 2,
            "repair_calls": 1,
            "transport_retries": 0,
            "response_contract_repairs": 1,
            "evidence_repairs": 1,
            "total_calls": 3,
        }
    )
    with pytest.raises(ValueError, match="deepseek_execution_budget_mismatch"):
        deepseek.DeepSeekExecutionReceiptV1.model_validate(
            {
                **impossible,
                "receipt_hash": canonical_hash(
                    "deepseek-evidence-compiler-596-1.v2", impossible
                ),
            }
        )

    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(result, response_contract_repair=None)
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(result, evidence_repair=None)
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(
            result,
            response_contract_repair=result.response_contract_repair.model_copy(
                update={"resolution_hash": "f" * 64}
            ),
        )
    forged_response_repair = result.response_contract_repair.model_copy(
        update={"resolution_hash": "f" * 64}
    )
    forged_receipt_payload = result.receipt.model_dump(
        mode="python", exclude={"receipt_hash"}
    )
    forged_receipt_payload["response_contract_repair"] = (
        forged_response_repair.model_dump(mode="python")
    )
    forged_receipt = result.receipt.model_copy(
        update={
            "response_contract_repair": forged_response_repair,
            "receipt_hash": canonical_hash(
                "deepseek-evidence-compiler-596-1.v2", forged_receipt_payload
            ),
        }
    )
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(
            result,
            response_contract_repair=forged_response_repair,
            receipt=forged_receipt,
        )
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(
            result,
            evidence_repair=result.evidence_repair.model_copy(
                update={"trace_hash": "f" * 64}
            ),
        )
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(
            result,
            receipt=result.receipt.model_copy(
                update={
                    "evidence_repair_summary": (
                        result.receipt.evidence_repair_summary.model_copy(
                            update={"trace_hash": "f" * 64}
                        )
                    )
                }
            ),
        )
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(
            result,
            receipt=result.receipt.model_copy(
                update={
                    "evidence_repair_summary": (
                        result.receipt.evidence_repair_summary.model_copy(
                            update={"summary_hash": "f" * 64}
                        )
                    )
                }
            ),
        )


@pytest.mark.asyncio
async def test_119_retry_plus_contract_repair_blocks_third_extra_before_transport() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        [
            "not-json",
            _shape_invalid_response(("product_code",)),
            _unknown_fields_response(("product_code",)),
            _extractor_response(attempt_hash="6" * 64),
        ]
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(repair=True),
            field_contracts=contracts,
            locators=locators,
        )

    assert caught.value.reason_code == "BATCH_EXTRA_CALL_BUDGET_EXHAUSTED"
    assert len(transport.calls) == 3


def test_119_fixed_dual_budget_rejects_duplicate_kind_before_any_call() -> None:
    response_budget = Schema67BatchBudgetV1()
    response_budget.claim_repair("response_contract")
    with pytest.raises(DeepSeekCompilerError) as caught:
        response_budget.claim_repair("response_contract")
    assert caught.value.reason_code == "BATCH_RESPONSE_CONTRACT_REPAIR_EXHAUSTED"
    assert response_budget.extractor_calls + response_budget.repair_calls == 0

    evidence_budget = Schema67BatchBudgetV1()
    evidence_budget.claim_repair("evidence")
    with pytest.raises(DeepSeekCompilerError) as caught:
        evidence_budget.claim_repair("evidence")
    assert caught.value.reason_code == "BATCH_EVIDENCE_REPAIR_EXHAUSTED"
    assert evidence_budget.extractor_calls + evidence_budget.repair_calls == 0


@pytest.mark.asyncio
async def test_119_batch_allows_only_one_retry_and_one_repair() -> None:
    contracts, locators = _inputs()
    batch = Schema67BatchBudgetV1()
    first = _FakeTransport(
        [
            "not-json",
            _extractor_response(),
            _extractor_response(attempt_hash="6" * 64),
        ]
    )
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=first,
        port=_FakePort(repair=True),
        field_contracts=contracts,
        locators=locators,
        batch_budget=batch,
    )
    assert result.receipt.transport_retries == 1
    assert result.receipt.response_contract_repairs == 0
    assert result.receipt.evidence_repairs == 1
    assert result.receipt.repair_calls == 1

    second_retry = _FakeTransport(["not-json"])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=second_retry,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
            batch_budget=batch,
        )
    assert caught.value.reason_code == "BATCH_TRANSPORT_RETRY_EXHAUSTED"
    assert len(second_retry.calls) == 1

    second_repair = _FakeTransport([_extractor_response()])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=second_repair,
            port=_FakePort(repair=True),
            field_contracts=contracts,
            locators=locators,
            batch_budget=batch,
        )
    assert caught.value.reason_code == "BATCH_EVIDENCE_REPAIR_EXHAUSTED"
    assert len(second_repair.calls) == 1


@pytest.mark.asyncio
async def test_119_complete_eight_task_fake_batch_has_bounded_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )
    outputs: list[str] = []
    ports: list[_FakePort] = []
    locator_groups = []
    for item in prepared:
        locator_refs = tuple(
            ref for prompt in item.field_prompts for ref in prompt.allowed_locator_refs
        )
        locators = tuple(
            CanonicalLocatorInputV1(
                locator_ref=ref,
                locator_kind="block",
                page_number=1,
                parent_refs=("page-1",),
                content_snapshot=f"content-{ref}",
                content_snapshot_sha256=_sha(f"content-{ref}"),
            )
            for ref in locator_refs
        )
        extractor_response = json.dumps(
            {
                "fields": [
                    {
                        "field_id": prompt.field_id,
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                    for prompt in item.field_prompts
                ],
            },
            separators=(",", ":"),
        )
        outputs.append(extractor_response)
        ports.append(
            _FakePort(
                task_id=item.provider_task_sha256,
                attempt_hash=item.provider_attempt_sha256,
                field_ids=tuple(prompt.field_id for prompt in item.field_prompts),
                expected_locator_refs=locator_refs,
                repair=len(ports) == 2,
            )
        )
        locator_groups.append(locators)
    monkeypatch.setattr(deepseek, "_schema67_binding_ports", lambda **_: tuple(ports))
    orchestrated_budget = Schema67BatchBudgetV1()
    monkeypatch.setattr(deepseek, "Schema67BatchBudgetV1", lambda: orchestrated_budget)
    third_field_ids = tuple(
        prompt.field_id for prompt in prepared[2].field_prompts
    )
    transport = _FakeTransport(
        [
            *outputs[:2],
            _shape_invalid_response(third_field_ids),
            _unknown_fields_response(third_field_ids),
            _unknown_fields_response((third_field_ids[0],)),
            *outputs[3:],
        ]
    )
    result = await _run_schema67_deepseek_batch(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
        admitted_sources=(),
        locators_by_task=tuple(locator_groups),
    )
    receipt = result.receipt
    assert receipt.task_count == 8
    assert plan.batch_budget.max_provider_calls == 10
    assert receipt.locator_calls == 0
    assert receipt.extractor_calls == 8
    assert receipt.provider_calls == 10
    assert receipt.transport_retries == 0
    assert receipt.response_contract_repairs == 1
    assert receipt.evidence_repairs == 1
    assert receipt.repair_calls == 2
    assert receipt.prior_provider_calls is None
    assert receipt.cumulative_provider_calls is None
    assert receipt.batch_receipt_sha256 == canonical_hash(
        "schema67-deepseek-batch-receipt.v2",
        receipt.model_dump(mode="python", exclude={"batch_receipt_sha256"}),
    )
    assert result.executions[2].response_contract_repair is not None
    assert result.executions[2].evidence_repair is not None
    assert result.executions[2].response_contract_repair.failure_code == "FIELD_ITEM_SHAPE"
    assert len(transport.calls) == 10
    all_raw_refs = {
        locator.locator_ref for group in locator_groups for locator in group
    }

    def strings(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, dict):
            return tuple(
                item
                for key, nested in value.items()
                for item in (key, *strings(nested))
            )
        if isinstance(value, list):
            return tuple(item for nested in value for item in strings(nested))
        return ()

    for _system, user in transport.calls:
        payload = json.loads(user)
        assert user.count('"locator_slot_catalog"') == 1
        assert user.count('"field_locator_slots"') == 1
        assert "locator_ref" not in strings(payload)
        assert all_raw_refs.isdisjoint(strings(payload))
        slots = [item["slot"] for item in payload["locator_slot_catalog"]]
        assert len(slots) == len(set(slots))
    exact_request_bodies = tuple(
        deepseek._deepseek_request_bytes(system=system, user=user)
        for system, user in transport.calls
    )
    assert all(
        json.loads(body)["response_format"] == {"type": "json_object"}
        for body in exact_request_bodies
    )
    assert max(len(body) for body in exact_request_bodies) < 131072
    exact_budget = Schema67BatchBudgetV1(
        task_count=8,
        extractor_calls=8,
        response_contract_repairs=1,
        evidence_repairs=1,
        repair_calls=2,
    )
    with pytest.raises(DeepSeekCompilerError) as caught:
        build_schema67_batch_receipt(
            execution_plan=plan,
            prepared_tasks=prepared,
            budget=exact_budget,
            executions=tuple(reversed(result.executions)),
        )
    assert caught.value.reason_code == "BATCH_EXECUTION_RECEIPT_INVALID"

    exact_budget.locator_calls = 1
    with pytest.raises(DeepSeekCompilerError) as caught:
        build_schema67_batch_receipt(
            execution_plan=plan,
            prepared_tasks=prepared,
            budget=exact_budget,
            executions=result.executions,
        )
    assert caught.value.reason_code == "BATCH_EXECUTION_RECEIPT_INVALID"
    exact_budget.locator_calls = 0

    ninth_contracts, ninth_locators = _inputs()
    ninth_transport = _FakeTransport([])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=ninth_transport,
            port=_FakePort(),
            field_contracts=ninth_contracts,
            locators=ninth_locators,
            batch_budget=exact_budget,
        )
    assert caught.value.reason_code == "BATCH_MAIN_TASK_BUDGET_EXHAUSTED"
    assert ninth_transport.calls == []

    # The provider-call ceiling comes from the completed eight-task orchestration,
    # not from a hand-seeded 9/10 counter. Isolate it from the separate task-count
    # gate and prove the next call is rejected before transport.
    assert orchestrated_budget.extractor_calls + orchestrated_budget.repair_calls == 10
    orchestrated_budget.task_count = 7
    eleventh_transport = _FakeTransport([_extractor_response()])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=eleventh_transport,
            port=_FakePort(),
            field_contracts=ninth_contracts,
            locators=ninth_locators,
            batch_budget=orchestrated_budget,
        )
    assert caught.value.reason_code == "BATCH_PROVIDER_CALL_BUDGET_EXHAUSTED"
    assert eleventh_transport.calls == []


@pytest.mark.asyncio
async def test_119_missing_synthesis_source_forces_unknown_review() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    inputs = list(_schema67_role_inputs(contracts, plan))
    synthesis_key = next(
        item.task_key for item in plan.task_slices if item.task_kind == "synthesis"
    )
    rate_index = next(
        index
        for index, item in enumerate(inputs)
        if item.task_key == synthesis_key and item.material_role == "rate_table"
    )
    rate_input = inputs[rate_index]
    missing_field = rate_input.allowed_locator_refs[0][0]
    inputs[rate_index] = replace(
        rate_input,
        allowed_locator_refs=tuple(
            (field_id, () if field_id == missing_field else refs)
            for field_id, refs in rate_input.allowed_locator_refs
        ),
    )
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=tuple(inputs),
    )
    synthesis = next(item for item in prepared if item.task_key == synthesis_key)
    prompt = next(item for item in synthesis.field_prompts if item.field_id == missing_field)
    assert prompt.requires_unknown_review is True

    locator_refs = tuple(
        ref for item in synthesis.field_prompts for ref in item.allowed_locator_refs
    )
    locators = tuple(
        CanonicalLocatorInputV1(
            locator_ref=ref,
            locator_kind="block",
            page_number=1,
            parent_refs=("page-1",),
            content_snapshot=f"content-{ref}",
            content_snapshot_sha256=_sha(f"content-{ref}"),
        )
        for ref in locator_refs
    )
    extractor_response = json.dumps(
        {
            "fields": [
                {
                    "field_id": item.field_id,
                    "state": "present" if item.field_id == missing_field else "unknown",
                    "value_snapshot": "forged" if item.field_id == missing_field else None,
                    "evidence": (
                        [
                            {
                                "locator_ref": "forged-block",
                                "quote_snapshot": "forged",
                            }
                        ]
                        if item.field_id == missing_field
                        else []
                    ),
                }
                for item in synthesis.field_prompts
            ],
        }
    )
    transport = _FakeTransport([extractor_response, extractor_response])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(
                task_id=synthesis.provider_task_sha256,
                attempt_hash=synthesis.provider_attempt_sha256,
                field_ids=tuple(item.field_id for item in synthesis.field_prompts),
                expected_locator_refs=locator_refs,
            ),
            field_contracts=synthesis.field_prompts,
            locators=locators,
        )
    assert caught.value.reason_code == "EXTRACTOR_FORCED_UNKNOWN_INVALID"
    prompt_payload = json.loads(transport.calls[0][1])
    assert prompt_payload["response_contract"]["forced_unknown_field_ids"] == [missing_field]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_response", "reason_code"),
    ((" ", "MODEL_CONTENT_EMPTY"), ("RAW_PRIVATE_SENTINEL{", "MODEL_JSON_INVALID")),
)
async def test_119_decode_failure_after_identical_retry_gets_one_contract_repair(
    invalid_response: str,
    reason_code: str,
) -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        [invalid_response, invalid_response, _unknown_fields_response(("product_code",))]
    )

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )

    assert len(transport.calls) == 3
    assert transport.calls[0] == transport.calls[1]
    assert transport.calls[2] != transport.calls[1]
    repair_payload = json.loads(transport.calls[2][1])
    assert repair_payload["repair_kind"] == "response_contract"
    assert repair_payload["reason_code"] == reason_code
    assert repair_payload["parent_extractor_request_sha256"] == (
        result.receipt.extractor_request_sha256
    )
    assert repair_payload["invalid_response_sha256"] == _sha(invalid_response)
    if invalid_response.strip():
        assert invalid_response not in transport.calls[2][1]
        assert invalid_response not in json.dumps(
            result.receipt.model_dump(mode="json"), sort_keys=True
        )
    assert result.response_contract_repair is not None
    assert result.response_contract_repair.failure_code == reason_code
    assert result.response_contract_repair.invalid_response_sha256 == _sha(invalid_response)
    assert result.receipt.response_contract_repairs == 1
    assert result.receipt.evidence_repairs == 0
    assert result.receipt.transport_retries == 1
    assert result.receipt.extractor_calls == 2
    assert result.receipt.repair_calls == 1
    assert result.receipt.total_calls == 3

    forged = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    assert isinstance(forged["response_contract_repair"], dict)
    forged["response_contract_repair"]["invalid_response_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="response_contract_repair_resolution_invalid"):
        deepseek.DeepSeekExecutionReceiptV1.model_validate(
            {
                **forged,
                "receipt_hash": canonical_hash(
                    "deepseek-evidence-compiler-596-1.v2", forged
                ),
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("repair_response", "reason_code"),
    ((" ", "MODEL_CONTENT_EMPTY"), ("not-json", "MODEL_JSON_INVALID")),
)
async def test_119_decode_contract_repair_failure_stops_without_fourth_call(
    repair_response: str,
    reason_code: str,
) -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(["not-json", "not-json", repair_response])

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )

    assert caught.value.reason_code == reason_code
    assert len(transport.calls) == 3
    assert transport.calls[0] == transport.calls[1]
    assert transport.calls[2] != transport.calls[1]
    assert "not-json" not in transport.calls[2][1]


@pytest.mark.asyncio
async def test_119_decode_contract_repair_parseable_failure_stops_without_fourth_call() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        ["not-json", "not-json", _shape_invalid_response(("product_code",))]
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )

    assert caught.value.reason_code == "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID"
    assert len(transport.calls) == 3
    assert transport.calls[0] == transport.calls[1]


@pytest.mark.asyncio
async def test_119_decode_repair_receipt_requires_exact_retry_history() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        ["not-json", "not-json", _unknown_fields_response(("product_code",))]
    )
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )
    forged = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    forged.update(
        {
            "extractor_calls": 1,
            "repair_calls": 1,
            "transport_retries": 0,
            "response_contract_repairs": 1,
            "evidence_repairs": 0,
            "total_calls": 2,
        }
    )

    with pytest.raises(ValueError, match="deepseek_decode_repair_history_mismatch"):
        deepseek.DeepSeekExecutionReceiptV1.model_validate(
            {
                **forged,
                "receipt_hash": canonical_hash(
                    "deepseek-evidence-compiler-596-1.v2", forged
                ),
            }
        )


@pytest.mark.asyncio
async def test_119_empty_content_gets_one_identical_retry_only() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport([" ", _extractor_response()])

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )

    assert result.receipt.total_calls == 2
    assert result.receipt.locator_calls == 0
    assert result.receipt.transport_retries == 1
    assert transport.calls[0] == transport.calls[1]


@pytest.mark.asyncio
async def test_119_deterministic_selection_custody_changes_with_locator_authority() -> None:
    contracts, locators = _inputs()
    first_transport = _FakeTransport([_extractor_response()])
    first = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=first_transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
    )
    changed_content = "保险责任以变更后的条款原文为准。"
    changed_locators = (
        locators[0].model_copy(
            update={
                "content_snapshot": changed_content,
                "content_snapshot_sha256": _sha(changed_content),
            }
        ),
    )
    second_transport = _FakeTransport([_extractor_response()])
    second = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=second_transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=changed_locators,
    )

    assert first.receipt.locator_selection_policy_sha256 == (
        second.receipt.locator_selection_policy_sha256
    )
    assert first.receipt.locator_authority_sha256 != second.receipt.locator_authority_sha256
    assert first.receipt.locator_selection_sha256 != second.receipt.locator_selection_sha256
    assert len(first_transport.calls) == len(second_transport.calls) == 1
    assert not hasattr(deepseek, "_parse_locator_selection")


@pytest.mark.asyncio
async def test_119_targeted_repair_is_extractor_only_and_hard_cap_three() -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport(
        [
            "not-json",
            _extractor_response(),
            _absent_extractor_response("本合同为不保证续保合同。", attempt_hash="6" * 64),
        ]
    )

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_FakePort(repair=True),
        field_contracts=contracts,
        locators=locators,
    )

    assert result.evidence_repair is not None
    assert result.initial_outputs[0].state == "unknown"
    assert result.final_outputs[0].state == "absent_explicitly"
    assert result.receipt.initial_outputs_sha256 != result.receipt.final_outputs_sha256
    with pytest.raises(ValueError, match="deepseek_task_execution_custody_mismatch"):
        replace(result, final_outputs=result.initial_outputs)
    assert result.receipt.total_calls == 3
    assert result.receipt.locator_calls == 0
    assert result.receipt.extractor_calls == 2
    assert result.receipt.transport_retries == 1
    assert result.receipt.response_contract_repairs == 0
    assert result.receipt.evidence_repairs == 1
    assert all("deepseek locator" not in call[0].casefold() for call in transport.calls)
    assert all("extractor" in call[0].casefold() for call in transport.calls)

    receipt_values = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values["model_identity"] = result.receipt.model_identity.model_copy(
        update={"deployment_id": "other-model"}
    ).model_dump(mode="python")
    with pytest.raises(ValueError):
        type(result.receipt).model_validate(
            {
                **receipt_values,
                "receipt_hash": canonical_hash(
                    "deepseek-evidence-compiler-596-1.v2", receipt_values
                ),
            }
        )


@pytest.mark.asyncio
async def test_119_transport_error_is_typed_and_does_not_echo_sensitive_data() -> None:
    contracts, locators = _inputs()
    sentinel = "Bearer secret-at-private-path /Users/alice/input.pdf https://private"
    transport = _FakeTransport([RuntimeError(sentinel)])

    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
        )

    assert caught.value.reason_code == "MODEL_TRANSPORT_FAILED"
    assert sentinel not in str(caught.value)
    assert len(transport.calls) == 1


def test_119_rejects_same_document_locator_owned_by_another_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, _locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(
        prepared=prepared,
        admitted_sources=(admitted,),
    )
    target, foreign = prepared.field_prompts[:2]
    foreign_ref = foreign.allowed_locator_refs[0]
    quote = f"content-{foreign_ref}"
    fields: list[dict[str, object]] = [
        {
            "product_version_id": "596-1",
            "field_id": prompt.field_id,
            "state": "unknown",
            "value_snapshot": None,
            "evidence": [],
        }
        for prompt in prepared.field_prompts
    ]
    fields[0] = {
        "product_version_id": "596-1",
        "field_id": target.field_id,
        "state": "present",
        "value_snapshot": quote,
        "evidence": [
            {
                "field_id": target.field_id,
                "source_sha256": admitted.source_sha256,
                "source_revision_id": admitted.document.subject.source_revision_id,
                "parse_attempt_id": admitted.document.attempt.attempt_id,
                "parsed_document_hash": admitted.document.document_hash,
                "parse_manifest_hash": admitted.manifest.manifest_hash,
                "page_number": 1,
                "block_id": foreign_ref,
                "locator": {
                    "subject_type": "block",
                    "subject_ref": foreign_ref,
                    "page_number": 1,
                    "parent_refs": [f"page-{admitted.role}"],
                    "content_snapshot": quote,
                    "content_snapshot_sha256": _sha(quote),
                },
                "quote_snapshot": quote,
                "quote_snapshot_sha256": _sha(quote),
            }
        ],
    }
    response = json.dumps({"fields": fields}, separators=(",", ":")).encode()
    calls = {"hydrate": 0, "bind": 0, "verify": 0}

    def forbidden_hydrate(*_args: object, **_kwargs: object) -> object:
        calls["hydrate"] += 1
        raise AssertionError("custody hydration must not run")

    def forbidden_bind(*_args: object, **_kwargs: object) -> object:
        calls["bind"] += 1
        raise AssertionError("057 binding must not run")

    def forbidden_verify(*_args: object, **_kwargs: object) -> object:
        calls["verify"] += 1
        raise AssertionError("057 verification must not run")

    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "hydrate_extractor_outputs",
        forbidden_hydrate,
    )
    monkeypatch.setattr(deepseek, "bind_freeform_arm_evidence", forbidden_bind)
    monkeypatch.setattr(
        evidence_verifier_module,
        "verify_evidence_batch",
        forbidden_verify,
    )

    with pytest.raises(DeepSeekCompilerError) as caught:
        port.bind_initial(response)

    assert caught.value.reason_code == "EVIDENCE_BINDING_FAILED"
    assert calls == {"hydrate": 0, "bind": 0, "verify": 0}


@pytest.mark.asyncio
async def test_119_model_returns_only_semantic_fields_and_code_hydrates_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(
        prepared=prepared,
        admitted_sources=(admitted,),
    )
    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "prepare_repair",
        lambda *_args, **_kwargs: None,
    )
    first_prompt = prepared.field_prompts[0]
    first_locator_ref = first_prompt.allowed_locator_refs[0]
    first_quote = f"content-{first_locator_ref}"
    response_fields: list[dict[str, object]] = [
        {
            "field_id": prompt.field_id,
            "state": "unknown",
            "value_snapshot": None,
            "evidence": [],
        }
        for prompt in prepared.field_prompts
    ]
    class _ExactSlotTransport(_FakeTransport):
        async def complete(self, system: str, user: str) -> str:
            self.calls.append((system, user))
            payload = json.loads(user)
            field_row = next(
                item
                for item in payload["field_locator_slots"]
                if item["field_id"] == first_prompt.field_id
            )
            source = field_row["sources"][0]
            response_fields[0] = {
                "field_id": first_prompt.field_id,
                "state": "present",
                "value_snapshot": first_quote,
                "evidence": [
                    {
                        "source_role": source["source_role"],
                        "locator_slot": source["allowed_slots"][0],
                        "quote_snapshot": first_quote,
                    }
                ],
            }
            return json.dumps({"fields": response_fields}, separators=(",", ":"))

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=_ExactSlotTransport(()),
        port=port,
        field_contracts=prepared.field_prompts,
        locators=locators,
    )

    assert tuple(item.product_version_id for item in result.final_outputs) == ("596-1",) * len(
        prepared.field_prompts
    )
    hydrated = result.final_outputs[0].evidence[0]
    exact_locator = next(item for item in locators if item.locator_ref == first_locator_ref)
    assert hydrated.field_id == first_prompt.field_id
    assert hydrated.source_sha256 == admitted.document.subject.source_sha256
    assert hydrated.source_revision_id == admitted.document.subject.source_revision_id
    assert hydrated.parse_attempt_id == admitted.document.attempt.attempt_id
    assert hydrated.parsed_document_hash == admitted.document.document_hash
    assert hydrated.parse_manifest_hash == admitted.manifest.manifest_hash
    assert hydrated.page_number == exact_locator.page_number
    assert hydrated.locator.subject_ref == exact_locator.locator_ref
    assert hydrated.locator.parent_refs == exact_locator.parent_refs
    assert hydrated.locator.content_snapshot_sha256 == exact_locator.content_snapshot_sha256


@pytest.mark.asyncio
async def test_119_model_cannot_self_attest_evidence_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(
        prepared=prepared,
        admitted_sources=(admitted,),
    )
    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "prepare_repair",
        lambda *_args, **_kwargs: None,
    )
    calls = {"hydrate": 0, "bind": 0, "verify": 0}

    def forbidden_hydrate(*_args: object, **_kwargs: object) -> object:
        calls["hydrate"] += 1
        raise AssertionError("custody hydration must not run")

    def forbidden_bind(*_args: object, **_kwargs: object) -> object:
        calls["bind"] += 1
        raise AssertionError("057 binding must not run")

    def forbidden_verify(*_args: object, **_kwargs: object) -> object:
        calls["verify"] += 1
        raise AssertionError("057 verification must not run")

    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "hydrate_extractor_outputs",
        forbidden_hydrate,
    )
    monkeypatch.setattr(deepseek, "bind_freeform_arm_evidence", forbidden_bind)
    monkeypatch.setattr(
        evidence_verifier_module,
        "verify_evidence_batch",
        forbidden_verify,
    )
    first = prepared.field_prompts[0]
    locator_ref = first.allowed_locator_refs[0]
    base_fields: list[dict[str, object]] = [
        {
            "field_id": prompt.field_id,
            "state": "unknown",
            "value_snapshot": None,
            "evidence": [],
        }
        for prompt in prepared.field_prompts
    ]
    top_level_custody = {
        "task_id": prepared.provider_task_sha256,
        "attempt_hash": prepared.provider_attempt_sha256,
        "arm_blueprint_hash": prepared.task_slice_sha256,
        "model_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
    }
    mutations: list[dict[str, object]] = [
        {**top_level_custody, "fields": base_fields},
    ]
    for key, value in (
        ("product_version_id", "596-1"),
        ("source_sha256", admitted.source_sha256),
        ("source_revision_id", admitted.document.subject.source_revision_id),
        ("parse_attempt_id", admitted.document.attempt.attempt_id),
        ("parsed_document_hash", admitted.document.document_hash),
        ("parse_manifest_hash", admitted.manifest.manifest_hash),
        ("page_number", 1),
        ("parent_refs", ["page-terms"]),
        ("content_snapshot_sha256", "c" * 64),
    ):
        field_values = [dict(item) for item in base_fields]
        field_values[0] = {
            "field_id": first.field_id,
            "state": "present",
            "value_snapshot": "candidate",
            "evidence": [
                {
                    "locator_ref": locator_ref,
                    "quote_snapshot": f"content-{locator_ref}",
                    key: value,
                }
            ],
        }
        mutations.append({"fields": field_values})

    for payload in mutations:
        with pytest.raises(DeepSeekCompilerError) as caught:
            await _run_deepseek_task(
                profile=_profile(),
                policy=_policy(),
                transport=_FakeTransport(
                    [
                        json.dumps(payload, separators=(",", ":")),
                        json.dumps(payload, separators=(",", ":")),
                    ]
                ),
                port=port,
                field_contracts=prepared.field_prompts,
                locators=locators,
            )
        assert caught.value.reason_code in {
            "EXTRACTOR_TOP_LEVEL_SHAPE_INVALID",
            "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID",
        }
    assert calls == {"hydrate": 0, "bind": 0, "verify": 0}


@pytest.mark.asyncio
async def test_119_rate_table_block_locators_cannot_authorize_known_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    role_inputs = _schema67_role_inputs(contracts, plan)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=role_inputs,
    )
    selected = tuple(
        next(
            item
            for item in prepared
            if item.task_kind == "material" and item.source_tasks[0].material_role == role
        )
        for role in ("terms", "brochure", "rate_table")
    )
    built = tuple(_admitted_source_for_prepared(item) for item in selected)

    class ResolutionAdapter:
        def __init__(self, task: Schema67PreparedTaskV1) -> None:
            profile = task.source_tasks[0].task_profile
            self.profile = profile.material_profile
            self.binding_hash = profile.material_profile_binding_hash
            self.parse_policy_receipt = profile.parse_policy_receipt
            self.resolved_template = SimpleNamespace(
                content_hash=task.source_tasks[0].input_refs.resolved_template.artifact_hash
            )

        def model_dump(self, **_kwargs: object) -> ResolutionAdapter:
            return self

        @classmethod
        def model_validate(cls, value: object) -> ResolutionAdapter:
            assert isinstance(value, cls)
            return value

    monkeypatch.setattr(deepseek, "MaterialProfileResolution", ResolutionAdapter)
    admitted = tuple(
        replace(
            source,
            material_profile_resolution=cast(MaterialProfileResolution, ResolutionAdapter(task)),
            capture_identity_sha256=_sha(f"capture-{source.role}"),
            content_snapshot_sha256=_sha(
                "\n".join(locator.content_snapshot for locator in locators)
            ),
            raw_structure_sha256=_sha(f"raw-{source.role}"),
            sanitized_structure_sha256=_sha(f"sanitized-{source.role}"),
        )
        for task, source, locators in built
    )
    locators_by_role = {source.role: locators for (_task, source, locators) in built}
    captures = tuple(
        Schema67CapturedContentV1(
            role=source.role,
            source_sha256=source.source_sha256,
            capture_identity_sha256=source.capture_identity_sha256 or "",
            raw_structure_sha256=source.raw_structure_sha256 or "",
            sanitized_structure_sha256=source.sanitized_structure_sha256 or "",
            content_snapshot="\n".join(
                locator.content_snapshot for locator in locators_by_role[source.role]
            ),
            content_snapshot_sha256=source.content_snapshot_sha256 or "",
        )
        for source in admitted
    )
    recovered_roles: list[str] = []

    def recover(
        *, admitted_source: AdmittedParseArtifactV1, content_snapshot: str
    ) -> tuple[CanonicalLocatorInputV1, ...]:
        assert content_snapshot
        recovered_roles.append(admitted_source.role)
        return locators_by_role[admitted_source.role]

    monkeypatch.setattr(deepseek, "_relation_admitted_sources", lambda _value: admitted)
    monkeypatch.setattr(deepseek, "recover_exact_mineru_block_locators", recover)

    result = prepare_schema67_real_execution_inputs(
        field_contracts=contracts,
        execution_plan=plan,
        relation_admission=object(),  # type: ignore[arg-type]
        captured_contents=captures,
    )

    assert recovered_roles == ["terms", "brochure"]
    rate_inputs = tuple(item for item in result.role_inputs if item.material_role == "rate_table")
    assert rate_inputs
    assert all(not refs for item in rate_inputs for _field_id, refs in item.allowed_locator_refs)
    prepared_again = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=result.role_inputs,
    )
    assert all(
        prompt.requires_unknown_review
        for task in prepared_again
        for prompt in task.field_prompts
        if "rate_table" in prompt.contract.source_roles
    )
    rate_task = next(
        task
        for task in prepared_again
        if task.task_kind == "material" and task.source_tasks[0].material_role == "rate_table"
    )
    rate_source = next(item for item in admitted if item.role == "rate_table")
    rate_port = _Schema67EvidenceBindingPort(
        prepared=rate_task,
        admitted_sources=(rate_source,),
    )
    calls = {"hydrate": 0, "bind": 0, "verify": 0}

    def forbidden_hydrate(*_args: object, **_kwargs: object) -> object:
        calls["hydrate"] += 1
        raise AssertionError("custody hydration must not run")

    def forbidden_bind(*_args: object, **_kwargs: object) -> object:
        calls["bind"] += 1
        raise AssertionError("057 binding must not run")

    def forbidden_verify(*_args: object, **_kwargs: object) -> object:
        calls["verify"] += 1
        raise AssertionError("057 verification must not run")

    monkeypatch.setattr(
        deepseek._Schema67EvidenceBindingPort,
        "hydrate_extractor_outputs",
        forbidden_hydrate,
    )
    monkeypatch.setattr(deepseek, "bind_freeform_arm_evidence", forbidden_bind)
    monkeypatch.setattr(
        evidence_verifier_module,
        "verify_evidence_batch",
        forbidden_verify,
    )
    for state in ("present", "absent_explicitly"):
        model_fields: list[dict[str, object]] = [
            {
                "field_id": prompt.field_id,
                "state": "unknown",
                "value_snapshot": None,
                "evidence": [],
            }
            for prompt in rate_task.field_prompts
        ]
        model_fields[0] = {
            "field_id": rate_task.field_prompts[0].field_id,
            "state": state,
            "value_snapshot": "forged-known-value",
            "evidence": [
                {
                    "locator_ref": "forged-block",
                    "quote_snapshot": "forged-known-value",
                }
            ],
        }
        with pytest.raises(DeepSeekCompilerError) as caught:
            await _run_deepseek_task(
                profile=_profile(),
                policy=_policy(),
                transport=_FakeTransport(
                    [
                        json.dumps({"fields": model_fields}, separators=(",", ":")),
                        json.dumps({"fields": model_fields}, separators=(",", ":")),
                    ]
                ),
                port=rate_port,
                field_contracts=rate_task.field_prompts,
                locators=(),
            )
        assert caught.value.reason_code == "EXTRACTOR_FORCED_UNKNOWN_INVALID"
    assert calls == {"hydrate": 0, "bind": 0, "verify": 0}


def test_119_locator_policy_and_provider_identity_bind_complete_authority() -> None:
    policy_payload = {
        "algorithm_version": "schema67-contract-lexical-locator-v2",
        "source": "field-contract-plus-mineru-locators",
        "contract_terms": ("field_name", "description", "category"),
        "normalization": "str.casefold",
        "unicode_sequence_regex": r"[\u3400-\u9fff]+",
        "whole_sequence_min_chars": 2,
        "whole_sequence_max_chars": 12,
        "ngram_widths": (2, 3, 4),
        "ascii_token_regex": r"[a-z0-9_]{3,}",
        "stoplist": (
            "产品",
            "信息",
            "内容",
            "相关",
            "情况",
            "是否",
            "说明",
            "要求",
            "规则",
            "保险",
        ),
        "score": ("term_length_squared", "field_name_exact_bonus:100"),
        "tie_break": ("score_desc", "input_ordinal_asc"),
        "input_order": "mineru_canonical_ordinal",
        "output_order": "locator_ref_lexicographic",
        "all_locators_threshold": 24,
        "ranked_match_limit": 8,
        "neighbor_offsets": (-1, 0, 1),
        "fallback_max_content_chars": 40,
        "fallback_max_locators": 24,
        "golden_reads": 0,
        "model_calls": 0,
    }
    expected_policy = canonical_hash(
        "schema67-deterministic-locator-selection-policy.v1",
        policy_payload,
    )
    assert deepseek.LOCATOR_SELECTION_POLICY_SHA256 == expected_policy
    for key, mutation_value in (
        ("normalization", "identity"),
        ("whole_sequence_min_chars", 1),
        ("whole_sequence_max_chars", 13),
    ):
        assert (
            canonical_hash(
                "schema67-deterministic-locator-selection-policy.v1",
                {**policy_payload, key: mutation_value},
            )
            != deepseek.LOCATOR_SELECTION_POLICY_SHA256
        )

    contracts, locators = _inputs()
    selection_a = deepseek._deterministic_locator_selection(
        port=_FakePort(),
        contracts=contracts,
        locators=locators,
    )
    extra = CanonicalLocatorInputV1(
        locator_ref="block-2",
        locator_kind="block",
        page_number=1,
        parent_refs=("page-1",),
        content_snapshot="第二个原始块",
        content_snapshot_sha256=_sha("第二个原始块"),
    )
    selection_b = deepseek._deterministic_locator_selection(
        port=_FakePort(expected_locator_refs=("block-2", "block-1")),
        contracts=contracts,
        locators=(extra, *locators),
    )
    selection_c = deepseek._deterministic_locator_selection(
        port=_FakePort(expected_locator_refs=("block-1", "block-2")),
        contracts=contracts,
        locators=(*locators, extra),
    )
    assert selection_a[0] == selection_b[0] == selection_c[0]
    assert selection_b[1] != selection_c[1]

    contract_set = _schema67_contract_set()
    plan = _execution_plan(contract_set)
    role_inputs = list(_schema67_role_inputs(contract_set, plan))
    original = prepare_schema67_deepseek_tasks(
        field_contracts=contract_set,
        execution_plan=plan,
        role_inputs=tuple(role_inputs),
    )
    first = role_inputs[0]
    field_id, _refs = first.allowed_locator_refs[0]
    role_inputs[0] = replace(
        first,
        allowed_locator_refs=(
            (field_id, ("different-exact-ref",)),
            *first.allowed_locator_refs[1:],
        ),
    )
    changed = prepare_schema67_deepseek_tasks(
        field_contracts=contract_set,
        execution_plan=plan,
        role_inputs=tuple(role_inputs),
    )
    assert original[0].provider_task_sha256 != changed[0].provider_task_sha256
    assert original[0].provider_attempt_sha256 != changed[0].provider_attempt_sha256


@pytest.mark.asyncio
async def test_119_exact_tenth_call_allowed_and_eleventh_blocked_pretransport() -> None:
    contracts, locators = _inputs()
    tenth_budget = Schema67BatchBudgetV1(extractor_calls=9)
    tenth_transport = _FakeTransport([_extractor_response()])
    await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=tenth_transport,
        port=_FakePort(),
        field_contracts=contracts,
        locators=locators,
        batch_budget=tenth_budget,
    )
    assert len(tenth_transport.calls) == 1
    assert tenth_budget.extractor_calls == 10

    eleventh_budget = Schema67BatchBudgetV1(extractor_calls=10)
    eleventh_transport = _FakeTransport([_extractor_response()])
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=eleventh_transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
            batch_budget=eleventh_budget,
        )
    assert caught.value.reason_code == "BATCH_PROVIDER_CALL_BUDGET_EXHAUSTED"
    assert eleventh_transport.calls == []


class _Schema67KnownTransport(_FakeTransport):
    def __init__(self, *, mismatch_field_id: str | None = None) -> None:
        super().__init__(())
        self.mismatch_field_id = mismatch_field_id

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        content_by_slot = {
            item["slot"]: item["content_snapshot"]
            for item in payload["locator_slot_catalog"]
        }
        sources_by_field = {
            item["field_id"]: item["sources"]
            for item in payload["field_locator_slots"]
        }
        fields = []
        for contract in payload["field_contracts"]:
            field_id = contract["field_id"]
            evidence = []
            for source in sources_by_field[field_id]:
                slot = source["allowed_slots"][0]
                evidence.append(
                    {
                        "source_role": source["source_role"],
                        "locator_slot": slot,
                        "quote_snapshot": content_by_slot[slot],
                    }
                )
            value = evidence[0]["quote_snapshot"]
            if field_id == self.mismatch_field_id:
                value = "normalized-value-does-not-equal-any-quote"
            fields.append(
                {
                    "field_id": field_id,
                    "state": "present",
                    "value_snapshot": value,
                    "evidence": evidence,
                }
            )
        return json.dumps({"fields": fields}, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.asyncio
async def test_119_mvp_single_call_demotes_only_complete_057_nonpass_union() -> None:
    result, transport, target = await _mvp_demoted_execution()

    assert len(transport.calls) == 1
    assert result.response_contract_repair is None
    assert result.evidence_repair is None
    assert result.evidence_demotion is not None
    assert tuple(deepseek.EvidenceDemotionReceiptV1.model_fields) == (
        "policy_sha256",
        "parent_bound_attempt_sha256",
        "verification_batch_hashes",
        "demoted_field_ids",
        "initial_output_sha256",
        "final_output_sha256",
        "final_evidence_receipt_hashes",
        "pass_preservation_sha256",
        "receipt_hash",
    )
    with pytest.raises(ValueError):
        deepseek.EvidenceDemotionReceiptV1.model_validate(
            {
                **result.evidence_demotion.model_dump(mode="python"),
                "prior_provider_calls": 2,
            }
        )
    assert result.evidence_demotion.demoted_field_ids == (target,)
    initial_by_id = {item.field_id: item for item in result.initial_outputs}
    final_by_id = {item.field_id: item for item in result.final_outputs}
    initial_receipts = {
        item.field_id: item for item in result.initial.evidence_receipts
    }
    final_receipts = {item.field_id: item for item in result.evidence_receipts}
    assert final_by_id[target].state == "unknown"
    assert final_by_id[target].value_snapshot is None
    assert final_by_id[target].evidence == ()
    assert final_receipts[target].state == "unknown"
    assert final_receipts[target].value_snapshot is None
    assert final_receipts[target].evidence == ()
    for field_id in result.receipt.field_ids[:-1]:
        assert final_by_id[field_id] == initial_by_id[field_id]
        assert final_receipts[field_id] == initial_receipts[field_id]


async def _mvp_demoted_execution() -> tuple[
    deepseek.DeepSeekTaskExecutionV1, _Schema67KnownTransport, str
]:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared_all = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )
    prepared = next(
        item
        for item in prepared_all
        if item.task_kind == "material" and len(item.field_prompts) == 8
    )
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    target = prepared.field_prompts[-1].field_id
    transport = _Schema67KnownTransport(mismatch_field_id=target)

    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_Schema67EvidenceBindingPort(
            prepared=prepared,
            admitted_sources=(admitted,),
        ),
        field_contracts=prepared.field_prompts,
        locators=locators,
        execution_plan_sha256=plan.execution_plan_sha256,
        task_slice_sha256=prepared.task_slice_sha256,
        _single_pass_mvp=True,
    )
    return result, transport, target


def _rehash_mvp_demotion(
    result: deepseek.DeepSeekTaskExecutionV1,
    **updates: object,
) -> tuple[deepseek.EvidenceDemotionReceiptV1, deepseek.DeepSeekExecutionReceiptV1]:
    assert result.evidence_demotion is not None
    values = result.evidence_demotion.model_dump(mode="python", exclude={"receipt_hash"})
    values.update(updates)
    demotion = deepseek.EvidenceDemotionReceiptV1.model_validate(
        {
            **values,
            "receipt_hash": canonical_hash(
                "schema67-evidence-demotion-receipt.v1", values
            ),
        }
    )
    receipt_values = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values["evidence_demotion"] = demotion.model_dump(mode="python")
    receipt = deepseek.DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(
                "deepseek-evidence-compiler-596-1.v2", receipt_values
            ),
        }
    )
    return demotion, receipt


@pytest.mark.asyncio
async def test_119_mvp_task_execution_recomputes_demotion_scope() -> None:
    result, _transport, target = await _mvp_demoted_execution()
    pass_field = result.receipt.field_ids[0]
    for scope in (
        (pass_field,),
        (target, pass_field),
        (pass_field, target),
    ):
        demotion, receipt = _rehash_mvp_demotion(
            result, demoted_field_ids=scope
        )
        with pytest.raises(
            ValueError, match="deepseek_evidence_demotion_custody_mismatch"
        ):
            replace(
                result,
                evidence_demotion=demotion,
                receipt=receipt,
            )

    with pytest.raises(ValueError, match="evidence_demotion_receipt_invalid"):
        _rehash_mvp_demotion(
            result,
            demoted_field_ids=(target, target),
        )

    demotion, receipt = _rehash_mvp_demotion(
        result, verification_batch_hashes=("f" * 64,)
    )
    with pytest.raises(
        ValueError, match="deepseek_evidence_demotion_custody_mismatch"
    ):
        replace(result, evidence_demotion=demotion, receipt=receipt)

    initial_receipts = result.initial.evidence_receipts
    receipt_values = result.receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values.update(
        {
            "evidence_demotion": None,
            "final_outputs_sha256": deepseek._outputs_sha256(result.initial_outputs),
            "evidence_receipt_hashes": tuple(
                item.receipt_hash for item in initial_receipts
            ),
        }
    )
    forged_receipt = deepseek.DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(
                "deepseek-evidence-compiler-596-1.v2", receipt_values
            ),
        }
    )
    with pytest.raises(
        ValueError, match="deepseek_evidence_demotion_custody_mismatch"
    ):
        replace(
            result,
            final_outputs=result.initial_outputs,
            evidence_receipts=initial_receipts,
            evidence_demotion=None,
            receipt=forged_receipt,
        )


@pytest.mark.asyncio
async def test_119_mvp_task_execution_rejects_pass_output_or_receipt_mutation() -> None:
    result, _transport, _target = await _mvp_demoted_execution()
    mutated_output = result.final_outputs[0].model_copy(
        update={"value_snapshot": "mutated-pass-value"}
    )
    final_outputs = (mutated_output, *result.final_outputs[1:])
    demotion, receipt = _rehash_mvp_demotion(
        result,
        final_output_sha256=deepseek._outputs_sha256(final_outputs),
    )
    receipt_values = receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values["final_outputs_sha256"] = deepseek._outputs_sha256(final_outputs)
    receipt = deepseek.DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(
                "deepseek-evidence-compiler-596-1.v2", receipt_values
            ),
        }
    )
    with pytest.raises(ValueError):
        replace(
            result,
            final_outputs=final_outputs,
            evidence_demotion=demotion,
            receipt=receipt,
        )

    mutated_receipts = (
        result.evidence_receipts[0].model_copy(update={"receipt_hash": "f" * 64}),
        *result.evidence_receipts[1:],
    )
    demotion, receipt = _rehash_mvp_demotion(
        result,
        final_evidence_receipt_hashes=tuple(
            item.receipt_hash for item in mutated_receipts
        ),
    )
    receipt_values = receipt.model_dump(mode="python", exclude={"receipt_hash"})
    receipt_values["evidence_receipt_hashes"] = tuple(
        item.receipt_hash for item in mutated_receipts
    )
    receipt = deepseek.DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(
                "deepseek-evidence-compiler-596-1.v2", receipt_values
            ),
        }
    )
    with pytest.raises(ValueError):
        replace(
            result,
            evidence_receipts=mutated_receipts,
            evidence_demotion=demotion,
            receipt=receipt,
        )


@pytest.mark.asyncio
async def test_119_mvp_multisource_any_nonpass_demotes_whole_field() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = next(
        item
        for item in prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=plan,
            role_inputs=_schema67_role_inputs(contracts, plan),
        )
        if item.task_kind == "synthesis"
    )
    admitted = []
    locators: list[CanonicalLocatorInputV1] = []
    for source_index in range(len(prepared.source_tasks)):
        prepared, source, source_locators = _admitted_source_for_prepared(
            prepared, source_index=source_index
        )
        admitted.append(source)
        locators.extend(source_locators)
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=_Schema67KnownTransport(),
        port=_Schema67EvidenceBindingPort(
            prepared=prepared,
            admitted_sources=tuple(admitted),
        ),
        field_contracts=prepared.field_prompts,
        locators=tuple(locators),
        execution_plan_sha256=plan.execution_plan_sha256,
        task_slice_sha256=prepared.task_slice_sha256,
        _single_pass_mvp=True,
    )
    assert result.evidence_demotion is not None
    assert isinstance(result.initial, deepseek.Schema67BoundAttemptV1)
    statuses_by_field = {
        field_id: tuple(
            result_item.status
            for batch in result.initial.verification_batches
            for result_item in batch.results
            if result_item.field_id == field_id
        )
        for field_id in result.receipt.field_ids
    }
    target, source_statuses = next(
        (field_id, statuses)
        for field_id, statuses in statuses_by_field.items()
        if "PASS" in statuses and any(status != "PASS" for status in statuses)
    )
    assert "PASS" in source_statuses
    assert any(status != "PASS" for status in source_statuses)
    assert target in result.evidence_demotion.demoted_field_ids
    assert next(item for item in result.final_outputs if item.field_id == target).state == (
        "unknown"
    )


@pytest.mark.asyncio
async def test_119_mvp_forced_unknown_stays_unknown_without_repair() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    role_inputs = tuple(
        replace(
            item,
            allowed_locator_refs=tuple(
                (field_id, ()) for field_id, _refs in item.allowed_locator_refs
            ),
        )
        if item.material_role == "rate_table"
        else item
        for item in _schema67_role_inputs(contracts, plan)
    )
    prepared = next(
        item
        for item in prepare_schema67_deepseek_tasks(
            field_contracts=contracts,
            execution_plan=plan,
            role_inputs=role_inputs,
        )
        if item.task_kind == "material"
        and item.source_tasks[0].material_role == "rate_table"
    )
    assert all(item.requires_unknown_review for item in prepared.field_prompts)
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    transport = _UnknownExtractorTransport()
    result = await _run_deepseek_task(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        port=_Schema67EvidenceBindingPort(
            prepared=prepared,
            admitted_sources=(admitted,),
        ),
        field_contracts=prepared.field_prompts,
        locators=locators,
        execution_plan_sha256=plan.execution_plan_sha256,
        task_slice_sha256=prepared.task_slice_sha256,
        _single_pass_mvp=True,
    )
    request_contract = json.loads(transport.calls[0][1])["response_contract"]
    assert request_contract["forced_unknown_field_ids"] == list(result.receipt.field_ids)
    assert all(
        item.state == "unknown" and item.value_snapshot is None and item.evidence == ()
        for item in result.final_outputs
    )
    assert result.evidence_demotion is None
    assert result.receipt.total_calls == 1
    assert result.receipt.transport_retries == 0
    assert result.receipt.response_contract_repairs == 0
    assert result.receipt.evidence_repairs == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "reason_code"),
    (
        ("not-json", "MODEL_JSON_INVALID"),
        (json.dumps({"wrong": []}), "EXTRACTOR_TOP_LEVEL_SHAPE_INVALID"),
        (
            _shape_invalid_response(("product_code",)),
            "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID",
        ),
        (
            json.dumps(
                {
                    "fields": [
                        {
                            "field_id": " product_code",
                            "state": "unknown",
                            "value_snapshot": None,
                            "evidence": [],
                        }
                    ]
                }
            ),
            "EXTRACTOR_STRING_CONSTRAINT_INVALID",
        ),
    ),
)
async def test_119_mvp_structural_failures_never_retry_or_demote(
    response: str,
    reason_code: str,
) -> None:
    contracts, locators = _inputs()
    transport = _FakeTransport((response, _extractor_response()))
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
            _single_pass_mvp=True,
        )
    assert caught.value.reason_code == reason_code
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_119_mvp_locator_failure_is_terminal_without_repair() -> None:
    contracts, locators = _inputs()
    response = json.dumps(
        {
            "fields": [
                {
                    "field_id": "product_code",
                    "state": "present",
                    "value_snapshot": "candidate",
                    "evidence": [
                        {
                            "source_role": "terms",
                            "locator_slot": "slot-9999",
                            "quote_snapshot": "保险责任以条款约定为准。",
                        }
                    ],
                }
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    transport = _FakeTransport((response, response))
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_FakePort(),
            field_contracts=contracts,
            locators=locators,
            _single_pass_mvp=True,
        )
    assert caught.value.reason_code == "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_119_mvp_source_custody_failure_is_pretransport_terminal() -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, _admitted, locators = _admitted_source_for_prepared(prepared)
    transport = _Schema67KnownTransport()
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=_Schema67EvidenceBindingPort(
                prepared=prepared,
                admitted_sources=(),
            ),
            field_contracts=prepared.field_prompts,
            locators=locators,
            execution_plan_sha256=plan.execution_plan_sha256,
            task_slice_sha256=prepared.task_slice_sha256,
            _single_pass_mvp=True,
        )
    assert caught.value.reason_code == "LOCATOR_AUTHORITY_MISMATCH"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_119_mvp_hydration_and_verifier_exceptions_produce_no_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_contracts, locators = _inputs()

    @dataclass(frozen=True)
    class _MvpHydrationFailPort(_FakePort):
        def hydrate_extractor_outputs(
            self,
            *,
            selections: tuple[deepseek._ExtractorFieldSelectionV1, ...],
            contracts: tuple[DeepSeekFieldPromptInputV1, ...],
            locators: tuple[CanonicalLocatorInputV1, ...],
        ) -> tuple[FreeformFieldOutputV1, ...]:
            del selections, contracts, locators
            raise DeepSeekCompilerError(
                "EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID"
            )

    hydration_transport = _FakeTransport(
        (_unknown_fields_response(("product_code",)),)
    )
    with pytest.raises(DeepSeekCompilerError) as hydration_failure:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=hydration_transport,
            port=_MvpHydrationFailPort(),
            field_contracts=prompt_contracts,
            locators=locators,
            _single_pass_mvp=True,
        )
    assert hydration_failure.value.reason_code == (
        "EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID"
    )
    assert len(hydration_transport.calls) == 1

    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )[0]
    prepared, admitted, locators = _admitted_source_for_prepared(prepared)
    port = _Schema67EvidenceBindingPort(prepared=prepared, admitted_sources=(admitted,))

    def verifier_failure(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("private verifier failure")

    monkeypatch.setattr(evidence_verifier_module, "verify_evidence_batch", verifier_failure)
    transport = _Schema67KnownTransport()
    with pytest.raises(DeepSeekCompilerError) as caught:
        await _run_deepseek_task(
            profile=_profile(),
            policy=_policy(),
            transport=transport,
            port=port,
            field_contracts=prepared.field_prompts,
            locators=locators,
            execution_plan_sha256=plan.execution_plan_sha256,
            task_slice_sha256=prepared.task_slice_sha256,
            _single_pass_mvp=True,
        )
    assert caught.value.reason_code == "EVIDENCE_BINDING_FAILED"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_119_mvp_exact_eight_calls_bind_cumulative_budget_and_request_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = _schema67_contract_set()
    plan = _execution_plan(contracts)
    prepared_all = prepare_schema67_deepseek_tasks(
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=_schema67_role_inputs(contracts, plan),
    )
    corrected_tasks = []
    ports = []
    locator_groups = []
    for prepared in prepared_all:
        admitted = []
        locators: list[CanonicalLocatorInputV1] = []
        for source_index in range(len(prepared.source_tasks)):
            prepared, source, source_locators = _admitted_source_for_prepared(
                prepared, source_index=source_index
            )
            admitted.append(source)
            locators.extend(source_locators)
        corrected_tasks.append(prepared)
        ports.append(
            _Schema67EvidenceBindingPort(
                prepared=prepared,
                admitted_sources=tuple(admitted),
            )
        )
        locator_groups.append(tuple(locators))
    monkeypatch.setattr(
        deepseek,
        "prepare_schema67_deepseek_tasks",
        lambda **_kwargs: tuple(corrected_tasks),
    )
    monkeypatch.setattr(
        deepseek,
        "_schema67_binding_ports",
        lambda **_kwargs: tuple(ports),
    )
    transport = _UnknownExtractorTransport()
    result = await _run_schema67_deepseek_batch(
        profile=_profile(),
        policy=_policy(),
        transport=transport,
        field_contracts=contracts,
        execution_plan=plan,
        role_inputs=(),
        admitted_sources=(),
        locators_by_task=tuple(locator_groups),
        _single_pass_mvp=True,
    )
    receipt = result.receipt
    assert len(transport.calls) == 8
    assert receipt.task_count == 8
    assert receipt.provider_calls == 8
    assert receipt.extractor_calls == 8
    assert receipt.transport_retries == 0
    assert receipt.response_contract_repairs == 0
    assert receipt.evidence_repairs == 0
    assert receipt.repair_calls == 0
    assert set(type(plan.batch_budget).model_fields).isdisjoint(
        {
            "prior_ledger_external_sha256",
            "prior_ledger_internal_sha256",
        }
    )
    assert receipt.prior_provider_calls == 2
    assert receipt.cumulative_provider_calls == 10
    assert set(receipt.model_dump(mode="python")).isdisjoint(
        {
            "prior_ledger_external_sha256",
            "prior_ledger_internal_sha256",
            "current_provider_calls",
        }
    )
    assert receipt.batch_budget_identity_sha256 == plan.batch_budget.budget_identity_sha256
    assert type(receipt).model_validate(receipt.model_dump(mode="python")) == receipt
    receipt_payload = receipt.model_dump(
        mode="python", exclude={"batch_receipt_sha256"}
    )
    assert receipt.batch_receipt_sha256 == canonical_hash(
        "schema67-deepseek-batch-receipt.v2",
        {
            "receipt": receipt_payload,
            "prior_provider_ledger": {
                "external_sha256": (
                    "20208d33cfbbeb825ab8ee88d406e9e07010b1fde99612145d340dc81fac0d03"
                ),
                "internal_sha256": (
                    "507411396195ea2aa66f304e9de1809863205671d5bc75b97b09802530cd65c3"
                ),
            },
        },
    )
    for field_name, invalid_value in (
        ("task_count", 7),
        ("extractor_calls", 7),
        ("locator_calls", 1),
        ("transport_retries", 1),
        ("response_contract_repairs", 1),
        ("evidence_repairs", 1),
        ("repair_calls", 1),
        ("provider_calls", 9),
        ("prior_provider_calls", None),
        ("cumulative_provider_calls", None),
    ):
        drifted = receipt.model_dump(mode="python")
        drifted[field_name] = invalid_value
        with pytest.raises(ValueError):
            type(receipt).model_validate(drifted)
    downgraded = receipt.model_dump(mode="python", exclude={"batch_receipt_sha256"})
    downgraded["prior_provider_calls"] = None
    downgraded["cumulative_provider_calls"] = None
    with pytest.raises(ValueError, match="batch_receipt_invalid"):
        type(receipt).model_validate(
            {
                **downgraded,
                "batch_receipt_sha256": canonical_hash(
                    "schema67-deepseek-batch-receipt.v2", downgraded
                ),
            }
        )
    for execution in result.executions:
        assert replace(execution) == execution
        assert (
            type(execution.receipt).model_validate(
                execution.receipt.model_dump(mode="python")
            )
            == execution.receipt
        )
    bodies = tuple(
        openai_compat_request_bytes(
            model="deepseek-v4-flash",
            temperature=0.0,
            max_tokens=8192,
            system=system,
            user=user,
            thinking="disabled",
            response_format="json_object",
        )
        for system, user in transport.calls
    )
    assert len(bodies) == 8
    assert all(len(body) < 131072 for body in bodies)

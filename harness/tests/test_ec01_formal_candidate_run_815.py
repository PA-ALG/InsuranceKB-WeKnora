from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol, cast

import pytest

pytestmark = pytest.mark.live

sys.path.insert(0, str(Path(__file__).parent))
import test_deepseek_locator_extractor_119 as fixtures  # type: ignore[import-not-found]  # noqa: E402

from insurance_harness.canonical import canonical_hash  # noqa: E402
from insurance_harness.goldenset import expert_golden_admission_596_2 as admission  # noqa: E402
from insurance_harness.knowledge_compiler import (  # noqa: E402
    deepseek_locator_extractor_596_1 as deepseek,
)
from insurance_harness.knowledge_compiler import (  # noqa: E402
    ec01_formal_candidate_run_815 as ec01,
)
from insurance_harness.knowledge_compiler import (  # noqa: E402
    formal_candidate_derivation_validator_815 as derivation_validator,
)
from insurance_harness.knowledge_compiler.ec01_formal_candidate_run_815 import (  # noqa: E402
    EC01FormalCandidateRun815V1,
    EC01FormalCandidateRunError,
    EC01RawResponse815V1,
    prepare_ec01_formal_candidate_request_manifest_815,
    require_ec01_formal_candidate_run_815,
    run_ec01_formal_candidate_815,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (  # noqa: E402
    FieldContractSetV1,
)

_REVISION_ROOT_VALUE = os.environ.get("WEKNORA_EC01_REVISION_SET_ROOT")
if not _REVISION_ROOT_VALUE:
    pytest.skip(
        "WEKNORA_EC01_REVISION_SET_ROOT is required for EC-01 replay tests",
        allow_module_level=True,
    )
_REVISION_ROOT = Path(_REVISION_ROOT_VALUE)
_INTEGRATION_HEAD = "e5b7170d2241c66fb5c286a10a0865a3222ac425"
_INTEGRATION_TREE = "83fa1e08cfa6b2fc90d41e63fb092a96b2f0b562"
_EXPERIMENT_ID = "92f7f2be-5cae-4fab-82c1-3af879859257"
_RUN_ID = "76cc60b2-2d53-4d95-84ef-fb510827d977"
_ATTEMPT_ID = "76e774a3-ad7b-4168-84fe-5dd0bfa5a655"
_RECEIPT_ID = "8cd3f1ce-441d-444a-9130-b9b9ac322172"
_REVISION_SHA256 = "a45b27adb592e89b0fd0a66785e63baff344edc68fd5d965326a59a62b94dc2a"
_SOURCE_SHA_BY_ROLE = {
    "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}


class _TestTransport(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _domain_hash(domain: str, payload: dict[str, object]) -> str:
    return _sha(domain.encode("ascii") + b"\0" + _canonical_bytes(payload))


def _common_exact_source_fragment(quotes: tuple[str, ...]) -> str:
    if len(quotes) == 1:
        return quotes[0]
    seed = min(quotes, key=len)
    for width in range(min(len(seed), 80), 1, -1):
        for start in range(len(seed) - width + 1):
            candidate = seed[start : start + width].strip()
            if len(candidate) >= 2 and all(candidate in quote for quote in quotes):
                return candidate
    raise AssertionError("fixture sources do not share an exact semantic fragment")


def _forced_unknown_field_ids(payload: dict[str, object]) -> set[str]:
    response_contract = payload["response_contract"]
    assert isinstance(response_contract, dict)
    rows = response_contract["forced_unknown_field_ids"]
    assert isinstance(rows, list)
    return {str(field_id) for field_id in rows}


def _extraction_context(
    payload: dict[str, object],
) -> tuple[tuple[dict[str, object], ...], dict[str, str], dict[str, list[dict[str, object]]]]:
    local_contexts = payload.get("field_local_contexts")
    if local_contexts is None:
        raw_contracts = cast(list[object], payload["field_contracts"])
        exact_contracts = tuple(
            cast(dict[str, object], row) for row in raw_contracts
        )
        exact_content_by_slot: dict[str, str] = {}
        for raw_row in cast(list[object], payload["locator_slot_catalog"]):
            row = cast(dict[str, object], raw_row)
            exact_content_by_slot[cast(str, row["slot"])] = cast(
                str, row["content_snapshot"]
            )
        exact_sources_by_field: dict[str, list[dict[str, object]]] = {}
        for raw_row in cast(list[object], payload["field_locator_slots"]):
            row = cast(dict[str, object], raw_row)
            exact_sources_by_field[cast(str, row["field_id"])] = cast(
                list[dict[str, object]], row["sources"]
            )
        return exact_contracts, exact_content_by_slot, exact_sources_by_field
    assert isinstance(local_contexts, list)
    projected_contracts: list[dict[str, object]] = []
    projected_content_by_slot: dict[str, str] = {}
    projected_sources_by_field: dict[str, list[dict[str, object]]] = {}
    for context in local_contexts:
        assert isinstance(context, dict)
        field_id = context["field_id"]
        contract = context["field_contract"]
        sources = context["sources"]
        assert isinstance(field_id, str)
        assert isinstance(contract, dict)
        assert isinstance(sources, list)
        projected_contracts.append(contract)
        projected_sources: list[dict[str, object]] = []
        for source in sources:
            assert isinstance(source, dict)
            locators = source["allowed_locators"]
            assert isinstance(locators, list)
            allowed_slots: list[str] = []
            for locator in locators:
                assert isinstance(locator, dict)
                slot = locator["slot"]
                content = locator["content_snapshot"]
                assert isinstance(slot, str)
                assert isinstance(content, str)
                allowed_slots.append(slot)
                projected_content_by_slot[slot] = content
            projected_sources.append(
                {
                    "source_role": source["source_role"],
                    "allowed_slots": allowed_slots,
                }
            )
        projected_sources_by_field[field_id] = projected_sources
    return (
        tuple(projected_contracts),
        projected_content_by_slot,
        projected_sources_by_field,
    )


def _native_selection_response(
    payload: dict[str, object],
    *,
    all_unknown: bool = False,
    include_task_key: bool = True,
) -> str:
    rows = cast(list[dict[str, object]], payload["field_selection_catalogs"])
    fields: list[dict[str, object]] = []
    for row in rows:
        selections = cast(list[dict[str, object]], row["selections"])
        known = bool(selections) and not all_unknown
        fields.append(
            {
                "field_id": row["field_id"],
                "state": "present" if known else "unknown",
                "selection_ids": [selections[0]["selection_id"]] if known else [],
                "typed_reason": None if known else "ANSWER_NOT_FOUND",
            }
        )
    response: dict[str, object] = {"fields": fields}
    if include_task_key:
        response["task_key"] = payload["task_key"]
    return _canonical_bytes(response).decode()


class _KnownTransport:
    def __init__(self, *, include_task_key: bool = True) -> None:
        self.include_task_key = include_task_key
        self.calls: list[tuple[str, str]] = []
        self.forced_unknown_field_ids: list[str] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        if "field_selection_catalogs" in payload:
            return _native_selection_response(
                payload,
                include_task_key=self.include_task_key,
            )
        contracts, content_by_slot, sources_by_field = _extraction_context(payload)
        forced_unknown = _forced_unknown_field_ids(payload)
        self.forced_unknown_field_ids.extend(
            str(row["field_id"])
            for row in contracts
            if row["field_id"] in forced_unknown
        )
        fields: list[dict[str, object]] = []
        for contract in contracts:
            field_id = cast(str, contract["field_id"])
            if field_id in forced_unknown:
                fields.append(
                    {
                        "field_id": field_id,
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                )
                continue
            evidence = []
            for source in sources_by_field[field_id]:
                slot = cast(list[str], source["allowed_slots"])[0]
                evidence.append(
                    {
                        "source_role": source["source_role"],
                        "locator_slot": slot,
                        "quote_snapshot": content_by_slot[slot][:200].strip(),
                    }
                )
            source_value = _common_exact_source_fragment(
                tuple(str(item["quote_snapshot"]) for item in evidence)
            )
            if len(evidence) > 1:
                for item in evidence:
                    item["quote_snapshot"] = source_value
            fields.append(
                {
                    "field_id": field_id,
                    "state": "present",
                    "value_snapshot": source_value,
                    "evidence": evidence,
                }
            )
        response: dict[str, object] = {"fields": fields}
        if self.include_task_key:
            response["task_key"] = payload["task_key"]
        return _canonical_bytes(response).decode()


class _NativeSelectionTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        return _native_selection_response(payload)


class _FieldLocalInvalidSelectionTransport(_KnownTransport):
    def __init__(
        self,
        *,
        invalid_field_count: int = 1,
        invalid_selection_id: str | None = None,
    ) -> None:
        super().__init__()
        self.remaining = invalid_field_count
        self.invalid_selection_id = invalid_selection_id
        self.target_field_ids: list[str] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        response = json.loads(_native_selection_response(payload))
        if self.remaining <= 0:
            return _canonical_bytes(response).decode()
        catalogs = cast(list[dict[str, object]], payload["field_selection_catalogs"])
        fields = cast(list[dict[str, object]], response["fields"])
        for target_index, target in enumerate(catalogs):
            selections = cast(list[dict[str, object]], target["selections"])
            if not selections:
                continue
            foreign_id = self.invalid_selection_id or next(
                (
                    cast(str, donor_selection["selection_id"])
                    for donor in catalogs
                    if donor is not target
                    for donor_selection in cast(
                        list[dict[str, object]], donor["selections"]
                    )[:1]
                    if donor_selection["selection_id"]
                    not in {item["selection_id"] for item in selections}
                ),
                "selection-" + "f" * 64,
            )
            fields[target_index]["selection_ids"] = [foreign_id]
            self.target_field_ids.append(cast(str, target["field_id"]))
            self.remaining -= 1
            if self.remaining == 0:
                break
        return _canonical_bytes(response).decode()


class _ExplicitUnknownSelectionTransport(_KnownTransport):
    def __init__(self) -> None:
        super().__init__()
        self.target_field_id: str | None = None

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        response = json.loads(_native_selection_response(payload))
        if self.target_field_id is None:
            fields = cast(list[dict[str, object]], response["fields"])
            target = next(item for item in fields if item["state"] == "present")
            target.update(
                state="unknown",
                selection_ids=[],
                typed_reason="ANSWER_NOT_FOUND",
            )
            self.target_field_id = cast(str, target["field_id"])
        return _canonical_bytes(response).decode()


class _FailingNativeSelectionTransport(_NativeSelectionTransport):
    def __init__(self, *, fail_call: int) -> None:
        super().__init__()
        self.fail_call = fail_call

    async def complete(self, system: str, user: str) -> str:
        if len(self.calls) + 1 == self.fail_call:
            self.calls.append((system, user))
            raise RuntimeError("provider context length exceeded")
        return await super().complete(system, user)


class _MalformedNativeSelectionTransport(_NativeSelectionTransport):
    def __init__(self, *, malformed_call: int) -> None:
        super().__init__()
        self.malformed_call = malformed_call

    async def complete(self, system: str, user: str) -> str:
        response_text = await super().complete(system, user)
        if len(self.calls) != self.malformed_call:
            return response_text
        response = json.loads(response_text)
        response["fields"] = response["fields"][:-1]
        return _canonical_bytes(response).decode()


async def _run_native_selection() -> EC01FormalCandidateRun815V1:
    contracts = fixtures._schema67_contract_set()
    projection = deepseek.build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    manifest = await prepare_ec01_formal_candidate_request_manifest_815(
        revision_set_root=_REVISION_ROOT,
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        field_contracts=contracts,
        execution_plan=projection.execution_plan,
        integration_head=_INTEGRATION_HEAD,
        integration_tree=_INTEGRATION_TREE,
    )
    manifest_sha256 = cast(str, json.loads(manifest)["manifest_sha256"])
    execution_identity_sha256 = canonical_hash(
        "ec01-execution-identity.v1",
        {
            "experiment_id": _EXPERIMENT_ID,
            "run_id": _RUN_ID,
            "attempt_id": _ATTEMPT_ID,
            "receipt_id": _RECEIPT_ID,
            "integration_head": _INTEGRATION_HEAD,
            "integration_tree": _INTEGRATION_TREE,
            "revision_set_sha256": _REVISION_SHA256,
            "request_identity_manifest_sha256": manifest_sha256,
            "model_execution_identity_sha256": deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        },
    )
    return await run_ec01_formal_candidate_815(
        revision_set_root=_REVISION_ROOT,
        request_identity_manifest_bytes=manifest,
        experiment_id=_EXPERIMENT_ID,
        execution_identity_sha256=execution_identity_sha256,
        run_id=_RUN_ID,
        attempt_id=_ATTEMPT_ID,
        receipt_id=_RECEIPT_ID,
        integration_head=_INTEGRATION_HEAD,
        integration_tree=_INTEGRATION_TREE,
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        transport=_NativeSelectionTransport(),
        field_contracts=contracts,
        execution_plan=projection.execution_plan,
    )


@pytest.mark.asyncio
async def test_ec01_native_selection_seals_disposition_and_coordinate_companion() -> None:
    result = await _run_native_selection()

    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert result.terminal.status == "SUCCEEDED"
    assert result.terminal.attempted_field_count == 25
    assert result.terminal.provider_visible_field_count == 25
    assert result.terminal.real_model_output_count == 25
    assert result.terminal.code_deferred_field_count == 42
    assert result.terminal.dispositioned_field_count == 67
    assert result.coordinate_evidence_companion.candidate_sha256 == (
        result.candidate.candidate_sha256
    )


class _QuoteRepairTransport(_KnownTransport):
    def __init__(
        self,
        *,
        repair_quote_is_exact: bool = True,
        repair_returns_explicit_unknown: bool = False,
    ) -> None:
        super().__init__()
        self.repair_quote_is_exact = repair_quote_is_exact
        self.repair_returns_explicit_unknown = repair_returns_explicit_unknown
        self.target_field_id: str | None = None
        self.initial_response_bytes: bytes | None = None
        self.repair_response_bytes: bytes | None = None

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        is_repair = payload.get("repair_kind") == "evidence"
        repair_fields = set(payload.get("field_ids", ()))
        forced_unknown = _forced_unknown_field_ids(payload)
        context_contracts, content_by_slot, sources_by_field = _extraction_context(
            payload
        )
        contracts = tuple(
            row
            for row in context_contracts
            if not is_repair or row["field_id"] in repair_fields
        )
        if self.target_field_id is None:
            self.target_field_id = next(
                cast(str, row["field_id"])
                for row in reversed(contracts)
                if row["field_id"] not in forced_unknown
            )
        fields: list[dict[str, object]] = []
        for contract in contracts:
            field_id = cast(str, contract["field_id"])
            if field_id in forced_unknown or (
                is_repair
                and field_id == self.target_field_id
                and self.repair_returns_explicit_unknown
            ):
                fields.append(
                    {
                        "field_id": field_id,
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                )
                continue
            evidence = []
            for source in sources_by_field[field_id]:
                slot = cast(list[str], source["allowed_slots"])[0]
                exact_quote = content_by_slot[slot][:200].strip()
                quote = exact_quote
                if field_id == self.target_field_id and (
                    not is_repair or not self.repair_quote_is_exact
                ):
                    quote = exact_quote[:1] + exact_quote[2:]
                evidence.append(
                    {
                        "source_role": source["source_role"],
                        "locator_slot": slot,
                        "quote_snapshot": quote,
                    }
                )
            source_value = _common_exact_source_fragment(
                tuple(str(item["quote_snapshot"]) for item in evidence)
            )
            if len(evidence) > 1 and field_id != self.target_field_id:
                for item in evidence:
                    item["quote_snapshot"] = source_value
            fields.append(
                {
                    "field_id": field_id,
                    "state": "present",
                    "value_snapshot": (
                        str(evidence[0]["quote_snapshot"])
                        if is_repair and field_id == self.target_field_id
                        else source_value
                    ),
                    "evidence": evidence,
                }
            )
        response_bytes = _canonical_bytes(
            {"task_key": payload["task_key"], "fields": fields}
        )
        if is_repair:
            self.repair_response_bytes = response_bytes
        elif self.initial_response_bytes is None:
            self.initial_response_bytes = response_bytes
        return response_bytes.decode()


class _FieldInvalidRepairTransport(_QuoteRepairTransport):
    def __init__(self, failure_kind: str) -> None:
        super().__init__(repair_quote_is_exact=True)
        self.failure_kind = failure_kind

    async def complete(self, system: str, user: str) -> str:
        response = await super().complete(system, user)
        request = json.loads(user)
        if request.get("repair_kind") != "evidence":
            return response
        payload = json.loads(response)
        row = next(
            item
            for item in payload["fields"]
            if item["field_id"] == self.target_field_id
        )
        if self.failure_kind == "locator":
            row["evidence"][0]["locator_slot"] = "field-9999-locator-9999"
        elif self.failure_kind == "string":
            row["value_snapshot"] = ""
        elif self.failure_kind == "shape":
            row.pop("value_snapshot")
        elif self.failure_kind == "semantic":
            row["value_snapshot"] = "与引文无关的字段答案"
        else:
            raise AssertionError(self.failure_kind)
        response_bytes = _canonical_bytes(payload)
        self.repair_response_bytes = response_bytes
        return response_bytes.decode()


class _AllUnknownTransport(_KnownTransport):
    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        if "field_selection_catalogs" in payload:
            return _native_selection_response(payload, all_unknown=True)
        contracts, _content_by_slot, _sources_by_field = _extraction_context(payload)
        return _canonical_bytes(
            {
                "task_key": payload["task_key"],
                "fields": [
                    {
                        "field_id": row["field_id"],
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                    for row in contracts
                ],
            }
        ).decode()


class _TwoTaskBatchQuoteRepairTransport(_KnownTransport):
    def __init__(
        self,
        *,
        quote_failure_initial_ordinals: tuple[int, ...] = (1, 2),
        unreadable_initial_ordinals: tuple[int, ...] = (),
        failure_field_indexes_by_ordinal: dict[int, tuple[int, ...]] | None = None,
        initial_explicit_unknown_field_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.initial_call_count = 0
        self.repair_initial_count: int | None = None
        self.target_field_ids: list[str] = []
        self.first_task_field_ids: tuple[str, ...] = ()
        self._quote_failure_initial_ordinals = quote_failure_initial_ordinals
        self._unreadable_initial_ordinals = unreadable_initial_ordinals
        self._failure_field_indexes_by_ordinal = (
            failure_field_indexes_by_ordinal or {}
        )
        self._initial_explicit_unknown_field_ids = frozenset(
            initial_explicit_unknown_field_ids
        )

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        is_repair = payload.get("repair_kind") == "evidence"
        if is_repair:
            self.repair_initial_count = self.initial_call_count
        else:
            self.initial_call_count += 1
        repair_fields = set(payload.get("field_ids", ()))
        forced_unknown = _forced_unknown_field_ids(payload)
        context_contracts, content_by_slot, sources_by_field = _extraction_context(
            payload
        )
        contracts = tuple(
            row
            for row in context_contracts
            if not is_repair or row["field_id"] in repair_fields
        )
        if not is_repair and self.initial_call_count == 1:
            self.first_task_field_ids = tuple(
                str(item["field_id"]) for item in contracts
            )
        if not is_repair:
            configured_indexes = self._failure_field_indexes_by_ordinal.get(
                self.initial_call_count
            )
            if configured_indexes is not None:
                self.target_field_ids.extend(
                    cast(str, contracts[index]["field_id"])
                    for index in configured_indexes
                )
            elif self.initial_call_count in self._quote_failure_initial_ordinals:
                self.target_field_ids.append(
                    next(
                        cast(str, row["field_id"])
                        for row in reversed(contracts)
                        if row["field_id"] not in forced_unknown
                        and row["field_id"]
                        not in self._initial_explicit_unknown_field_ids
                    )
                )
        fields: list[dict[str, object]] = []
        for contract in contracts:
            field_id = cast(str, contract["field_id"])
            if field_id in forced_unknown or (
                not is_repair
                and field_id in self._initial_explicit_unknown_field_ids
            ):
                fields.append(
                    {
                        "field_id": field_id,
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                )
                continue
            evidence = []
            for source in sources_by_field[field_id]:
                slot = cast(list[str], source["allowed_slots"])[0]
                exact_quote = content_by_slot[slot][:200].strip()
                quote = exact_quote
                if not is_repair and field_id in self.target_field_ids:
                    quote = exact_quote[:1] + exact_quote[2:]
                evidence.append(
                    {
                        "source_role": source["source_role"],
                        "locator_slot": slot,
                        "quote_snapshot": quote,
                    }
                )
            source_value = _common_exact_source_fragment(
                tuple(str(item["quote_snapshot"]) for item in evidence)
            )
            if len(evidence) > 1 and (
                is_repair or field_id not in self.target_field_ids
            ):
                for item in evidence:
                    item["quote_snapshot"] = source_value
            fields.append(
                {
                    "field_id": field_id,
                    "state": "present",
                    "value_snapshot": (
                        str(evidence[0]["quote_snapshot"])
                        if is_repair and field_id in self.target_field_ids
                        else source_value
                    ),
                    "evidence": evidence,
                }
            )
        response = {"task_key": payload["task_key"], "fields": fields}
        if (
            not is_repair
            and self.initial_call_count in self._unreadable_initial_ordinals
        ):
            return "not-json"
        return _canonical_bytes(response).decode()


def _native_execution_plan(
    contracts: FieldContractSetV1,
) -> deepseek.Schema67ExecutionPlanV1:
    return deepseek.build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    ).execution_plan


_CACHED_NATIVE_KNOWN_RUN: EC01FormalCandidateRun815V1 | None = None


async def _run(transport: _TestTransport) -> EC01FormalCandidateRun815V1:
    global _CACHED_NATIVE_KNOWN_RUN
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)
    request_manifest = await prepare_ec01_formal_candidate_request_manifest_815(
        revision_set_root=_REVISION_ROOT,
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        field_contracts=contracts,
        execution_plan=plan,
        integration_head=_INTEGRATION_HEAD,
        integration_tree=_INTEGRATION_TREE,
    )
    manifest_sha256 = json.loads(request_manifest)["manifest_sha256"]
    execution_identity_sha256 = canonical_hash(
        "ec01-execution-identity.v1",
        {
            "experiment_id": _EXPERIMENT_ID,
            "run_id": _RUN_ID,
            "attempt_id": _ATTEMPT_ID,
            "receipt_id": _RECEIPT_ID,
            "integration_head": _INTEGRATION_HEAD,
            "integration_tree": _INTEGRATION_TREE,
            "revision_set_sha256": _REVISION_SHA256,
            "request_identity_manifest_sha256": manifest_sha256,
            "model_execution_identity_sha256": deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        },
    )
    result = await run_ec01_formal_candidate_815(
        revision_set_root=_REVISION_ROOT,
        request_identity_manifest_bytes=request_manifest,
        experiment_id=_EXPERIMENT_ID,
        execution_identity_sha256=execution_identity_sha256,
        run_id=_RUN_ID,
        attempt_id=_ATTEMPT_ID,
        receipt_id=_RECEIPT_ID,
        integration_head=_INTEGRATION_HEAD,
        integration_tree=_INTEGRATION_TREE,
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        transport=transport,
        field_contracts=contracts,
        execution_plan=plan,
    )
    known_transport = cast(_KnownTransport, transport)
    if type(transport) is _KnownTransport and known_transport.include_task_key:
        _CACHED_NATIVE_KNOWN_RUN = result
    return result


async def _cached_native_known_run() -> EC01FormalCandidateRun815V1:
    if _CACHED_NATIVE_KNOWN_RUN is not None:
        return _CACHED_NATIVE_KNOWN_RUN
    return await _run(_KnownTransport())


@pytest.mark.asyncio
async def test_ec01_offline_binding_failure_keeps_all_initial_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ArmFailureAfterRequestManifest(_KnownTransport):
        async def complete(self, system: str, user: str) -> str:
            if not self.calls:
                monkeypatch.setattr(
                    deepseek._Schema67EvidenceBindingPort,
                    "bind_native_selection_outputs",
                    lambda _self, _outputs, _catalogs: (_ for _ in ()).throw(
                        RuntimeError("offline Evidence binding failed")
                    ),
                )
            return await super().complete(system, user)

    transport = _ArmFailureAfterRequestManifest()

    with pytest.raises(EC01FormalCandidateRunError) as caught:
        await _run(transport)

    assert caught.value.reason_code == "EVIDENCE_BINDING_FAILED"
    assert caught.value.terminal is not None
    assert caught.value.terminal.status == "FAILED"
    assert caught.value.terminal.raw_count == 8
    assert len(caught.value.raw_responses) == 8
    assert caught.value.repair_raw_responses == ()
    assert caught.value.candidate is None
    assert len(transport.calls) == 8


@pytest.mark.asyncio
async def test_ec01_request_manifest_binds_schema_rows_sha256() -> None:
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)

    manifest_bytes = await prepare_ec01_formal_candidate_request_manifest_815(
        revision_set_root=_REVISION_ROOT,
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        field_contracts=contracts,
        execution_plan=plan,
        integration_head=_INTEGRATION_HEAD,
        integration_tree=_INTEGRATION_TREE,
    )
    manifest = json.loads(manifest_bytes)

    assert manifest["schema_rows_sha256"] == contracts.schema_rows_sha256


@pytest.mark.asyncio
async def test_ec01_same_run_reuses_prepared_inputs_but_public_require_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)
    prepared = SimpleNamespace(
        revision_validation=SimpleNamespace(
            validation_sha256="1" * 64,
            revision_set_sha256=_REVISION_SHA256,
        ),
        role_inputs=(),
        admitted_sources=(),
        locators_by_task=(),
        source_projections=(),
        execution_projection=SimpleNamespace(
            provider_visible_field_ids=("product_name",),
            code_deferred=(),
        ),
        selection_catalog=SimpleNamespace(),
    )
    preparation_calls = 0

    def _counting_prepare(**_kwargs: object) -> object:
        nonlocal preparation_calls
        preparation_calls += 1
        return prepared

    raw_responses = tuple(
        EC01RawResponse815V1(
            ordinal=ordinal,
            task_key=task_key,
            response_bytes=f'{{"ordinal":{ordinal}}}'.encode(),
            byte_size=len(f'{{"ordinal":{ordinal}}}'.encode()),
            response_sha256=_sha(f'{{"ordinal":{ordinal}}}'.encode()),
        )
        for ordinal, task_key in enumerate(ec01._TASK_KEYS, start=1)
    )

    class _SyntheticRecordingTransport:
        def __init__(self, _delegate: object, _task_rows: object) -> None:
            self.raw_responses = list(raw_responses)
            self.repair_raw_responses: list[EC01RawResponse815V1] = []

    candidate = SimpleNamespace(
        fields=(SimpleNamespace(state="present"),),
        candidate_sha256="2" * 64,
    )
    companion = SimpleNamespace(companion_sha256="3" * 64)
    terminal = SimpleNamespace(terminal_sha256="4" * 64)
    request_manifest_bytes = b'{"manifest":"synthetic-prepared-input"}'
    manifest_sha256 = "5" * 64
    batch_execution = SimpleNamespace(
        receipt=SimpleNamespace(batch_receipt_sha256="6" * 64)
    )

    async def _build_synthetic_manifest(**_kwargs: object) -> bytes:
        return request_manifest_bytes

    async def _run_synthetic_batch(**_kwargs: object) -> object:
        return batch_execution

    monkeypatch.setattr(ec01, "_prepare_c1_inputs", _counting_prepare)
    monkeypatch.setattr(
        ec01,
        "_build_request_manifest",
        _build_synthetic_manifest,
    )
    monkeypatch.setattr(
        ec01,
        "_require_request_manifest",
        lambda *_args, **_kwargs: ({"tasks": []}, manifest_sha256),
    )
    monkeypatch.setattr(ec01, "_require_execution_identity", lambda **_kwargs: None)
    monkeypatch.setattr(
        ec01,
        "_require_execution_identity_shape",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(ec01, "_RecordingTransport", _SyntheticRecordingTransport)
    monkeypatch.setattr(
        deepseek,
        "_run_schema67_deepseek_batch",
        _run_synthetic_batch,
    )
    monkeypatch.setattr(
        admission,
        "make_total_control_schema67_candidate_v2",
        lambda **_kwargs: candidate,
    )
    monkeypatch.setattr(
        ec01,
        "_replay_native_selection_coordinates_815",
        lambda **_kwargs: (),
    )
    monkeypatch.setattr(
        ec01,
        "make_coordinate_evidence_companion_815",
        lambda **_kwargs: companion,
    )
    monkeypatch.setattr(ec01, "_make_terminal", lambda **_kwargs: terminal)

    def _require_with_prepared(**kwargs: object) -> object:
        assert kwargs["prepared_inputs"] is prepared
        return kwargs["run"]

    monkeypatch.setattr(
        ec01,
        "_require_ec01_formal_candidate_run_with_prepared_815",
        _require_with_prepared,
        raising=False,
    )

    assert (
        await prepare_ec01_formal_candidate_request_manifest_815(
            revision_set_root=_REVISION_ROOT,
            profile=fixtures._profile(),
            policy=fixtures._policy(),
            field_contracts=contracts,
            execution_plan=plan,
            integration_head=_INTEGRATION_HEAD,
            integration_tree=_INTEGRATION_TREE,
        )
        == request_manifest_bytes
    )
    result = await run_ec01_formal_candidate_815(
        revision_set_root=_REVISION_ROOT,
        request_identity_manifest_bytes=request_manifest_bytes,
        experiment_id=_EXPERIMENT_ID,
        execution_identity_sha256="7" * 64,
        run_id=_RUN_ID,
        attempt_id=_ATTEMPT_ID,
        receipt_id=_RECEIPT_ID,
        integration_head=_INTEGRATION_HEAD,
        integration_tree=_INTEGRATION_TREE,
        profile=fixtures._profile(),
        policy=fixtures._policy(),
        transport=cast(_TestTransport, object()),
        field_contracts=contracts,
        execution_plan=plan,
    )

    assert preparation_calls == 2
    exact_terminal = result.terminal
    exact_candidate = result.candidate
    exact_companion = result.coordinate_evidence_companion
    exact_derivation_sha256 = result.derivation_sha256
    exact_bytes_and_hashes = (
        result.request_manifest_bytes,
        tuple(row.response_bytes for row in result.raw_responses),
        result.terminal.terminal_sha256,
        result.candidate.candidate_sha256,
        result.coordinate_evidence_companion.companion_sha256,
        result.derivation_sha256,
    )
    assert (
        ec01.require_ec01_formal_candidate_run_815(
            run=result,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
        is result
    )
    assert preparation_calls == 3
    assert result.terminal == exact_terminal
    assert result.candidate == exact_candidate
    assert result.coordinate_evidence_companion == exact_companion
    assert result.derivation_sha256 == exact_derivation_sha256
    assert result.derivation_sha256 == result.recomputed_derivation_sha256()
    assert (
        result.request_manifest_bytes,
        tuple(row.response_bytes for row in result.raw_responses),
        result.terminal.terminal_sha256,
        result.candidate.candidate_sha256,
        result.coordinate_evidence_companion.companion_sha256,
        result.derivation_sha256,
    ) == exact_bytes_and_hashes


@pytest.mark.asyncio
async def test_ec01_fake_exact8_raw_replay_seals_formal_candidate() -> None:
    transport = _KnownTransport()
    result = await _run(transport)
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)
    provider_visible_field_ids = tuple(
        field_id for task in plan.task_slices for field_id in task.field_ids
    )
    assert result.terminal.status == "SUCCEEDED"
    assert result.terminal.raw_count == 8
    assert result.terminal.attempted_field_count == len(provider_visible_field_ids)
    assert result.terminal.provider_visible_field_count == len(
        provider_visible_field_ids
    )
    assert result.terminal.real_model_output_count == len(provider_visible_field_ids)
    assert result.terminal.code_deferred_field_count == len(
        plan.deferred_unknown_field_ids
    )
    assert result.terminal.dispositioned_field_count == 67
    assert result.terminal.experiment_id == _EXPERIMENT_ID
    assert result.terminal.execution_identity_sha256 == result.execution_identity_sha256
    assert result.terminal.run_id == _RUN_ID
    assert result.terminal.attempt_id == _ATTEMPT_ID
    assert result.terminal.receipt_id == _RECEIPT_ID
    assert result.terminal.integration_head == _INTEGRATION_HEAD
    assert result.terminal.integration_tree == _INTEGRATION_TREE
    assert result.schema_rows_sha256 == contracts.schema_rows_sha256
    assert result.terminal.schema_rows_sha256 == result.schema_rows_sha256
    assert result.candidate_kind == "FORMAL"
    assert tuple(item.ordinal for item in result.raw_responses) == tuple(range(1, 9))
    assert result.repair_raw_responses == ()
    assert all(item.response_sha256 == _sha(item.response_bytes) for item in result.raw_responses)
    assert tuple(item.field_id for item in result.candidate.fields) == admission.ORDERED_FIELD_IDS
    assert len(result.candidate.fields) == 67
    assert len(result.candidate.evidence_receipts) == 67
    known_count = sum(
        item.state != "unknown" for item in result.candidate.fields
    )
    assert 1 <= known_count <= len(provider_visible_field_ids)
    assert sum(
        item.state == "unknown" for item in result.candidate.fields
    ) == 67 - known_count
    assert result.candidate.batch_receipt.provider_calls == 8
    assert result.candidate.batch_receipt.transport_retries == 0
    assert result.candidate.batch_receipt.response_contract_repairs == 0
    assert result.candidate.batch_receipt.evidence_repairs == 0
    assert result.candidate.batch_receipt.repair_calls == 0
    request_manifest = json.loads(result.request_manifest_bytes)
    assert request_manifest["schema_rows_sha256"] == result.schema_rows_sha256
    assert len(request_manifest["tasks"]) == 8
    request_field_ids = tuple(
        field_id
        for row in request_manifest["tasks"]
        for field_id in row["field_ids"]
    )
    raw_field_ids = tuple(
        field["field_id"]
        for raw in result.raw_responses
        for field in json.loads(raw.response_bytes)["fields"]
    )
    assert request_field_ids == raw_field_ids == provider_visible_field_ids
    assert len(request_field_ids) == len(set(request_field_ids)) == 25
    assert set(provider_visible_field_ids).isdisjoint(plan.deferred_unknown_field_ids)
    assert set(provider_visible_field_ids) | set(plan.deferred_unknown_field_ids) == set(
        admission.ORDERED_FIELD_IDS
    )
    assert tuple(row["task_key"] for row in request_manifest["tasks"]) == tuple(
        f"terms-{index:02d}" for index in range(1, 6)
    ) + ("brochure-01", "rate_table-01", "multi-source-01")
    assert tuple(
        row["canonical_request"]["external_sha256"] for row in request_manifest["tasks"]
    ) == tuple(
        execution.receipt.extractor_request_sha256
        for execution in result.candidate.batch_execution.executions
    )
    assert len(transport.calls) == 8
    parameters = signature(run_ec01_formal_candidate_815).parameters
    assert not {"admitted_sources", "locators_by_task", "parser", "parsed_document"} & set(
        parameters
    )
    for required in (
        "experiment_id",
        "execution_identity_sha256",
        "run_id",
        "attempt_id",
        "receipt_id",
        "integration_head",
        "integration_tree",
    ):
        assert parameters[required].default is parameters[required].empty
    known = next(item for item in result.candidate.fields if item.state == "present")
    evidence = known.evidence[0]
    assert evidence.source_sha256 in _SOURCE_SHA_BY_ROLE
    assert len(evidence.source_revision_id) == 64
    assert evidence.page_number >= 1
    assert evidence.quote_snapshot
    assert (
        require_ec01_formal_candidate_run_815(
            run=result,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
        is result
    )
    field_attempt_manifest, derivation_validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=result,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )
    assert derivation_validation.status == "PASS"
    assert len(field_attempt_manifest.rows) == 67
    model_rows = tuple(
        row
        for row in field_attempt_manifest.rows
        if row.derivation_kind == "MODEL_RESPONSE"
    )
    deferred_rows = tuple(
        row
        for row in field_attempt_manifest.rows
        if row.derivation_kind == "CODE_OWNED_DEFERRED_UNKNOWN"
    )
    assert tuple(row.field_id for row in model_rows) == tuple(
        field_id
        for field_id in admission.ORDERED_FIELD_IDS
        if field_id in set(provider_visible_field_ids)
    )
    assert tuple(row.field_id for row in deferred_rows) == plan.deferred_unknown_field_ids
    assert all(row.task_key is not None for row in model_rows)
    assert all(row.request_body_sha256 is not None for row in model_rows)
    assert all(row.raw_response_sha256 is not None for row in model_rows)
    assert all(
        row.raw_response_byte_size is not None and row.raw_response_byte_size > 0
        for row in model_rows
    )
    assert all(
        row.task_key is None
        and row.request_body_sha256 is None
        and row.raw_response_sha256 is None
        and row.raw_response_byte_size is None
        for row in deferred_rows
    )


def test_ec01_original_run_artifact_loader_has_closed_signature() -> None:
    parameters = signature(
        ec01.require_ec01_formal_candidate_run_artifact_815
    ).parameters

    assert set(parameters) == {
        "artifact_root",
        "revision_set_root",
        "field_contracts",
        "execution_plan",
    }
    assert "candidate" not in parameters
    assert "terminal" not in parameters
    assert "request_manifest" not in parameters
    assert "raw_responses" not in parameters


def test_ec01_original_run_artifact_reader_preserves_exact_wire_order(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "original-run-wire"
    artifact_root.mkdir(mode=0o700)
    payload = b'{"task_key":"terms-01","fields":[]}'
    path = artifact_root / "raw-response-01.json"
    path.write_bytes(payload)
    path.chmod(0o600)

    artifact_dir_fd, opened = ec01._open_original_run_artifact_root_815(
        artifact_root
    )
    try:
        observed, decoded = ec01._read_original_run_artifact_json_815(
            artifact_dir_fd,
            "raw-response-01.json",
            trailing_newline=False,
            require_sorted_canonical=False,
        )
        ec01._require_original_run_artifact_root_binding_815(
            artifact_root,
            artifact_dir_fd,
            opened,
        )
    finally:
        os.close(artifact_dir_fd)

    assert observed == payload
    assert decoded == {"task_key": "terms-01", "fields": []}


@pytest.mark.asyncio
async def test_ec01_batch_keeps_one_targeted_repair_raw_and_lineage(
) -> None:
    transport = _FieldLocalInvalidSelectionTransport()
    result = await _run(transport)
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)

    assert result.terminal.status == "SUCCEEDED"
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert len(transport.calls) == 8
    assert len(transport.target_field_ids) == 1
    target_field_id = transport.target_field_ids[0]
    target = next(
        item for item in result.candidate.fields if item.field_id == target_field_id
    )
    assert target.state == "unknown"
    assert target.value_snapshot is None
    assert target.evidence == ()
    assert result.candidate.batch_receipt.provider_calls == 8
    assert result.candidate.batch_receipt.evidence_repairs == 0
    assert result.candidate.batch_receipt.transport_retries == 0
    assert result.candidate.batch_receipt.response_contract_repairs == 0
    assert result.candidate.batch_receipt.repair_calls == 0
    assert all(
        execution.evidence_repair is None
        for execution in result.candidate.batch_execution.executions
    )
    assert (
        require_ec01_formal_candidate_run_815(
            run=result,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
        is result
    )


@pytest.mark.asyncio
async def test_ec01_invalid_targeted_repair_becomes_typed_unknown_candidate() -> None:
    transport = _FieldLocalInvalidSelectionTransport()

    result = await _run(transport)

    assert result.terminal.status == "SUCCEEDED"
    assert result.terminal.attempted_field_count == 25
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert len(transport.calls) == 8
    assert result.terminal.raw_count == 8
    assert len(transport.target_field_ids) == 1
    target_field_id = transport.target_field_ids[0]
    execution = next(
        item for item in result.candidate.batch_execution.executions
        if target_field_id in item.receipt.field_ids
    )
    final = {item.field_id: item for item in execution.final_outputs}
    initial = {item.field_id: item for item in execution.initial_outputs}
    invalid = final[target_field_id]
    assert invalid.state == "unknown"
    assert invalid.value_snapshot is None
    assert invalid.evidence == ()
    assert execution.evidence_repair is None
    assert all(
        final[field_id] == initial[field_id]
        for field_id in execution.receipt.field_ids
        if field_id != target_field_id
    )


@pytest.mark.asyncio
async def test_ec01_initial_unknown_is_not_recounted_as_repaired_unknown() -> None:
    transport = _ExplicitUnknownSelectionTransport()

    result = await _run(transport)

    assert result.terminal.status == "SUCCEEDED"
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert result.candidate.batch_receipt.provider_calls == 8
    assert result.candidate.batch_receipt.evidence_repairs == 0
    assert result.candidate.batch_receipt.repair_calls == 0
    assert all(
        execution.evidence_repair is None
        for execution in result.candidate.batch_execution.executions
    )
    assert transport.target_field_id is not None
    fields = {item.field_id: item for item in result.candidate.fields}
    unknown = fields[transport.target_field_id]
    assert unknown.state == "unknown"
    assert unknown.value_snapshot is None
    assert unknown.evidence == ()
    assert tuple(fields) == admission.ORDERED_FIELD_IDS
    assert any(item.state != "unknown" for item in result.candidate.fields)


@pytest.mark.asyncio
async def test_ec01_oversized_targeted_request_reaches_transport_and_keeps_transport_failure(
) -> None:
    transport = _FailingNativeSelectionTransport(fail_call=1)

    with pytest.raises(EC01FormalCandidateRunError) as caught:
        await _run(transport)

    assert caught.value.reason_code == "MODEL_TRANSPORT_FAILED"
    assert caught.value.terminal is not None
    assert caught.value.terminal.failure_reason == "MODEL_TRANSPORT_FAILED"
    assert caught.value.raw_responses == ()
    assert caught.value.repair_raw_responses == ()
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_ec01_failed_terminal_binds_completed_targeted_raw_prefix() -> None:
    transport = _FailingNativeSelectionTransport(fail_call=2)

    with pytest.raises(EC01FormalCandidateRunError) as caught:
        await _run(transport)

    failure = caught.value
    assert failure.reason_code == "MODEL_TRANSPORT_FAILED"
    assert failure.terminal is not None
    assert failure.terminal.status == "FAILED"
    assert tuple(row.ordinal for row in failure.raw_responses) == (1,)
    assert failure.repair_raw_responses == ()
    assert failure.terminal.raw_count == 1
    assert failure.terminal.raw_index_sha256 == ec01._raw_index_sha256(
        failure.raw_responses,
        failure.repair_raw_responses,
    )
    assert (
        ec01._require_terminal_raw_prefix(
            terminal=failure.terminal,
            raw_responses=failure.raw_responses,
            repair_raw_responses=failure.repair_raw_responses,
        )
        is failure.terminal
    )

    targeted = failure.raw_responses[0]
    invalid_prefixes = (
        (targeted, targeted),
        (replace(targeted, ordinal=2),),
        (replace(targeted, response_sha256="0" * 64),),
        (replace(targeted, task_key=ec01._TASK_KEYS[1]),),
    )
    for invalid_prefix in invalid_prefixes:
        with pytest.raises(EC01FormalCandidateRunError):
            ec01._require_terminal_raw_prefix(
                terminal=failure.terminal,
                raw_responses=invalid_prefix,
                repair_raw_responses=(),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind",
    (
        "cross_field",
        "unregistered_a",
        "unregistered_b",
        "unregistered_c",
    ),
)
async def test_ec01_field_local_repair_failure_becomes_typed_unknown(
    failure_kind: str,
) -> None:
    transport = _FieldLocalInvalidSelectionTransport(
        invalid_selection_id=(
            None
            if failure_kind == "cross_field"
            else "selection-" + _sha(failure_kind.encode("utf-8"))
        )
    )

    result = await _run(transport)

    assert result.terminal.status == "SUCCEEDED"
    assert result.terminal.attempted_field_count == 25
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert len(transport.target_field_ids) == 1
    target_field_id = transport.target_field_ids[0]
    execution = next(
        item
        for item in result.candidate.batch_execution.executions
        if target_field_id in item.receipt.field_ids
    )
    final = {item.field_id: item for item in execution.final_outputs}
    initial = {item.field_id: item for item in execution.initial_outputs}
    assert final[target_field_id].state == "unknown"
    assert final[target_field_id].value_snapshot is None
    assert final[target_field_id].evidence == ()
    assert execution.evidence_repair is None
    assert all(
        final[field_id] == initial[field_id]
        for field_id in execution.receipt.field_ids
        if field_id != target_field_id
    )


@pytest.mark.asyncio
async def test_ec01_all_unknown_rejects_formal_candidate() -> None:
    transport = _AllUnknownTransport()

    with pytest.raises(EC01FormalCandidateRunError) as caught:
        await _run(transport)

    assert caught.value.reason_code == "FORMAL_CANDIDATE_ALL_UNKNOWN"
    assert caught.value.terminal is not None
    assert caught.value.terminal.status == "FAILED"
    assert caught.value.terminal.attempted_field_count == 25
    assert caught.value.terminal.provider_visible_field_count == 25
    assert caught.value.terminal.code_deferred_field_count == 42
    assert caught.value.terminal.dispositioned_field_count == 67
    assert caught.value.terminal.raw_count == 8
    assert len(caught.value.raw_responses) == 8
    assert caught.value.repair_raw_responses == ()


@pytest.mark.asyncio
async def test_ec01_explicit_unknown_targeted_repair_can_seal_candidate() -> None:
    transport = _ExplicitUnknownSelectionTransport()

    result = await _run(transport)

    assert result.terminal.status == "SUCCEEDED"
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert len(transport.calls) == 8
    assert transport.target_field_id is not None
    repaired = next(
        item
        for execution in result.candidate.batch_execution.executions
        for item in execution.final_outputs
        if item.field_id == transport.target_field_id
    )
    assert repaired.state == "unknown"
    assert repaired.value_snapshot is None
    assert repaired.evidence == ()
    assert all(
        execution.evidence_repair is None
        for execution in result.candidate.batch_execution.executions
    )


@pytest.mark.asyncio
async def test_ec01_replay_accepts_typed_unknown_from_invalid_present_repair(
) -> None:
    transport = _FieldLocalInvalidSelectionTransport()
    result = await _run(transport)
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)

    assert (
        require_ec01_formal_candidate_run_815(
            run=result,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
        is result
    )

    assert len(transport.target_field_ids) == 1
    target_field_id = transport.target_field_ids[0]
    output = next(
        item
        for execution in result.candidate.batch_execution.executions
        for item in execution.final_outputs
        if item.field_id == target_field_id
    )
    assert output.state == "unknown"
    assert output.value_snapshot is None
    assert output.evidence == ()


@pytest.mark.asyncio
async def test_ec01_collects_exact8_initials_before_ordered_group_repairs() -> None:
    transport = _FieldLocalInvalidSelectionTransport(invalid_field_count=2)
    result = await _run(transport)

    assert result.terminal.status == "SUCCEEDED"
    assert len(transport.calls) == 8
    assert len(transport.target_field_ids) == 2
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert result.candidate.batch_receipt.provider_calls == 8
    assert result.candidate.batch_receipt.evidence_repairs == 0
    assert result.candidate.batch_receipt.transport_retries == 0
    assert result.candidate.batch_receipt.response_contract_repairs == 0
    final_by_field = {
        item.field_id: item
        for execution in result.candidate.batch_execution.executions
        for item in execution.final_outputs
    }
    assert all(
        final_by_field[field_id].state == "unknown"
        and final_by_field[field_id].value_snapshot is None
        and final_by_field[field_id].evidence == ()
        for field_id in transport.target_field_ids
    )


@pytest.mark.asyncio
async def test_ec01_replays_task8_multi_source_repair() -> None:
    transport = _FieldLocalInvalidSelectionTransport(invalid_field_count=3)
    result = await _run(transport)
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)

    assert result.terminal.status == "SUCCEEDED"
    assert len(result.raw_responses) == 8
    assert result.repair_raw_responses == ()
    assert len(transport.calls) == 8
    assert len(transport.target_field_ids) == 3
    assert (
        require_ec01_formal_candidate_run_815(
            run=result,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
        is result
    )
    fields = {item.field_id: item for item in result.candidate.fields}
    assert all(
        fields[field_id].state == "unknown"
        and fields[field_id].value_snapshot is None
        and fields[field_id].evidence == ()
        for field_id in transport.target_field_ids
    )

    present_field_ids = {
        item.field_id for item in result.candidate.fields if item.state == "present"
    }
    changed_ordinal, first_payload, first_known = next(
        (ordinal, payload, row)
        for ordinal, raw in enumerate(result.raw_responses)
        for payload in (json.loads(raw.response_bytes),)
        for row in payload["fields"]
        if row["field_id"] in present_field_ids
    )
    first_known.update(
        state="unknown",
        selection_ids=[],
        typed_reason="ANSWER_NOT_FOUND",
    )
    changed_bytes = _canonical_bytes(first_payload)
    changed_raw = replace(
        result.raw_responses[changed_ordinal],
        response_bytes=changed_bytes,
        byte_size=len(changed_bytes),
        response_sha256=_sha(changed_bytes),
    )
    changed_raws = tuple(
        changed_raw if ordinal == changed_ordinal else raw
        for ordinal, raw in enumerate(result.raw_responses)
    )
    changed_run = replace(
        result,
        raw_responses=changed_raws,
        terminal=result.terminal.rehash_with_raw(changed_raws),
    )
    changed_run = replace(
        changed_run, derivation_sha256=changed_run.recomputed_derivation_sha256()
    )
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=changed_run,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "RAW_PARSED_CANDIDATE_MISMATCH"


@pytest.mark.asyncio
async def test_ec01_batch_repair_fields_follow_schema_order_not_lexical_order() -> None:
    transport = _FieldLocalInvalidSelectionTransport(invalid_field_count=2)

    result = await _run(transport)

    assert len(transport.calls) == 8
    assert len(transport.target_field_ids) == 2
    assert tuple(
        field_id
        for field_id in admission.ORDERED_FIELD_IDS
        if field_id in set(transport.target_field_ids)
    ) == tuple(transport.target_field_ids)
    fields = {item.field_id: item for item in result.candidate.fields}
    assert all(
        fields[field_id].state == "unknown"
        and fields[field_id].value_snapshot is None
        and fields[field_id].evidence == ()
        for field_id in transport.target_field_ids
    )
    assert result.candidate.batch_receipt.evidence_repairs == 0


@pytest.mark.asyncio
async def test_ec01_unreadable_initial_task_repairs_its_complete_field_scope() -> None:
    transport = _MalformedNativeSelectionTransport(malformed_call=1)

    with pytest.raises(EC01FormalCandidateRunError) as caught:
        await _run(transport)

    assert caught.value.reason_code == "SELECTION_RESPONSE_SHAPE_INVALID"
    assert caught.value.terminal is not None
    assert caught.value.terminal.status == "FAILED"
    assert len(caught.value.raw_responses) == 8
    assert caught.value.repair_raw_responses == ()
    assert caught.value.candidate is None
    assert len(transport.calls) == 8


@pytest.mark.asyncio
async def test_ec01_first_structural_failure_keeps_raw_and_terminal() -> None:
    transport = _KnownTransport(include_task_key=False)
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        await _run(transport)
    assert caught.value.reason_code == "SELECTION_RESPONSE_SHAPE_INVALID"
    assert caught.value.terminal is not None
    assert caught.value.terminal.status == "FAILED"
    assert caught.value.terminal.raw_count == 8
    assert len(caught.value.raw_responses) == 8
    assert caught.value.candidate is None
    assert len(transport.calls) == 8


@pytest.mark.asyncio
async def test_ec01_invalid_fresh_identity_stops_before_transport() -> None:
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)
    transport = _KnownTransport()
    invalid_rows = (
        ("not-a-uuid", _RUN_ID, _ATTEMPT_ID, _RECEIPT_ID, _INTEGRATION_HEAD),
        (_EXPERIMENT_ID, _EXPERIMENT_ID, _ATTEMPT_ID, _RECEIPT_ID, _INTEGRATION_HEAD),
        (_EXPERIMENT_ID, _RUN_ID, _ATTEMPT_ID, _RECEIPT_ID, "old-head"),
    )
    for experiment_id, run_id, attempt_id, receipt_id, integration_head in invalid_rows:
        with pytest.raises(EC01FormalCandidateRunError) as caught:
            await run_ec01_formal_candidate_815(
                revision_set_root=_REVISION_ROOT,
                request_identity_manifest_bytes=b"",
                experiment_id=experiment_id,
                execution_identity_sha256="0" * 64,
                run_id=run_id,
                attempt_id=attempt_id,
                receipt_id=receipt_id,
                integration_head=integration_head,
                integration_tree=_INTEGRATION_TREE,
                profile=fixtures._profile(),
                policy=fixtures._policy(),
                transport=transport,
                field_contracts=contracts,
                execution_plan=plan,
            )
        assert caught.value.reason_code == "EXECUTION_IDENTITY_INVALID"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_ec01_replay_freshly_rebuilds_complete_request_manifest() -> None:
    result = await _cached_native_known_run()
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)
    manifest = json.loads(result.request_manifest_bytes)
    manifest["tasks"][0]["system"]["external_sha256"] = "0" * 64
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256")
    manifest_sha256 = _domain_hash("weknora.ec.request-preflight.v1", unsigned)
    manifest["manifest_sha256"] = manifest_sha256
    manifest_bytes = _canonical_bytes(manifest) + b"\n"
    execution_identity_sha256 = canonical_hash(
        "ec01-execution-identity.v1",
        {
            "experiment_id": result.experiment_id,
            "run_id": result.run_id,
            "attempt_id": result.attempt_id,
            "receipt_id": result.receipt_id,
            "integration_head": result.integration_head,
            "integration_tree": result.integration_tree,
            "revision_set_sha256": _REVISION_SHA256,
            "request_identity_manifest_sha256": manifest_sha256,
            "model_execution_identity_sha256": deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        },
    )
    terminal = replace(
        result.terminal,
        execution_identity_sha256=execution_identity_sha256,
        request_manifest_sha256=manifest_sha256,
    ).rehash_with_raw(result.raw_responses)
    drift = replace(
        result,
        execution_identity_sha256=execution_identity_sha256,
        request_manifest_sha256=manifest_sha256,
        request_manifest_bytes=manifest_bytes,
        terminal=terminal,
    )
    drift = replace(drift, derivation_sha256=drift.recomputed_derivation_sha256())
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=drift,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "REQUEST_MANIFEST_INVALID"


@pytest.mark.asyncio
async def test_ec01_replay_rejects_changed_or_cross_task_raw() -> None:
    result = await _cached_native_known_run()
    contracts = fixtures._schema67_contract_set()
    plan = _native_execution_plan(contracts)
    first_payload = json.loads(result.raw_responses[0].response_bytes)
    first_payload["fields"][0] = {
        "field_id": first_payload["fields"][0]["field_id"],
        "state": "unknown",
        "selection_ids": [],
        "typed_reason": "ANSWER_NOT_FOUND",
    }
    changed_bytes = _canonical_bytes(first_payload)
    changed_raw = replace(
        result.raw_responses[0],
        response_bytes=changed_bytes,
        byte_size=len(changed_bytes),
        response_sha256=_sha(changed_bytes),
    )
    rows = (changed_raw, *result.raw_responses[1:])
    changed = replace(result, raw_responses=rows, terminal=result.terminal.rehash_with_raw(rows))
    changed = replace(changed, derivation_sha256=changed.recomputed_derivation_sha256())
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=changed,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "RAW_PARSED_CANDIDATE_MISMATCH"

    raw0, raw1 = result.raw_responses[:2]
    swapped = (
        EC01RawResponse815V1(
            1, raw0.task_key, raw1.response_bytes, raw1.byte_size, raw1.response_sha256
        ),
        EC01RawResponse815V1(
            2, raw1.task_key, raw0.response_bytes, raw0.byte_size, raw0.response_sha256
        ),
        *result.raw_responses[2:],
    )
    changed = replace(
        result, raw_responses=swapped, terminal=result.terminal.rehash_with_raw(swapped)
    )
    changed = replace(changed, derivation_sha256=changed.recomputed_derivation_sha256())
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=changed,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "RAW_PARSED_CANDIDATE_MISMATCH"

    stale_identity = replace(result, execution_identity_sha256="0" * 64)
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=stale_identity,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "EXECUTION_IDENTITY_INVALID"

    stale_git = replace(result, integration_head="a" * 40)
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=stale_git,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "REQUEST_MANIFEST_INVALID"

    stale_schema = replace(result, schema_rows_sha256="0" * 64)
    stale_schema = replace(
        stale_schema,
        derivation_sha256=stale_schema.recomputed_derivation_sha256(),
    )
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=stale_schema,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "FORMAL_RUN_IDENTITY_INVALID"

    stale_terminal_schema = replace(
        result,
        terminal=replace(result.terminal, schema_rows_sha256="0" * 64),
    )
    stale_terminal_schema = replace(
        stale_terminal_schema,
        derivation_sha256=stale_terminal_schema.recomputed_derivation_sha256(),
    )
    with pytest.raises(EC01FormalCandidateRunError) as caught:
        require_ec01_formal_candidate_run_815(
            run=stale_terminal_schema,
            revision_set_root=_REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert caught.value.reason_code == "FORMAL_RUN_IDENTITY_INVALID"

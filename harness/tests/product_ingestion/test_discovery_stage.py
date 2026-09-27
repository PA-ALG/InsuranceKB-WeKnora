from __future__ import annotations

import hashlib
import json
import typing
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import HttpUrl, SecretStr

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileResult, ReviewResult
from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.discovery import DISCOVERY_PROMPT, DISCOVERY_REVIEW_PROMPT
from insurance_harness.product_ingestion.discovery_stage import run_discovery_stage
from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductRunState,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_discovery import case, prepared  # noqa: F401


class PriorArtifacts:
    def __init__(self) -> None:
        self.summary = {
            "state": "ACCEPTED",
            "reused": False,
            "reason_codes": ["DISCOVERY_ACCEPTED"],
            "counts": {
                "proposed_new": 1,
                "duplicate": 0,
                "update_proposal": 0,
                "rejected": 0,
                "published": 0,
            },
            "coverage": None,
            "accepted_member_count": 1,
        }
        self.delta = {"output": {"pages": [{"stable_key": "retained-page"}], "definitions": []}}

    def list_artifacts(self, **kwargs: object) -> list[typing.Any]:
        return [SimpleNamespace(payload=json_bytes(self.summary))]

    list_effective_artifacts = list_artifacts

    def get_artifact(self, **kwargs: typing.Any) -> SimpleNamespace:
        assert kwargs["artifact_kind"] == "compile_delta" and kwargs["run_id"] == "original"
        return SimpleNamespace(payload=json_bytes(self.delta))


async def retry(
    artifacts: typing.Any, base: typing.Any, *, processing_recovery: bool = False
) -> typing.Any:
    return await run_discovery_stage(
        service=typing.cast(ProductScopeServices, None),
        artifacts=typing.cast(ProductArtifactStore, artifacts),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot, SimpleNamespace(run_id="retry", retry_of_run_id="original")
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="a" * 64)),
        job=typing.cast(JobSnapshot, None),
        request=typing.cast(BatchConceptCompileRequest830G3V1, None),
        field_delta=typing.cast(CompileResult, {"field": "retry result"}),
        entity_id="entity",
        base=base,
        processing_recovery=processing_recovery,
    )


@pytest.mark.asyncio
async def test_accepted_discovery_not_in_published_base_cannot_be_silently_dropped() -> None:
    with pytest.raises(Exception, match="DISCOVERY_RESULT_NOT_IN_PUBLISHED_BASE"):
        await retry(PriorArtifacts(), {"published_projection": {"pages": [], "definitions": []}})


@pytest.mark.asyncio
async def test_published_discovery_is_carried_without_any_executor_call() -> None:
    artifacts = PriorArtifacts()
    result = await retry(artifacts, {"published_projection": artifacts.delta["output"]})
    summary = json.loads(
        next(row.payload for row in result.drafts if row.artifact_kind == "discovery_summary")
    )
    assert summary["reused"] is True and summary["state"] == "ACCEPTED"
    assert summary["accepted_member_count"] == 0 and summary["call_ids"] == []


@pytest.mark.asyncio
async def test_processing_recovery_reuses_failed_discovery_without_model() -> None:
    artifacts = PriorArtifacts()
    artifacts.summary.update(
        state="FAILED", reason_codes=["DISCOVERY_GENERATION_FAILED"], accepted_member_count=0
    )
    result = await retry(artifacts, {"published_projection": {}}, processing_recovery=True)
    summary = json.loads(
        next(row.payload for row in result.drafts if row.artifact_kind == "discovery_summary")
    )
    assert summary["state"] == "FAILED" and summary["reused"] is True
    assert summary["reason_codes"] == ["DISCOVERY_GENERATION_FAILED"]
    assert summary["call_ids"] == []


@pytest.mark.asyncio
async def test_recovery_keeps_unpublished_discovery_explicitly_pending() -> None:
    result = await retry(PriorArtifacts(), {"published_projection": {}}, processing_recovery=True)
    summary = json.loads(
        next(row.payload for row in result.drafts if row.artifact_kind == "discovery_summary")
    )
    assert summary["state"] == "PENDING"
    assert summary["reason_codes"] == ["DISCOVERY_REVALIDATION_REQUIRED"]
    assert summary["reused_from_run_id"] == "original"
    assert summary["accepted_member_count"] == 0 and summary["call_ids"] == []


def test_unchanged_sources_requires_exact_entity_schema_and_version_binding() -> None:
    from insurance_harness.product_ingestion.discovery_stage import _unchanged_sources

    source = dict(revision_id="revision", block_id="block", text="unchanged original")
    binding = dict(
        entity_id="entity",
        entity_version="version-1",
        schema_pack_id="schema",
        schema_version="1",
        profile_sha256="a" * 64,
    )
    request = SimpleNamespace(
        resolution_inputs=SimpleNamespace(
            corpus=SimpleNamespace(
                entries=[
                    SimpleNamespace(
                        blocks=[SimpleNamespace(model_dump=lambda **kwargs: source, **source)]
                    )
                ]
            )
        ),
        entity_bindings=[SimpleNamespace(entity_id="entity", model_dump=lambda **kwargs: binding)],
    )
    base = {"published_projection": {"sources": [source], "entity_bindings": [binding.copy()]}}
    typed_request = typing.cast(BatchConceptCompileRequest830G3V1, request)
    assert _unchanged_sources(typed_request, base) is True
    base["published_projection"]["entity_bindings"][0]["schema_version"] = "2"
    assert _unchanged_sources(typed_request, base) is False


@pytest.fixture(scope="module")
def discovery_scenario(request: typing.Any) -> tuple[typing.Any, ...]:
    scenario = request.getfixturevalue("case")
    _, request, delta, _, proposal = prepared(scenario)
    base = request.base_request
    scope = ProductScope(
        tenant_id=str(base.tenant_id),
        space_id=base.space_id,
        raw_knowledge_base_id=base.raw_kb_id,
        wiki_knowledge_base_id=base.wiki_kb_id,
    )
    template_specs: tuple[tuple[str, Literal["extract", "verify"], str, bytes], ...] = (
        ("discovery-generate", "extract", "g3-open-discovery", DISCOVERY_PROMPT),
        ("discovery-review", "verify", "g3-open-discovery-review", DISCOVERY_REVIEW_PROMPT),
    )
    templates = tuple(
        ModelTemplatePolicy(
            template_id=identity,
            role=role,
            purpose=purpose,
            run_schema_version="830-g3-v1",
            prompt_sha256=hashlib.sha256(prompt).hexdigest(),
            max_context_bytes=300000,
            max_output_tokens=16384,
        )
        for identity, role, purpose, prompt in template_specs
    )
    settings = ProductModelSettings(
        scope=scope,
        endpoint=HttpUrl("https://fixture.invalid/v1/chat/completions"),
        api_key=SecretStr("fixture-key-never-used"),
        model="gemini-3.7-flash-medium",
        policy_version="g3-user-gemini-gateway-v1",
        expires_at=datetime(2100, 1, 1, tzinfo=UTC),
        templates=templates,
        field_template_id=templates[0].template_id,
        max_request_bytes=400000,
        max_response_bytes=400000,
        timeout_seconds=60.0,
    )
    return request, delta, scenario[2], scope, settings, proposal


class ModelPackages:
    """Only the existing executor port is faked; no projector/reviewer is mocked."""

    def __init__(
        self,
        proposal: typing.Any,
        *,
        malformed: typing.Any = None,
        disposition: typing.Any = "ACCEPT",
    ) -> None:
        self.proposal = proposal
        self.malformed = malformed
        self.disposition = disposition
        self.calls: list[dict[str, typing.Any]] = []
        self.responses: dict[str, bytes] = {}
        self.review_envelope: dict[str, typing.Any] | None = None

    async def execute_stage_call(self, **kwargs: typing.Any) -> SimpleNamespace:
        ordinal = len(self.calls)
        context = json.loads(kwargs["content"])
        assert kwargs["input_sha256"] == hashlib.sha256(kwargs["content"]).hexdigest()
        assert kwargs["stage_key"] == "synthesis"
        expected_prompt = DISCOVERY_PROMPT if ordinal == 0 else DISCOVERY_REVIEW_PROMPT
        assert kwargs["prompt"] == expected_prompt
        assert ordinal < 2, "unexpected repair/retry call"
        self.calls.append(kwargs)
        if (ordinal == 0 and self.malformed == "generation") or (
            ordinal == 1 and self.malformed == "review"
        ):
            content = '{"malformed":'
        elif ordinal == 0:
            content = json_bytes(self.proposal).decode()
        else:
            score = dict(
                business_value=25,
                reuse=20,
                evidence_quality=20,
                definability=15,
                novel_identity=10,
                name_stability=10,
            )
            self.review_envelope = dict(
                contract="product-discovery-review.830.v1",
                review=dict(
                    contract="concept-review-output.830.g2.v1",
                    request_hash=context["request_hash"],
                    output_hash=context["output_hash"],
                    decision="PASS",
                    reasons=["Independent fixture review"],
                    page_scores={key: score for key in context["review_member_ids"]},
                ),
                disposition_checks=[
                    dict(
                        candidate_id=row["candidate_id"],
                        decision=self.disposition,
                        reason="Independent disposition check",
                    )
                    for row in context["dispositions"]
                ],
            )
            content = json_bytes(self.review_envelope).decode()
        raw = json_bytes(dict(choices=[dict(message=dict(content=content), finish_reason="stop")]))
        call_id = "fixture-model-call-" + str(ordinal)
        # Retention belongs to the executor; its persistent store is tested separately.
        self.responses[call_id] = raw
        return SimpleNamespace(
            state="recorded", raw=raw, call_id=call_id, diagnostic=None, policy_receipt=object()
        )


async def execute_scenario(scenario: typing.Any, **options: typing.Any) -> tuple[typing.Any, ...]:
    request, delta, entity, scope, settings, proposal = scenario
    executor = ModelPackages(proposal, **options)
    result = await run_discovery_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(configuration=SimpleNamespace(model=settings), model_executor=executor),
        ),
        artifacts=typing.cast(ProductArtifactStore, object()),
        scope=scope,
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="current-discovery", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
        field_delta=delta,
        entity_id=entity,
        base={"published_projection": {"sources": [], "entity_bindings": []}},
    )
    drafts = {row.artifact_kind: row for row in result.drafts}
    assert len(drafts) == len(result.drafts)
    summary = json.loads(drafts["discovery_summary"].payload)
    return result, drafts, summary, executor


@pytest.mark.asyncio
async def test_malformed_generation_is_failed_with_one_call_and_unchanged_fields(
    discovery_scenario: typing.Any,
) -> None:
    result, drafts, summary, executor = await execute_scenario(
        discovery_scenario,
        malformed="generation",
    )
    assert summary["state"] == "FAILED"
    assert summary["reason_codes"] == ["DISCOVERY_GENERATION_FAILED"]
    assert summary["accepted_member_count"] == 0
    assert result.state == ProductRunState.PARTIAL_SUCCESS
    assert len(executor.calls) == len(summary["call_ids"]) == 1
    assert set(executor.responses) == set(summary["call_ids"])
    assert (
        json.loads(next(iter(executor.responses.values())))["choices"][0]["message"]["content"]
        == '{"malformed":'
    )
    assert drafts["compile_delta"].payload == json_bytes(discovery_scenario[1])
    assert "discovery_review" not in drafts
    assert "discovery_proposal" not in drafts


@pytest.mark.asyncio
async def test_malformed_review_is_failed_with_two_calls_and_recorded_generation(
    discovery_scenario: typing.Any,
) -> None:
    result, drafts, summary, executor = await execute_scenario(
        discovery_scenario,
        malformed="review",
    )
    assert summary["state"] == "FAILED"
    assert summary["reason_codes"] == ["DISCOVERY_REVIEW_FAILED"]
    assert result.state == ProductRunState.PARTIAL_SUCCESS
    assert len(executor.calls) == len(summary["call_ids"]) == 2
    assert set(executor.responses) == set(summary["call_ids"])
    assert json.loads(drafts["discovery_response"].payload) == executor.proposal
    assert drafts["discovery_response"].origin_call_id == summary["call_ids"][0]
    assert drafts["discovery_proposal"].origin == ArtifactOrigin.MODEL
    assert drafts["compile_delta"].payload == json_bytes(discovery_scenario[1])
    assert "discovery_review_context" in drafts
    assert "discovery_review" not in drafts
    assert summary["counts"]["proposed_new"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "disposition,expected", [("REJECT", "REJECTED"), ("NEEDS_HUMAN", "PENDING")]
)
async def test_disposition_failure_overrides_inner_pass_without_merging(
    discovery_scenario: typing.Any,
    disposition: typing.Any,
    expected: typing.Any,
) -> None:
    result, drafts, summary, executor = await execute_scenario(
        discovery_scenario,
        disposition=disposition,
    )
    assert summary["state"] == expected
    assert summary["reason_codes"] == ["DISCOVERY_" + expected]
    assert result.state == ProductRunState.PARTIAL_SUCCESS
    assert len(executor.calls) == 2
    assert executor.review_envelope["review"]["decision"] == "PASS"
    assert (
        sum(next(iter(executor.review_envelope["review"]["page_scores"].values())).values()) == 100
    )
    assert json.loads(drafts["discovery_review_response"].payload) == executor.review_envelope
    assert json.loads(drafts["discovery_disposition"].payload)["state"] == expected
    assert "discovery_review" not in drafts
    assert summary["accepted_member_count"] == 0
    assert drafts["compile_delta"].payload == json_bytes(discovery_scenario[1])


@pytest.mark.asyncio
async def test_accepted_group_keeps_actual_review_binding_and_merged_delta(
    discovery_scenario: typing.Any,
) -> None:
    result, drafts, summary, executor = await execute_scenario(discovery_scenario)
    request, fields = discovery_scenario[:2]
    assert result.state == ProductRunState.SUCCEEDED
    assert summary["state"] == "ACCEPTED" and summary["accepted_member_count"] == 1
    assert summary["counts"]["published"] == 0
    assert len(executor.calls) == 2
    merged = CompileResult.model_validate_json(drafts["compile_delta"].payload)
    review = ReviewResult.model_validate_json(drafts["discovery_review"].payload)
    assert merged.output.fields == fields.output.fields
    assert len(merged.output.pages) == 1
    assert review.output.model_dump(mode="json") == executor.review_envelope["review"]
    assert review.execution.raw_output == compiler._canonical_json(review.output)
    assert review.execution.implementation == "platform-independent-discovery-review.830.g3.v1"
    composed = compiler.compose_batch_output(request, merged)
    assert review.output.output_hash == compiler.compile_output_hash_g3(composed)
    assert review.execution.context_hash == compiler._batch_sha256(
        "batch-concept-review-context.830.g3.v1",
        compiler.review_context_g3(request, composed),
    )
    assert drafts["discovery_review"].origin_call_id == summary["call_ids"][1]
    assert json.loads(drafts["discovery_review_response"].payload) == executor.review_envelope
    assert set(executor.responses) == set(summary["call_ids"])

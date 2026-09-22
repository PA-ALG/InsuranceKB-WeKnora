"""Contracts for the separate source discovery task."""

from __future__ import annotations

import hashlib
import json
import typing
from types import SimpleNamespace

import pytest

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput, free_page_id
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceBlock
from insurance_harness.knowledge_compiler.g3_discovery_routing import route_discovery_source_windows
from insurance_harness.product_ingestion import discovery
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.discovery_stage import (
    run_discovery_generation_stage,
    run_independent_discovery_final_review,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def test_exclusion_index_contains_schema_identity_without_field_results(case: typing.Any) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    assert index["schema_fields"]
    assert all(
        set(row) <= {"field_key", "short_title", "concept_ids"} for row in index["schema_fields"]
    )
    assert "unknown" not in json.dumps(index)
    assert all("value" not in row and "state" not in row for row in index["schema_fields"])


def test_independent_context_covers_sources_without_field_delta(case: typing.Any) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    windows = discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
        max_context_bytes=100_000,
    )
    assert windows
    assert all(len(discovery._bytes(row)) <= 100_000 for row in windows)
    assert all("comparison" not in row and "field_delta_hash" not in row for row in windows)
    assert all("source_options" in row for row in windows)
    assert len({row["window"]["window_id"] for row in windows}) == len(windows)


def test_all_original_spans_appear_in_exactly_one_window() -> None:
    sources: dict[str, SourceBlock] = {}
    for material in ("a", "b"):
        raw = (material + "条件、除外、办理流程。\n") * 450 + material + "尾部说明"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        sources[material] = SourceBlock(
            tenant_id=7,
            space_id="space",
            raw_kb_id="raw",
            knowledge_id=material,
            parse_attempt=1,
            revision_id="revision-" + material,
            source_hash=digest,
            parse_hash=digest,
            parser_identity="parser",
            block_id="block",
            page_number=1,
            text=raw,
            source_type="DOCUMENT",
        )
    windows = typing.cast(
        tuple[dict[str, typing.Any], ...],
        route_discovery_source_windows(sources, max_source_chars=2000, max_span_chars=500),
    )
    assert len(windows) > 1
    for ref, source in sources.items():
        ranges = sorted(
            (span["start"], span["end"])
            for window in windows
            for option in window["source_options"]
            if option["source_ref"] == ref
            for span in option["spans"]
        )
        assert ranges[0][0] == 0 and ranges[-1][1] == len(source.text)
        assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:], strict=False))


def test_independent_review_binds_server_final_hash_not_candidate_hash(case: typing.Any) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    with pytest.raises(ValueError, match="final composed output hash mismatch"):
        discovery.render_independent_discovery_review_context(
            request=request,
            entity_id=entity_id,
            exclusion_index=index,
            discovery_candidates={
                "definitions": [],
                "pages": [],
                "dispositions": [],
                "sources": [],
            },
            final_composed_output_hash="0" * 64,
            # Deliberately malformed boundary input: the hash fence must reject it first.
            final_composed_output=typing.cast(CompileOutput, None),
        )


def _proposal(context: typing.Any, *, title: typing.Any = "独立办理流程") -> dict[str, typing.Any]:
    span = context["source_options"][0]["spans"][0]
    quote = span["quote"][:35]
    evidence = [{"source_ref": context["source_options"][0]["source_ref"], "quote": quote}]
    body = "办理说明：" + quote
    return {
        "contract": "product-discovery-proposal.830.v1",
        "proposal": {
            "contract": "g3-d-compile-semantic-references.local.v1",
            "transformation": "SYNTHESIZE",
            "definitions": [],
            "fields": [],
            "pages": [
                {
                    "page_ref": "new-process",
                    "entity_ref": context["window"]["entity_ref"],
                    "stable_key": "independent-process",
                    "title": title,
                    "body": body,
                    "evidence": evidence,
                    "concept_refs": [],
                    "conditions": [],
                    "exceptions": [],
                    "valid_time": "",
                    "audit_reason": "Useful process",
                }
            ],
        },
        "dispositions": [
            {
                "candidate_id": "candidate-process",
                "disposition": "PROPOSED_NEW",
                "text": body,
                "evidence": evidence,
                "reason": "Separate process",
                "business_use": "Guide processing",
                "member_ref": "new-process",
                "existing_target": None,
            }
        ],
    }


def test_schema_field_name_cannot_become_free_page_even_if_unknown(case: typing.Any) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )[0]
    proposal = _proposal(context, title=index["schema_fields"][0]["short_title"])
    with pytest.raises(ValueError, match="schema field duplicate"):
        discovery.project_independent_discovery_response(
            raw=discovery._bytes(proposal),
            request=request,
            entity_id=entity_id,
            exclusion_index=index,
            context=context,
        )


def test_existing_concept_alias_cannot_become_new_free_page(case: typing.Any) -> None:
    request, _delta, entity_id = case
    existing = request.base_request.existing_definitions
    alias = "受保对象"
    definition = existing[0].model_copy(update={"aliases": (alias,)})
    base = request.base_request.model_copy(
        update={
            "existing_definitions": (definition, *existing[1:]),
        }
    )
    request = request.model_copy(update={"base_request": base})
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )[0]
    with pytest.raises(ValueError, match="existing concept duplicate"):
        discovery.project_independent_discovery_response(
            raw=discovery._bytes(_proposal(context, title=alias)),
            request=request,
            entity_id=entity_id,
            exclusion_index=index,
            context=context,
        )


def test_valid_independent_page_projects_without_field_delta(case: typing.Any) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )[0]
    candidate = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(context)),
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
        context=context,
    )
    assert candidate.output.fields == ()
    assert len(candidate.output.pages) == 1
    assert candidate.output.pages[0].evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("fenced", [False, True])
async def test_generation_stage_records_each_window_without_field_delta(
    case: typing.Any, fenced: typing.Any
) -> None:
    request, _delta, entity_id = case

    class Executor:
        def __init__(self) -> None:
            self.calls: list[dict[str, typing.Any]] = []

        async def execute_stage_call(self, **kwargs: typing.Any) -> SimpleNamespace:
            assert kwargs["stage_key"] == "discovery"
            assert len(kwargs["operation_key"]) <= 128
            context = json.loads(kwargs["content"])
            self.calls.append(kwargs)
            response = _proposal(context)
            content = json.dumps(response)
            if fenced:
                content = "```json\n" + content + "\n```"
            raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            return SimpleNamespace(
                state="recorded",
                raw=raw,
                call_id=f"call-{len(self.calls)}",
                diagnostic=None,
                policy_receipt=object(),
            )

    executor = Executor()
    settings = SimpleNamespace(
        templates=[
            SimpleNamespace(
                role="extract",
                purpose="g3-independent-discovery",
                prompt_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
                max_context_bytes=100_000,
                template_id="independent-discovery",
            )
        ]
    )
    result = await run_discovery_generation_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(configuration=SimpleNamespace(model=settings), model_executor=executor),
        ),
        artifacts=typing.cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **kwargs: ())
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="discovery-run", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
    )
    artifacts = {row.artifact_kind: row for row in result.drafts if row.artifact_key == "product"}
    assert "discovery_candidates" in artifacts and "discovery_delta" in artifacts
    assert len(executor.calls) >= 1
    coverage = json.loads(artifacts["discovery_summary"].payload)["coverage"]
    assert coverage["complete"] is True
    assert len(coverage["entities"]) == len(request.entity_bindings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_review",
    [
        False,
        None,
        [],
        "synonym_pending",
        "fenced_pass",
    ],
)
async def test_final_review_binds_actual_composed_hash_and_keeps_whole_group(
    case: typing.Any,
    invalid_review: typing.Any,
) -> None:
    request, field_delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )[0]
    candidate = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(context)),
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
        context=context,
    )
    free_output = candidate.output
    old = field_delta.output
    merged = CompileOutput(
        request_hash=old.request_hash,
        definitions=(*old.definitions, *free_output.definitions),
        fields=old.fields,
        pages=(*old.pages, *free_output.pages),
        audit=tuple(sorted((*old.audit, *free_output.audit), key=lambda row: row.key)),
        transformation="SYNTHESIZE",
    )
    delta = compiler.record_model_compile(
        request,
        merged,
        run_id="independent-final-review",
        implementation="fixture-composed-discovery",
        raw=compiler._canonical_json(merged),
    )
    final = compiler.compose_batch_output(request, delta)
    final_hash = compiler.compile_output_hash_g3(final)
    candidate_id = context["window"]["window_id"] + ":candidate-process"
    candidates = {
        "output": free_output.model_dump(mode="json"),
        "dispositions": [
            {
                **_proposal(context)["dispositions"][0],
                "candidate_id": candidate_id,
                "member_id": free_page_id(free_output.pages[0]),
            }
        ],
        "sources": [
            {
                "source_ref": context["source_options"][0]["source_ref"],
                "spans": context["source_options"][0]["spans"][:1],
            }
        ],
    }

    class Executor:
        async def execute_stage_call(self, **kwargs: typing.Any) -> SimpleNamespace:
            view = json.loads(kwargs["content"])
            assert view["output_hash"] == final_hash
            assert "fields" not in json.dumps(view["candidate_members"])
            score = dict(
                business_value=25,
                reuse=20,
                evidence_quality=20,
                definability=15,
                novel_identity=10,
                name_stability=10,
            )
            response: dict[str, typing.Any] = {
                "contract": "product-discovery-review.830.v1",
                "review": {
                    "contract": "concept-review-output.830.g2.v1",
                    "request_hash": view["request_hash"],
                    "output_hash": view["output_hash"],
                    "decision": "PASS",
                    "reasons": ["Original evidence verified"],
                    "page_scores": {key: score for key in view["review_member_ids"]},
                },
                "disposition_checks": [
                    {
                        "candidate_id": candidate_id,
                        "decision": "ACCEPT",
                        "reason": "Unique useful process",
                    }
                ],
            }
            if invalid_review == "synonym_pending":
                response["review"]["decision"] = "NEEDS_HUMAN"
                response["review"]["reasons"] = ["Possible synonym of a Schema concept"]
                response["disposition_checks"][0].update(
                    decision="NEEDS_HUMAN",
                    reason="Schema synonym uncertain",
                )
            content = (
                json.dumps(response)
                if invalid_review is False
                or invalid_review == "synonym_pending"
                or invalid_review == "fenced_pass"
                else invalid_review
            )
            if invalid_review == "fenced_pass":
                content = "```json\n" + content + "\n```"
            raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            return SimpleNamespace(
                state="recorded",
                raw=raw,
                call_id="review-call",
                diagnostic=None,
                policy_receipt=object(),
            )

    settings = SimpleNamespace(
        templates=[
            SimpleNamespace(
                role="verify",
                purpose="g3-independent-discovery-review",
                prompt_sha256=hashlib.sha256(
                    discovery.INDEPENDENT_DISCOVERY_REVIEW_PROMPT
                ).hexdigest(),
                max_context_bytes=300_000,
                template_id="independent-review",
            )
        ]
    )
    outcome = await run_independent_discovery_final_review(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(
                configuration=SimpleNamespace(model=settings), model_executor=Executor()
            ),
        ),
        artifacts=typing.cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **kwargs: ())
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="discovery-run", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
        discovery_candidates=candidates,
        final_composed_output=final,
        final_composed_output_hash=final_hash,
        exclusion_index=index,
        entity_id=entity_id,
    )
    if invalid_review is False or invalid_review == "fenced_pass":
        assert outcome.decision == "ACCEPTED"
        assert outcome.reviewed_output.pages == free_output.pages
        assert outcome.review_output is not None
        assert outcome.review_output.output_hash == final_hash
    elif invalid_review == "synonym_pending":
        assert outcome.decision == "PENDING"
        assert outcome.reviewed_output.pages == ()
        assert outcome.summary["accepted_member_count"] == 0
    else:
        assert outcome.decision == "FAILED"
        assert outcome.reviewed_output.pages == ()
        assert outcome.summary["accepted_member_count"] == 0

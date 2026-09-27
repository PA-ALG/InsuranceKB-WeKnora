"""The normal final-review path may prune explicit local failures once."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.discovery import DEPENDENCY_DISCOVERY_REVIEW_PROMPT
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from tests.product_ingestion.test_native_multiwindow_closure import aggregated_candidates

pytest_plugins = ("tests.product_ingestion.test_discovery",)


class ReviewExecutor:
    def __init__(self, mode: str = "local") -> None:
        self.mode = mode
        self.views: list[dict[str, Any]] = []

    async def execute_stage_call(self, **kwargs: Any) -> Any:
        view = json.loads(kwargs["content"])
        self.views.append(view)
        scores = {
            key: dict(
                business_value=25,
                reuse=20,
                evidence_quality=0,
                definability=15,
                novel_identity=10,
                name_stability=10,
            )
            for key in view["review_member_ids"]
        }
        checks = [
            {"candidate_id": row["candidate_id"], "decision": "ACCEPT", "reason": "reviewed"}
            for row in view["dispositions"]
        ]
        first = len(self.views) == 1
        if first and self.mode in {"local", "second_fail", "empty"}:
            failed = list(scores) if self.mode == "empty" else list(scores)[:1]
            for key in failed:
                scores[key]["business_value"] = 0
        if self.mode == "global" or (not first and self.mode == "second_fail"):
            decision = "NEEDS_HUMAN"
        else:
            decision = "PASS"
        response: dict[str, Any] = {
            "contract": "product-discovery-review.830.v1",
            "review": {
                "contract": "concept-review-output.830.g2.v1",
                "request_hash": view["request_hash"],
                "output_hash": view["output_hash"],
                "decision": decision,
                "reasons": ["reviewed"],
                "page_scores": scores,
            },
            "disposition_checks": checks,
        }
        if self.mode == "invalid":
            response["review"]["output_hash"] = "f" * 64
        raw = json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()
        return SimpleNamespace(
            state="recorded",
            raw=raw,
            call_id=f"review-{len(self.views)}",
            diagnostic=None,
            policy_receipt=object(),
        )


def services(executor: Any) -> Any:
    template = SimpleNamespace(
        role="verify",
        purpose="g3-dependency-discovery-review",
        prompt_sha256=hashlib.sha256(DEPENDENCY_DISCOVERY_REVIEW_PROMPT).hexdigest(),
        max_context_bytes=300000,
        template_id="dependency-review",
    )
    return SimpleNamespace(
        configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
        model_executor=executor,
    )


async def compile_case(case: Any, mode: str) -> tuple[Any, ReviewExecutor]:
    from insurance_harness.product_ingestion.discovery_review_compilation import (
        compile_reviewed_discovery,
    )

    request, _, _, candidates = aggregated_candidates(case)
    executor = ReviewExecutor(mode)
    result = await compile_reviewed_discovery(
        service=services(executor),
        artifacts=cast(ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **kwargs: ())),
        scope=cast(ProductScope, SimpleNamespace()),
        run=cast(ProductRunSnapshot, SimpleNamespace(run_id="pruning-run", retry_of_run_id=None)),
        stage=cast(StageSnapshot, SimpleNamespace(dependency_sha256="a" * 64)),
        job=cast(JobSnapshot, SimpleNamespace()),
        request=request,
        field_delta=case[1],
        discovery_candidates=candidates,
    )
    return result, executor


@pytest.mark.asyncio
async def test_local_failure_is_pruned_then_exact_survivor_is_reviewed(case: Any) -> None:
    result, executor = await compile_case(case, "local")
    assert len(executor.views) == 2
    assert [len(row["review_member_ids"]) for row in executor.views] == [2, 1]
    assert executor.views[0]["output_hash"] != executor.views[1]["output_hash"]
    assert result.review is not None
    assert len(result.delta.output.pages) == 1
    assert result.delta.output.fields == case[1].output.fields
    keys = [(row.artifact_kind, row.artifact_key) for row in result.drafts]
    assert len(keys) == len(set(keys))
    assert ("native_review_pruning", "product") in keys
    assert sum(kind == "discovery_final_summary" and key == "product" for kind, key in keys) == 1
    assert any(key.startswith("initial:") for _, key in keys)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,count", [("global", 1), ("empty", 1), ("invalid", 1), ("second_fail", 2)]
)
async def test_review_failures_never_cause_unbounded_or_unjustified_calls(
    case: Any, mode: str, count: int
) -> None:
    result, executor = await compile_case(case, mode)
    assert len(executor.views) == count
    assert result.review is None
    assert result.delta == case[1]


def test_final_summary_reports_additional_review_isolation() -> None:
    from insurance_harness.product_ingestion.api import combine_discovery_summaries
    from insurance_harness.product_ingestion.stages import json_bytes

    combined = combine_discovery_summaries(
        json_bytes(
            {
                "state": "PENDING",
                "dependency_policy": "candidate-dependencies.830.v1",
                "pending_candidate_count": 0,
            }
        ),
        json_bytes(
            {
                "state": "ACCEPTED",
                "dependency_policy": "candidate-dependencies.830.v1",
                "pending_candidate_count": 1,
                "accepted_member_count": 1,
            }
        ),
    )
    assert combined is not None
    summary = json.loads(combined)
    assert summary["state"] == "PENDING"
    assert summary["pending_candidate_count"] == 1

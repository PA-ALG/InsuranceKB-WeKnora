"""One persistent worker flow with relation admission/review and preparation retry.

All platform/model ports are local fixtures; this is not a live business receipt.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.progression import admit_uploads
from tests.product_ingestion.test_native_admission import response as admitted
from tests.product_ingestion.test_native_relation_policy import relation_policy
from tests.product_ingestion.test_native_runtime import NativeModel, NativePort, native_settings
from tests.product_ingestion.test_pipeline_runtime import (
    SCOPE,
    FixturePlatform,
    _base_snapshot_with_navigation,
    _compose,
    _finish,
    _sqlite_engine,
)


@pytest.mark.asyncio
async def test_relation_worker_keeps_review_across_preparation_retry(tmp_path: Path) -> None:
    base, parent = _base_snapshot_with_navigation()
    settings = native_settings(tmp_path, parent).model_copy(
        update={"product_ingestion_runtime_json": SecretStr(json.dumps(relation_policy(tmp_path)))}
    )

    class Model(NativeModel):
        def __init__(self) -> None:
            super().__init__()
            self.relation_reviews: list[dict[str, Any]] = []

        def __call__(self, request: httpx.Request) -> httpx.Response:
            context = json.loads(json.loads(request.content)["messages"][-1]["content"])
            if context.get("contract") == "native-knowledge-admission-context.830.v4":
                self.admission_requests.append(context)
                result = admitted(context, supported=True)
                result["contract"] = "native-knowledge-admission.830.v4"
                page = result["pages"][0]
                page.pop("evidence")
                for segment in page["content_provenance"]["segments"]:
                    segment.pop("evidence_indexes")
                    segment["evidence_refs"] = [
                        context["source_options"][0]["spans"][0]["evidence_ref"]
                    ]
                definition = {
                    key: deepcopy(page[key])
                    for key in (
                        "member_ref",
                        "action",
                        "expected_revision_sha256",
                        "title",
                        "body",
                        "content_provenance",
                        "audit_reason",
                    )
                }
                definition.update(
                    member_ref="d1",
                    canonical_key="runtime-relation",
                    sense_key="category",
                    aliases=[],
                )
                result["definitions"] = [definition]
                page.update(
                    stable_key="$relation",
                    concept_refs=["d1"],
                    relation={
                        "predicate": "benefit_reduced_by_advance_payment",
                        "object_ref": "d1",
                    },
                )
                result["decisions"][0]["member_refs"].append("d1")
                for decision in result["decisions"]:
                    decision["depends_on"] = []
            elif context.get("contract") == "product-discovery-review-context.830.v9":
                self.relation_reviews.append(context)
                score = dict(
                    business_value=25,
                    reuse=20,
                    evidence_quality=20,
                    definability=15,
                    novel_identity=10,
                    name_stability=10,
                )
                result = {
                    "contract": "product-discovery-review.830.v1",
                    "review": {
                        "contract": "concept-review-output.830.g2.v1",
                        "request_hash": context["request_hash"],
                        "output_hash": context["output_hash"],
                        "decision": "PASS",
                        "reasons": ["synthetic worker fixture"],
                        "page_scores": {key: score for key in context["review_member_ids"]},
                    },
                    "disposition_checks": [
                        {
                            "candidate_id": row["candidate_id"],
                            "decision": "ACCEPT",
                            "reason": "synthetic worker fixture",
                        }
                        for row in context["dispositions"]
                    ],
                }
            else:
                return super().__call__(request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(result)}}]}
            )

    class Platform(FixturePlatform):
        fail_preparation = True

        def __call__(self, request: httpx.Request) -> httpx.Response:
            if self.fail_preparation and request.url.path.endswith("/platform/preparations"):
                return httpx.Response(
                    400, json={"success": False, "error": "fixture preparation failure"}
                )
            return super().__call__(request)

    engine = _sqlite_engine(tmp_path / "relation-worker.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model, native = Platform(base), Model(), NativePort()
    native.fail = False
    runtime, context, client = await _compose(settings, factory, platform, model)
    service = context.bindings[SCOPE.space_id]
    service.platform.native_discovery = native
    service.native_admission_executor._client = client
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="relation-worker", expected_upload_count=1
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        first = await _finish(runtime, context, jobs, origin.run_id)
        assert len(model.admission_requests) == len(model.relation_reviews) == 1, (
            first.terminal_reason,
            runtime.issues,
        )
        summary = json.loads(
            context.artifacts.get_effective_artifact(
                scope=SCOPE, run_id=origin.run_id, artifact_kind="discovery_final_summary"
            ).payload
        )
        assert summary["state"] == "ACCEPTED"
        page = next(
            m for m in model.relation_reviews[0]["candidate_members"] if "business_relation" in m
        )
        assert page["evidence"]
        counts = (
            len(model.identity_requests),
            len(model.field_requests),
            len(model.native_requests),
            len(model.admission_requests),
        )
        platform.fail_preparation = False
        child = context.store.retry_processing(
            scope=SCOPE, run_id=first.run_id, expected_version=first.version
        )
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=child.run_id)
        assert "compilation" in {s.stage_key for s in plan.reused_stages}
        second = await _finish(runtime, context, jobs, child.run_id)
        assert counts == (
            len(model.identity_requests),
            len(model.field_requests),
            len(model.native_requests),
            len(model.admission_requests),
        )
        assert len(model.relation_reviews) == 1
        assert second.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}, (
            second.terminal_reason,
            runtime.issues,
        )
        summary = json.loads(
            context.artifacts.get_effective_artifact(
                scope=SCOPE, run_id=child.run_id, artifact_kind="discovery_final_summary"
            ).payload
        )
        assert summary["state"] == "ACCEPTED"
    finally:
        await runtime.close()
        await client.aclose()
        engine.dispose()

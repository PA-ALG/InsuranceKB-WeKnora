"""Exercise complementary source identity through the permanent worker pipeline."""

import json
import typing
from pathlib import Path

import pytest

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.progression import admit_uploads
from tests.product_ingestion.test_pipeline_runtime import (
    SCOPE,
    FixtureModel,
    FixturePlatform,
    _base_snapshot,
    _compose,
    _finish,
    _settings,
    _sqlite_engine,
)


class ComplementaryIdentityModel(FixtureModel):
    def _identity(self, content: typing.Any) -> typing.Any:
        semantic = super()._identity(content)
        for material in semantic["materials"]:
            entity = material["entities"][0]
            entity["identity_evidence_refs"].append("classification")
            if material["material_role"] == "terms":
                entity["issuer"] = None
                removed = {"issuer"}
            else:
                entity["product_code"] = None
                entity["filing_or_registration"] = None
                removed = {"product-code"}
                if material["material_role"] == "rate_table":
                    entity["issuer"] = None
                    removed.add("issuer")
            entity["identity_evidence_refs"] = sorted(
                set(entity["identity_evidence_refs"]) - removed
            )
            material["evidence"] = [
                row for row in material["evidence"] if row["evidence_ref"] not in removed
            ]
        return semantic


@pytest.mark.asyncio
async def test_complementary_identity_reaches_publication_without_refilling_fields(
    tmp_path: Path,
) -> None:
    base, base_candidate = _base_snapshot()
    settings = _settings(tmp_path, base_candidate)
    engine = _sqlite_engine(tmp_path / "joint-identity.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), ComplementaryIdentityModel()
    runtime, context, client = await _compose(settings, factory, platform, model)
    try:
        run = context.store.create_run(
            scope=SCOPE, idempotency_key="joint-identity", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, run.run_id)
        terminal = await _finish(runtime, context, jobs, run.run_id)
        assert terminal.state is ProductRunState.PARTIAL_SUCCESS, terminal.terminal_reason
        assert len(model.identity_requests) == 1
        assert platform.activations == 1
        identity = json.loads(
            context.artifacts.get_artifact(
                scope=SCOPE, run_id=run.run_id, artifact_kind="identity", artifact_key="product"
            ).payload
        )
        assert identity["resolution"]["compiler_version"] == (
            "batch-entity-resolution-compiler.830.g3.v3"
        )
        proposals = identity["proposals"]["proposals"]
        terms = next(row for row in proposals if row["material_role"] == "terms")
        assert terms["entities"][0]["issuer"] is None
        adaptation = context.artifacts.get_artifact(
            scope=SCOPE,
            run_id=run.run_id,
            artifact_kind="identity_adaptation",
            artifact_key="product",
        )
        assert adaptation.origin_call_id
        assert len(base_candidate.request.entity_bindings) == 5
        assert platform.candidate is not None
        assert len(platform.candidate.request.entity_bindings) == 6
    finally:
        await runtime.close()
        await client.aclose()
        engine.dispose()

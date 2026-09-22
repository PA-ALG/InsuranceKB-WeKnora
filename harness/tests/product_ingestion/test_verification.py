import asyncio
import hashlib
import json
import time
import typing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import httpx
import pytest

from insurance_harness.jobs import NonRetryableJobError, RetryableJobError
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    _batch_sha256,
    _without_hash,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceIdentity
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform_client import PlatformClient
from insurance_harness.product_ingestion.signing import canonical
from insurance_harness.product_ingestion.verification import verify_published_product


@lru_cache(maxsize=1)
def fixture_candidate() -> typing.Any:
    path = Path(__file__).parents[1] / "fixtures/batch_concept_compile_830_g3/candidate.json"
    return BatchConceptCandidateBundle830G3V1.model_validate_json(path.read_bytes())


def setup(
    *,
    entity: str = "ping-an-e-sheng-bao",
    change: typing.Any = None,
    status: int | None = None,
    candidate: typing.Any = None,
) -> typing.Any:
    candidate = candidate or fixture_candidate()
    base = candidate.request.base_request
    scope = ProductScope(
        tenant_id=str(base.tenant_id),
        space_id=base.space_id,
        raw_knowledge_base_id=base.raw_kb_id,
        wiki_knowledge_base_id=base.wiki_kb_id,
    )
    scope_wire = {
        "tenant_id": base.tenant_id,
        "space_id": base.space_id,
        "raw_kb_id": base.raw_kb_id,
        "wiki_kb_id": base.wiki_kb_id,
    }
    receipt = {**scope_wire, "release_id": "fixture-release", "activation_epoch": 10}
    members = {
        m.member_id: m.model_dump(mode="json")
        for m in candidate.page_manifest.members
        if m.owner_id == entity
    }
    sources = {(s.revision_id, s.block_id): s for s in base.sources}
    seen = []

    def evidence_map(member: typing.Any) -> typing.Any:
        result = {}
        for e in member["payload"].get("evidence", []):
            preimage = [
                candidate.candidate_hash,
                member["member_id"],
                e["revision_id"],
                e["block_id"],
                e["page_number"],
                e["start"],
                e["end"],
                e["quote_hash"],
            ]
            result["citation-" + hashlib.sha256(canonical(preimage)).hexdigest()[:24]] = e
        return result

    def respond(request: typing.Any) -> typing.Any:
        seen.append(request)
        if status:
            return httpx.Response(status, text="private source fixture-secret")
        suffix = request.url.path.split("/raw/" + base.raw_kb_id, 1)[1]
        data: typing.Any
        if suffix == "/current":
            data = {"release_id": receipt["release_id"], "activation_epoch": 10}
        elif suffix.endswith("/search"):
            assert request.url.params["q"] == next(
                b.display_name for b in candidate.request.entity_bindings if b.entity_id == entity
            )
            data = [
                {
                    "kind": m["kind"],
                    "logical_slug": m["member_id"],
                    "revision_id": candidate.candidate_hash,
                    "payload": m["payload"],
                }
                for m in members.values()
                if m["kind"] == "entity_overview"
            ]
        else:
            assert request.url.params["release_id"] == receipt["release_id"]
            member_id = suffix.split("/concept-pages/")[1].split("/")[0]
            member = deepcopy(members[member_id])
            evidence = evidence_map(member)
            if "/citations/" not in suffix:
                data = {
                    "contract": "concept-page-read.830.g2.v1",
                    "read_mode": "pinned",
                    "release_id": receipt["release_id"],
                    "activation_epoch": 10,
                    "candidate_hash": candidate.candidate_hash,
                    "space_id": base.space_id,
                    "raw_kb_id": base.raw_kb_id,
                    "wiki_kb_id": base.wiki_kb_id,
                    "member": member,
                    "related_members": [],
                    "citations": [
                        {"citation_id": cid, "page_number": e["page_number"], "quote": e["quote"]}
                        for cid, e in evidence.items()
                    ],
                }
            else:
                cid = suffix.split("/citations/")[1].split("/")[0]
                e = evidence[cid]
                source = sources[e["revision_id"], e["block_id"]]
                data = {
                    "contract": "concept-citation-content-authority.830.g3.v1",
                    "release_id": receipt["release_id"],
                    "activation_epoch": 10,
                    "candidate_hash": candidate.candidate_hash,
                    "member_id": member_id,
                    "citation_id": cid,
                    "scope": scope_wire,
                    "source": {k: e[k] for k in SourceIdentity.model_fields},
                    "revision_source": {"file_sha256": e["source_hash"], "page_count": 100},
                    "block_id": e["block_id"],
                    "page_number": e["page_number"],
                    "quote_hash": e["quote_hash"],
                    "opaque_token": "fixture-token-not-for-report",
                    "expires_at_unix": int(time.time()) + 300,
                    "bbox": {
                        "coordinate_space": "normalized_0_1e6_top_left",
                        "x0": 1,
                        "y0": 2,
                        "x1": 3,
                        "y1": 4,
                    },
                    "source_locator": {
                        "contract": "concept-source-block-locator.830.g3.v1",
                        "source_block_sha256": hashlib.sha256(source.text.encode()).hexdigest(),
                        "source_page_number": e["page_number"],
                        "start": e["start"],
                        "end": e["end"],
                        "block_global_start": 0,
                        "global_start": e["start"],
                        "global_end": e["end"],
                        "actual_page_number": e["page_number"],
                    },
                }
        if change:
            change(suffix, data)
        return httpx.Response(200, json={"success": True, "data": data})

    api = PlatformClient(
        base_url="http://fixture",
        credential="fixture-secret",
        scope=scope,
        timeout_seconds=3,
        max_response_bytes=2_000_000,
        transport=httpx.MockTransport(respond),
    )

    async def run() -> typing.Any:
        try:
            return await verify_published_product(
                platform=api,
                scope=scope,
                receipt=receipt,
                candidate=candidate,
                current_entity_ids=(entity,),
            )
        finally:
            await api.close()

    return run, seen, members, candidate


def test_published_product_uses_real_typed_fixture_and_only_current_entity_reads() -> None:
    run, seen, members, _ = setup()
    report = asyncio.run(run())
    fields = [m for m in members.values() if m["kind"] == "field_assertion"]
    assert report["status"] == "PASS"
    assert report["field_count"] == len(fields)
    assert report["verified_field_count"] == 3
    assert report["citation_count"] == sum(len(m["payload"]["evidence"]) for m in fields)
    assert len([r for r in seen if r.url.path.endswith("/current")]) == 2
    assert all(r.method == "GET" and r.url.host == "fixture" for r in seen)
    assert "fixture-token" not in json.dumps(report)
    assert "fixture-secret" not in json.dumps(report)


def test_unknown_fields_are_accepted_without_citation_calls() -> None:
    entity = next(
        b.entity_id
        for b in fixture_candidate().request.entity_bindings
        if b.display_name == "平安重大疾病保险示例"
    )
    run, seen, _, _ = setup(entity=entity)
    report = asyncio.run(run())
    assert report["status"] == "PASS" and report["verified_field_count"] == 0
    assert report["missing_field_count"] == report["field_count"]
    assert not any("/citations/" in r.url.path for r in seen)


@pytest.mark.parametrize(
    "fault",
    ["head", "search", "scope", "payload", "missing-citation", "source", "offset", "pdf-page"],
)
def test_read_or_evidence_drift_never_produces_pass(fault: typing.Any) -> None:
    def change(suffix: str, data: typing.Any) -> None:
        if fault == "head" and suffix == "/current":
            data["release_id"] = "different"
        if fault == "search" and suffix.endswith("/search"):
            data.clear()
        if (
            "/concept-pages/" in suffix
            and "/citations/" not in suffix
            and data["member"]["kind"] == "field_assertion"
        ):
            if fault == "scope":
                data["raw_kb_id"] = "different"
            if fault == "payload":
                data["member"]["payload"]["value"] = "private unverified value"
            if fault == "missing-citation" and data["citations"]:
                data["citations"].pop()
        if "/citations/" in suffix:
            if fault == "source":
                data["source"]["knowledge_id"] = "different"
            if fault == "offset":
                data["source_locator"]["start"] += 1
            if fault == "pdf-page":
                data["source_locator"]["actual_page_number"] = 101

    run, _, _, _ = setup(change=change)
    with pytest.raises(NonRetryableJobError, match="VERIFY_") as error:
        asyncio.run(run())
    assert "private" not in str(error.value)


def test_typed_source_mutation_is_rejected_before_transport() -> None:
    original = fixture_candidate()
    field = next(
        m
        for m in original.page_manifest.members
        if m.owner_id == "ping-an-e-sheng-bao"
        and m.kind == "field_assertion"
        and m.payload["state"] == "present"
    )
    e = field.payload["evidence"][0]
    sources = tuple(
        s.model_copy(update={"text": "changed original"})
        if (s.revision_id, s.block_id) == (e["revision_id"], e["block_id"])
        else s
        for s in original.request.base_request.sources
    )
    base = original.request.base_request.model_copy(update={"sources": sources})
    request = original.request.model_copy(update={"base_request": base})
    candidate = original.model_copy(update={"request": request})
    run, seen, _, _ = setup(candidate=candidate)
    with pytest.raises(NonRetryableJobError, match="VERIFY_SOURCE"):
        asyncio.run(run())
    assert not seen


@pytest.mark.parametrize("status,error", [(503, RetryableJobError), (403, NonRetryableJobError)])
def test_transport_errors_remain_explicit_without_retry(
    status: typing.Any, error: typing.Any
) -> None:
    run, seen, _, _ = setup(status=status)
    with pytest.raises(error):
        asyncio.run(run())
    assert len(seen) == 1


def test_head_drift_after_evidence_reads_fails_without_changing_publication() -> None:
    current_reads = 0

    def change(suffix: str, data: typing.Any) -> None:
        nonlocal current_reads
        if suffix == "/current":
            current_reads += 1
            if current_reads == 2:
                data["activation_epoch"] += 1

    run, seen, _, _ = setup(change=change)
    with pytest.raises(NonRetryableJobError, match="VERIFY_CURRENT_RELEASE_MISMATCH"):
        asyncio.run(run())
    assert current_reads == 2
    assert any("/citations/" in request.url.path for request in seen)
    assert all(request.method == "GET" for request in seen)


def test_existing_unique_quote_authority_needs_no_invented_g3_locator() -> None:
    def change(suffix: str, data: typing.Any) -> None:
        if "/citations/" in suffix:
            data["contract"] = "concept-citation-content-authority.830.g2.v1"
            data.pop("source_locator")

    run, _, _, _ = setup(change=change)
    assert asyncio.run(run())["status"] == "PASS"


def test_candidate_validation_keeps_worker_heartbeat_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.product_ingestion import verification

    run, _, _, _ = setup()
    original = _batch_sha256
    ticks: list[int] = []
    observed: list[bool] = []

    def slow_hash(*args: typing.Any) -> typing.Any:
        before = len(ticks)
        time.sleep(0.08)
        observed.append(len(ticks) > before)
        return original(*args)

    monkeypatch.setattr(verification, "_batch_sha256", slow_hash)

    async def exercise() -> None:
        async def heartbeat() -> None:
            while True:
                ticks.append(True)
                await asyncio.sleep(0.005)

        task = asyncio.create_task(heartbeat())
        try:
            assert (await run())["status"] == "PASS"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())
    assert observed == [True]


def test_exact_duplicate_evidence_uses_one_citation() -> None:
    original = fixture_candidate()
    target = next(
        m
        for m in original.page_manifest.members
        if m.owner_id == "ping-an-e-sheng-bao"
        and m.kind == "field_assertion"
        and m.payload["state"] == "present"
    )
    payload = deepcopy(target.payload)
    payload["evidence"].append(deepcopy(payload["evidence"][0]))
    members = tuple(
        m.model_copy(update={"payload": payload}) if m.member_id == target.member_id else m
        for m in original.page_manifest.members
    )
    candidate = original.model_copy(
        update={"page_manifest": original.page_manifest.model_copy(update={"members": members})}
    )
    candidate = candidate.model_copy(
        update={
            "candidate_hash": _batch_sha256(
                candidate.contract, _without_hash(candidate, "candidate_hash")
            )
        }
    )
    run, _, _, _ = setup(candidate=candidate)
    assert asyncio.run(run())["status"] == "PASS"

"""PV-4a acceptance: the metadata publish path (PV-4 Spec §3.3, appendix A §2).

Protected file: written by Claude. From Active and a v2 registry the planner changes only the
registered version entities (identity, sale period, family) and their claims
(`product_version_ref`), adds the `supersedes` relations of unique predecessors and removes stale
ones; every other member is untouched. Bundles stay under the size limit, a product's entity comes
before its claims, and the live loop replans on the Active of each step, stops on a platform error
and never runs past its bundle limit.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import (
    Candidate,
    Decision,
    DecisionInput,
    Head,
    PlatformError,
    Release,
    ReleaseMember,
)
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.enums import ClaimState, Origin, SourceClass, UnknownReason
from insurance_harness.contracts.knowledge import Claim, Entity, Relation, supersedes_relation_id
from insurance_harness.ingest.identity_refresh import (
    RefreshError,
    plan_refresh,
    refresh_bundles,
    run_refresh,
)
from insurance_harness.ingest.product_versions import MetadataBasis, ProductFamily, ProductVersion
from insurance_harness.ingest.registry import ProductRegistry
from tests.ingest.upload_helpers import entry, registry

COMMIT = "f" * 40
BASIS = MetadataBasis(
    repository="PA-ALG/pingan-life-product-documents",
    commit=COMMIT,
    catalog_sha256="e" * 64,
    synced_at="2026-11-01T08:00:00Z",
)
ALLOWED_ENTITY = {"lifecycle", "product_family"}


def _member(kind: str, slug: str, payload: dict[str, Any]) -> ReleaseMember:
    return ReleaseMember(
        kind=kind,
        logical_slug=slug,
        member_digest=member_digest(payload),
        payload=payload,
        evidence_refs=[],
        access_scope="space",
    )


def entity_member(entity_id: str, **identifiers: str) -> ReleaseMember:
    payload = Entity(
        entity_id=entity_id,
        entity_type="product",
        names=[f"产品{entity_id}"],
        identifiers=identifiers or {"product_code": entity_id},
        classification_labels=["demo"],
        owner_module="harness",
    ).model_dump(mode="json")
    return _member("entity", f"entity/{entity_id}", payload)


def claim_member(subject: str, field: str) -> ReleaseMember:
    key = f"{subject}/{field}"
    payload = Claim(
        claim_id=key,
        logical_key=key,
        subject_ref=subject,
        predicate=field,
        state=ClaimState.UNKNOWN,
        origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=UnknownReason.NOT_IN_MATERIAL,
    ).model_dump(mode="json")
    return _member("claim", key, payload)


def relation_member(newer: str, older: str, predicate: str = "supersedes") -> ReleaseMember:
    if predicate == "supersedes":
        rid = supersedes_relation_id(newer, older)
    else:
        rid = f"{predicate}/{newer}"
    relation = Relation.model_validate(
        {"relation_id": rid, "predicate": predicate, "from": newer, "to": older}
    )
    payload = relation.model_dump(mode="json")
    return _member("relation", f"relation/{rid}", payload)


def active(*members: ReleaseMember, epoch: int = 3) -> Release:
    ordered = sorted(members, key=lambda m: m.logical_slug)
    return Release(id=f"release-{epoch}", epoch=epoch, members=ordered)


def v2(**versions: ProductVersion | None) -> ProductRegistry:
    value = registry(p1828=entry("1828", "terms"), p1814=entry("1814", "terms"))
    products = {
        pid: product.model_copy(update={"version": versions.get(f"p{pid}")})
        for pid, product in value.products.items()
    }
    return value.model_copy(
        update={"contract": "product-registry.v2", "products": products, "metadata_basis": BASIS}
    )


NEWER = ProductVersion(
    version_key="2635-1",
    plan_code="2635",
    version_no=1,
    sale_start="2024-09-01",
    source_status="on_sale",
    family=ProductFamily(key="智盈倍护", display_name="智盈倍护"),
    predecessor="1814",
)
OLDER = ProductVersion(
    version_key="1814-1",
    plan_code="1814",
    version_no=1,
    sale_start="2024-04-23",
    sale_end="2024-09-01",
    source_status="discontinued",
    family=ProductFamily(key="智盈倍护", display_name="智盈倍护"),
)


def base_release() -> Release:
    return active(
        entity_member("1828"),
        entity_member("1814"),
        entity_member("other"),
        claim_member("1828", "waiting_period"),
        claim_member("1828", "grace_period"),
        claim_member("1814", "waiting_period"),
        claim_member("other", "waiting_period"),
        relation_member("1828", "9999"),  # stale: 9999 is no predecessor
        relation_member("1828", "concept-x", predicate="relates_to_concept"),
        _member("navigation", "navigation/main", {"navigation_id": "main"}),
        _member("presentation_profile", "presentation/p", {"profile_id": "p"}),
    )


def changed(plan: Any) -> dict[str, dict[str, Any]]:
    return {m.logical_slug: m.payload for m in plan.members}


def test_the_plan_touches_only_registered_versions_and_their_claims() -> None:
    a = base_release()
    plan = plan_refresh(a, v2(p1828=NEWER, p1814=OLDER))
    out = changed(plan)
    assert set(out) == {
        "entity/1828",
        "entity/1814",
        "1828/waiting_period",
        "1828/grace_period",
        "1814/waiting_period",
        "relation/supersedes/1828/1814",
    }
    assert plan.removals == ("relation/supersedes/1828/9999",)
    assert out["entity/1828"]["identifiers"] == {
        "product_code": "2635",
        "version_key": "2635-1",
        "filing_no": entry("1828", "terms").clause_codes[0],
    }
    assert out["entity/1828"]["lifecycle"]["sale_start"] == "2024-09-01"
    assert out["entity/1828"]["lifecycle"]["basis_commit"] == COMMIT
    assert out["entity/1814"]["product_family"] == {"key": "智盈倍护", "display_name": "智盈倍护"}
    for slug in ("1828/waiting_period", "1828/grace_period", "1814/waiting_period"):
        assert out[slug]["product_version_ref"] == out[slug]["subject_ref"]
    assert out["relation/supersedes/1828/1814"]["from"] == "1828"
    assert out["relation/supersedes/1828/1814"]["to"] == "1814"
    assert plan.counts == {
        "entities": 2,
        "claims": 3,
        "relations_added": 1,
        "relations_removed": 1,
    }
    assert not plan.noop


def test_changed_members_keep_every_other_key_and_their_envelope() -> None:
    a = base_release()
    by_slug = {m.logical_slug: m for m in a.members}
    plan = plan_refresh(a, v2(p1828=NEWER, p1814=OLDER))
    for new in plan.members:
        old = by_slug.get(new.logical_slug)
        if old is None:
            continue
        assert (new.kind, new.access_scope, new.evidence_refs) == (
            old.kind,
            old.access_scope,
            old.evidence_refs,
        )
        assert new.member_digest == member_digest(new.payload)
        before, after = dict(old.payload), dict(new.payload)
        if new.kind == "claim":
            before.pop("product_version_ref"), after.pop("product_version_ref")
        else:
            for key in ALLOWED_ENTITY:
                before.pop(key, None), after.pop(key, None)
            before.pop("identifiers"), after.pop("identifiers")
        assert before == after


def test_an_unversioned_entry_keeps_its_entity_but_gets_claim_refs() -> None:
    plan = plan_refresh(base_release(), v2(p1828=NEWER, p1814=None))
    out = changed(plan)
    assert "entity/1814" not in out  # no version record: today's identity is already published
    assert out["1814/waiting_period"]["product_version_ref"] == "1814"


def test_an_applied_refresh_is_a_noop_and_a_stale_relation_alone_is_not() -> None:
    registry_v2 = v2(p1828=NEWER, p1814=OLDER)
    a = base_release()
    plan = plan_refresh(a, registry_v2)
    applied = _apply(a, plan.members, plan.removals)
    assert plan_refresh(applied, registry_v2).noop
    with_stale = _apply(applied, [relation_member("1814", "1828")], ())
    stale = plan_refresh(with_stale, registry_v2)
    assert not stale.noop
    assert stale.members == ()
    assert stale.removals == ("relation/supersedes/1814/1828",)


def test_a_v1_registry_is_refused() -> None:
    with pytest.raises(RefreshError) as refused:
        plan_refresh(base_release(), registry(p1828=entry("1828", "terms")))
    assert refused.value.code == "REGISTRY_NOT_V2"


def test_bundles_stay_under_the_limit_and_keep_a_product_together() -> None:
    a = base_release()
    plan = plan_refresh(a, v2(p1828=NEWER, p1814=OLDER))
    whole = refresh_bundles(plan, a.head, compiler_identity="harness/identity_refresh")
    assert len(whole) == 1
    limit = _size(whole[0]) // 2
    split = refresh_bundles(
        plan, a.head, compiler_identity="harness/identity_refresh", max_bytes=limit
    )
    assert len(split) >= 2
    seen: list[str] = []
    for bundle in split:
        assert _size(bundle) <= limit
        assert bundle.origin == Origin.IDENTITY_REFRESH
        assert (bundle.base_release_id, bundle.base_epoch) == (a.id, a.epoch)
        assert bundle.review_plan == []
        seen += [m.logical_slug for m in bundle.members]
        if "relation/supersedes/1828/9999" in bundle.removals:
            # A product's relation changes travel with its entity.
            slugs = [m.logical_slug for m in bundle.members]
            assert "entity/1828" in slugs and "relation/supersedes/1828/1814" in slugs
    assert sorted(seen) == sorted(m.logical_slug for m in plan.members)
    assert sorted(r for b in split for r in b.removals) == list(plan.removals)
    for product in ("1828", "1814"):
        assert seen.index(f"entity/{product}") < seen.index(f"{product}/waiting_period")


class FakeClient:
    """Applies activated bundles to an in-memory Head like the platform's materialize."""

    def __init__(self, start: Release, fail_on: int | None = None) -> None:
        self.current, self.fail_on = start, fail_on
        self.bundles: dict[str, CandidateBundle] = {}
        self.decisions: list[DecisionInput] = []
        self.activations = 0

    def active(self, space_id: str) -> Release:
        return self.current

    def submit(self, space_id: str, bundle: CandidateBundle) -> Candidate:
        cid = f"c-{len(self.bundles) + 1}"
        self.bundles[cid] = bundle
        return Candidate(id=cid, status="created")

    def decide(self, space_id: str, candidate_id: str, decision: DecisionInput) -> Decision:
        self.decisions.append(decision)
        return Decision(
            id=f"d-{candidate_id}", candidate_id=candidate_id, outcome="approve", digest="x"
        )

    def activate(self, space_id: str, candidate_id: str, decision_id: str) -> Release:
        if self.fail_on is not None and self.activations + 1 == self.fail_on:
            raise PlatformError("NEEDS_REBASE")
        bundle = self.bundles[candidate_id]
        assert (bundle.base_release_id, bundle.base_epoch) == (self.current.id, self.current.epoch)
        members = [
            ReleaseMember(**m.model_dump(mode="json")) for m in bundle.members
        ]
        self.current = _apply(self.current, members, bundle.removals)
        self.activations += 1
        return self.current

    def release(self, space_id: str, release_id: str) -> Release:
        return self.current


def test_the_live_loop_replans_each_step_until_nothing_is_left() -> None:
    registry_v2 = v2(p1828=NEWER, p1814=OLDER)
    a = base_release()
    plan = plan_refresh(a, registry_v2)
    limit = _size(refresh_bundles(plan, a.head, compiler_identity="x")[0]) // 2
    client = FakeClient(a)
    summary = run_refresh(client, registry_v2, live=True, max_bytes=limit)  # type: ignore[arg-type]
    assert client.activations >= 2
    assert summary["releases"] == [f"release-{3 + n}" for n in range(1, client.activations + 1)]
    assert "stopped" not in summary
    assert plan_refresh(client.current, registry_v2).noop
    assert {(d.outcome, d.mode, d.policy_ref) for d in client.decisions} == {
        ("approve", "machine", f"identity_refresh@{COMMIT}")
    }


def test_a_dry_run_sends_nothing() -> None:
    client = FakeClient(base_release())
    summary = run_refresh(client, v2(p1828=NEWER, p1814=OLDER), live=False)  # type: ignore[arg-type]
    assert client.bundles == {} and client.decisions == []
    assert summary["dry_run"] is True
    assert summary["bundles"] == 1
    assert summary["entities"] == 2 and summary["claims"] == 3


def test_a_platform_error_stops_the_loop_with_its_code() -> None:
    client = FakeClient(base_release(), fail_on=1)
    summary = run_refresh(client, v2(p1828=NEWER, p1814=OLDER), live=True)  # type: ignore[arg-type]
    assert summary["stopped"] == "NEEDS_REBASE"
    assert client.activations == 0


def test_the_loop_never_runs_past_its_bundle_limit() -> None:
    registry_v2 = v2(p1828=NEWER, p1814=OLDER)
    a = base_release()
    first = refresh_bundles(plan_refresh(a, registry_v2), a.head, compiler_identity="x")[0]
    limit = _size(first) // 2
    client = FakeClient(a)
    summary = run_refresh(
        client, registry_v2, live=True, max_bytes=limit, max_bundles=1  # type: ignore[arg-type]
    )
    assert client.activations == 1
    assert summary["stopped"] == "MAX_BUNDLES"


def _apply(
    release: Release, members: Any, removals: Any
) -> Release:
    by_slug = {m.logical_slug: m for m in release.members}
    for slug in removals:
        del by_slug[slug]
    for m in members:
        by_slug[m.logical_slug] = ReleaseMember(**m.model_dump(mode="json"))
    return active(*by_slug.values(), epoch=release.epoch + 1)


def _size(bundle: CandidateBundle) -> int:
    return len(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))


def test_the_head_type_is_the_clients() -> None:
    assert base_release().head == Head(release_id="release-3", epoch=3)

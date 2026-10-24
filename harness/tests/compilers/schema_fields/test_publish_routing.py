"""RV1 acceptance: publishing with --route (Spec §3.4, §4).

Protected file: written by Claude. Without an admitted pack the product is only submitted and waits
in the human queue with its reason codes; an admitted, fully scored product goes live as machine
review with its policy reference; a claim below its field threshold queues the whole product.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields import publish as command
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.ingest import source_map as source_map_module

SHA = "ab" * 32
PAGES = [
    PageText(
        "保险条款.pdf",
        SHA,
        1,
        "1.4 等待期\n自本合同生效之日起90日内为等待期。\n本合同不设宽限期。\n阅读指引\n",
    )
]
SOURCE = SegmentedSource(PAGES)
CATALOG = SCHEMA_PACK_CATALOG
FIELDS = [("term_a", "期限甲", ["D1P1S1"], "90日"), ("term_b", "期限乙", ["D1P1S2"], None)]
REVIEWER, AT = "deepseek-flash@review-v1", "2026-10-17T12:00:00Z"


class Reader:
    def __init__(self, base_url: str, api_key: str) -> None:
        pass

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        return PAGES


class Platform:
    """Records requests; activation publishes exactly the members that were submitted."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, Any]] = []
        self.members: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/space-1/")
        self.seen.append((request.method, path, body))
        if path == "releases/active":
            return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
        if path == "candidates":
            assert isinstance(body, dict)
            self.members = body["members"]
            return ok({"id": "cand_1", "status": "created"}, 201)
        if path == "candidates/cand_1/decisions":
            return ok(
                {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve", "digest": "e" * 64}
            )
        return ok({"id": "rel_1", "epoch": 1, "candidate_id": "cand_1", "members": self.members})


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


@pytest.fixture
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Platform:
    fields = [
        FieldResult(
            field_key=key,
            state="present" if value else "absent_explicitly",
            value=value,
            evidence=SOURCE.evidence(ids),
            segment_ids=ids,
        )
        for key, _, ids, value in FIELDS
    ]
    output = CompileOutput(
        pack_id="pack", entity_id="1828", model="m", fields=fields, cards_version="v"
    )
    (tmp_path / "1828").mkdir()
    (tmp_path / "1828" / "output.json").write_text(output.model_dump_json(), encoding="utf-8")
    source_map = {
        "space_id": "space-1",
        "products": {"1828": [{"knowledge_id": "k-1", "parse_attempt": 2}]},
    }
    (tmp_path / "map.json").write_text(json.dumps(source_map), encoding="utf-8")
    titles = [{"field_key": key, "short_title": title} for key, title, _, _ in FIELDS]
    entry = {
        "pack": {
            "schema_pack_id": "pack",
            "entity_type": "insurance_product",
            "applicable_classifications": ["demo_class"],
            "presentation_profile_ref": {"profile_id": "profile_pack", "profile_version": "1"},
            "fields": [{**title, "description": "d"} for title in titles],
        },
        "profile": {
            "profile_id": "profile_pack",
            "profile_version": "1",
            "profile_sha256": "cd" * 32,
            "schema_pack_id": "pack",
            "sections": [{"section_key": "terms", "display_name": "条款", "fields": titles}],
        },
    }
    catalog = tmp_path / "repo" / CATALOG
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps({"entries": [entry]}, ensure_ascii=False), encoding="utf-8")
    product = tmp_path / "repo" / "dataset" / "shouxian_product" / "演示"
    product.mkdir(parents=True)
    meta = {"planCode": "1828", "clauseName": "演示产品"}
    (product / "product_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    monkeypatch.setattr(source_map_module, "WeKnoraSourcePages", Reader)
    server = Platform()
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    return server


def routed(
    tmp_path: Path, policy: dict[str, Any] | None, scores: dict[str, float] | None
) -> list[str]:
    args = [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--source-map",
        str(tmp_path / "map.json"),
    ]
    args += ["--repo", str(tmp_path / "repo"), "--route"]
    if policy is not None:
        (tmp_path / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
        args += ["--review-policy", str(tmp_path / "policy.json")]
    if scores is not None:
        document = {"reviewer": REVIEWER, "reviewed_at": AT, "scores": scores}
        (tmp_path / "scores.json").write_text(json.dumps(document), encoding="utf-8")
        args += ["--scores", str(tmp_path / "scores.json")]
    return args


ADMITTED = {"version": "test", "admitted_packs": ["pack"], "thresholds": {"pack": {"default": 0.9}}}
FULL = {"1828/term_a": 0.95, "1828/term_b": 0.9}


def claims_of(platform: Platform) -> dict[str, dict[str, Any]]:
    submitted = platform.seen[1][2]
    return {m["logical_slug"]: m["payload"] for m in submitted["members"] if m["kind"] == "claim"}


def test_routing_without_an_admitted_pack_leaves_the_product_in_the_human_queue(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    assert command.main(routed(tmp_path, None, None)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["review"] == "human"
    assert summary["reasons"] == ["PACK_NOT_ADMITTED", "SCORES_MISSING", "THRESHOLD_MISSING"]
    assert (summary["decision_id"], summary["release_id"]) == (None, None)
    assert [path for _, path, _ in platform.seen] == ["releases/active", "candidates"]
    assert {claim["review"]["mode"] for claim in claims_of(platform).values()} == {"human"}
    assert platform.seen[1][2]["review_plan"] == [
        {"mode": "human", "policy_ref": None, "sample_size": None}
    ]


def test_an_admitted_and_fully_scored_product_goes_live_as_machine_review(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    assert command.main(routed(tmp_path, ADMITTED, FULL)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["review"] == "machine" and "reasons" not in summary
    assert (summary["decision_id"], summary["release_id"]) == ("dec_1", "rel_1")
    assert [(method, path) for method, path, _ in platform.seen] == [
        ("GET", "releases/active"),
        ("POST", "candidates"),
        ("POST", "candidates/cand_1/decisions"),
        ("POST", "candidates/cand_1/activations"),
        ("GET", "releases/rel_1"),
        ("POST", "releases/rel_1/samples"),  # RV4c: a machine publish submits its sample
    ]
    assert platform.seen[2][2] == {
        "outcome": "approve",
        "mode": "machine",
        "policy_ref": "review-policy@test",
    }
    assert {key: claim["review"] for key, claim in claims_of(platform).items()} == {
        key: {"mode": "machine", "score": score, "reviewer": REVIEWER, "reviewed_at": AT}
        for key, score in FULL.items()
    }
    assert platform.seen[1][2]["review_plan"] == [
        {"mode": "machine", "policy_ref": "review-policy@test", "sample_size": None}
    ]


def test_a_product_below_its_threshold_is_queued_with_the_reason(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    strict = {**ADMITTED, "thresholds": {"pack": {"default": 0.9, "fields": {"term_b": 0.99}}}}
    assert command.main(routed(tmp_path, strict, FULL)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert (summary["review"], summary["reasons"]) == ("human", ["BELOW_THRESHOLD"])
    assert [path for _, path, _ in platform.seen] == ["releases/active", "candidates"]

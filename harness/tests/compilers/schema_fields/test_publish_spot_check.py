"""RV4c acceptance: a machine-reviewed publish submits its spot-check sample (Spec §2.3).

Protected file: written by Claude. After a machine decision activates the release, the publish
samples the claims it brought live (against the active release it read before) and submits them;
a human decision samples nothing; a failed submission never undoes the publish and is reported, so
the report command can submit later.
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
ADMITTED = {"version": "test", "admitted_packs": ["pack"], "thresholds": {"pack": {"default": 0.9}}}
SCORES = {
    "reviewer": "r@v",
    "reviewed_at": "2026-10-17T12:00:00Z",
    "scores": {"1828/term_a": 0.95, "1828/term_b": 0.9},
}
POLICY = {
    "version": "t",
    "default": {"rate": 1.0, "minimum": 1, "target": 0.9, "must_check": []},
    "packs": {"pack": {"rate": 1.0, "minimum": 1, "target": 0.9, "must_check": ["term_b"]}},
}


class Reader:
    def __init__(self, base_url: str, api_key: str) -> None:
        pass

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        return PAGES


class Platform:
    def __init__(self, samples_fail: bool = False) -> None:
        self.seen: list[tuple[str, str, Any]] = []
        self.members: list[dict[str, Any]] = []
        self.samples_fail = samples_fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/space-1/")
        self.seen.append((request.method, path, body))
        if path == "releases/active":
            return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
        if path == "candidates":
            self.members = body["members"]
            return ok({"id": "cand_1", "status": "created"}, 201)
        if path == "candidates/cand_1/decisions":
            return ok(
                {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve", "digest": "e" * 64}
            )
        if path == "releases/rel_1/samples":
            if self.samples_fail:
                return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
            return ok(
                {
                    "samples": [
                        {
                            "id": f"s{i}",
                            "space_id": "space-1",
                            "release_id": "rel_1",
                            "logical_slug": item["slug"],
                            "member_digest": "d" * 64,
                            "stratum": item["stratum"],
                            "created_by": "svc",
                            "created_at": "2026-10-18T12:00:00Z",
                        }
                        for i, item in enumerate(body["samples"])
                    ]
                },
                201,
            )
        return ok({"id": "rel_1", "epoch": 1, "candidate_id": "cand_1", "members": self.members})


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server: Platform) -> list[str]:
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
    for name, data in (("policy.json", ADMITTED), ("scores.json", SCORES), ("spot.json", POLICY)):
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    monkeypatch.setattr(source_map_module, "WeKnoraSourcePages", Reader)
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    return [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--source-map",
        str(tmp_path / "map.json"),
        "--repo",
        str(tmp_path / "repo"),
        "--spot-check-policy",
        str(tmp_path / "spot.json"),
    ]


def test_a_machine_publish_submits_the_sample_of_what_it_brought_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Platform()
    argv = prepare(tmp_path, monkeypatch, server)
    route = [
        "--route",
        "--review-policy",
        str(tmp_path / "policy.json"),
        "--scores",
        str(tmp_path / "scores.json"),
    ]
    assert command.main([*argv, *route]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["review"] == "machine" and summary["samples"] == 2
    [body] = [body for method, path, body in server.seen if path == "releases/rel_1/samples"]
    assert body == {
        "samples": [
            {"slug": "1828/term_a", "stratum": "pack/rest"},
            {"slug": "1828/term_b", "stratum": "pack/must"},
        ]
    }


def test_a_human_publish_samples_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Platform()
    argv = prepare(tmp_path, monkeypatch, server)
    assert command.main([*argv, "--decide", "human", "--reason", "人工确认", "--activate"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["release_id"] == "rel_1" and "samples" not in summary
    assert not [path for _, path, _ in server.seen if path.endswith("/samples")]


def test_a_failed_submission_keeps_the_publish_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = Platform(samples_fail=True)
    argv = prepare(tmp_path, monkeypatch, server)
    route = [
        "--route",
        "--review-policy",
        str(tmp_path / "policy.json"),
        "--scores",
        str(tmp_path / "scores.json"),
    ]
    assert command.main([*argv, *route]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["release_id"] == "rel_1"
    assert summary["samples"] == {"stopped": "SERVICE_UNAVAILABLE"}

"""S3e-1 acceptance: every publish carries the shipped navigation and the profile's display data.

Protected file: written by Claude (Spec §2.1, §2.2). Navigation is replaced whole with each publish,
like the presentation profile, so a reader always finds the one the release was published with; the
profile names its pack and defines its fields from the catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields import publish as command
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.ingest import source_map as source_map_module

SHA = "ab" * 32
PAGES = [
    PageText("保险条款.pdf", SHA, 1, "1.4 等待期\n自本合同生效之日起90日内为等待期。\n阅读指引\n")
]
SOURCE = SegmentedSource(PAGES)
CATALOG = SCHEMA_PACK_CATALOG
CATALOG_ENTRY = {
    "pack": {
        "schema_pack_id": "pack",
        "display_name": "演示险",
        "entity_type": "insurance_product",
        "applicable_classifications": ["demo_class"],
        "presentation_profile_ref": {"profile_id": "profile_pack", "profile_version": "1"},
        "fields": [
            {
                "field_key": "waiting_period",
                "short_title": "等待期",
                "description": "合同生效后一段时间内不赔付的期间。",
                "schema_category": "06 保障责任",
            }
        ],
    },
    "profile": {
        "profile_id": "profile_pack",
        "profile_version": "1",
        "profile_sha256": "cd" * 32,
        "schema_pack_id": "pack",
        "sections": [
            {
                "section_key": "contract",
                "display_name": "投保与合同",
                "fields": [{"field_key": "waiting_period", "short_title": "等待期"}],
            }
        ],
    },
}


class Reader:
    def __init__(self, base_url: str, api_key: str) -> None:
        pass

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        return PAGES


def member(kind: str, slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "logical_slug": slug,
        "member_digest": member_digest(payload),
        "payload": payload,
        "evidence_refs": [],
        "access_scope": "space",
    }


ACTIVE = {
    "id": "rel_0",
    "epoch": 2,
    "members": [
        member("entity", "entity/1828", {"entity_id": "1828"}),
        member(
            "claim", "1828/waiting_period", {"subject_ref": "1828", "predicate": "waiting_period"}
        ),
        member("claim", "1828/old_field", {"subject_ref": "1828", "predicate": "old_field"}),
        member("claim", "2000/old_field", {"subject_ref": "2000", "predicate": "old_field"}),
    ],
}


class Platform:
    def __init__(self, active: dict[str, Any] | None) -> None:
        self.active = active
        self.seen: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/space-1/")
        self.seen.append((request.method, path, body))
        if path == "releases/active":
            if self.active is None:
                return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
            return ok(self.active)
        if path == "candidates":
            return ok({"id": "cand_1", "status": "created"}, 201)
        return ok(
            {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve", "digest": "e" * 64}
        )


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, active: dict[str, Any] | None) -> Any:
    field = FieldResult(
        field_key="waiting_period",
        state="present",
        value="90日",
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D1P1S1"],
    )
    output = CompileOutput(
        pack_id="pack", entity_id="1828", model="m", fields=[field], cards_version="cards-x"
    )
    (tmp_path / "1828").mkdir()
    (tmp_path / "1828" / "output.json").write_text(output.model_dump_json(), encoding="utf-8")
    source_map = {
        "space_id": "space-1",
        "products": {"1828": [{"knowledge_id": "k-1", "parse_attempt": 2}]},
    }
    (tmp_path / "map.json").write_text(json.dumps(source_map), encoding="utf-8")
    catalog = tmp_path / "repo" / CATALOG
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps({"entries": [CATALOG_ENTRY]}, ensure_ascii=False), encoding="utf-8"
    )
    product = tmp_path / "repo" / "dataset" / "shouxian_product" / "演示"
    product.mkdir(parents=True)
    meta = {"planCode": "1828", "clauseName": "演示重大疾病保险"}
    (product / "product_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    monkeypatch.setattr(source_map_module, "WeKnoraSourcePages", Reader)
    server = Platform(active)
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    argv = [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--source-map",
        str(tmp_path / "map.json"),
    ]
    code = command.main([*argv, "--repo", str(tmp_path / "repo")])
    return code, server


def test_a_publish_carries_the_navigation_and_the_profile_display_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, server = publish(tmp_path, monkeypatch, None)
    assert code == 0
    submitted = next(body for method, path, body in server.seen if path == "candidates")
    members = {m["logical_slug"]: m for m in submitted["members"]}
    navigation = members["navigation/enterprise"]
    assert navigation["kind"] == "navigation"
    assert navigation["payload"]["navigation_id"] == "enterprise"
    assert [d["domain_key"] for d in navigation["payload"]["domains"]] == [
        "product",
        "service_benefit",
    ]
    profile = members["presentation/profile_pack"]["payload"]
    assert profile["display_name"] == "演示险"
    [field] = profile["sections"][0]["fields"]
    assert field["description"] == "合同生效后一段时间内不赔付的期间。"
    assert field["schema_category"] == "06 保障责任"

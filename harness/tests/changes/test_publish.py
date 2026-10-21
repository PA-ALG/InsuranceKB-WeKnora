"""Offline delta publishing uses real Claim conversion and HTTP protocol over fakes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.assemble import assemble
from insurance_harness.bundle.client import PlatformClient
from insurance_harness.compilers.schema_fields import publish as first_publish
from insurance_harness.compilers.schema_fields import publish_changes as command
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.contracts.knowledge import Claim, Evidence
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from tests.compilers.schema_fields.test_publish_cli import PAGES, SHA, SOURCE, Platform
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401


class DeltaPlatform(Platform):
    def __init__(self, active: dict[str, Any]) -> None:
        super().__init__()
        self.active = active
        self.fail_activation = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/active"):
            self.seen.append((request.method, "releases/active", None))
            return httpx.Response(200, json={"success": True, "data": self.active})
        if request.url.path.endswith("/activations") and self.fail_activation:
            self.seen.append((request.method, "activations", None))
            return httpx.Response(409, json={"success": False, "code": "NEEDS_REBASE"})
        return super().__call__(request)


def active(claims: list[Claim]) -> dict[str, Any]:
    bundle = assemble(claims, compiler_identity="test")
    return {
        "id": "rel_base",
        "epoch": 3,
        "members": [item.model_dump(mode="json") for item in bundle.members],
    }


def withdrawn(claim: Claim) -> Claim:
    proof = claim.evidence[0].model_copy(
        update={
            "source_ref": f"source:v1:withdrawn:1:{SHA}",
            "quote": "旧值",
            "quote_sha256": hashlib.sha256("旧值".encode()).hexdigest(),
        }
    )
    return claim.model_copy(update={"value": "旧值", "evidence": [proof]})


@pytest.fixture
def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> tuple[list[str], DeltaPlatform, list[Claim]]:
    request.getfixturevalue("prepared_files")
    output = CompileOutput.model_validate_json((tmp_path / "1828/output.json").read_text())
    incoming = claims_from(output, SOURCE, {"保险条款.pdf": SourceRevision("k-1", 2)})
    server = DeltaPlatform(active(incoming))
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(
            base,
            key,
            transport=httpx.MockTransport(server),
        ),
    )
    return (
        [
            "--run-root",
            str(tmp_path),
            "--product",
            "1828",
            "--source-map",
            str(tmp_path / "map.json"),
            "--repo",
            str(tmp_path / "repo"),
        ],
        server,
        incoming,
    )


def test_noop_never_submits_missing_page_metadata(setup: Any, capsys: Any) -> None:
    argv, server, _ = setup
    assert command.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["no_changes"] is True and result["counts"]["unchanged"] == 2
    assert result["candidate_id"] is None
    assert [path for _, path, _ in server.seen] == ["releases/active"]


def test_delta_only_changes_claims_and_reports_stale_concepts(setup: Any, capsys: Any) -> None:
    argv, server, incoming = setup
    server.active = active([withdrawn(incoming[0]), incoming[1]])
    server.active["members"].append(
        {
            "kind": "concept",
            "logical_slug": "concept/waiting",
            "member_digest": "f" * 64,
            "payload": {"based_on": {incoming[0].logical_key: "e" * 64}},
        }
    )
    assert command.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["supersede"] == 1 and result["counts"]["unchanged"] == 1
    assert result["stale_concepts"] == ["concept/waiting"]
    assert result["candidate_id"] == "cand_1"
    body = next(body for _, path, body in server.seen if path == "candidates")
    assert body["base_release_id"] == "rel_base"
    claims = [item for item in body["members"] if item["kind"] == "claim"]
    assert [item["logical_slug"] for item in claims] == [incoming[0].logical_key]
    assert claims[0]["payload"]["maintenance"]["reason"] == "supersede"
    assert {item["kind"] for item in body["members"]} == {
        "claim",
        "entity",
        "presentation_profile",
        "navigation",
    }


def test_dry_run_is_read_only(setup: Any, capsys: Any) -> None:
    argv, server, incoming = setup
    server.active = active([withdrawn(incoming[0]), incoming[1]])
    assert command.main([*argv, "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True and result["counts"]["supersede"] == 1
    assert result["candidate_id"] is None
    assert all(method == "GET" for method, _, _ in server.seen)


def test_existing_page_members_are_kept(setup: Any, capsys: Any) -> None:
    argv, server, incoming = setup
    server.active = active([withdrawn(incoming[0]), incoming[1]])
    for kind, slug in [
        ("entity", "entity/1828"),
        ("presentation_profile", "presentation/profile_pack"),
        ("navigation", "navigation/enterprise"),
    ]:
        server.active["members"].append(
            {"kind": kind, "logical_slug": slug, "member_digest": "e" * 64, "payload": {}}
        )
    assert command.main(argv) == 0
    capsys.readouterr()
    body = next(body for _, path, body in server.seen if path == "candidates")
    assert len(body["members"]) == 1


def test_conflict_only_writes_safe_hashes(
    setup: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    argv, server, incoming = setup
    proof = Evidence.model_validate(
        {
            **incoming[0].evidence[0].model_dump(mode="json"),
            "quote": "原材料不同说法",
            "quote_sha256": hashlib.sha256("原材料不同说法".encode()).hexdigest(),
        }
    )
    server.active = active(
        [
            incoming[0].model_copy(
                update={
                    "value": "SECRET-OLD",
                    "evidence": [proof],
                }
            ),
            incoming[1],
        ]
    )
    mapping = json.loads((tmp_path / "map.json").read_text())
    mapping["products"]["1828"] = [
        {"knowledge_id": "new-doc", "parse_attempt": 2},
        {"knowledge_id": "k-1", "parse_attempt": 2},
    ]
    (tmp_path / "map.json").write_text(json.dumps(mapping))

    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            return (
                PAGES
                if knowledge == "new-doc"
                else [
                    PageText("旧保险条款.pdf", SHA, 1, "原材料不同说法。阅读指引"),
                ]
            )

    monkeypatch.setattr(command, "reader_from_env", lambda: Reader())
    assert command.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["conflict"] == 1 and result["no_changes"] is True
    assert result["conflicts"] == [incoming[0].logical_key]
    lines = (tmp_path / "review_items.jsonl").read_text()
    item = json.loads(lines)
    assert item["slug"] == incoming[0].logical_key and item["verdict"] == "conflict"
    assert item["hashes"] and "SECRET-OLD" not in lines and "原材料不同说法" not in lines
    assert all(method == "GET" for method, _, _ in server.seen)


def test_needs_rebase_does_not_retry_and_reports_known_ids(setup: Any, capsys: Any) -> None:
    argv, server, incoming = setup
    server.active = active([withdrawn(incoming[0]), incoming[1]])
    server.fail_activation = True
    assert command.main([*argv, "--decide", "human", "--reason", "checked", "--activate"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["stopped"] == "NEEDS_REBASE"
    assert result["candidate_id"] == "cand_1" and result["decision_id"] == "dec_1"
    assert sum(path == "candidates" for _, path, _ in server.seen) == 1
    assert sum(path == "activations" for _, path, _ in server.seen) == 1


def test_old_command_rejects_an_existing_product(setup: Any, monkeypatch: Any, capsys: Any) -> None:
    argv, server, _ = setup
    monkeypatch.setattr(
        first_publish,
        "PlatformClient",
        lambda base, key: PlatformClient(
            base,
            key,
            transport=httpx.MockTransport(server),
        ),
    )
    assert first_publish.main(argv) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["stopped"] == "ALREADY_PUBLISHED"
    assert all(method == "GET" for method, _, _ in server.seen)


def test_all_materials_withdrawn_can_publish_only_removals(
    setup: Any,
    tmp_path: Path,
    capsys: Any,
) -> None:
    argv, server, _ = setup
    path = tmp_path / "1828/output.json"
    raw = json.loads(path.read_text())
    raw["fields"] = []
    path.write_text(json.dumps(raw))
    mapping = json.loads((tmp_path / "map.json").read_text())
    mapping["products"]["1828"] = []
    (tmp_path / "map.json").write_text(json.dumps(mapping))
    assert command.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["retract"] == 2
    body = next(body for _, path, body in server.seen if path == "candidates")
    assert not [item for item in body["members"] if item["kind"] == "claim"]
    assert set(body["removals"]) == {"1828/waiting_period", "1828/premium_grace_period"}


def test_machine_route_requires_scores_only_for_changed_claims(
    setup: Any,
    tmp_path: Path,
    capsys: Any,
) -> None:
    argv, server, incoming = setup
    server.active = active([withdrawn(incoming[0]), incoming[1]])
    for filename, data in {
        "policy.json": {
            "version": "test",
            "admitted_packs": ["pack"],
            "thresholds": {"pack": {"default": 0.9}},
        },
        "scores.json": {
            "reviewer": "r",
            "reviewed_at": "2026-10-21T12:00:00Z",
            "scores": {incoming[0].logical_key: 0.99},
        },
        "spot.json": {"version": "test", "default": {"rate": 0.0, "minimum": 0, "target": 0.99}},
    }.items():
        (tmp_path / filename).write_text(json.dumps(data))
    assert (
        command.main(
            [
                *argv,
                "--route",
                "--review-policy",
                str(tmp_path / "policy.json"),
                "--scores",
                str(tmp_path / "scores.json"),
                "--spot-check-policy",
                str(tmp_path / "spot.json"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["review"] == "machine" and result["release_id"] == "rel_1"
    body = next(body for _, path, body in server.seen if path == "candidates")
    claims = [item for item in body["members"] if item["kind"] == "claim"]
    assert len(claims) == 1 and claims[0]["payload"]["review"]["score"] == 0.99
    assert incoming[1].logical_key not in {item["logical_slug"] for item in claims}


def test_first_publish_still_allows_another_products_active_claims(
    setup: Any,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    argv, server, incoming = setup
    other = incoming[0].model_copy(update={"subject_ref": "other", "logical_key": "other/waiting"})
    server.active = active([other])
    monkeypatch.setattr(
        first_publish,
        "PlatformClient",
        lambda base, key: PlatformClient(
            base,
            key,
            transport=httpx.MockTransport(server),
        ),
    )
    assert first_publish.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["candidate_id"] == "cand_1"
    body = next(body for _, path, body in server.seen if path == "candidates")
    assert body["base_release_id"] == "rel_base" and not body["removals"]


@pytest.mark.parametrize("entrypoint", [command, first_publish])
@pytest.mark.parametrize("metadata", ["revision", "file", None])
@pytest.mark.parametrize("second_doc", ["b-doc", "file"])
def test_material_reordering_keeps_compiled_segment_pointers_publishable(
    setup: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    entrypoint: Any,
    metadata: str | None,
    second_doc: str,
) -> None:
    argv, server, _ = setup
    server.active = active([])
    output_path = tmp_path / "1828/output.json"
    raw = json.loads(output_path.read_text())
    if metadata == "revision":
        raw["materials"] = [f"a-doc:2:{SHA}", f"{second_doc}:2:{SHA}"]
        for field in raw["fields"]:
            field["segment_ids"] = [item.replace("D1", "D2") for item in field["segment_ids"]]
    else:
        raw["materials"] = [f"file:{SHA}"] if metadata == "file" else None
    output_path.write_text(json.dumps(raw))
    mapping = json.loads((tmp_path / "map.json").read_text())
    mapping["products"]["1828"] = [
        {"knowledge_id": second_doc, "parse_attempt": 2},
        {"knowledge_id": "a-doc", "parse_attempt": 2},
    ]
    (tmp_path / "map.json").write_text(json.dumps(mapping))

    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            return (
                PAGES
                if knowledge == second_doc
                else [
                    PageText("其他保险条款.pdf", SHA, 1, "本合同保障责任。阅读指引"),
                ]
            )

    monkeypatch.setattr(entrypoint, "reader_from_env", lambda: Reader())
    monkeypatch.setattr(
        entrypoint,
        "PlatformClient",
        lambda base, key: PlatformClient(
            base,
            key,
            transport=httpx.MockTransport(server),
        ),
    )
    assert entrypoint.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["candidate_id"] == "cand_1"
    body = next(body for _, path, body in server.seen if path == "candidates")
    claims = [member for member in body["members"] if member["kind"] == "claim"]
    assert claims and all(
        item["evidence_refs"] == [f"source:v1:{second_doc}:2:{SHA}"] for item in claims
    )

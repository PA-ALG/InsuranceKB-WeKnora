"""SK-2b Spec §3, §4, §6 (RED, written by Claude): the copies, candidates and withdraw commands."""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle.client import Candidate, Release
from insurance_harness.compilers.methods import cli
from insurance_harness.compilers.methods.admission import CandidateFile
from insurance_harness.compilers.methods.copies import (
    MethodCopy,
    empty_book,
    load_copies,
    save_copies,
)
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.ingest.registry import ProductRegistry, load_registry, save_registry
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from tests.compilers.methods.discovery_helpers import (
    DISCOVERY_KB,
    DiscoveryWorld,
    FakePlatform,
    chunk,
    page,
)
from tests.compilers.methods.helpers import (
    DECK_A,
    METHOD_A,
    FakeModel,
    World,
    candidate,
    compiled,
    full_answer,
    release_from,
)
from tests.ingest.upload_helpers import RAW_KB, SPACE


class FakeClient:
    def __init__(self, active: Release | None) -> None:
        self.active_release = active
        self.calls: list[str] = []
        self.submitted: list[CandidateBundle] = []

    def active(self, space_id: str) -> Release | None:
        self.calls.append("active")
        return self.active_release

    def submit(self, space_id: str, bundle: CandidateBundle) -> Candidate:
        self.calls.append("submit")
        self.submitted.append(bundle)
        return Candidate(id="cand-1", status="pending")


class FakeWiki:
    def __init__(self, pages: list[Any]) -> None:
        self.native = pages

    def pages(self, kb_id: str) -> list[Any]:
        assert kb_id == DISCOVERY_KB
        return self.native


def configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://platform.invalid")
    monkeypatch.setenv(API_KEY_ENV, "test-only")


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    status = cli.main(list(argv))
    out = capsys.readouterr().out
    assert METHOD_A not in out and "需求销售方法.pptx" not in out
    return status, json.loads(out)


def registry_file(tmp_path: Path, registry: ProductRegistry) -> Path:
    path = tmp_path / "registry.json"
    save_registry(registry, path)
    return path


def test_copies_plans_by_default_and_copies_only_when_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch)
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    monkeypatch.setattr(cli, "MaterialPlatform", lambda *_: platform)
    registry, copies = registry_file(tmp_path, world.registry), tmp_path / "copies.json"
    args = ["copies", "--registry", str(registry), "--copies", str(copies),
            "--discovery-kb", DISCOVERY_KB, "--run-root", str(tmp_path / "run")]
    status, summary = run(capsys, *args)
    assert status == 0 and summary["counts"] == {"to_copy": 2} and summary["live"] is False
    assert not copies.exists() and platform.writes() == []
    status, summary = run(capsys, *args, "--live")
    assert status == 0 and summary["counts"] == {"copied": 2}
    assert len(load_copies(copies, SPACE, DISCOVERY_KB).copies) == 2
    report = (tmp_path / "run" / "copy_report.json").read_text(encoding="utf-8")
    assert json.loads(report)["counts"] == {"copied": 2} and "pptx" not in report


def test_copies_refuses_the_raw_knowledge_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch)
    world = DiscoveryWorld()
    monkeypatch.setattr(cli, "MaterialPlatform", lambda *_: FakePlatform(world))
    registry = registry_file(tmp_path, world.registry)
    status, summary = run(capsys, "copies", "--registry", str(registry),
                          "--copies", str(tmp_path / "c.json"), "--discovery-kb", RAW_KB,
                          "--run-root", str(tmp_path / "run"))
    assert (status, summary) == (2, {"stopped": "DISCOVERY_KB_INVALID"})


def test_candidates_writes_the_candidate_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch)
    world = DiscoveryWorld()
    platform = FakePlatform(world)
    monkeypatch.setattr(cli, "MaterialPlatform", lambda *_: platform)
    registry, copies = registry_file(tmp_path, world.registry), tmp_path / "copies.json"
    common = ["--registry", str(registry), "--copies", str(copies), "--discovery-kb", DISCOVERY_KB]
    assert run(capsys, "copies", *common, "--run-root", str(tmp_path / "run"), "--live")[0] == 0
    copy_a = next(c.copy_knowledge_id for c in load_copies(copies, SPACE, DISCOVERY_KB).copies
                  if c.knowledge_id == "k-deck-a")
    texts = [text for slide in DECK_A for text in slide]
    wiki = FakeWiki([page(METHOD_A, chunk(copy_a, *texts))])
    monkeypatch.setattr(cli, "NativeWikiReader", lambda *_: wiki)
    monkeypatch.setattr(cli, "reader_from_env", lambda: world.reader)
    out = tmp_path / "candidates.json"
    status, summary = run(capsys, "candidates", *common, "--out", str(out))
    assert status == 0 and summary["candidates"] == 1
    written = CandidateFile.model_validate_json(out.read_text(encoding="utf-8"))
    assert [c.copy_knowledge_id for c in written.candidates] == [copy_a]


def published(world: World) -> Release:
    run_ = compiled(world, [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))],
                    FakeModel({METHOD_A: full_answer}))
    assert run_.bundle is not None
    return release_from(run_.bundle)


def test_withdraw_writes_the_plan_then_the_registry_then_submits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch)
    world = World()
    client = FakeClient(published(world))
    monkeypatch.setattr(cli, "PlatformClient", lambda *_: client)
    registry = registry_file(tmp_path, world.registry)
    run_root = tmp_path / "run"
    seen: list[tuple[bool, bool, list[str]]] = []
    real = save_registry

    def checked(saved: ProductRegistry, path: Path) -> None:
        seen.append(((run_root / "candidate.json").exists(), (run_root / "report.json").exists(),
                     list(client.calls)))
        real(saved, path)

    monkeypatch.setattr(cli, "save_registry", checked)
    method_id = world.registry.methods[0].method_id
    status, summary = run(capsys, "withdraw", "--registry", str(registry), "--method-id",
                          method_id, "--run-root", str(run_root), "--live")
    assert status == 0 and summary["candidate_id"] == "cand-1" and summary["removals"] == 6
    assert seen == [(True, True, ["active"])]  # planned, then the registry, then the submission
    assert client.calls == ["active", "submit"]  # submitted only: people decide on the platform
    assert load_registry(registry).methods[0].suppressed is True
    plan = CandidateBundle.model_validate_json((run_root / "candidate.json").read_text())
    assert client.submitted == [plan]


def test_withdraw_offline_submits_nothing_and_refuses_unknown_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch)
    world = World()
    client = FakeClient(published(world))
    monkeypatch.setattr(cli, "PlatformClient", lambda *_: client)
    registry = registry_file(tmp_path, world.registry)
    method_id = world.registry.methods[0].method_id
    args = ["withdraw", "--registry", str(registry), "--run-root", str(tmp_path / "run")]
    status, summary = run(capsys, *args, "--method-id", method_id)
    assert status == 0 and summary["candidate_id"] is None and client.calls == ["active"]
    before = registry.read_bytes()
    status, summary = run(capsys, *args, "--method-id", "sm-" + "0" * 24)
    assert (status, summary) == (2, {"stopped": "METHOD_UNKNOWN"})
    assert registry.read_bytes() == before


def test_candidates_refuses_a_mapping_onto_the_raw_base_before_reading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """#518 review R2: the isolation holds at every entry that reads the discovery base."""
    configure(monkeypatch)
    world = DiscoveryWorld()
    raw = world.raws["k-deck-a"]
    onto_raw = empty_book(SPACE, RAW_KB).model_copy(update={"copies": (MethodCopy(
        copy_knowledge_id=raw.knowledge_id, knowledge_id=raw.knowledge_id,
        parse_attempt=raw.parse_attempt, sha256=raw.sha256,
    ),)})
    copies = tmp_path / "copies.json"
    save_copies(onto_raw, copies)

    def unreachable(*_: Any) -> Any:
        raise AssertionError("nothing may be read")

    for name in ("MaterialPlatform", "NativeWikiReader", "reader_from_env"):
        monkeypatch.setattr(cli, name, unreachable)
    registry, out = registry_file(tmp_path, world.registry), tmp_path / "candidates.json"
    status, summary = run(capsys, "candidates", "--registry", str(registry), "--copies",
                          str(copies), "--discovery-kb", RAW_KB, "--out", str(out))
    assert (status, summary) == (2, {"stopped": "DISCOVERY_KB_INVALID"})
    assert not out.exists()

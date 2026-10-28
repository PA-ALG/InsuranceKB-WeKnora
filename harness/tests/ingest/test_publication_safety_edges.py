"""Run-lock ownership and successful-publication/sample-failure boundaries."""

import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from insurance_harness.compilers.schema_fields import publish, publish_changes
from insurance_harness.eval import compile_run, review_run
from insurance_harness.ingest.publication import PublicationError, run_publication
from insurance_harness.ingest.registry import RegistryError
from insurance_harness.ingest.uploads import main
from insurance_harness.models.durable import run_lock
from tests.ingest.test_publication import (
    Active,
    Commands,
    command,
    digest,
    environment,  # noqa: F401
    option,
    publish_run,
    published,
    stored,
    two_products,
    write_output,
)
from tests.ingest.test_publication_safety import SampledCommands


def assert_held(root: Path) -> None:
    with (root / ".lock").open("rb") as lock:
        with pytest.raises(BlockingIOError):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def assert_released(root: Path) -> None:
    with (root / ".lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("symlink", [False, True])
def test_worktree_git_file_and_resolved_symlink_are_rejected_before_seed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symlink: bool,
) -> None:
    current = two_products()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    run = repo / "run"
    if symlink:
        link = tmp_path / "linked"
        link.symlink_to(repo, target_is_directory=True)
        run = link / "run"
    seed = tmp_path / "seed"
    write_output(seed, current, "1818")
    commands, active = Commands(monkeypatch, current), Active(set())
    with pytest.raises(PublicationError, match="^RUN_ROOT_INVALID$"):
        run_publication(stored(tmp_path, current), run, client=active.client(),
                        stage_config=tmp_path / "stages.json", seed_from=[seed])
    assert not run.exists() and commands.calls == [] and active.requests == []


def test_parent_lock_covers_seed_commands_http_and_receipts_with_child_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, root = two_products(), tmp_path / "run"
    seed = tmp_path / "seed"
    write_output(seed, current, "1818")
    commands, active = Commands(monkeypatch, current), Active({"1818"})
    registry_path = stored(tmp_path, current)
    stages: list[str] = []

    def locked(command: Callable[[list[str]], int], stage: str) -> Callable[[list[str]], int]:
        def invoke(argv: list[str]) -> int:
            assert_held(root)
            stages.append(stage)
            if stage in {"compile", "review"}:
                child = Path(option(argv, "--run-root"))
                with run_lock(child):
                    assert_held(root)
                    assert_held(child)
                    result = command(argv)
                assert_released(child)
                return result
            return command(argv)
        return invoke

    for module, name in ((compile_run, "compile"), (review_run, "review"),
                         (publish, "first"), (publish_changes, "changes")):
        monkeypatch.setattr(module, "main", locked(module.main, name))
    handle = active.handle

    def locked_http(request: httpx.Request) -> httpx.Response:
        assert_held(root)
        stages.append("active")
        return handle(request)

    monkeypatch.setattr(active, "handle", locked_http)
    replace = os.replace

    def locked_replace(source: str, target: Path) -> None:
        assert_held(root)
        stages.append(Path(target).name)
        replace(source, target)

    monkeypatch.setattr(os, "replace", locked_replace)
    report = run_publication(registry_path, root, client=active.client(),
                             stage_config=tmp_path / "stages.json", seed_from=[seed])
    assert report.failed == {} and len(report.routes) == 2
    # Planning reads Active first to judge the seed's carry (S12c-4), still under the lock.
    assert stages == ["active", "output.json", "compile", "active", "changes", "review",
                      "scored.json", "changes", "published.json", "first", "published.json"]
    assert len(commands.calls) == 5
    assert_released(root)


def test_reentrant_call_does_not_release_the_callers_parent_lock(tmp_path: Path) -> None:
    current, root = two_products(), tmp_path / "run"
    active = Active(set())
    with run_lock(root):
        report = publish_run(tmp_path, current, active, products=[])
        assert report.planned_compile == [] and report.planned_publish == []
        assert_held(root)
    assert_released(root)
    assert active.requests == []


@pytest.mark.parametrize("invalid_registry", [False, True])
def test_registry_errors_keep_their_type_and_code_and_release_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_registry: bool,
) -> None:
    current, root = two_products(), tmp_path / "run"
    path = stored(tmp_path, current)
    if invalid_registry:
        path.write_text("not json", encoding="utf-8")
    commands, active = Commands(monkeypatch, current), Active(set())
    with pytest.raises(RegistryError) as error:
        run_publication(path, root, client=active.client(), stage_config=tmp_path / "stages.json",
                        products=["unregistered"])
    assert error.value.code == ("REGISTRY_INVALID" if invalid_registry else "PRODUCT_UNKNOWN")
    assert commands.calls == [] and active.requests == []
    assert_released(root)


def test_lock_acquisition_io_error_is_safe_and_stops_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = two_products()
    root = tmp_path / "run"
    root.write_bytes(b"existing file")
    commands, active = Commands(monkeypatch, current), Active(set())
    with pytest.raises(PublicationError, match="^RUN_ROOT_INVALID$"):
        publish_run(tmp_path, current, active)
    assert root.read_bytes() == b"existing file" and commands.calls == [] and active.requests == []


def test_interruption_in_a_command_releases_parent_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, root = two_products(), tmp_path / "run"
    commands, active = Commands(monkeypatch, current), Active(set())

    def interrupt(argv: list[str]) -> int:
        assert_held(root)
        raise KeyboardInterrupt

    monkeypatch.setattr(compile_run, "main", interrupt)
    with pytest.raises(KeyboardInterrupt):
        publish_run(tmp_path, current, active)
    assert_released(root)
    assert commands.calls == [] and active.requests == [] and published(root) == {}


@pytest.mark.parametrize("existing", [False, True])
def test_sample_failure_keeps_first_or_change_receipt_and_next_run_does_not_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool,
) -> None:
    current, root = two_products(), tmp_path / "run"
    commands = SampledCommands(monkeypatch, current, {"1818": "PLATFORM_UNAVAILABLE"})
    commands.routes = dict.fromkeys(current.products, "machine")
    active = Active(set(current.products) if existing else set())
    report = publish_run(tmp_path, current, active)
    assert report.routes == dict.fromkeys(current.products, "machine") and report.failed == {}
    assert report.model_dump()["samples_failed"] == {
        "1818": {"release_id": "rel-1818", "stopped": "PLATFORM_UNAVAILABLE"},
    }
    assert published(root) == {p: digest(root / "compile", p) for p in current.products}
    assert len(commands.named("changes" if existing else "first")) == (4 if existing else 2)
    commands.calls.clear()
    active.requests.clear()
    again = publish_run(tmp_path, current, active)
    assert again.routes == {} and again.model_dump()["samples_failed"] == {}
    assert commands.calls == [] and len(active.requests) == 1  # planning's carry read (S12c-4)


@pytest.mark.usefixtures("environment")
def test_zero_successful_samples_is_a_successful_cli_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    current = two_products()
    stored(tmp_path, current)
    Commands(monkeypatch, current)

    def zero_samples(argv: list[str]) -> int:
        product = option(argv, "--product")
        print(json.dumps({"product": product, "review": "machine", "release_id": f"rel-{product}",
                          "samples": 0}))
        return 0

    monkeypatch.setattr(publish, "main", zero_samples)
    assert main(command(tmp_path), transport=httpx.MockTransport(Active(set()).handle)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["samples_failed"] == {} and report["failed"] == {}
    assert report["routes"] == dict.fromkeys(current.products, "machine")
    assert set(published(tmp_path / "run")) == set(current.products)

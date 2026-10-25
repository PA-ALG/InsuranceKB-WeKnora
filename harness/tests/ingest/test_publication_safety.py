"""S5b-4b acceptance (protected, written by Claude): the run root is held and kept outside git, and
a machine publish whose spot-check sample was not submitted is reported with its release (Spec
docs/design/slices/S5b-4b-登记表产品的编译发布编排.md §3 step 5, §4, §6 item 9; review R2, R3).
Reuses the fakes of test_publication.
"""

import fcntl
import json
import os
from pathlib import Path

import httpx
import pytest

from insurance_harness.ingest.publication import (
    PublicationError,
    PublicationReport,
    run_publication,
)
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.uploads import main
from tests.ingest.test_publication import (
    BASE,
    Active,
    Commands,
    command,
    digest,
    published,
    stored,
    two_products,
    write_output,
)


class SampledCommands(Commands):
    """Machine publishes report their release and, for some products, a failed sample submission."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, current: ProductRegistry, unsampled: dict[str, str]
    ) -> None:
        super().__init__(monkeypatch, current)
        self.unsampled = unsampled

    def publish(self, kind: str, argv: list[str]) -> int:
        product = argv[argv.index("--product") + 1]
        if self.routes.get(product) != "machine" or "--dry-run" in argv:
            return super().publish(kind, argv)
        self.calls.append((kind, argv))
        failure = self.unsampled.get(product)
        samples: object = {"stopped": failure} if failure else 3
        print(
            json.dumps(
                {
                    "product": product,
                    "review": "machine",
                    "release_id": f"rel-{product}",
                    "samples": samples,
                }
            )
        )
        return 0


def seeded(tmp_path: Path) -> Path:
    seeds = tmp_path / "seeds"
    current = two_products()
    for product in ("1818", "1828"):
        write_output(seeds, current, product)
    return seeds


def run_at(
    tmp_path: Path, run: Path, active: Active, *, dry_run: bool = False
) -> PublicationReport:
    return run_publication(
        stored(tmp_path, two_products()),
        run,
        client=active.client(),
        stage_config=tmp_path / "stages.json",
        seed_from=[seeded(tmp_path)],
        dry_run=dry_run,
    )


def test_a_run_root_inside_a_git_repository_is_refused_before_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    run = tmp_path / "repo" / "run"
    commands, active = Commands(monkeypatch, two_products()), Active({"1818"})
    with pytest.raises(PublicationError) as error:
        run_at(tmp_path, run, active)
    assert error.value.code == "RUN_ROOT_INVALID"
    assert commands.calls == [] and active.requests == []
    assert not (run / "compile").exists()


def test_a_run_root_in_use_is_refused_and_a_dry_run_takes_no_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    commands, active = Commands(monkeypatch, two_products()), Active({"1818"})
    descriptor = os.open(run / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PublicationError) as error:
            run_at(tmp_path, run, active)
        assert error.value.code == "RUN_ROOT_BUSY"
        assert commands.calls == [] and active.requests == []
        assert not (run / "compile").exists()
        planned = run_at(tmp_path, run, active, dry_run=True)
        assert planned.planned_publish == ["1818", "1828"]
        assert sorted(path.name for path in run.iterdir()) == [".lock"]
    finally:
        os.close(descriptor)


def test_a_machine_publish_without_its_sample_is_reported_with_its_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    commands = SampledCommands(monkeypatch, current, {"1818": "PLATFORM_UNAVAILABLE"})
    commands.routes = {"1818": "machine", "1828": "machine"}
    report = run_at(tmp_path, tmp_path / "run", Active(set()))
    assert report.routes == {"1818": "machine", "1828": "machine"}
    assert report.model_dump()["samples_failed"] == {
        "1818": {"release_id": "rel-1818", "stopped": "PLATFORM_UNAVAILABLE"}
    }
    assert report.failed == {}
    compiled = tmp_path / "run" / "compile"
    assert published(tmp_path / "run") == {p: digest(compiled, p) for p in ("1818", "1828")}


def test_the_command_exits_1_only_when_a_sample_was_not_submitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", BASE)
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")
    stored(tmp_path, two_products())
    seeds = seeded(tmp_path)
    commands = SampledCommands(monkeypatch, two_products(), {})
    commands.routes = {"1818": "machine"}
    transport = httpx.MockTransport(Active(set()).handle)
    assert main(command(tmp_path, "--seed-from", str(seeds)), transport=transport) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["samples_failed"] == {}
    commands.unsampled = {"1818": "PLATFORM_UNAVAILABLE"}
    (tmp_path / "run" / "published.json").unlink()
    assert main(command(tmp_path, "--seed-from", str(seeds)), transport=transport) == 1
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["samples_failed"]["1818"] == {
        "release_id": "rel-1818",
        "stopped": "PLATFORM_UNAVAILABLE",
    }

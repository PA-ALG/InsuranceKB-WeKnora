"""Current G3: frozen build context and exact runtime reuse, no Docker builds."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = "sha256:" + "a" * 64
TAG = "wechatopenai/weknora-app:local-base"


def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "app_reuse_under_test", ROOT / "scripts/app_artifact.py"
    )
    assert spec is not None and spec.loader is not None
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def require_port(m: ModuleType, name: str) -> Callable[..., Any]:
    port = getattr(m, name, None)
    assert callable(port), f"formal BA0 port missing: {name}"
    return cast(Callable[..., Any], port)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Build fixture")
    paths = {
        "config/app.yaml": "safe",
        "scripts/app_artifact.py": "# old build tool",
        "scripts/start.sh": "start",
        "migrations/001.sql": "select 1;",
        "dataset/samples/a": "sample",
        "skills/preloaded/a/SKILL.md": "skill",
        "go.mod": "module fixture",
        "go.sum": "checksum",
        "cmd/download/duckdb/duckdb.go": "download",
        "cmd/server/main.go": "old go",
        "deploy/local-build/app-external-dependencies.v1.json": "{}",
        "docker/Dockerfile.app": (
            "ARG BUILDER_IMAGE\nARG RUNTIME_IMAGE\nFROM ${BUILDER_IMAGE} AS builder\n"
            "RUN echo builder\nFROM ${RUNTIME_IMAGE} AS runtime\n"
            "COPY --from=builder /app/WeKnora ./WeKnora\n"
        ),
        "docs/note.md": "old docs",
    }
    for name, value in paths.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "cmd/server/main.go").write_text("new go")
    (repo / "scripts/app_artifact.py").write_text("# new build tool")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "changed go and formal build tool")
    return repo, base, git(repo, "rev-parse", "HEAD")


class ImageRunner:
    def __init__(self, source: str, *, bad_id: bool = False, bad_source: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.source = source
        self.bad_id = bad_id
        self.bad_source = bad_source

    def __call__(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(args))
        if args[0] != "docker":
            return subprocess.run(args, **kwargs)
        assert "inspect" in args, "preflight may only inspect Docker"
        record = {
            "Id": "sha256:" + "b" * 64 if self.bad_id else BASE,
            "Os": "linux",
            "Architecture": "arm64",
            "RepoTags": [TAG],
            "RootFS": {"Layers": ["sha256:" + "c" * 64]},
            "Config": {
                "Labels": {
                    "io.insurancekb.app.build-source-head": "f" * 40
                    if self.bad_source
                    else self.source
                },
                "User": "1000",
                "Entrypoint": ["entrypoint"],
            },
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(record), "")


def facts(
    m: ModuleType,
    history: tuple[Path, str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    repo, old, new = history
    result: dict[str, Any] = require_port(m, "runtime_reuse_facts")(
        repo_root=repo,
        build_source_head=new,
        runtime_source_head=old,
        runtime_image=BASE,
        runner=runner or ImageRunner(old),
        docker_context="colima",
    )
    return result


def test_freeze_uses_commit_not_dirty_worktree_and_releases_context(
    history: tuple[Path, str, str],
) -> None:
    m = module()
    freeze = require_port(m, "frozen_source_context")
    repo, _, source = history
    (repo / "cmd/server/main.go").write_text("uncommitted must not build")
    with freeze(repo_root=repo, source_head=source) as snapshot:
        snapshot = Path(snapshot)
        assert snapshot != repo
        assert (snapshot / "cmd/server/main.go").read_text() == "new go"
        (repo / "docs/note.md").write_text("unrelated changes during build")
        assert (snapshot / "docs/note.md").read_text() == "old docs"
    assert not snapshot.exists()


def test_freeze_subset_port_is_reusable_for_harness(history: tuple[Path, str, str]) -> None:
    m = module()
    repo, _, source = history
    with require_port(m, "frozen_source_context")(
        repo_root=repo, source_head=source, paths=("cmd/server",)
    ) as snapshot:
        assert (Path(snapshot) / "cmd/server/main.go").exists()
        assert not (Path(snapshot) / "config").exists()


def test_runtime_reuse_allows_go_and_only_explicit_build_tool(
    history: tuple[Path, str, str],
) -> None:
    result = facts(module(), history)
    assert result["image_id"] == BASE
    assert result["image_reference"] == TAG
    assert result["source_head"] == history[1]
    assert result["refreshed_runtime_paths"] == ["scripts/app_artifact.py"]


@pytest.mark.parametrize(
    "path",
    [
        "scripts/start.sh",
        "config/app.yaml",
        "migrations/001.sql",
        "skills/preloaded/a/SKILL.md",
        "go.sum",
        "cmd/download/duckdb/duckdb.go",
        "deploy/local-build/app-external-dependencies.v1.json",
    ],
)
def test_runtime_resource_or_dependency_drift_rejected(
    history: tuple[Path, str, str], path: str
) -> None:
    m = module()
    repo, old, _ = history
    (repo / path).write_text("changed non-Go runtime input")
    git(repo, "add", path)
    git(repo, "commit", "-qm", "resource drift")
    with pytest.raises(m.ArtifactContractError, match="runtime|dependency"):
        facts(m, (repo, old, git(repo, "rev-parse", "HEAD")))


@pytest.mark.parametrize("field", ["bad_id", "bad_source"])
def test_runtime_image_identity_and_source_are_verified(
    history: tuple[Path, str, str], field: str
) -> None:
    m = module()
    runner = ImageRunner(history[1], **{field: True})
    with pytest.raises(m.ArtifactContractError, match="image|source"):
        facts(m, history, runner)


def test_formal_rebase_dockerfile_refreshes_only_binary_and_build_tool() -> None:
    dockerfile = (ROOT / "docker/Dockerfile.app").read_text()
    assert "ARG EXISTING_APP_RUNTIME" in dockerfile.split("FROM ", 1)[0]
    assert "FROM ${EXISTING_APP_RUNTIME} AS runtime-rebase" in dockerfile
    stage = dockerfile.split("FROM ${EXISTING_APP_RUNTIME} AS runtime-rebase", 1)[1].split(
        "\nFROM ", 1
    )[0]
    copies = [line for line in stage.splitlines() if line.startswith("COPY ")]
    assert len(copies) == 2
    assert any("/app/WeKnora" in line for line in copies)
    assert any("/app/scripts/app_artifact.py" in line for line in copies)
    assert not any("/app/scripts " in line for line in copies)


def test_cold_compile_does_not_require_previous_cache_probe() -> None:
    dockerfile = (ROOT / "docker/Dockerfile.app").read_text()
    compile_section = dockerfile.split("COPY . .", 1)[1].split("FROM ", 1)[0]
    assert ".ba0-app-cache-v1" not in compile_section
    assert "id=ba0-app-go-mod-v1" in compile_section
    assert "id=ba0-app-go-build-v1" in compile_section


def test_runtime_recipe_change_cannot_be_hidden_as_go_only(history: tuple[Path, str, str]) -> None:
    m = module()
    repo, old, _ = history
    p = repo / "docker/Dockerfile.app"
    p.write_text(p.read_text().replace("RUN echo builder", "RUN install-other-dependency"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "dependency recipe drift")
    with pytest.raises(m.ArtifactContractError, match="recipe"):
        facts(m, (repo, old, git(repo, "rev-parse", "HEAD")))


def test_runtime_base_enters_canonical_identity(
    history: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    m = module()
    require_port(m, "runtime_reuse_facts")
    repo, old, new = history
    manifest = repo / "manifest.json"
    manifest.write_text("{}")
    lock = repo / "deploy/local-build/app-external-dependencies.v1.json"
    definition = {
        "artifact": "weknora-app",
        "external_dependency_lock": str(lock.relative_to(repo)),
        "build_contract": {"target": "runtime", "platform": "linux/arm64"},
        "required_paths": [],
        "dockerfile": "docker/Dockerfile.app",
        "dockerignore": ".dockerignore",
    }
    monkeypatch.setattr(m, "load_manifest", lambda _: definition)
    monkeypatch.setattr(m, "load_dependency_lock", lambda _: {})
    monkeypatch.setattr(m, "resolve_inputs", lambda *a, **k: ())
    monkeypatch.setattr(
        m,
        "build_metadata",
        lambda **k: {
            "version": "1",
            "commit_id": new,
            "source_date_epoch": 0,
            "build_time": "1970-01-01 00:00:00 UTC",
        },
    )
    chosen = {"image_id": BASE, "source_head": old}
    monkeypatch.setattr(m, "runtime_reuse_facts", lambda **k: dict(chosen))
    kwargs = dict(
        repo_root=repo,
        manifest_path=manifest,
        dependency_lock_path=lock,
        build_source_head=new,
        integration_head=new,
        effective_build_args={},
        runner=lambda args, **kw: subprocess.CompletedProcess(args, 0, "", ""),
    )
    plain = m.canonical_identity(**kwargs)
    first = m.canonical_identity(**kwargs, reuse_runtime_image=BASE, reuse_runtime_source=old)
    chosen["image_id"] = "sha256:" + "b" * 64
    second = m.canonical_identity(
        **kwargs, reuse_runtime_image=chosen["image_id"], reuse_runtime_source=old
    )
    assert (
        len(
            {
                plain["artifact_identity"],
                first["artifact_identity"],
                second["artifact_identity"],
            }
        )
        == 3
    )
    assert "runtime_reuse" not in plain
    assert json.loads(first["canonical_bytes"])["runtime_reuse"]["image_id"] == BASE


@pytest.mark.parametrize("reuse_hit", [False, True])
def test_selector_retains_lookup_receipt_and_runtime_parent_proof(
    history: tuple[Path, str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reuse_hit: bool
) -> None:
    m = module()
    runtime = facts(m, history)
    source = history[2]
    identity = dict(
        artifact="weknora-app",
        artifact_identity="sha256:" + "1" * 64,
        build_source_head=source,
        integration_head=source,
        manifest_sha256="2" * 64,
        dependency_lock_sha256="3" * 64,
        target="runtime",
        platform="linux/arm64",
        version="1",
        commit_id=source,
        source_date_epoch=0,
        build_time="1970-01-01 00:00:00 UTC",
        runtime_reuse=runtime,
    )
    built = "sha256:" + "d" * 64
    labels = m._required_labels(identity)
    calls = []
    base_record = json.loads(ImageRunner(history[1])(("docker", "inspect", BASE)).stdout)
    child_record = dict(
        base_record,
        Id=built,
        RootFS={"Layers": runtime["parent_layers"] + ["sha256:" + "e" * 64]},
    )
    child_record["Config"] = dict(base_record["Config"], Labels=labels)

    def runner(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(args), kwargs["cwd"]))
        if "inspect" in args:
            record = child_record if built in args else base_record
            return subprocess.CompletedProcess(args, 0, json.dumps(record), "")
        if "ls" in args:
            return subprocess.CompletedProcess(args, 0, built if reuse_hit else "", "")
        assert "build" in args
        assert args[args.index("--target") + 1] == "runtime-rebase"
        assert "EXISTING_APP_RUNTIME=" + TAG in args
        assert "--pull=false" in args
        assert (kwargs["cwd"] / "cmd/server/main.go").read_text() == "new go"
        Path(args[args.index("--iidfile") + 1]).write_text(built)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(m, "_selector_build_args", lambda *a: {})
    with require_port(m, "frozen_source_context")(
        repo_root=history[0], source_head=source
    ) as snapshot:
        receipt = m.select_or_build_app(
            repo_root=snapshot,
            identity=identity,
            evidence_out=tmp_path / "receipt.json",
            runner=runner,
            real_build_budget_remaining=1,
            docker_context="colima",
        )
    assert receipt["selector"] == ("REUSE" if reuse_hit else "BUILD_AFFECTED")
    assert receipt["build_invocations"] == (0 if reuse_hit else 1)
    assert sum("build" in args for args, _ in calls) == (0 if reuse_hit else 1)
    assert receipt["runtime_reuse"]["image_id"] == BASE
    assert all(path != history[0] for args, path in calls)


@pytest.mark.parametrize("defect", ["parent", "config", "id"])
def test_rebased_result_rejects_wrong_parent_config_or_id(
    history: tuple[Path, str, str], defect: str
) -> None:
    m = module()
    runtime = facts(m, history)
    child_id = "sha256:" + "d" * 64
    record = json.loads(ImageRunner(history[1])(("docker", "inspect", BASE)).stdout)
    record["Id"] = child_id
    record["RootFS"]["Layers"] += ["sha256:" + "e" * 64]
    if defect == "parent":
        record["RootFS"]["Layers"][0] = "sha256:" + "f" * 64
    elif defect == "config":
        record["Config"]["User"] = "0"
    else:
        record["Id"] = BASE

    def runner(args: Sequence[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, json.dumps(record), "")

    with pytest.raises(m.ArtifactContractError, match="rebased image"):
        m._verify_rebased_image(history[0], child_id, runtime, runner, "colima")


def test_pure_go_change_allows_empty_runtime_resource_diff(history: tuple[Path, str, str]) -> None:
    m = module()
    repo, old, _ = history
    git(repo, "checkout", old, "--", "scripts/app_artifact.py")
    git(repo, "commit", "-qm", "pure Go source without runtime changes")
    result = facts(m, (repo, old, git(repo, "rev-parse", "HEAD")))
    assert result["image_id"] == BASE


def test_unqualified_docker_build_keeps_original_runtime_default() -> None:
    source = (ROOT / "docker/Dockerfile.app").read_text()
    stages = [line for line in source.splitlines() if line.startswith("FROM ")]
    assert stages[-1] == "FROM ${RUNTIME_IMAGE} AS runtime"
    m = module()
    old = (
        "ARG RUNTIME_IMAGE\nFROM base AS builder\nRUN build\n"
        "FROM ${RUNTIME_IMAGE} AS runtime\nRUN install-critical-runtime\n"
    )
    stage = (
        "FROM ${EXISTING_APP_RUNTIME} AS runtime-rebase\n"
        "COPY --from=builder /app/WeKnora /app/WeKnora\n"
    )
    revised = old.replace(
        "FROM ${RUNTIME_IMAGE} AS runtime", stage + "\nFROM ${RUNTIME_IMAGE} AS runtime"
    )
    assert m._runtime_recipe(revised) == m._runtime_recipe(old)
    assert m._runtime_recipe(
        revised.replace("install-critical-runtime", "wrong-runtime")
    ) != m._runtime_recipe(old)


def test_frozen_directories_remain_traversable_under_private_umask(
    history: tuple[Path, str, str],
) -> None:
    import os
    import stat

    m = module()
    previous = os.umask(0o077)
    try:
        with m.frozen_source_context(repo_root=history[0], source_head=history[2]) as snapshot:
            directories = [Path(snapshot), *[p for p in Path(snapshot).rglob("*") if p.is_dir()]]
            assert all(stat.S_IMODE(p.stat().st_mode) == 0o755 for p in directories)
            assert stat.S_IMODE((Path(snapshot) / "scripts/start.sh").stat().st_mode) == 0o644
    finally:
        os.umask(previous)

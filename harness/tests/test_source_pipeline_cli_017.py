"""CLI and resource-lifecycle contracts for source pipelines."""

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from insurance_harness.compiler import cli as compiler_cli
from insurance_harness.compiler.models import RunManifest
from insurance_harness.compiler.templates import TemplateRegistry
from insurance_harness.config import HarnessSettings
from insurance_harness.db import Base, make_engine
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import is_database_bound_scope
from insurance_harness.schemas import SchemaRegistry
from insurance_harness.sources import DirectorySourceRequest
from tests.support.source_pipeline import (
    REGISTRY,
    NoModelCalls,
)


def _production_settings(**updates: object) -> HarnessSettings:
    values: dict[str, object] = {
        "weknora_base_url": "https://weknora.invalid",
        "weknora_api_key": "secret",
        "model_profile": "production",
        "production_model_provider": "bailian",
        "production_model_deployment_id": "qwen3-prod-20260722-sha256-a1",
        "production_model_family": "qwen",
        "production_model_policy_version": "pwb-v1",
        "judge_mode": "guarded",
        "llm_base_url": "https://provider.invalid/compatible-mode/v1",
        "llm_api_key": "provider-secret",
    }
    for name in HarnessSettings.model_fields:
        if not name.startswith("production_expected_"):
            continue
        if name.endswith(("_hash", "_digest")):
            values[name] = "a" * 64
        elif name == "production_expected_clean_integration_sha":
            values[name] = "b" * 40
        else:
            values[name] = f"test-{name.removeprefix('production_expected_')}"
    values.update(updates)
    return HarnessSettings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("command", ["extract", "extract-replay"])
def test_cli_rejects_zero_concurrency_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    async def reject_dispatch(args: object) -> int:
        del args
        pytest.fail("zero concurrency must fail during argument parsing")

    monkeypatch.setattr(compiler_cli, "_cmd_extract", reject_dispatch)
    monkeypatch.setattr(compiler_cli, "_cmd_extract_replay", reject_dispatch)
    if command == "extract":
        argv = [
            "extract",
            "--source",
            "weknora",
            "--space-id",
            "space-1",
            "--parser-fingerprint",
            "parser-v1",
            "--knowledge-id",
            "knowledge-1",
            "--product-id",
            "PRODUCT01",
            "--product-name",
            "Product One",
            "--run-dir",
            str(tmp_path / "run"),
            "--concurrency",
            "0",
        ]
    else:
        argv = [
            "extract-replay",
            str(tmp_path / "product"),
            "--replay-identity",
            "fixture-1",
            "--parser-fingerprint",
            "parser-v1",
            "--run-dir",
            str(tmp_path / "run"),
            "--concurrency",
            "0",
        ]

    with pytest.raises(SystemExit) as error:
        compiler_cli.main(argv)
    assert error.value.code == 2


def test_production_extract_requires_and_dispatches_explicit_weknora_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[argparse.Namespace] = []

    async def fake_extract(args: argparse.Namespace) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(compiler_cli, "_cmd_extract", fake_extract)
    assert (
        compiler_cli.main(
            [
                "extract",
                "--source",
                "weknora",
                "--space-id",
                "space-1",
                "--parser-fingerprint",
                "pdfplumber@0.11:text-v1",
                "--knowledge-id",
                "knowledge-1",
                "--product-id",
                "PRODUCT01",
                "--product-name",
                "Product One",
                "--db-url",
                "sqlite:///scope.db",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    assert len(captured) == 1
    args = captured[0]
    assert args.source == "weknora"
    assert args.knowledge_ids == ["knowledge-1"]
    assert not hasattr(args, "product_dir")


def test_extract_replay_is_the_only_cli_command_with_directory_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    captured: list[argparse.Namespace] = []

    async def fake_replay(args: argparse.Namespace) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(compiler_cli, "_cmd_extract_replay", fake_replay, raising=False)
    assert (
        compiler_cli.main(
            [
                "extract-replay",
                str(product_dir),
                "--replay-identity",
                "golden:product-1",
                "--parser-fingerprint",
                "fixture-parser-v1",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    assert len(captured) == 1
    args = captured[0]
    assert args.product_dir == product_dir
    assert args.replay_identity == "golden:product-1"
    assert not hasattr(args, "source")
    assert not hasattr(args, "space_id")


def test_extract_replay_constructs_only_directory_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeDirectorySource:
        def __init__(self, **kwargs: object) -> None:
            captured["source_kwargs"] = kwargs

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            captured["pipeline_kwargs"] = kwargs

        async def run(self, **kwargs: object) -> SimpleNamespace:
            captured["run_kwargs"] = kwargs
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="replay", product_dir=str(product_dir)),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    monkeypatch.setattr(
        compiler_cli, "DirectoryDocumentSource", FakeDirectorySource, raising=False
    )
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)
    monkeypatch.setattr(
        compiler_cli,
        "load_settings",
        lambda: SimpleNamespace(
            model_profile="offline-eval",
            judge_mode="claude-session",
            table_provider="pdfplumber",
        ),
    )
    monkeypatch.setattr(compiler_cli, "build_client", lambda *args: (NoModelCalls(), "replay"))
    monkeypatch.setattr(compiler_cli, "load_schema_registry", lambda _: REGISTRY)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)

    assert (
        compiler_cli.main(
            [
                "extract-replay",
                str(product_dir),
                "--replay-identity",
                "golden:product-1",
                "--parser-fingerprint",
                "fixture-parser-v1",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    assert captured["source_kwargs"] == {
        "replay_identity": "golden:product-1",
        "parser_fingerprint": "fixture-parser-v1",
    }
    pipeline_kwargs = captured["pipeline_kwargs"]
    assert isinstance(pipeline_kwargs, dict)
    assert isinstance(pipeline_kwargs["source"], FakeDirectorySource)
    assert pipeline_kwargs.get("scope") is None
    run_kwargs = captured["run_kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["product_dir"] == product_dir
    assert run_kwargs["source_request"] == DirectorySourceRequest(product_dir=product_dir)


def test_production_extract_loads_bound_scope_and_passes_all_source_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = f"sqlite:///{tmp_path}/scope.db"
    seed_engine = make_engine(db_url)
    Base.metadata.create_all(seed_engine)
    with Session(seed_engine) as session:
        session.add(
            KnowledgeSpace(
                id="space-1",
                name="Production",
                tenant_id="tenant-1",
                raw_kb_id="raw-1",
                wiki_kb_id="wiki-1",
                binding_status="bound",
            )
        )
        session.commit()
    seed_engine.dispose()
    settings = _production_settings(
        db_url=db_url,
        production_expected_space_id="space-1",
        source_max_documents_per_batch=3,
        source_max_batch_bytes=4_000,
        source_max_batch_pages=50,
        source_max_batch_chunks=600,
    )
    captured: dict[str, object] = {}

    class TrackingSession:
        def __init__(self, engine: object) -> None:
            self._session = Session(engine)  # type: ignore[arg-type]

        def __enter__(self) -> Session:
            captured["session_active"] = True
            return self._session

        def __exit__(self, *args: object) -> None:
            del args
            self._session.close()
            captured["session_active"] = False

    class FakeWeKnoraClient:
        def __init__(self, client_settings: HarnessSettings) -> None:
            assert client_settings is settings
            captured["client"] = self

        async def aclose(self) -> None:
            captured["client_closed"] = True

    class FakeWeKnoraSource:
        def __init__(self, **kwargs: object) -> None:
            captured["source_kwargs"] = kwargs
            self.scope = kwargs["scope"]

    class RejectDirectorySource:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            pytest.fail("production extract must not construct DirectoryDocumentSource")

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            captured["pipeline_kwargs"] = kwargs

        async def run(self, **kwargs: object) -> SimpleNamespace:
            captured["run_kwargs"] = kwargs
            assert captured["session_active"] is False
            pipeline_kwargs = captured["pipeline_kwargs"]
            assert isinstance(pipeline_kwargs, dict)
            scope = pipeline_kwargs["scope"]
            assert is_database_bound_scope(scope)
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="production", product_dir=""),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    monkeypatch.setattr(compiler_cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(
        compiler_cli,
        "_build_production_compiler_client",
        lambda *args, **kwargs: NoModelCalls(),
    )
    monkeypatch.setattr(compiler_cli, "load_schema_registry", lambda _: REGISTRY)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)
    monkeypatch.setattr(compiler_cli, "Session", TrackingSession)
    monkeypatch.setattr(compiler_cli, "WeKnoraClient", FakeWeKnoraClient, raising=False)
    monkeypatch.setattr(
        compiler_cli, "WeKnoraDocumentSource", FakeWeKnoraSource, raising=False
    )
    monkeypatch.setattr(compiler_cli, "DirectoryDocumentSource", RejectDirectorySource)
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)

    assert (
        compiler_cli.main(
            [
                "extract",
                "--source",
                "weknora",
                "--space-id",
                "space-1",
                "--parser-fingerprint",
                "parser-v1",
                "--knowledge-id",
                "knowledge-1",
                "--knowledge-id",
                "knowledge-2",
                "--product-id",
                "PRODUCT01",
                "--product-name",
                "Product One",
                "--db-url",
                db_url,
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    source_kwargs = captured["source_kwargs"]
    assert isinstance(source_kwargs, dict)
    assert source_kwargs["client"] is captured["client"]
    assert source_kwargs["parser_fingerprint"] == "parser-v1"
    assert source_kwargs["source_max_documents_per_batch"] == 3
    assert source_kwargs["source_max_batch_bytes"] == 4_000
    assert source_kwargs["source_max_batch_pages"] == 50
    assert source_kwargs["source_max_batch_chunks"] == 600
    run_kwargs = captured["run_kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["product_dir"] is None
    assert run_kwargs["product_id"] == "PRODUCT01"
    assert run_kwargs["product_name"] == "Product One"
    assert run_kwargs["source_request"].knowledge_ids == (
        "knowledge-1",
        "knowledge-2",
    )
    assert captured["client_closed"] is True


@pytest.mark.parametrize(
    "failure_stage",
    [
        "schema",
        "canonical_builder",
        "engine_constructor",
        "weknora_constructor",
        "scope",
        "source_constructor",
        "pipeline_constructor",
        "run",
        "source_aclose",
        "model_aclose",
    ],
)
async def test_production_extract_attempts_all_registered_resource_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    events: list[str] = []
    resources: list[str] = []

    class ClosableModel:
        def __init__(self, name: str) -> None:
            self.name = name
            resources.append(name)

        async def complete(self, system: str, user: str) -> str:
            del system, user
            return "[]"

        async def aclose(self) -> None:
            events.append(f"close:{self.name}")
            if failure_stage == f"{self.name}_aclose":
                raise RuntimeError(f"boom:{failure_stage}")

    class FakeEngine:
        def __init__(self) -> None:
            events.append("create:engine")

        def dispose(self) -> None:
            events.append("dispose:engine")

    class FakeSession:
        def __init__(self, engine: object) -> None:
            del engine

        def __enter__(self) -> object:
            return object()

        def __exit__(self, *args: object) -> None:
            del args

    class FakeSource:
        pass

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            if failure_stage == "pipeline_constructor":
                raise RuntimeError(f"boom:{failure_stage}")

        async def run(self, **kwargs: object) -> SimpleNamespace:
            if failure_stage == "run":
                raise RuntimeError(f"boom:{failure_stage}")
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="production", product_dir=""),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    settings = _production_settings(
        db_url="sqlite:///unused.db",
        production_expected_space_id="space-1",
    )

    def load_registry(_: object) -> SchemaRegistry:
        if failure_stage == "schema":
            raise RuntimeError(f"boom:{failure_stage}")
        return REGISTRY

    def make_production_client(*args: object, **kwargs: object) -> ClosableModel:
        del args, kwargs
        if failure_stage == "canonical_builder":
            raise RuntimeError(f"boom:{failure_stage}")
        return ClosableModel("model")

    def make_fake_engine(_: str) -> FakeEngine:
        if failure_stage == "engine_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return FakeEngine()

    def make_source_client(_: HarnessSettings) -> ClosableModel:
        if failure_stage == "weknora_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return ClosableModel("source")

    def load_fake_scope(session: object, space_id: str) -> object:
        del session, space_id
        if failure_stage == "scope":
            raise RuntimeError(f"boom:{failure_stage}")
        return object()

    def make_document_source(**kwargs: object) -> FakeSource:
        del kwargs
        if failure_stage == "source_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return FakeSource()

    monkeypatch.setattr(compiler_cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(
        compiler_cli,
        "_build_production_compiler_client",
        make_production_client,
    )
    monkeypatch.setattr(compiler_cli, "load_schema_registry", load_registry)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "make_engine", make_fake_engine)
    monkeypatch.setattr(compiler_cli, "WeKnoraClient", make_source_client)
    monkeypatch.setattr(compiler_cli, "Session", FakeSession)
    monkeypatch.setattr(compiler_cli, "load_scope", load_fake_scope)
    monkeypatch.setattr(compiler_cli, "WeKnoraDocumentSource", make_document_source)
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)
    args = argparse.Namespace(
        replay_dir=None,
        model=None,
        schema_dir=tmp_path / "schema",
        templates_dir=None,
        db_url=None,
        space_id="space-1",
        parser_fingerprint="parser-v1",
        concurrency=1,
        product_id="PRODUCT01",
        product_name="Product One",
        run_dir=tmp_path / "run",
        knowledge_ids=["knowledge-1"],
        line_key="t",
        resume=False,
    )

    with pytest.raises(RuntimeError, match=rf"^boom:{failure_stage}$"):
        await compiler_cli._cmd_extract(args)  # noqa: SLF001

    for resource in resources:
        assert f"close:{resource}" in events
    if "create:engine" in events:
        assert "dispose:engine" in events


@pytest.mark.parametrize(
    "failure_stage",
    [
        "schema",
        "judge_constructor",
        "source_constructor",
        "pipeline_constructor",
        "run",
        "judge_aclose",
    ],
)
async def test_replay_extract_attempts_all_registered_resource_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    events: list[str] = []
    resources: list[str] = []

    class ClosableModel:
        def __init__(self, name: str) -> None:
            self.name = name
            resources.append(name)

        async def complete(self, system: str, user: str) -> str:
            del system, user
            return "[]"

        async def aclose(self) -> None:
            events.append(f"close:{self.name}")
            if failure_stage == f"{self.name}_aclose":
                raise RuntimeError(f"boom:{failure_stage}")

    class FakeDirectorySource:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            if failure_stage == "source_constructor":
                raise RuntimeError(f"boom:{failure_stage}")

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            if failure_stage == "pipeline_constructor":
                raise RuntimeError(f"boom:{failure_stage}")

        async def run(self, **kwargs: object) -> SimpleNamespace:
            if failure_stage == "run":
                raise RuntimeError(f"boom:{failure_stage}")
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="replay", product_dir=str(tmp_path)),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    settings = HarnessSettings(
        weknora_base_url="https://unused.invalid",
        weknora_api_key="unused",
        model_profile="offline-eval",
        llm_base_url="https://llm.invalid",
        llm_api_key="secret",
        llm_model_judge_fallback="judge-model",
        judge_mode="gateway",
    )
    model_client = ClosableModel("model")

    def load_registry(_: object) -> SchemaRegistry:
        if failure_stage == "schema":
            raise RuntimeError(f"boom:{failure_stage}")
        return REGISTRY

    def make_judge_client(**kwargs: object) -> ClosableModel:
        del kwargs
        if failure_stage == "judge_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return ClosableModel("judge")

    monkeypatch.setattr(compiler_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        compiler_cli, "build_client", lambda *args: (model_client, "model")
    )
    monkeypatch.setattr(compiler_cli, "load_schema_registry", load_registry)
    monkeypatch.setattr(compiler_cli, "OpenAICompatClient", make_judge_client)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "DirectoryDocumentSource", FakeDirectorySource)
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)
    args = argparse.Namespace(
        replay_dir=None,
        model=None,
        schema_dir=tmp_path / "schema",
        templates_dir=None,
        replay_identity="fixture-1",
        parser_fingerprint="parser-v1",
        concurrency=1,
        product_dir=tmp_path / "product",
        run_dir=tmp_path / "run",
        line_key="t",
        resume=False,
    )

    with pytest.raises(RuntimeError, match=rf"^boom:{failure_stage}$"):
        await compiler_cli._cmd_extract_replay(args)  # noqa: SLF001

    for resource in resources:
        assert f"close:{resource}" in events


@pytest.mark.parametrize(
    "omitted_flag",
    ["--source", "--space-id", "--parser-fingerprint", "--knowledge-id"],
)
def test_production_extract_missing_source_identity_never_dispatches_or_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    omitted_flag: str,
) -> None:
    argv = [
        "extract",
        "--source",
        "weknora",
        "--space-id",
        "space-1",
        "--parser-fingerprint",
        "parser-v1",
        "--knowledge-id",
        "knowledge-1",
        "--product-id",
        "PRODUCT01",
        "--product-name",
        "Product One",
        "--db-url",
        "sqlite:///scope.db",
        "--run-dir",
        str(tmp_path / "run"),
    ]
    index = argv.index(omitted_flag)
    del argv[index : index + 2]

    async def reject_dispatch(args: object) -> int:
        del args
        pytest.fail("invalid production arguments must not dispatch")

    monkeypatch.setattr(compiler_cli, "_cmd_extract", reject_dispatch)
    with pytest.raises(SystemExit) as caught:
        compiler_cli.main(argv)

    assert caught.value.code == 2


def test_production_extract_rejects_directory_source_value(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        compiler_cli.main(
            [
                "extract",
                "--source",
                "directory",
                "--space-id",
                "space-1",
                "--parser-fingerprint",
                "parser-v1",
                "--knowledge-id",
                "knowledge-1",
                "--product-id",
                "PRODUCT01",
                "--product-name",
                "Product One",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )

    assert caught.value.code == 2

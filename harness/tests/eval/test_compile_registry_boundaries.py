"""Registry CLI boundaries over temporary files and the existing fake completion port."""

import json
from pathlib import Path
from typing import NoReturn

import pytest

from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.eval import compile_run
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import CallLedger, StageModelConfig
from tests.eval.test_compile_run import CONFIG, TEXT, factory, write_json
from tests.eval.test_compile_run import repo as prepared_repo  # noqa: F401


@pytest.fixture
def repo(request: pytest.FixtureRequest) -> Path:
    directory: Path = request.getfixturevalue("prepared_repo")
    return directory


def registry_file(tmp_path: Path, product: str = "created") -> Path:
    path = tmp_path / "registry.json"
    write_json(path, {
        "contract": "product-registry.v1", "space_id": "space", "raw_kb_id": "raw",
        "products": {product: {
            "names": ["登记名称", "别名"], "clause_codes": [], "schema_pack_id": "pack-a",
            "origin": "created", "materials": [
                {"knowledge_id": knowledge, "parse_attempt": attempt, "sha256": digest * 64,
                 "role": "terms", "file_name": f"{knowledge}-保险条款.pdf"}
                for knowledge, attempt, digest in (("z", 2, "b"), ("a", 7, "a"))
            ],
        }}, "pending": [], "decisions": [],
    })
    return path


def argv(
    repo: Path, root: Path, *sources: str, products: tuple[str, ...] = ("created",),
) -> list[str]:
    return ["--repo", str(repo), "--run-root", str(root), "--products", *products,
            "--stage", "schema_fields", "--stage-config", "unused", *sources]


def unexpected(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail("registry preflight reached a dataset, page reader or model")


def test_registry_cli_uses_canonical_facts_and_fixed_revisions_without_dataset(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reads: list[tuple[str, str, int]] = []

    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            reads.append((space, knowledge, attempt))
            return [PageText(f"{knowledge}-保险条款.pdf", ("a" if knowledge == "a" else "b") * 64,
                             1, TEXT)]

    build, sent = factory(["m"] * 4)

    def client(config: StageModelConfig, *, ledger: CallLedger) -> CompletionPort:
        return build(ledger)

    monkeypatch.setattr(compile_run, "source_directory", unexpected)
    monkeypatch.setattr(compile_run, "declared_pack", unexpected)
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    monkeypatch.setattr(compile_run, "reader_from_env", Reader)
    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", client)
    registry, root = registry_file(tmp_path), tmp_path / "run"
    args = argv(repo, root, "--registry", str(registry))
    assert compile_run.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["products"][0]["display_name"] == "登记名称"
    output = json.loads((root / "created/output.json").read_text())
    assert output["pack_id"] == "pack-a"
    assert output["materials"] == ["a:7:" + "a" * 64, "z:2:" + "b" * 64]
    assert reads == [("space", "a", 7), ("space", "z", 2)]
    assert json.loads((root / "product-map.json").read_text()) == {"登记名称": "created"}
    assert len(sent) == 2
    assert compile_run.main(args) == 0
    assert json.loads(capsys.readouterr().out)["products"][0]["reused"] is True
    assert len(sent) == 2

    # The same bytes under a new parse attempt must compile again, rather than reuse.
    document = json.loads(registry.read_text())
    document["products"]["created"]["materials"][1]["parse_attempt"] = 8
    write_json(registry, document)
    assert compile_run.main(args) == 0
    assert json.loads(capsys.readouterr().out)["products"][0]["reused"] is False
    assert len(sent) == 4 and reads[-2:] == [("space", "a", 8), ("space", "z", 2)]


@pytest.mark.parametrize("failure,code", [
    ("unknown", "PRODUCT_UNKNOWN"), ("missing", "REGISTRY_IO_ERROR"),
    ("invalid", "REGISTRY_INVALID"), ("unicode", "REGISTRY_INVALID"),
])
def test_registry_cli_preflights_all_products_before_reader_or_model(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], failure: str, code: str,
) -> None:
    registry = registry_file(tmp_path)
    if failure == "missing":
        registry.unlink()
    elif failure in {"invalid", "unicode"}:
        registry.write_bytes(b"private material {broken" if failure == "invalid" else b"\xff")
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    monkeypatch.setattr(compile_run, "reader_from_env", unexpected)
    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", unexpected)
    root = tmp_path / "run"
    assert compile_run.main(argv(repo, root, "--registry", str(registry),
                                 products=("created", "not-registered"))) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"stopped": code, "products": []}
    assert not captured.err and str(tmp_path) not in captured.out
    assert "private material" not in captured.out
    assert not root.exists()


def test_facts_without_pages_rejects_before_constructing_completion(
    repo: Path, tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        compile_run.compile_products(
            repo, ["p1"], completion_factory=unexpected, run_root=tmp_path / "run",
            max_sent=0, facts=lambda _: ("产品一", "pack-a"),
        )
    assert not (tmp_path / "run").exists()

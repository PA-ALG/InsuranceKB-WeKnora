"""S5b-6 round-2 acceptance (protected, written by Claude): the effective material role is part of
a compile output's input identity, and a recorded role applies only to the registered file.

Spec docs/design/slices/S5b-6-已确认材料角色用于编译.md §5. Offline: temporary registries, a fake
page reader and the existing fake completion port; no HTTP or model calls.
"""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput, CompletionPort
from insurance_harness.compilers.schema_fields.prompt import VALUE_PROTOCOL_VERSION
from insurance_harness.eval import compile_run
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest import publication
from insurance_harness.ingest.registry import MaterialEntry, ProductEntry, ProductRegistry
from insurance_harness.ingest.source_map import SourceEntry, SourceMapError, load_trusted_pages
from insurance_harness.models import CallLedger, StageModelConfig
from tests.eval.test_compile_registry_boundaries import argv, registry_file, unexpected
from tests.eval.test_compile_run import CONFIG, TEXT, factory, write_json
from tests.eval.test_compile_run import repo as prepared_repo  # noqa: F401
from tests.ingest.upload_helpers import entry, knowledge_id, material, registry


@pytest.fixture
def repo(request: pytest.FixtureRequest) -> Path:
    directory: Path = request.getfixturevalue("prepared_repo")
    return directory


def test_a_changed_recorded_role_makes_the_compile_output_stale(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            return [
                PageText(
                    f"{knowledge}-保险条款.pdf", ("a" if knowledge == "a" else "b") * 64, 1, TEXT
                )
            ]

    build, sent = factory(["m"] * 6)

    def client(config: StageModelConfig, *, ledger: CallLedger) -> CompletionPort:
        return build(ledger)

    monkeypatch.setattr(compile_run, "source_directory", unexpected)
    monkeypatch.setattr(compile_run, "declared_pack", unexpected)
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    monkeypatch.setattr(compile_run, "reader_from_env", Reader)
    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", client)
    path, root = registry_file(tmp_path), tmp_path / "run"
    args = argv(repo, root, "--registry", str(path))
    assert compile_run.main(args) == 0
    capsys.readouterr()
    output = json.loads((root / "created/output.json").read_text())
    assert output["material_roles"] == {
        "a:7:" + "a" * 64: "terms",
        "z:2:" + "b" * 64: "terms",
    }, "each material's effective role is recorded with the output"
    assert compile_run.main(args) == 0
    assert json.loads(capsys.readouterr().out)["products"][0]["reused"] is True
    calls = len(sent)

    # Same files, same revisions: only the recorded role changes.
    document = json.loads(path.read_text())
    document["products"]["created"]["materials"][0]["role"] = "brochure"
    write_json(path, document)
    assert compile_run.main(args) == 0
    assert json.loads(capsys.readouterr().out)["products"][0]["reused"] is False
    assert len(sent) > calls
    output = json.loads((root / "created/output.json").read_text())
    assert output["material_roles"]["z:2:" + "b" * 64] == "brochure"


def planning_registry(role: str) -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1",
        space_id="space",
        raw_kb_id="raw",
        products={
            "a": ProductEntry(
                names=["a"],
                clause_codes=[],
                schema_pack_id="pack-a",
                origin="created",
                materials=[
                    MaterialEntry(
                        knowledge_id="a-1",
                        parse_attempt=1,
                        sha256="b" * 64,
                        role=role,
                        file_name="file.pdf",
                    )
                ],
            )
        },
        pending=[],
        decisions=[],
    )


def store(root: Path, roles: dict[str, str] | None) -> None:
    output = CompileOutput(
        entity_id="a",
        pack_id="pack-a",
        model="fake",
        materials=["a-1:1:" + "b" * 64],
        material_roles=roles,
        cards_version=cards_version(),
        value_protocol=VALUE_PROTOCOL_VERSION,
    )
    path = root / "compile" / "a" / "output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = output.model_dump_json(indent=2).encode()
    path.write_bytes(data)
    publication._save_published(root, {"a": hashlib.sha256(data).hexdigest()})


def test_publication_planning_recompiles_after_a_role_change(tmp_path: Path) -> None:
    store(tmp_path, {"a-1:1:" + "b" * 64: "terms"})
    assert publication.plan(planning_registry("terms"), tmp_path, ["a"]).compile == []
    result = publication.plan(planning_registry("brochure"), tmp_path, ["a"])
    assert result.compile == ["a"] and result.publish == ["a"]


def test_an_output_without_recorded_roles_is_not_reused(tmp_path: Path) -> None:
    store(tmp_path, None)
    assert publication.plan(planning_registry("terms"), tmp_path, ["a"]).compile == ["a"]


class ShaReader:
    def __init__(self, sha: str) -> None:
        self.sha = sha

    def pages(self, space_id: str, knowledge: str, attempt: int) -> list[PageText]:
        return [PageText("费率表.pdf", self.sha, 1, "转换标准表第一页")]


def test_a_recorded_role_needs_the_registered_file() -> None:
    expected, other = "c" * 64, "d" * 64
    entries = [SourceEntry(knowledge_id="k", parse_attempt=1, role="rate_table", sha256=expected)]
    trusted, _ = load_trusted_pages(ShaReader(expected), "space", entries)
    assert [p.document for p in trusted.table_headers["rate_table"]] == ["费率表.pdf"]
    with pytest.raises(SourceMapError) as caught:
        load_trusted_pages(ShaReader(other), "space", entries)
    assert caught.value.code == "MATERIAL_IDENTITY_MISMATCH"


def test_the_registry_source_map_carries_the_registered_sha() -> None:
    value = registry(p1828=entry("1828", "terms"))
    assert value.source_map().products["1828"] == [
        SourceEntry(
            knowledge_id=knowledge_id("1828", "terms"),
            parse_attempt=1,
            role="terms",
            sha256=material("1828", "terms")["sha256"],
        ),
    ]

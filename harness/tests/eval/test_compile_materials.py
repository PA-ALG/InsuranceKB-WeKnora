"""Material-aware reuse uses actual revisions and replaces only complete outputs."""

import fcntl
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.trust_policy import TrustedPages
from insurance_harness.compilers.schema_fields import engine
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import (
    SELECTION_DRAWS,
    CompileError,
    CompileOutput,
    CompletionPort,
)
from insurance_harness.eval import compile_run, product_sources
from insurance_harness.eval.compile_run import ProductRun, compile_products, prior_sends
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.models import (
    CallLedger,
    ModelBudgetExceeded,
    OpenAICompatibleCompletion,
    StageModelConfig,
)

CONFIG = StageModelConfig(
    stage="schema_fields", provider="example", base_url="https://api.example.com",
    model="offline", api_key_env="TEST_KEY", max_tokens=4096, policy_version="test.1",
)
TEXT = "等待期为90日。\n阅读指引"


def save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    directory = root / "dataset/shouxian_product/product"
    save(directory / "product_meta.json", {"planCode": "p", "clauseName": "产品"})
    (directory / "保险条款.pdf").write_bytes(b"terms")
    save(root / "dataset/golden/v2/manifest.json", {"products": {"p": {"pack_id": "pack"}}})
    save(root / SCHEMA_PACK_CATALOG, {
        "entries": [{"pack": {"schema_pack_id": "pack", "fields": [{
            "field_key": "waiting_period", "short_title": "等待期", "description": "等待期",
            "formation_method": "原文抽取",
        }]}}],
    })

    def read(path: Path) -> list[PageText]:
        return [PageText(path.name, hashlib.sha256(path.read_bytes()).hexdigest(), 1, TEXT)]

    monkeypatch.setattr(product_sources, "read_pdf", read)
    return root


def completion_factory(
    sent: list[str], *, invalid: bool = False,
) -> Callable[[CallLedger], CompletionPort]:
    def factory(ledger: CallLedger) -> CompletionPort:
        def answer(request: httpx.Request) -> httpx.Response:
            sent.append(request.content.decode())
            data = json.loads(json.loads(request.content)["messages"][1]["content"])
            raw = "SOURCE-SECRET" if invalid else json.dumps({"fields": [{
                "ordinal": f["ordinal"], "field_key": f["field_key"], "state": "unknown",
                "segments": [],
            } for f in data["schema_fields"]]})
            return httpx.Response(200, json={
                "model": "offline-fixed", "choices": [{
                    "message": {"content": raw}, "finish_reason": "stop",
                }],
            })

        return OpenAICompatibleCompletion(
            CONFIG, ledger=ledger, environ={"TEST_KEY": "offline"},
            transport=httpx.MockTransport(answer),
        )

    return factory


def compile_at(repo: Path, root: Path, sent: list[str], **options: Any) -> list[ProductRun]:
    return compile_products(
        repo, ["p"], completion_factory=completion_factory(sent), run_root=root,
        max_sent=options.pop("max_sent", 20), **options,
    )


def output_at(root: Path) -> dict[str, Any]:
    return json.loads((root / "p/output.json").read_text())  # type: ignore[no-any-return]


def mapped(
    *, knowledge: str = "knowledge", attempt: int = 7, digest: str = "a" * 64,
) -> tuple[TrustedPages[PageText], dict[str, SourceRevision]]:
    return TrustedPages([PageText("original.pdf", digest, 1, TEXT)], {}), {
        "original.pdf": SourceRevision(knowledge, attempt),
    }


def test_local_materials_record_actual_hash_and_recompile_changed_file(
    repo: Path, tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    assert output_at(root)["materials"] == [f"file:{hashlib.sha256(b'terms').hexdigest()}"]
    assert compile_at(repo, root, sent)[0].reused
    (product_sources.source_directory(repo, "p") / "保险条款.pdf").write_bytes(b"reissued")
    assert not compile_at(repo, root, sent)[0].reused
    assert len(sent) == prior_sends(root) == 2 * SELECTION_DRAWS
    assert output_at(root)["materials"] == [f"file:{hashlib.sha256(b'reissued').hexdigest()}"]


def test_material_list_includes_headers_and_reuses_reordered_input(
    repo: Path, tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    evidence = [PageText("terms.pdf", "b" * 64, 1, TEXT)]
    headers = [PageText("rates.pdf", "a" * 64, 1, "交费期间\n10年交\n0 999")]
    read = TrustedPages(evidence, {"rate_table": headers})
    compile_at(repo, root, sent, page_source=lambda _: read)
    assert output_at(root)["materials"] == ["file:" + "a" * 64, "file:" + "b" * 64]
    ordinary = [*evidence, PageText("manual.pdf", "c" * 64, 1, "说明书")]
    next_root = tmp_path / "ordered"
    compile_at(repo, next_root, sent, page_source=lambda _: ordinary)
    assert compile_at(repo, next_root, sent, page_source=lambda _: ordinary[::-1])[0].reused
    changed = TrustedPages(evidence, {"rate_table": [
        PageText("rates.pdf", "d" * 64, 1, headers[0].text),
    ]})
    assert not compile_at(repo, root, sent, page_source=lambda _: changed)[0].reused


@pytest.mark.parametrize("changed", [
    {"knowledge": "another"}, {"attempt": 8}, {"digest": "b" * 64},
])
def test_source_revision_identity_changes_force_new_compile(
    repo: Path, tmp_path: Path, changed: dict[str, Any],
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent, revision_page_source=lambda _: mapped())
    assert output_at(root)["materials"] == ["knowledge:7:" + "a" * 64]
    assert compile_at(repo, root, sent, revision_page_source=lambda _: mapped())[0].reused
    assert not compile_at(
        repo, root, sent, revision_page_source=lambda _: mapped(**changed),
    )[0].reused
    assert len(sent) == prior_sends(root) == 2 * SELECTION_DRAWS


def test_changed_cards_version_recompiles_and_records_current_version(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    monkeypatch.setattr(engine, "cards_version", lambda: "next-cards")
    monkeypatch.setattr(compile_run, "cards_version", lambda: "next-cards", raising=False)
    assert not compile_at(repo, root, sent)[0].reused
    assert output_at(root)["cards_version"] == "next-cards"
    assert len(sent) == 2 * SELECTION_DRAWS


@pytest.mark.parametrize("missing", [True, False])
def test_legacy_output_without_materials_recompiles(
    repo: Path, tmp_path: Path, missing: bool,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    previous = output_at(root)
    if missing:
        previous.pop("materials", None)
    else:
        previous["materials"] = None
    save(root / "p/output.json", previous)
    assert not compile_at(repo, root, sent)[0].reused
    assert output_at(root)["materials"]
    assert len(sent) == 2 * SELECTION_DRAWS


def test_failed_recompile_preserves_old_output_and_raw_attempts(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    old = (root / "p/output.json").read_bytes()
    (product_sources.source_directory(repo, "p") / "保险条款.pdf").write_bytes(b"changed")
    with pytest.raises(CompileError):
        compile_products(
            repo, ["p"], completion_factory=completion_factory(sent, invalid=True),
            run_root=root, max_sent=20,
        )
    assert (root / "p/output.json").read_bytes() == old
    assert (root / "p/responses/attempt-01/001.txt").exists()
    assert (root / "p/responses/attempt-02/001.txt").read_text() == "SOURCE-SECRET"
    assert len(sent) == prior_sends(root) == SELECTION_DRAWS + 1


def test_changed_material_does_not_bypass_cumulative_budget(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent, max_sent=SELECTION_DRAWS)
    old = (root / "p/output.json").read_bytes()
    (product_sources.source_directory(repo, "p") / "保险条款.pdf").write_bytes(b"changed")
    with pytest.raises(ModelBudgetExceeded):
        compile_at(repo, root, sent, max_sent=SELECTION_DRAWS)
    assert (root / "p/output.json").read_bytes() == old
    assert len(sent) == prior_sends(root) == SELECTION_DRAWS


def test_atomic_replacement_failure_preserves_old_output(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    old = (root / "p/output.json").read_bytes()
    (product_sources.source_directory(repo, "p") / "保险条款.pdf").write_bytes(b"changed")

    def refuse(source: object, target: object) -> None:
        assert (root / "p/output.json").read_bytes() == old
        raise OSError("replace refused")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="replace refused"):
        compile_at(repo, root, sent)
    assert (root / "p/output.json").read_bytes() == old
    assert sorted(p.name for p in (root / "p").iterdir()) == ["output.json", "responses"]


@pytest.mark.parametrize("metadata", [
    ["file:wrong"], ["file:" + "b" * 64, "file:" + "a" * 64], ["SOURCE-SECRET"],
    ["file:" + "a" * 64, "knowledge:7:" + "b" * 64],
    ["knowledge:7:" + "a" * 64, "knowledge:7:" + "b" * 64],
])
def test_malformed_stored_material_metadata_fails_closed(
    repo: Path, tmp_path: Path, metadata: list[str],
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    output = output_at(root)
    output["materials"] = metadata
    save(root / "p/output.json", output)
    with pytest.raises(ValueError):
        compile_at(repo, root, sent)
    assert len(sent) == SELECTION_DRAWS


@pytest.mark.parametrize("kind", ["hash", "duplicate_page", "missing_revision", "bad_revision"])
def test_ambiguous_or_invalid_current_identity_never_reuses(
    repo: Path, tmp_path: Path, kind: str,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent, revision_page_source=lambda _: mapped())
    read, revisions = mapped()
    if kind == "hash":
        read.evidence.append(PageText("original.pdf", "b" * 64, 2, TEXT))
    elif kind == "duplicate_page":
        read.evidence.append(read.evidence[0])
    elif kind == "missing_revision":
        revisions.clear()
    else:
        revisions["original.pdf"] = SourceRevision("bad:identity", 0)
    with pytest.raises(ValueError):
        compile_at(repo, root, sent, revision_page_source=lambda _: (read, revisions))
    assert len(sent) == SELECTION_DRAWS


def test_replay_refuses_changed_revision_with_identical_pages(repo: Path, tmp_path: Path) -> None:
    source = tmp_path / "original"
    sent: list[str] = []
    compile_at(repo, source, sent, revision_page_source=lambda _: mapped())
    with pytest.raises(ValueError):
        compile_products(
            repo, ["p"], completion_factory=None, run_root=tmp_path / "replay",
            replay_from=source, max_sent=0, revision_page_source=lambda _: mapped(attempt=8),
        )
    assert len(sent) == SELECTION_DRAWS


def test_cli_retains_fixed_revision_identity_and_canonical_order_on_rerun(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, source_map = tmp_path / "run", tmp_path / "sources.json"
    sent: list[str] = []
    reads: list[tuple[str, int]] = []
    writes: list[bool] = []
    original_write = compile_run.write_candidate

    def write(directory: Path, runs: list[ProductRun], *, replace: bool = False) -> None:
        descriptor = os.open(directory / ".lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        writes.append(replace)
        original_write(directory, runs, replace=replace)

    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            reads.append((knowledge, attempt))
            if knowledge == "a-term":
                return [PageText("original-保险条款.pdf", "a" * 64, 1, TEXT)]
            return [PageText("original-费率表.pdf", "b" * 64, 1,
                             "年交费率表\n交费期间\n10年交\n0 999")]

    def client(config: StageModelConfig, *, ledger: CallLedger) -> CompletionPort:
        return completion_factory(sent)(ledger)

    entries = [
        {"knowledge_id": "z-rate", "parse_attempt": 3},
        {"knowledge_id": "a-term", "parse_attempt": 7},
    ]
    monkeypatch.setattr(compile_run, "reader_from_env", Reader)
    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", client)
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    monkeypatch.setattr(compile_run, "write_candidate", write)
    argv = [
        "--repo", str(repo), "--products", "p", "--stage", "schema_fields",
        "--stage-config", "unused", "--run-root", str(root), "--source-map", str(source_map),
    ]
    save(source_map, {"space_id": "s", "products": {"p": entries}})
    assert compile_run.main(argv) == 0
    assert output_at(root)["materials"] == ["a-term:7:" + "a" * 64, "z-rate:3:" + "b" * 64]
    assert reads == [("a-term", 7), ("z-rate", 3)]
    save(source_map, {"space_id": "s", "products": {"p": entries[::-1]}})
    assert compile_run.main(argv) == 0
    assert len(sent) == SELECTION_DRAWS
    assert reads[-2:] == [("a-term", 7), ("z-rate", 3)]
    entries[1]["parse_attempt"] = 8
    save(source_map, {"space_id": "s", "products": {"p": entries}})
    stale = json.loads((root / "candidate.json").read_text())
    save(root / "candidate.json", {**stale, "stale": True})
    assert compile_run.main(argv) == 0
    assert len(sent) == prior_sends(root) == 2 * SELECTION_DRAWS
    assert output_at(root)["materials"] == ["a-term:8:" + "a" * 64, "z-rate:3:" + "b" * 64]
    assert "stale" not in json.loads((root / "candidate.json").read_text())
    assert writes == [False, True, True]
    assert capsys.readouterr().out.count('"stopped"') == 0


def test_file_hashes_are_case_insensitive_without_losing_document_multiplicity(
    repo: Path, tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    pages = [PageText(name, "A" * 64, 1, TEXT) for name in ("one.pdf", "two.pdf")]
    compile_at(repo, root, sent, page_source=lambda _: pages)
    assert output_at(root)["materials"] == ["file:" + "a" * 64] * 2
    lower = [PageText(p.document, p.document_sha256.lower(), p.page, p.text) for p in pages]
    assert compile_at(repo, root, sent, page_source=lambda _: lower)[0].reused
    assert len(sent) == SELECTION_DRAWS


@pytest.mark.parametrize("field,value", [("entity_id", "another"), ("pack_id", "another-pack")])
def test_legacy_output_still_validates_product_and_pack_before_recompile(
    repo: Path, tmp_path: Path, field: str, value: str,
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    output = output_at(root)
    output.pop("materials")
    output[field] = value
    save(root / "p/output.json", output)
    with pytest.raises(ValueError, match="stored output does not match"):
        compile_at(repo, root, sent)
    assert len(sent) == SELECTION_DRAWS


def test_missing_cards_version_never_reuses_material_match(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    output = output_at(root)
    output.pop("cards_version")
    save(root / "p/output.json", output)
    assert not compile_at(repo, root, sent)[0].reused and len(sent) == 2 * SELECTION_DRAWS


def test_cli_recompile_failure_keeps_candidate_and_sanitizes_source_content(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    compile_run.write_candidate(root, [ProductRun("p", "产品", "pack", False, 1, 1)])
    old_output = (root / "p/output.json").read_bytes()
    old_candidate = (root / "candidate.json").read_bytes()
    (product_sources.source_directory(repo, "p") / "保险条款.pdf").write_bytes(b"changed")

    def client(config: StageModelConfig, *, ledger: CallLedger) -> CompletionPort:
        return completion_factory(sent, invalid=True)(ledger)

    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", client)
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    assert compile_run.main([
        "--repo", str(repo), "--products", "p", "--stage", "schema_fields",
        "--stage-config", "unused", "--run-root", str(root),
    ]) == 2
    assert "SOURCE-SECRET" not in capsys.readouterr().out
    assert (root / "p/output.json").read_bytes() == old_output
    assert (root / "candidate.json").read_bytes() == old_candidate


def test_direct_revision_callback_canonicalizes_evidence_headers_and_reuses_reordering(
    repo: Path, tmp_path: Path,
) -> None:
    catalog = repo / SCHEMA_PACK_CATALOG
    data = json.loads(catalog.read_text())
    data["entries"][0]["pack"]["fields"].append({
        "field_key": "premium_payment_term", "short_title": "交费期间",
        "description": "交费期间", "formation_method": "原文抽取",
    })
    save(catalog, data)
    terms = [PageText(f"{name}-保险条款.pdf", digest * 64, 1, text) for name, digest, text in (
        ("a", "a", TEXT), ("z", "b", "等待期为180日。\n阅读指引"),
    )]
    rates = [PageText(f"{name}-费率表.pdf", digest * 64, 1, text) for name, digest, text in (
        ("b", "c", "年交费率表\n交费期间\n10年交\n0 999"),
        ("y", "d", "年交费率表\n交费期间\n20年交\n0 888"),
    )]
    revisions = {p.document: SourceRevision(name, attempt) for p, name, attempt in (
        (terms[0], "a-doc", 7), (terms[1], "z-doc", 3),
        (rates[0], "b-doc", 2), (rates[1], "y-doc", 4),
    )}
    requests: list[str] = []

    class Extract:
        model = "offline"

        def complete(self, *, system: str, user: str) -> str:
            requests.append(user)
            request = json.loads(user)
            rows = []
            for field in request["schema_fields"]:
                row = {"ordinal": field["ordinal"], "field_key": field["field_key"]}
                if "segments" in request:
                    needle = "90日" if field["field_key"] == "waiting_period" else "10年交"
                    sid = next(line.split()[0] for line in request["segments"].splitlines()
                               if needle in line)
                    row.update(state="present", segments=[sid])
                else:
                    row["value"] = "90日" if field["field_key"] == "waiting_period" else "10年"
                rows.append(row)
            return json.dumps({"fields": rows}, ensure_ascii=False)

    root = tmp_path / "run"
    reverse = TrustedPages(terms[::-1], {"rate_table": rates[::-1]})
    compile_products(repo, ["p"], completion_factory=lambda _: Extract(), run_root=root,
                     max_sent=0, revision_page_source=lambda _: (reverse, revisions))
    output = CompileOutput.model_validate_json((root / "p/output.json").read_text())
    rebuilt = claims_from(output, SegmentedSource(terms, table_headers={"rate_table": rates}),
                          revisions)
    assert [claim.evidence[0].source_ref.split(":")[2] for claim in rebuilt] == ["a-doc", "b-doc"]
    assert [f.segment_ids for f in output.fields] == [["D1P1S1"], ["D3P1S1"]]
    canonical = TrustedPages(terms, {"rate_table": rates})
    calls = len(requests)
    runs = compile_products(repo, ["p"], completion_factory=lambda _: Extract(), run_root=root,
                            max_sent=0, revision_page_source=lambda _: (canonical, revisions))
    assert runs[0].reused and len(requests) == calls

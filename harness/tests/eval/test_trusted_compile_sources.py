"""Production compile entry points preserve bounded headers and reject stale replay identity."""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval import compile_run, product_sources
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.source_map import SourceEntry, SourceMap, trusted_page_source

TERM, AGE = "premium_payment_term", "entry_age_range"
RATE_TEXT = "年交费率表\n交费期间\n10年交 20年交\n0 999 888\n"


class Completion:
    model = "offline"

    def complete(self, *, system: str, user: str) -> str:
        data = json.loads(user)
        assert "999" not in user and "888" not in user
        if "segments" in data:
            header = next(
                line.split()[0] for line in data["segments"].splitlines() if "10年交" in line
            )
            rows = [
                {
                    "ordinal": f["ordinal"],
                    "field_key": f["field_key"],
                    "state": "present",
                    "segments": [header],
                }
                for f in data["schema_fields"]
            ]
        else:
            rows = [
                {"ordinal": f["ordinal"], "field_key": f["field_key"], "value": "10年、20年"}
                for f in data["schema_fields"]
            ]
        return json.dumps({"fields": rows}, ensure_ascii=False)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    directory = root / "dataset/shouxian_product/example"
    directory.mkdir(parents=True)
    (directory / "product_meta.json").write_text(
        json.dumps({"planCode": "p", "clauseName": "产品"})
    )
    for name in ("保险条款.pdf", "费率表.pdf"):
        (directory / name).write_bytes(name.encode())
    catalog = root / SCHEMA_PACK_CATALOG
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "pack": {
                            "schema_pack_id": "pack",
                            "fields": [
                                {
                                    "field_key": key,
                                    "short_title": key,
                                    "description": key,
                                    "formation_method": "原文抽取",
                                }
                                for key in (TERM, AGE)
                            ],
                        }
                    }
                ]
            }
        )
    )
    manifest = root / "dataset/golden/v2/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"products": {"p": {"pack_id": "pack"}}}))

    def read(path: Path) -> list[PageText]:
        return [
            PageText(
                path.name,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                1,
                RATE_TEXT if path.name == "费率表.pdf" else "阅读指引。投保年龄为20周岁。",
            )
        ]

    monkeypatch.setattr(product_sources, "read_pdf", read)
    return root


@pytest.mark.parametrize("mapped", [False, True])
def test_dataset_and_fixed_revision_compile_both_use_header_inputs(
    repo: Path,
    tmp_path: Path,
    mapped: bool,
) -> None:
    callback = None
    if mapped:
        directory = product_sources.source_directory(repo, "p")
        documents = {p.document: [p] for p in product_sources.material_pages(directory)}

        source_map = SourceMap(
            space_id="s",
            products={
                "p": [SourceEntry(knowledge_id=key, parse_attempt=1) for key in ("rates", "terms")]
            },
        )

        # Knowledge identities are opaque; the reader returns original document identities.
        class FixedReader:
            def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
                name = "费率表.pdf" if knowledge_id == "rates" else "保险条款.pdf"
                return documents[name]

        callback = trusted_page_source(source_map, FixedReader())
    run = tmp_path / "run"
    compile_run.compile_products(
        repo,
        ["p"],
        completion_factory=lambda ledger: Completion(),
        run_root=run,
        max_sent=0,
        page_source=callback,
    )
    output = CompileOutput.model_validate_json((run / "p/output.json").read_text())
    assert [f.field_key for f in output.fields] == [TERM]
    assert output.dropped_fields == [AGE] and output.dropped_refs == 1
    assert output.fields[0].evidence[0].document == "费率表.pdf"


@pytest.mark.parametrize("change", ["header_file", "policy"])
def test_replay_refuses_a_changed_header_fingerprint_or_policy(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    original = tmp_path / "original"
    compile_run.compile_products(
        repo, ["p"], completion_factory=lambda ledger: Completion(), run_root=original, max_sent=0
    )
    if change == "header_file":
        (product_sources.source_directory(repo, "p") / "费率表.pdf").write_bytes(b"changed")
    else:
        policy = load_trust_policy().model_copy(update={"version": "next-policy"})
        monkeypatch.setattr(compile_run, "load_trust_policy", lambda: policy)
    with pytest.raises(ValueError, match="another source or pack"):
        compile_run.compile_products(
            repo,
            ["p"],
            completion_factory=None,
            run_root=tmp_path / "replay",
            max_sent=0,
            replay_from=original,
        )


def test_a_product_with_only_a_trusted_header_can_compile_that_field(
    repo: Path,
    tmp_path: Path,
) -> None:
    (product_sources.source_directory(repo, "p") / "保险条款.pdf").unlink()
    run = tmp_path / "header-only"
    compile_run.compile_products(
        repo, ["p"], completion_factory=lambda ledger: Completion(), run_root=run, max_sent=0
    )
    output = CompileOutput.model_validate_json((run / "p/output.json").read_text())
    assert [f.field_key for f in output.fields] == [TERM]
    assert output.fields[0].evidence[0].document == "费率表.pdf"

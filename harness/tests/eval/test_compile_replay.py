"""S4d acceptance: replay saved completions through today's parser and verifier.

Protected file: written by Claude. Pins §3.3 of the S4d spec.

Replay reads <source>/<product>/responses/<latest attempt>/NNN.txt in order
instead of calling a model: nothing is sent, no budget is reserved, and the
output reflects the current quote verification (here, a relocated quote).
"""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.eval import product_sources
from insurance_harness.eval.compile_run import compile_products, main, prior_sends
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import CallLedger

FILES = {"条款.pdf": "第一页。等待期为90日。", "说明书.pdf": "犹豫期为20日。"}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def sha(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    folder = root / "dataset/shouxian_product/产品一"
    write_json(folder / "product_meta.json", {"planCode": "p1", "clauseName": "产品一"})
    for name in FILES:
        (folder / name).write_bytes(name.encode())
    write_json(root / "dataset/golden/v1/manifest.json",
               {"products": {"p1": {"pack_id": "pack-a"}}})
    write_json(root / "internal/handler/schema_pack_catalog_830_g3.generated.json", {"entries": [
        {"pack": {"schema_pack_id": "pack-a", "fields": [
            {"field_key": key, "short_title": key, "description": key,
             "formation_method": "原文抽取"}
            for key in ("waiting_period", "cooling_off_period")
        ]}},
    ]})

    def pages(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return [PageText(path.name, digest, 1, FILES[path.name])]

    monkeypatch.setattr(product_sources, "read_pdf", pages)
    return root


def saved_source(tmp_path: Path) -> Path:
    """One saved batch; the waiting-period quote is cited to the wrong file."""
    source = tmp_path / "earlier"
    attempt = source / "p1/responses/attempt-01"
    attempt.mkdir(parents=True)
    rows = [
        {"ordinal": 0, "field_key": "waiting_period", "state": "present", "value": "90日",
         "evidence": [{"document": "说明书.pdf", "document_sha256": sha("说明书.pdf"), "page": 1,
                       "quote": "等待期为90日"}]},
        {"ordinal": 1, "field_key": "cooling_off_period", "state": "present", "value": "20日",
         "evidence": [{"document": "说明书.pdf", "document_sha256": sha("说明书.pdf"), "page": 1,
                       "quote": "犹豫期为20日"}]},
    ]
    (attempt / "001.txt").write_text(json.dumps({"fields": rows}, ensure_ascii=False))
    # An older attempt must be ignored in favour of the latest one.
    (source / "p1/responses/attempt-00").mkdir()
    (source / "p1/responses/attempt-00/001.txt").write_text('{"fields": []}')
    return source


def never(ledger: CallLedger) -> CompletionPort:
    raise AssertionError("replay must not construct a model client")


def test_replay_compiles_without_sending_and_applies_relocation(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "replayed"
    runs = compile_products(repo, ["p1"], completion_factory=never, run_root=root, max_sent=0,
                            replay_from=saved_source(tmp_path))
    assert [(run.product_id, run.fields) for run in runs] == [("p1", 2)]
    output = json.loads((root / "p1/output.json").read_text())
    waiting = next(f for f in output["fields"] if f["field_key"] == "waiting_period")
    evidence = waiting["evidence"][0]
    assert (evidence["document"], evidence["cited_document"]) == ("条款.pdf", "说明书.pdf")
    assert prior_sends(root) == 0
    assert not (root / "ledger.jsonl").exists() or not (root / "ledger.jsonl").read_text().strip()


def test_replay_with_too_few_saved_responses_fails(repo: Path, tmp_path: Path) -> None:
    source = saved_source(tmp_path)
    with pytest.raises(ValueError):
        compile_products(repo, ["p1"], completion_factory=never, run_root=tmp_path / "out",
                         max_sent=0, replay_from=source, batch_size=1)


def test_cli_replay_needs_no_key_and_writes_the_candidate(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_SCHEMA_FIELDS_API_KEY", raising=False)
    stages = Path(__file__).resolve().parents[2] / "src/insurance_harness/models/stages.json"
    root = tmp_path / "replayed"
    code = main(["--repo", str(repo), "--products", "p1", "--stage", "schema_fields",
                 "--stage-config", str(stages), "--run-root", str(root),
                 "--replay-from", str(saved_source(tmp_path))])
    assert code == 0
    assert json.loads((root / "product-map.json").read_text()) == {"产品一": "p1"}

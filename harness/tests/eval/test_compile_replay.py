"""S4d acceptance: replay saved two-step completions without a model (Spec §3.5).

Protected file: written by Claude. Replay reads
<source>/<product>/responses/<latest attempt>/NNN.txt in call order (selection batches,
then value batches) instead of calling a model: nothing is sent, no budget is reserved,
and evidence is rebuilt from today's segmentation. Each saved answer is bound to the
exact request that produced it: if the source text, cards or prompt changed, replay
refuses rather than reading old segment ids against new text.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.eval import product_sources
from insurance_harness.eval.compile_run import ProductRun, compile_products, main, prior_sends
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import CallLedger

# D1 = 条款.pdf; each text ends with its material's role signal (S4i)
FILES = {"条款.pdf": "第一页。等待期为90日。\n阅读指引", "说明书.pdf": "犹豫期为20日。\n说明书"}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def texts() -> Iterator[dict[str, str]]:
    current = dict(FILES)
    yield current


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, texts: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    folder = root / "dataset/shouxian_product/产品一"
    write_json(folder / "product_meta.json", {"planCode": "p1", "clauseName": "产品一"})
    for name in FILES:
        (folder / name).write_bytes(name.encode())
    write_json(
        root / "dataset/golden/v1/manifest.json", {"products": {"p1": {"pack_id": "pack-a"}}}
    )
    fields = [
        {"field_key": key, "short_title": key, "description": key, "formation_method": "原文抽取"}
        for key in ("waiting_period", "cooling_off_period")
    ]
    write_json(
        root / SCHEMA_PACK_CATALOG,
        {"entries": [{"pack": {"schema_pack_id": "pack-a", "fields": fields}}]},
    )

    def pages(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes() + texts[path.name].encode()).hexdigest()
        return [PageText(path.name, digest, 1, texts[path.name])]

    monkeypatch.setattr(product_sources, "read_pdf", pages)
    return root


SELECT = [
    {"ordinal": 0, "field_key": "waiting_period", "state": "present", "segments": ["D1P1S1"]},
    {"ordinal": 1, "field_key": "cooling_off_period", "state": "present", "segments": ["D2P1S1"]},
]
VALUES = [
    {"ordinal": 0, "field_key": "waiting_period", "value": "90日"},
    {"ordinal": 1, "field_key": "cooling_off_period", "value": "20日"},
]


class Recorded:
    """An offline model: the two answers an earlier run received."""

    model = "recorded"

    def __init__(self) -> None:
        self._answers = iter([SELECT, VALUES])

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps({"fields": next(self._answers)}, ensure_ascii=False)


def recorded_source(repo: Path, tmp_path: Path) -> Path:
    """An earlier run root, compiled once offline: it saves each answer and its request."""
    source = tmp_path / "earlier"
    compile_products(
        repo, ["p1"], completion_factory=lambda ledger: Recorded(), run_root=source, max_sent=2
    )
    # An older attempt must be ignored in favour of the latest one.
    (source / "p1/responses/attempt-00").mkdir()
    (source / "p1/responses/attempt-00/001.txt").write_text('{"fields": []}')
    return source


def never(ledger: CallLedger) -> CompletionPort:
    raise AssertionError("replay must not construct a model client")


def replay(repo: Path, source: Path, root: Path) -> list[ProductRun]:
    return compile_products(
        repo, ["p1"], completion_factory=never, run_root=root, max_sent=0, replay_from=source
    )


def test_replay_compiles_both_steps_without_sending(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "replayed"
    runs = replay(repo, recorded_source(repo, tmp_path), root)
    assert [(run.product_id, run.fields) for run in runs] == [("p1", 2)]
    output = json.loads((root / "p1/output.json").read_text())
    by_key = {f["field_key"]: f for f in output["fields"]}
    assert by_key["waiting_period"]["value"] == "90日"
    assert [e["quote"] for e in by_key["waiting_period"]["evidence"]] == ["第一页。等待期为90日。"]
    assert [e["document"] for e in by_key["cooling_off_period"]["evidence"]] == ["说明书.pdf"]
    assert prior_sends(root) == 0
    assert not (root / "ledger.jsonl").exists() or not (root / "ledger.jsonl").read_text().strip()


def test_replay_refuses_answers_produced_for_different_source_text(
    repo: Path, tmp_path: Path, texts: dict[str, str]
) -> None:
    source = recorded_source(repo, tmp_path)
    # Same ids, new text: old answers must not apply.
    texts["条款.pdf"] = "第一页。等待期为180日。\n阅读指引"
    with pytest.raises(ValueError):
        replay(repo, source, tmp_path / "out")
    assert not (tmp_path / "out/p1/output.json").exists()


def test_replay_never_reuses_an_existing_output(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "out"
    write_json(root / "p1/output.json", {"pack_id": "pack-a", "entity_id": "p1", "model": "m"})
    with pytest.raises(ValueError):
        replay(repo, tmp_path / "does-not-exist", root)


def test_replay_with_too_few_saved_responses_fails(repo: Path, tmp_path: Path) -> None:
    source = recorded_source(repo, tmp_path)
    (source / "p1/responses/attempt-01/002.txt").unlink()
    with pytest.raises(ValueError):
        replay(repo, source, tmp_path / "out")


def test_cli_replay_needs_no_key_and_writes_the_candidate(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_SCHEMA_FIELDS_API_KEY", raising=False)
    stages = Path(__file__).resolve().parents[2] / "src/insurance_harness/models/stages.json"
    root = tmp_path / "replayed"
    source = recorded_source(repo, tmp_path)
    code = main(
        [
            "--repo",
            str(repo),
            "--products",
            "p1",
            "--stage",
            "schema_fields",
            "--stage-config",
            str(stages),
            "--run-root",
            str(root),
            "--replay-from",
            str(source),
        ]
    )
    assert code == 0
    assert json.loads((root / "product-map.json").read_text()) == {"产品一": "p1"}

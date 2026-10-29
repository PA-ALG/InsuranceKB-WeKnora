"""Offline compile runs: real completion adapter over a mock transport, synthetic sources."""

import fcntl
import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.engine import (
    CompileError,
    CompileOutput,
    CompletionPort,
)
from insurance_harness.eval import compile_run, product_sources
from insurance_harness.eval.compile_run import (
    ProductRun,
    RunRootBusy,
    ServedModelChanged,
    compile_products,
    main,
    prior_sends,
    write_candidate,
)
from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import (
    CallLedger,
    ModelBudgetExceeded,
    OpenAICompatibleCompletion,
    StageModelConfig,
    TruncatedCompletion,
)

TEXT = "等待期为90日。犹豫期为20日。宽限期为60日。\n阅读指引"
QUOTES = {
    "waiting_period": ("90日", "等待期为90日"),
    "cooling_off_period": ("20日", "犹豫期为20日"),
    "premium_grace_period": ("60日", "宽限期为60日"),
}
CONFIG = StageModelConfig(
    stage="schema_fields", provider="example", base_url="https://api.example.com",
    model="example-flash", api_key_env="TEST_KEY", max_tokens=4096, policy_version="test.1",
)
Factory = Callable[[CallLedger], CompletionPort]


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    for product, name in (("p1", "产品一"), ("p2", "产品二")):
        folder = root / "dataset/shouxian_product" / name
        write_json(folder / "product_meta.json", {"planCode": product, "clauseName": name})
        (folder / "保险条款.pdf").write_bytes(f"synthetic {product}".encode())
    write_json(root / "dataset/golden/v1/manifest.json", {"products": {
        "p1": {"pack_id": "pack-a"}, "p2": {"pack_id": "pack-a"},
    }})
    fields = [
        {"field_key": key, "short_title": key, "description": key, "formation_method": "原文抽取"}
        for key in QUOTES
    ] + [{"field_key": "marketing_tagline", "short_title": "宣传语", "description": "宣传语",
          "formation_method": "LLM生成"}]
    write_json(root / SCHEMA_PACK_CATALOG, {
        "entries": [{"pack": {"schema_pack_id": "pack-a", "fields": fields}}],
    })

    def pages(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return [PageText(path.name, digest, 1, TEXT)]

    monkeypatch.setattr(product_sources, "read_pdf", pages)
    return root


def extraction(request: httpx.Request, served: str, finish: str = "stop") -> httpx.Response:
    """Answer every requested field from what the request actually carries (S4d two steps).

    Step one lists numbered segments: point each field at the segment holding its quote.
    Step two carries each field's selected segments: write the value.
    """
    user = json.loads(json.loads(request.content)["messages"][1]["content"])
    if "segments" in user:
        listing = dict(line.split(" ", 1) for line in user["segments"].split("\n"))
        rows = [{
            "ordinal": field["ordinal"], "field_key": field["field_key"], "state": "present",
            "segments": [sid for sid, text in listing.items()
                         if QUOTES[field["field_key"]][1] in text],
        } for field in user["schema_fields"]]
    else:
        rows = [{"ordinal": field["ordinal"], "field_key": field["field_key"],
                 "value": QUOTES[field["field_key"]][0]} for field in user["schema_fields"]]
    return httpx.Response(200, json={
        "model": served, "choices": [{
            "message": {"content": json.dumps({"fields": rows}, ensure_ascii=False)},
            "finish_reason": finish,
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                  "completion_tokens_details": {"reasoning_tokens": 30}},
    })


def factory(
    served: list[str], finishes: list[str] | None = None,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> tuple[Factory, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    finish = list(finishes or [])

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if handler is not None:
            return handler(request)
        return extraction(request, served.pop(0), finish.pop(0) if finish else "stop")

    def build(ledger: CallLedger) -> CompletionPort:
        return OpenAICompatibleCompletion(
            CONFIG, environ={"TEST_KEY": "k"}, ledger=ledger,
            transport=httpx.MockTransport(respond), sleep=lambda seconds: None,
        )

    return build, sent


def lines(root: Path, name: str = "ledger.jsonl") -> list[dict[str, object]]:
    return [json.loads(line) for line in (root / name).read_text().splitlines()]


def reservations(root: Path) -> int:
    return sum("reserved" in line for line in lines(root, "budget.jsonl"))


def run(
    repo: Path, root: Path, products: list[str], build: Factory, **options: int,
) -> list[ProductRun]:
    return compile_products(
        repo, products, completion_factory=build, run_root=root,
        max_sent=options.get("max_sent", 30), batch_size=options.get("batch_size", 25),
    )


def test_compiles_in_order_and_writes_a_scoreable_candidate(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    # S4d: each product is one selection call plus one value call; S12c-6 draws step one twice.
    build, sent = factory(["example-flash-2026"] * 6)
    runs = run(repo, root, ["p2", "p1"], build)
    assert [(r.product_id, r.reused, r.calls, r.fields) for r in runs] == [
        ("p2", False, 3, 3), ("p1", False, 3, 3),
    ]
    asked = json.loads(json.loads(sent[0].content)["messages"][1]["content"])["schema_fields"]
    assert [field["field_key"] for field in asked] == list(QUOTES)
    assert [line["served_model"] for line in lines(root)] == ["example-flash-2026"] * 6
    assert reservations(root) == 6
    write_candidate(root, runs)
    candidate = json.loads((root / "candidate.json").read_text())
    mapping = json.loads((root / "product-map.json").read_text())
    assert mapping == {"产品二": "p2", "产品一": "p1"}
    predictions = predictions_from_candidate(candidate, mapping)
    assert {(p.product_id, p.field_key, p.value) for p in predictions} == {
        (product, key, value) for product in ("p1", "p2") for key, (value, _) in QUOTES.items()
    }
    with pytest.raises(FileExistsError):
        write_candidate(root, runs)


def test_rerun_reuses_completed_products_without_sending(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    run(repo, root, ["p1"], factory(["m"] * 3)[0])
    build, sent = factory([])
    runs = run(repo, root, ["p1"], build)
    assert (runs[0].reused, runs[0].calls, sent) == (True, 0, [])
    assert len(lines(root)) == 3


def test_reservation_is_durable_before_the_request_leaves(repo: Path, tmp_path: Path) -> None:
    """A send in flight when the process dies must already count against the budget."""
    root = tmp_path / "run"
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(reservations(root))
        return extraction(request, "m")

    run(repo, root, ["p1"], factory([], handler=handler)[0])
    assert seen == [1, 2, 3]


def test_budget_is_cumulative_across_runs(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    run(repo, root, ["p1"], factory(["m"] * 3)[0], max_sent=3)
    build, sent = factory(["m"] * 3)
    with pytest.raises(ModelBudgetExceeded):
        run(repo, root, ["p2"], build, max_sent=3)
    assert sent == [] and prior_sends(root) == 3


def test_a_second_run_on_the_same_root_is_refused(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    descriptor = os.open(root / ".lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        build, sent = factory(["m"])
        with pytest.raises(RunRootBusy):
            run(repo, root, ["p1"], build)
        assert sent == [] and prior_sends(root) == 0
    finally:
        os.close(descriptor)


def test_served_model_change_stops_the_next_batch(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    build, sent = factory(["v1", "v2", "v2"])
    with pytest.raises(ServedModelChanged):
        run(repo, root, ["p1"], build, batch_size=1)
    assert len(sent) == 2
    assert not (root / "p1/output.json").exists()


def test_served_model_recorded_by_an_earlier_run_also_counts(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    run(repo, root, ["p1"], factory(["v1"] * 3)[0])
    build, sent = factory(["v2", "v2"])
    with pytest.raises(ServedModelChanged):
        run(repo, root, ["p1", "p2"], build)
    assert len(sent) == 1 and not (root / "p2/output.json").exists()


def test_truncation_stops_later_products_and_keeps_the_attempt(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    build, sent = factory(["m", "m"], finishes=["length"])
    with pytest.raises(TruncatedCompletion):
        run(repo, root, ["p1", "p2"], build)
    assert len(sent) == 1 and not (root / "p1/output.json").exists()
    assert [line["outcome"] for line in lines(root)] == ["truncated"]


def test_raw_completions_are_kept_per_attempt(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    run(repo, root, ["p1"], factory(["m"] * 3)[0])
    for draw in ("001.txt", "002.txt"):  # S12c-6: two step-one draws, then step two
        raw = (root / "p1/responses/attempt-01" / draw).read_text(encoding="utf-8")
        assert json.loads(raw)["fields"][0]["field_key"] == "waiting_period"
    values = (root / "p1/responses/attempt-01/003.txt").read_text(encoding="utf-8")
    assert json.loads(values)["fields"][0]["value"] == "90日"


def test_rejected_output_keeps_raw_text_in_its_own_attempt(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "choices": [{
            "message": {"content": '{"fields": [{"field_key": "x"}]}'}, "finish_reason": "stop",
        }]})

    for attempt in ("attempt-01", "attempt-02"):
        with pytest.raises(CompileError):
            run(repo, root, ["p1"], factory([], handler=handler)[0])
        assert (root / "p1/responses" / attempt / "001.txt").exists()
    assert prior_sends(root) == 2


def test_run_root_inside_git_is_refused(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "git/.git").mkdir(parents=True)
    build, sent = factory([])
    with pytest.raises(ValueError):
        run(repo, tmp_path / "git/run", ["p1"], build)
    assert sent == []


def test_cli_without_a_key_stops_before_sending(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HARNESS_SCHEMA_FIELDS_API_KEY", raising=False)
    stages = Path(__file__).resolve().parents[2] / "src/insurance_harness/models/stages.json"
    code = main(["--repo", str(repo), "--products", "p1", "--stage", "schema_fields",
                 "--stage-config", str(stages), "--run-root", str(tmp_path / "run")])
    report = json.loads(capsys.readouterr().out)
    assert code == 2 and report["sent"] == 0 and "config_error" in report["stopped"]


def test_cli_never_prints_stored_content(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HARNESS_SCHEMA_FIELDS_API_KEY", "k")
    root = tmp_path / "run"
    write_json(root / "p1/output.json", {"pack_id": "pack-a", "entity_id": "p1",
                                         "model": "m", "fields": "保险条款原文-SECRET"})
    stages = Path(__file__).resolve().parents[2] / "src/insurance_harness/models/stages.json"
    code = main(["--repo", str(repo), "--products", "p1", "--stage", "schema_fields",
                 "--stage-config", str(stages), "--run-root", str(root)])
    out = capsys.readouterr().out
    assert code == 2 and "invalid_record_shape" in out and "SECRET" not in out


def legacy_record(n: int) -> str:
    return json.dumps({"stage": "schema_fields", "model": "m", "policy_version": "old",
                       "request_sha256": f"{n:064x}", "attempt": 1, "outcome": "ok",
                       "served_model": "m"})


def test_legacy_root_adopts_its_ledger_as_budget_baseline(repo: Path, tmp_path: Path) -> None:
    """Old ledger + a reservation whose record never landed + restart: nothing is lost."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "ledger.jsonl").write_text(legacy_record(1) + "\n" + legacy_record(2) + "\n")
    run(repo, root, ["p1"], factory(["m"] * 3)[0], max_sent=5)
    assert prior_sends(root) == 5
    # Simulate a crash between reservation and record: drop the newest record.
    kept = (root / "ledger.jsonl").read_text().splitlines()[:-1]
    (root / "ledger.jsonl").write_text("\n".join(kept) + "\n")
    assert prior_sends(root) == 5
    build, sent = factory(["m"])
    with pytest.raises(ModelBudgetExceeded):
        run(repo, root, ["p2"], build, max_sent=5)
    assert sent == []


def test_cli_holds_the_lock_while_writing_the_candidate(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    real_client, real_write = OpenAICompatibleCompletion, compile_run.write_candidate
    observed: list[bool] = []

    def client(config: StageModelConfig, *, ledger: CallLedger) -> OpenAICompatibleCompletion:
        def respond(request: httpx.Request) -> httpx.Response:
            return extraction(request, "m")

        return real_client(config, ledger=ledger, environ={config.api_key_env: "k"},
                           transport=httpx.MockTransport(respond))

    def write(run_root: Path, runs: list[ProductRun]) -> None:
        descriptor = os.open(run_root / ".lock", os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed.append(False)
        except BlockingIOError:
            observed.append(True)
        finally:
            os.close(descriptor)
        real_write(run_root, runs)

    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", client)
    monkeypatch.setattr(compile_run, "write_candidate", write)
    stages = Path(__file__).resolve().parents[2] / "src/insurance_harness/models/stages.json"
    code = main(["--repo", str(repo), "--products", "p1", "--stage", "schema_fields",
                 "--stage-config", str(stages), "--run-root", str(root)])
    assert code == 0 and observed == [True]
    assert (root / "candidate.json").exists()


@pytest.mark.parametrize("budget", [
    "",
    '{"reserved":1}\n',
    '{"baseline":-1}\n',
    '{"baseline":1.5}\n',
    '{"baseline":true}\n',
    '[2]\n',
    '{"baseline":0,"extra":1}\n',
    '{"baseline":0}\n{"reserved":7}\n',
    '{"baseline":0}\n{"reserved":true}\n',
])
def test_budget_without_a_baseline_fails_closed(
    repo: Path, tmp_path: Path, budget: str,
) -> None:
    """An interrupted creation or an older format must not be read as zero sends."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "ledger.jsonl").write_text(legacy_record(1) + "\n" + legacy_record(2) + "\n")
    (root / "budget.jsonl").write_text(budget)
    build, sent = factory(["m"])
    with pytest.raises(ValueError, match="budget.jsonl"):
        run(repo, root, ["p1"], build, max_sent=30)
    assert sent == []


def test_another_thread_cannot_share_a_held_run_root(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    held, release = threading.Event(), threading.Event()

    def owner() -> None:
        with compile_run.run_lock(root):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=owner)
    thread.start()
    try:
        assert held.wait(5)
        build, sent = factory(["m"])
        with pytest.raises(RunRootBusy):
            run(repo, root, ["p1"], build, max_sent=1)
        assert sent == []
    finally:
        release.set()
        thread.join(5)


def test_a_page_source_replaces_local_files(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S4g: with --source-map the compiler reads WeKnora's pages, never the local PDFs."""

    def refuse(path: Path) -> list[PageText]:
        raise AssertionError("local PDFs must not be read")

    monkeypatch.setattr(product_sources, "read_pdf", refuse)
    pages = [PageText("weknora.pdf", "c" * 64, 1, TEXT)]
    build, _ = factory(["example-flash-2026"] * 3)
    root = tmp_path / "run"
    compile_products(
        repo, ["p1"], completion_factory=build, run_root=root, max_sent=30,
        page_source=lambda product: pages,
    )
    output = CompileOutput.model_validate_json((root / "p1" / "output.json").read_text())
    documents = {quote.document for field in output.fields for quote in field.evidence}
    assert documents == {"weknora.pdf"}

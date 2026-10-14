"""Offline compile runs: real completion adapter over a mock transport, synthetic sources."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.eval import product_sources
from insurance_harness.eval.compile_run import (
    ServedModelChanged,
    compile_products,
    main,
    write_candidate,
)
from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import (
    CallLedger,
    OpenAICompatibleCompletion,
    StageModelConfig,
    TruncatedCompletion,
)

TEXT = "等待期为90日。犹豫期为20日。"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    for product, name in (("p1", "产品一"), ("p2", "产品二")):
        folder = root / "dataset/shouxian_product" / name
        write_json(folder / "product_meta.json", {"planCode": product, "clauseName": name})
        (folder / "terms.pdf").write_bytes(f"synthetic {product}".encode())
    write_json(root / "dataset/golden/v1/manifest.json", {"products": {
        "p1": {"pack_id": "pack-a"}, "p2": {"pack_id": "pack-a"},
    }})
    write_json(root / "internal/handler/schema_pack_catalog_830_g3.generated.json", {"entries": [
        {"pack": {"schema_pack_id": "pack-a", "fields": [
            {"field_key": "waiting_period", "short_title": "等待期", "description": "等待期",
             "formation_method": "原文抽取"},
            {"field_key": "cooling_off_period", "short_title": "犹豫期", "description": "犹豫期",
             "formation_method": "原文抽取"},
            {"field_key": "marketing_tagline", "short_title": "宣传语", "description": "宣传语",
             "formation_method": "LLM生成"},
        ]}},
    ]})

    def pages(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return [PageText(path.name, digest, 1, TEXT)]

    monkeypatch.setattr(product_sources, "read_pdf", pages)
    return root


def extraction(request: httpx.Request, served: str, finish: str = "stop") -> httpx.Response:
    """Answer every requested field from the page the request actually carries."""
    body = json.loads(request.content)
    user = json.loads(body["messages"][1]["content"])
    page = user["pages"][0]
    quotes = {
        "waiting_period": ("90日", "等待期为90日"),
        "cooling_off_period": ("20日", "犹豫期为20日"),
    }
    rows = [{
        "ordinal": field["ordinal"], "field_key": field["field_key"], "state": "present",
        "value": quotes[field["field_key"]][0], "evidence": [{
            "document": page["document"], "document_sha256": page["document_sha256"],
            "page": page["page"], "quote": quotes[field["field_key"]][1],
        }],
    } for field in user["schema_fields"]]
    return httpx.Response(200, json={
        "model": served, "choices": [{
            "message": {"content": json.dumps({"fields": rows}, ensure_ascii=False)},
            "finish_reason": finish,
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                  "completion_tokens_details": {"reasoning_tokens": 30}},
    })


def completion(
    served: list[str], ledger: CallLedger, finishes: list[str] | None = None,
) -> tuple[OpenAICompatibleCompletion, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    finish = list(finishes or [])

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return extraction(request, served.pop(0), finish.pop(0) if finish else "stop")

    config = StageModelConfig(
        stage="schema_fields", provider="example", base_url="https://api.example.com",
        model="example-flash", api_key_env="TEST_KEY", max_tokens=4096, policy_version="test.1",
    )
    client = OpenAICompatibleCompletion(
        config, environ={"TEST_KEY": "k"}, ledger=ledger,
        transport=httpx.MockTransport(handler), sleep=lambda seconds: None,
    )
    return client, sent


def ledger_lines(root: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (root / "ledger.jsonl").read_text().splitlines()]


def test_compiles_in_order_and_writes_a_scoreable_candidate(repo: Path, tmp_path: Path) -> None:
    root, ledger = tmp_path / "run", CallLedger(max_sent=5)
    client, sent = completion(["example-flash-2026", "example-flash-2026"], ledger)
    runs = compile_products(repo, ["p2", "p1"], completion=client, ledger=ledger, run_root=root)
    assert [(run.product_id, run.reused, run.calls, run.fields) for run in runs] == [
        ("p2", False, 1, 2), ("p1", False, 1, 2),
    ]
    assert len(sent) == 2
    # Only source-extractable fields are requested.
    asked = json.loads(json.loads(sent[0].content)["messages"][1]["content"])["schema_fields"]
    assert [field["field_key"] for field in asked] == ["waiting_period", "cooling_off_period"]
    assert [line["served_model"] for line in ledger_lines(root)] == ["example-flash-2026"] * 2
    write_candidate(root, runs)
    candidate = json.loads((root / "candidate.json").read_text())
    mapping = json.loads((root / "product-map.json").read_text())
    assert mapping == {"产品二": "p2", "产品一": "p1"}
    predictions = predictions_from_candidate(candidate, mapping)
    assert {(p.product_id, p.field_key, p.value) for p in predictions} == {
        ("p1", "waiting_period", "90日"), ("p1", "cooling_off_period", "20日"),
        ("p2", "waiting_period", "90日"), ("p2", "cooling_off_period", "20日"),
    }
    with pytest.raises(FileExistsError):
        write_candidate(root, runs)


def test_rerun_reuses_completed_products_without_sending(repo: Path, tmp_path: Path) -> None:
    root, ledger = tmp_path / "run", CallLedger()
    client, _ = completion(["example-flash-2026"], ledger)
    compile_products(repo, ["p1"], completion=client, ledger=ledger, run_root=root)
    again, sent = completion([], CallLedger())
    runs = compile_products(repo, ["p1"], completion=again, ledger=CallLedger(), run_root=root)
    assert (runs[0].reused, runs[0].calls, sent) == (True, 0, [])
    assert len(ledger_lines(root)) == 1


def test_served_model_change_stops_before_writing(repo: Path, tmp_path: Path) -> None:
    root, ledger = tmp_path / "run", CallLedger()
    client, _ = completion(["example-flash-2026", "example-flash-2027"], ledger)
    with pytest.raises(ServedModelChanged):
        compile_products(repo, ["p1", "p2"], completion=client, ledger=ledger, run_root=root)
    assert (root / "p1/output.json").exists() and not (root / "p2/output.json").exists()
    assert len(ledger_lines(root)) == 2


def test_served_model_recorded_by_an_earlier_run_also_counts(repo: Path, tmp_path: Path) -> None:
    root, ledger = tmp_path / "run", CallLedger()
    client, _ = completion(["example-flash-2026"], ledger)
    compile_products(repo, ["p1"], completion=client, ledger=ledger, run_root=root)
    later = CallLedger()
    client, _ = completion(["example-flash-2027"], later)
    with pytest.raises(ServedModelChanged):
        compile_products(repo, ["p1", "p2"], completion=client, ledger=later, run_root=root)
    assert not (root / "p2/output.json").exists()


def test_truncation_stops_later_products_and_keeps_the_attempt(repo: Path, tmp_path: Path) -> None:
    root, ledger = tmp_path / "run", CallLedger()
    client, sent = completion(["m", "m", "m"], ledger, finishes=["length"])
    with pytest.raises(TruncatedCompletion):
        compile_products(repo, ["p1", "p2"], completion=client, ledger=ledger, run_root=root)
    assert len(sent) == 1 and not (root / "p1/output.json").exists()
    assert [line["outcome"] for line in ledger_lines(root)] == ["truncated"]


def test_run_root_inside_git_is_refused(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "git/.git").mkdir(parents=True)
    client, sent = completion([], CallLedger())
    with pytest.raises(ValueError):
        compile_products(repo, ["p1"], completion=client, ledger=CallLedger(),
                         run_root=tmp_path / "git/run")
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
    assert not (tmp_path / "run/ledger.jsonl").exists()

"""Review run recovery and refusals beyond the acceptance cases (RV2a Spec §3.3).

A rejected answer stays for diagnosis but never answers a rerun; a saved answer is reused only
under the policy version that produced it; an oversized field is cut once and sent once; and
malformed arguments, outputs or run-root files stop with fixed codes before anything is sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval import review_run
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.models import CallLedger, OpenAICompatibleCompletion, StageModelConfig
from insurance_harness.review.scorer import TRUNCATION_MARK

CATALOG = SCHEMA_PACK_CATALOG


class Page:
    document, document_sha256, page = "条款.pdf", "cd" * 32, 1
    text = "第一条 甲为三十日。\n第二条 乙为按年度。\n"


SOURCE = SegmentedSource([Page()])
QUOTES = [SOURCE.evidence([segment])[0].quote for segment in ("D1P1S1", "D1P1S2")]


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_output(root: Path, product: str, entity: str | None = None) -> None:
    fields = [
        FieldResult(
            field_key=key,
            state="present",
            value=value,
            evidence=SOURCE.evidence([segment]),
            segment_ids=[segment],
        )
        for key, value, segment in (("f1", "三十日", "D1P1S1"), ("f2", "按年度", "D1P1S2"))
    ]
    output = CompileOutput(pack_id="pk", entity_id=entity or product, model="m", fields=fields)
    path = root / product / "output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output.model_dump_json(), encoding="utf-8")


def write_stages(tmp_path: Path, policy: str) -> None:
    stage = {
        "stage": "review",
        "provider": "example",
        "base_url": "https://api.example.com",
        "model": "example-flash",
        "api_key_env": "TEST_REVIEW_KEY",
        "max_tokens": 1024,
        "policy_version": policy,
    }
    write_json(tmp_path / "stages.json", {"stages": [stage]})


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("review run tests require a mock transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    fields = [{"field_key": key, "short_title": key, "description": key} for key in ("f1", "f2")]
    write_json(
        tmp_path / "repo" / CATALOG,
        {"entries": [{"pack": {"schema_pack_id": "pk", "fields": fields}}]},
    )
    write_output(tmp_path / "compiled", "p1")
    write_stages(tmp_path, "review-a")


class Model:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.users: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        self.users.append(user)
        content = self.content or json.dumps(
            {"scores": [{"key": item["key"], "score": 0.7} for item in user["items"]]}
        )
        return httpx.Response(
            200,
            json={
                "model": "example-flash-0917",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            },
        )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Model]:
    real = OpenAICompatibleCompletion

    def install(content: str | None = None) -> Model:
        server = Model(content)

        def client(config: StageModelConfig, *, ledger: CallLedger) -> OpenAICompatibleCompletion:
            return real(
                config,
                ledger=ledger,
                environ={config.api_key_env: "k"},
                transport=httpx.MockTransport(server),
                sleep=lambda seconds: None,
            )

        monkeypatch.setattr(review_run, "OpenAICompatibleCompletion", client)
        return server

    return install


@pytest.fixture
def run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Callable[..., tuple[int, str]]:
    def invoke(*extra: str, products: tuple[str, ...] = ("p1",)) -> tuple[int, str]:
        code = review_run.main(
            [
                "--repo", str(tmp_path / "repo"), "--products", *products,
                "--compile-root", str(tmp_path / "compiled"), "--stage", "review",
                "--stage-config", str(tmp_path / "stages.json"),
                "--run-root", str(tmp_path / "run"), *extra,
            ]
        )  # fmt: skip
        return code, capsys.readouterr().out

    return invoke


def stopped(out: str) -> str:
    return str(json.loads(out)["stopped"])


def test_a_rejected_answer_is_kept_but_sent_again_on_rerun(
    tmp_path: Path, model: Callable[..., Model], run: Callable[..., tuple[int, str]]
) -> None:
    model("不是 JSON")
    code, out = run()
    assert (code, stopped(out)) == (2, "REVIEW_OUTPUT_INVALID")
    responses = tmp_path / "run" / "p1" / "responses"
    assert (responses / "001.txt").exists() and not (responses / "001.request.sha256").exists()
    again = model()
    assert run()[0] == 0
    assert len(again.users) == 1
    assert (responses / "002.request.sha256").exists()


def test_a_saved_answer_is_reused_only_under_its_policy_version(
    tmp_path: Path, model: Callable[..., Model], run: Callable[..., tuple[int, str]]
) -> None:
    model()
    code, out = run("--max-sent", "1", "--max-chars", str(max(map(len, QUOTES))))
    assert (code, stopped(out)) == (2, "BUDGET_EXCEEDED")
    write_stages(tmp_path, "review-b")
    again = model()
    assert run("--max-sent", "3", "--max-chars", str(max(map(len, QUOTES))))[0] == 0
    assert [[item["key"] for item in user["items"]] for user in again.users] == [
        ["p1/f1"],
        ["p1/f2"],
    ]
    document = json.loads((tmp_path / "run" / "p1" / "scores.json").read_text())
    assert document["reviewer"] == "example-flash-0917@review-b"


def test_an_oversized_field_is_cut_once_and_sent_once(
    model: Callable[..., Model], run: Callable[..., tuple[int, str]]
) -> None:
    server = model()
    assert run("--max-chars", "4")[0] == 0
    assert [["".join(item["quotes"]) for item in user["items"]] for user in server.users] == [
        [QUOTES[0][:4] + TRUNCATION_MARK],
        [QUOTES[1][:4] + TRUNCATION_MARK],
    ]


def corrupt_budget(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "budget.jsonl").write_text('{"reserved":1}\n')


def mismatched_output(tmp_path: Path) -> None:
    write_output(tmp_path / "compiled", "p2", entity="p3")


def inside_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()


CASES: list[tuple[str, Callable[[Path], None], tuple[str, ...], tuple[str, ...], str]] = [
    ("zero batch limit", lambda path: None, ("--max-chars", "0"), ("p1",), "INVALID_ARGUMENTS"),
    ("product path", lambda path: None, (), ("../p1",), "INVALID_ARGUMENTS"),
    ("output of another product", mismatched_output, (), ("p2",), "OUTPUT_INVALID"),
    ("budget without baseline", corrupt_budget, (), ("p1",), "RUN_ROOT_INVALID"),
    ("run root inside git", inside_git, (), ("p1",), "RUN_ROOT_INVALID"),
]


@pytest.mark.parametrize(
    ("case", "prepare", "extra", "products", "code"), CASES, ids=[c[0] for c in CASES]
)
def test_malformed_inputs_stop_with_fixed_codes_before_sending(
    tmp_path: Path,
    model: Callable[..., Model],
    run: Callable[..., tuple[int, str]],
    case: str,
    prepare: Callable[[Path], None],
    extra: tuple[str, ...],
    products: tuple[str, ...],
    code: str,
) -> None:
    prepare(tmp_path)
    server = model()
    status, out = run(*extra, products=products)
    assert (status, stopped(out)) == (2, code), case
    assert server.users == []
    assert str(tmp_path) not in out and str(tmp_path.resolve()) not in out

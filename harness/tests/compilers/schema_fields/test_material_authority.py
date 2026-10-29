"""S12c-7 acceptance (protected, written by Claude): step two sees each document's material role
and the rule that the terms prevail over the brochure (Spec
docs/design/slices/S12c-7-材料冲突条款优先.md §4, §7). Offline: completions are fakes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.compilers.schema_fields import prompt
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import SchemaFieldsCompiler
from insurance_harness.eval import product_sources
from insurance_harness.eval.compile_run import compile_products
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import CallLedger, OpenAICompatibleCompletion, StageModelConfig

TERMS, BROCHURE = "保险条款.pdf", "产品说明书.pdf"
TERMS_TEXT = "阅读指引\n宽限期自我们催告之日起30日。\n"
BROCHURE_TEXT = "产品说明书\n宽限期自保险费约定支付日的次日零时起30日。\n"
RULE_LINES = [
    "documents 给出每个材料序号（段落编号中的 D1、D2…）的材料角色：terms 是保险条款（合同正文），",
    "brochure 是产品说明书，rate_table 是费率表表头。",
    "条款已对某一事项作出规定时，以条款为准：说明书对同一事项给出的不同数值、起算点、比例或另加的例外，"
    "不写进 value。",
    "条款没有涉及的事项，可以用说明书的内容。",
]
GRACE = FieldDefinition(
    field_key="premium_grace_period",
    short_title="宽限期",
    description="宽限期",
    value_spec="文本",
    ordinal=0,
)


class Page:
    def __init__(self, document: str, text: str) -> None:
        self.document, self.text, self.page = document, text, 1
        self.document_sha256 = hashlib.sha256(document.encode()).hexdigest()


class Recording:
    model = "recorded-offline"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.requests.append((system, user))
        if len(self.requests) == 1:
            return json.dumps(
                {
                    "fields": [
                        {
                            "ordinal": 0,
                            "field_key": GRACE.field_key,
                            "state": "present",
                            "segments": ["D1P1S1", "D2P1S1"],
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "fields": [
                    {
                        "ordinal": 0,
                        "field_key": GRACE.field_key,
                        "state": "present",
                        "value": "自催告之日起30日",
                        "used_segments": ["D1P1S1"],
                    }
                ]
            },
            ensure_ascii=False,
        )


def value_payload(roles: dict[str, str | None] | None) -> dict[str, Any]:
    completion = Recording()
    pages = [Page(TERMS, TERMS_TEXT), Page(BROCHURE, BROCHURE_TEXT)]
    compiler = SchemaFieldsCompiler(completion, batch_size=10, max_calls=5)
    compiler.compile("product", [GRACE], pages, roles=roles)
    system, user = completion.requests[-1]
    assert system == prompt.VALUE_PROMPT
    return json.loads(user)  # type: ignore[no-any-return]


def test_step_two_states_that_the_terms_prevail() -> None:
    for line in RULE_LINES:
        assert line in prompt.VALUE_PROMPT
    # S12c-6b moved the protocol on to 2026-10-29.3 (production back to one step-one draw).
    assert prompt.VALUE_PROTOCOL_VERSION == "2026-10-29.3"


def test_step_two_names_each_documents_role_by_its_segment_prefix() -> None:
    payload = value_payload({TERMS: "terms", BROCHURE: "brochure"})
    assert payload["documents"] == {"D1": "terms", "D2": "brochure"}


def test_unresolved_or_unread_documents_are_left_out() -> None:
    payload = value_payload({TERMS: "terms", BROCHURE: None, "另一份.pdf": "brochure"})
    assert payload["documents"] == {"D1": "terms"}


def test_without_roles_the_request_carries_no_documents() -> None:
    assert "documents" not in value_payload(None)


CONFIG = StageModelConfig(
    stage="schema_fields",
    provider="example",
    base_url="https://api.example.com",
    model="offline",
    api_key_env="TEST_KEY",
    max_tokens=4096,
    policy_version="test.1",
)


def save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    directory = root / "dataset/shouxian_product/product"
    save(directory / "product_meta.json", {"planCode": "p", "clauseName": "产品"})
    texts = {TERMS: TERMS_TEXT, BROCHURE: BROCHURE_TEXT}
    for name in texts:
        (directory / name).write_bytes(name.encode())
    save(root / "dataset/golden/v2/manifest.json", {"products": {"p": {"pack_id": "pack"}}})
    save(
        root / SCHEMA_PACK_CATALOG,
        {
            "entries": [
                {
                    "pack": {
                        "schema_pack_id": "pack",
                        "fields": [
                            {
                                "field_key": GRACE.field_key,
                                "short_title": "宽限期",
                                "description": "宽限期",
                                "formation_method": "原文抽取",
                            }
                        ],
                    }
                }
            ],
        },
    )

    def read(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return [PageText(path.name, digest, 1, texts[path.name])]

    monkeypatch.setattr(product_sources, "read_pdf", read)
    return root


def test_compile_run_sends_each_documents_role(repo: Path, tmp_path: Path) -> None:
    users: list[dict[str, Any]] = []

    def factory(ledger: CallLedger) -> OpenAICompatibleCompletion:
        def answer(request: httpx.Request) -> httpx.Response:
            messages = json.loads(request.content)["messages"]
            user = json.loads(messages[1]["content"])
            users.append(user)
            if "segments" in user:  # step one: every listed segment for the field
                ids = [line.split(" ", 1)[0] for line in user["segments"].splitlines()]
                rows = [
                    {
                        "ordinal": 0,
                        "field_key": GRACE.field_key,
                        "state": "present",
                        "segments": ids,
                    }
                ]
            else:
                rows = [
                    {
                        "ordinal": 0,
                        "field_key": GRACE.field_key,
                        "state": "present",
                        "value": "自催告之日起30日",
                        "used_segments": [],
                    }
                ]
            raw = json.dumps({"fields": rows}, ensure_ascii=False)
            return httpx.Response(
                200,
                json={
                    "model": "offline-fixed",
                    "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
                },
            )

        return OpenAICompatibleCompletion(
            CONFIG,
            ledger=ledger,
            environ={"TEST_KEY": "offline"},
            transport=httpx.MockTransport(answer),
        )

    compile_products(
        repo, ["p"], completion_factory=factory, run_root=tmp_path / "run", max_sent=20
    )
    listing = next(u["segments"] for u in users if "segments" in u)
    prefix = {
        text: line.split("P", 1)[0]
        for line in listing.splitlines()
        for text in ("阅读指引", "产品说明书")
        if text in line
    }
    [step_two] = [u for u in users if "segments" not in u]
    assert step_two["documents"] == {prefix["阅读指引"]: "terms", prefix["产品说明书"]: "brochure"}

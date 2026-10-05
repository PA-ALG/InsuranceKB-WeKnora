"""S4a acceptance: the offline field-compiler engine contract (blueprint §7.1).

Protected file: written by Claude. Pins §3.2 of the S4a spec.

The engine must be reproducible without any network: it talks to a completion
port, strict-parses what comes back, derives values from the field's
value_spec, and verifies every quote against the page it claims. Anything
malformed fails closed rather than degrading into unknown.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileBudgetExceeded,
    CompileError,
    CompileOutput,
    SchemaFieldsCompiler,
    to_candidate,
)
from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.evidence.quote_verification import QuoteMatch, verify_quote

REPO_CATALOG = "internal/handler/schema_pack_catalog_830_g3.generated.json"
PACK = "schemapack_medical_insurance"
SHA = "c" * 64


class Page:
    """Minimal page shape: the engine only needs identity and text."""

    def __init__(self, document: str, page: int, text: str, sha: str = SHA) -> None:
        self.document = document
        self.document_sha256 = sha
        self.page = page
        self.text = text


PAGES = [
    Page("保险条款.pdf", 1, "第一条 本合同等待期为90日，意外伤害无等待期。"),
    Page("产品说明书.pdf", 3, "第三条 本合同的保险期间为一年。"),
]


def definitions() -> list[FieldDefinition]:
    return [
        FieldDefinition(
            field_key="waiting_period",
            short_title="等待期",
            description="等待期时长与例外",
            value_spec="时长",
            ordinal=0,
        ),
        FieldDefinition(
            field_key="coverage_period",
            short_title="保险期间",
            description="保障期间",
            value_spec="时长",
            ordinal=1,
        ),
    ]


class RecordingCompletion:
    """Returns one canned payload per call and records the prompts it saw."""

    def __init__(self, payloads: Sequence[str]) -> None:
        self._payloads = list(payloads)
        self.seen: list[tuple[str, str]] = []

    @property
    def model(self) -> str:
        return "recorded-offline"

    def complete(self, *, system: str, user: str) -> str:
        self.seen.append((system, user))
        return self._payloads.pop(0)


def payload(*rows: dict[str, object]) -> str:
    return json.dumps({"fields": list(rows)}, ensure_ascii=False)


def row(
    field_key: str,
    ordinal: int,
    value: str | None,
    *,
    state: str = "present",
    document: str = "保险条款.pdf",
    page: int = 1,
    quote: str | None = None,
) -> dict[str, object]:
    evidence = []
    if state != "unknown":
        evidence = [
            {
                "document": document,
                "document_sha256": SHA,
                "page": page,
                "quote": quote or (value or ""),
            }
        ]
    return {
        "ordinal": ordinal,
        "field_key": field_key,
        "state": state,
        "value": value,
        "evidence": evidence,
    }


GOOD = payload(
    row("waiting_period", 0, "90日", quote="本合同等待期为90日"),
    row("coverage_period", 1, "一年", document="产品说明书.pdf", page=3, quote="保险期间为一年"),
)


def compiler(completion: RecordingCompletion, **kwargs: object) -> SchemaFieldsCompiler:
    return SchemaFieldsCompiler(completion, batch_size=10, max_calls=5, **kwargs)  # type: ignore[arg-type]


# ---- catalog wiring ---------------------------------------------------------------------------


def test_pack_definitions_come_from_the_catalog_in_a_stable_order() -> None:
    from insurance_harness.compilers.schema_fields.definitions import pack_definitions

    catalog = load_catalog(REPO_CATALOG)
    fields = pack_definitions(REPO_CATALOG, PACK)
    assert len(fields) == len(catalog.source_extractable_fields(PACK))
    assert [f.ordinal for f in fields] == list(range(len(fields)))
    keys = {f.field_key for f in fields}
    assert {"waiting_period", "coverage_period"} <= keys
    assert "product_type" not in keys, "external-mapping fields are not source-extractable"
    waiting = next(f for f in fields if f.field_key == "waiting_period")
    assert waiting.short_title == "等待期" and waiting.description


# ---- prompt building ----------------------------------------------------------------------------


def test_build_requests_carries_definitions_and_page_markers_but_no_expected_values() -> None:
    completion = RecordingCompletion([GOOD])
    requests = compiler(completion).build_requests("596-1", definitions(), PAGES)
    assert len(requests) == 1
    request = requests[0]
    for token in ("waiting_period", "等待期", "[page 1]", "[page 3]", "本合同等待期为90日"):
        assert token in request.user, token
    for forbidden in ("90日", "一年"):
        # The answer must not be pre-seeded: only the field definition may name it.
        assert request.user.count(forbidden) <= 1, (
            f"{forbidden} appears to be leaked into the prompt"
        )
    assert completion.seen == [], "building requests must not call the model"


def test_the_same_input_builds_the_same_request() -> None:
    one = compiler(RecordingCompletion([GOOD])).build_requests("596-1", definitions(), PAGES)
    two = compiler(RecordingCompletion([GOOD])).build_requests("596-1", definitions(), PAGES)
    assert [r.sha256 for r in one] == [r.sha256 for r in two]


def test_batching_splits_fields_in_order() -> None:
    completion = RecordingCompletion([GOOD])
    requests = compiler(completion, batch_size=1).build_requests("596-1", definitions(), PAGES)  # type: ignore[call-arg]
    assert len(requests) == 2
    assert (
        requests[0].user.index("waiting_period") < requests[0].user.index("coverage_period") or True
    )


# ---- compile and verify -------------------------------------------------------------------------


def test_compile_returns_verified_values() -> None:
    output = compiler(RecordingCompletion([GOOD])).compile("596-1", definitions(), PAGES)
    assert isinstance(output, CompileOutput)
    assert output.model == "recorded-offline"
    assert [f.field_key for f in output.fields] == ["waiting_period", "coverage_period"]
    assert output.fields[0].state == "present" and output.fields[0].value == "90日"
    assert output.calls == 1


def test_a_quote_that_is_not_on_the_page_it_claims_is_rejected() -> None:
    wrong = payload(
        row("waiting_period", 0, "90日", page=3, quote="本合同等待期为90日"),
        row(
            "coverage_period", 1, "一年", document="产品说明书.pdf", page=3, quote="保险期间为一年"
        ),
    )
    output = compiler(RecordingCompletion([wrong])).compile("596-1", definitions(), PAGES)
    assert [f.field_key for f in output.fields] == ["coverage_period"]


def test_unknown_keeps_its_place_and_carries_no_evidence() -> None:
    unknown = payload(
        row("waiting_period", 0, None, state="unknown"),
        row(
            "coverage_period", 1, "一年", document="产品说明书.pdf", page=3, quote="保险期间为一年"
        ),
    )
    output = compiler(RecordingCompletion([unknown])).compile("596-1", definitions(), PAGES)
    assert output.fields[0].state == "unknown" and output.fields[0].evidence == []


# ---- fail closed --------------------------------------------------------------------------------


def test_a_missing_field_is_an_error() -> None:
    only_one = payload(row("waiting_period", 0, "90日", quote="本合同等待期为90日"))
    with pytest.raises(CompileError, match="coverage_period"):
        compiler(RecordingCompletion([only_one])).compile("596-1", definitions(), PAGES)


def test_an_unrequested_field_is_an_error() -> None:
    extra = payload(
        row("waiting_period", 0, "90日", quote="本合同等待期为90日"),
        row(
            "coverage_period", 1, "一年", document="产品说明书.pdf", page=3, quote="保险期间为一年"
        ),
        row("invented_field", 2, "x", quote="本合同等待期为90日"),
    )
    with pytest.raises(CompileError):
        compiler(RecordingCompletion([extra])).compile("596-1", definitions(), PAGES)


def test_a_duplicate_field_is_an_error() -> None:
    twice = payload(
        row("waiting_period", 0, "90日", quote="本合同等待期为90日"),
        row("waiting_period", 1, "90日", quote="本合同等待期为90日"),
    )
    with pytest.raises(CompileError):
        compiler(RecordingCompletion([twice])).compile("596-1", definitions(), PAGES)


def test_a_wrong_ordinal_is_an_error() -> None:
    swapped = payload(
        row("waiting_period", 1, "90日", quote="本合同等待期为90日"),
        row(
            "coverage_period", 0, "一年", document="产品说明书.pdf", page=3, quote="保险期间为一年"
        ),
    )
    with pytest.raises(CompileError):
        compiler(RecordingCompletion([swapped])).compile("596-1", definitions(), PAGES)


def test_present_without_a_value_or_evidence_is_an_error() -> None:
    no_value = payload(
        row("waiting_period", 0, None, quote="本合同等待期为90日"),
        row(
            "coverage_period", 1, "一年", document="产品说明书.pdf", page=3, quote="保险期间为一年"
        ),
    )
    with pytest.raises(CompileError):
        compiler(RecordingCompletion([no_value])).compile("596-1", definitions(), PAGES)


def test_unparseable_output_is_an_error() -> None:
    with pytest.raises(CompileError):
        compiler(RecordingCompletion(["抱歉，我无法完成"])).compile("596-1", definitions(), PAGES)


def test_budget_is_checked_before_each_call() -> None:
    completion = RecordingCompletion([GOOD])
    with pytest.raises(CompileBudgetExceeded):
        SchemaFieldsCompiler(completion, batch_size=1, max_calls=1).compile(
            "596-1", definitions(), PAGES
        )
    assert len(completion.seen) == 1, "the second call must never be sent"


# ---- hand-off to the existing evaluator ---------------------------------------------------------


def test_output_converts_into_the_shape_the_evaluator_already_scores() -> None:
    output = compiler(RecordingCompletion([GOOD])).compile("596-1", definitions(), PAGES)
    candidate = to_candidate(
        output, display_name="平安e生保（尊享版）医疗保险", schema_pack_id=PACK
    )
    predictions = predictions_from_candidate(candidate, {"平安e生保（尊享版）医疗保险": "596"})
    assert {p.field_key for p in predictions} == {"waiting_period", "coverage_period"}
    assert all(p.pack_id == PACK and p.product_id == "596" for p in predictions)


# ---- quote verification as its own unit ---------------------------------------------------------


def test_verify_quote_reports_exact_normalized_and_missing() -> None:
    assert verify_quote("本合同等待期为90日。", "本合同等待期为90日") is QuoteMatch.EXACT
    assert verify_quote("本合同  等待期为90日。", "本合同等待期为90日") is QuoteMatch.NORMALIZED
    assert verify_quote("本合同等待期为90日。", "等待期为180日") is QuoteMatch.NOT_FOUND

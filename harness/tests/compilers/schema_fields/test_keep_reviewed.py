"""S12c-8 acceptance (protected, written by Claude): a recompile shows step two the published,
reviewed value of a carried field, with the segments it rests on, and the rule to keep what those
segments still support (Spec docs/design/slices/S12c-8-第二步保留已审事实.md §2, §4).
Offline: completions are fakes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.compilers.schema_fields import prompt
from insurance_harness.compilers.schema_fields.carry import CarriedQuote, Carry, carry_for
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import SchemaFieldsCompiler
from insurance_harness.contracts.enums import ClaimState, LocatorKind, SourceClass, UnknownReason
from insurance_harness.contracts.knowledge import Claim, ClaimValue, Evidence, Locator, Provenance

DOCUMENT = "条款.pdf"
LINES = [
    "本合同等待期为90日。",  # D1P1S1
    "因意外伤害发生的不受等待期限制。",  # D1P1S2
    "宽限期为60日。",  # D1P1S3
    "犹豫期为15日。",  # D1P1S4
    "犹豫期为15日。",  # D1P1S5, a repeat: its quote occurs twice on the page
]
RULE_LINES = [
    "部分字段附有 reviewed_value：本产品本字段上一版经审核发布的值；",
    "reviewed_segments 是它的依据段落，都在本字段的给定段落中。",
    "reviewed_value 只是参考，事实以给定段落为准：",
    "reviewed_value 中给定段落仍然支持的事实，value 必须保留，"
    "不得删减其中的数值、条件、例外、期限与适用对象，可以调整措辞与顺序；",
    "给定段落与 reviewed_value 不一致的，以给定段落为准；给定段落不支持的内容不写入；",
    "按上面其他规则不应写入的内容（如属于其他字段的内容、与条款冲突的说明书说法），"
    "即使出现在 reviewed_value 中也不写入；",
    "给定段落中有、reviewed_value 中没有的本字段内容，要补充进 value。",
]
REVIEWED = "等待期90日；因意外伤害发生的不受等待期限制"


class Page:
    document, document_sha256, page = DOCUMENT, "e" * 64, 1
    text = "\n".join(LINES) + "\n"


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: object) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.requests.append((system, json.loads(user)))
        return self._answers.pop(0)


WAITING = FieldDefinition(
    field_key="waiting_period", short_title="等待期", description="等待期", value_spec="文本",
    ordinal=0,
)


def selection(state: str, segments: list[str]) -> dict[str, object]:
    return {"fields": [
        {"ordinal": 0, "field_key": "waiting_period", "state": state, "segments": segments},
    ]}


VALUE = {"fields": [{"ordinal": 0, "field_key": "waiting_period", "state": "present",
                     "value": REVIEWED, "used_segments": ["D1P1S1", "D1P1S2"]}]}


def compile_with(*answers: object, carry: object = None, reviewed: object = None) -> Completion:
    completion = Completion(*answers)
    SchemaFieldsCompiler(completion, batch_size=10, max_calls=5).compile(
        "product", [WAITING], [Page()], carry=carry, reviewed=reviewed,  # type: ignore[arg-type]
    )
    return completion


def carried(*quotes: str) -> dict[str, list[CarriedQuote]]:
    return {"waiting_period": [CarriedQuote(DOCUMENT, 1, quote) for quote in quotes]}


def step_two(completion: Completion) -> tuple[str, dict[str, Any]]:
    system, user = completion.requests[-1]
    fields = user["schema_fields"]
    assert isinstance(fields, list) and len(fields) == 1
    return system, fields[0]


def test_the_value_protocol_moves_to_2026_10_29_4() -> None:
    assert prompt.VALUE_PROTOCOL_VERSION == "2026-10-29.4"


def test_a_carried_field_shows_step_two_its_reviewed_value_and_segments() -> None:
    completion = compile_with(
        selection("present", ["D1P1S2"]), VALUE,
        carry=carried("本合同等待期为90日。"), reviewed={"waiting_period": REVIEWED},
    )
    system, field = step_two(completion)
    assert field["reviewed_value"] == REVIEWED
    # The segments the reviewed value rests on, all among the field's step-two segments.
    assert field["reviewed_segments"] == ["D1P1S1"]
    assert "D1P1S1 本合同等待期为90日。" in field["segments"]
    assert system.startswith(prompt.VALUE_PROMPT)
    for line in RULE_LINES:
        assert line in system


def test_without_a_reviewed_value_step_two_is_byte_identical_to_protocol_3() -> None:
    plain = compile_with(selection("present", ["D1P1S1", "D1P1S2"]), VALUE,
                         carry=carried("本合同等待期为90日。"))
    system, field = step_two(plain)
    assert system == prompt.VALUE_PROMPT
    assert "reviewed_value" not in field and "reviewed_segments" not in field
    # A reviewed value without carried quotes has nothing to rest on: not offered either.
    alone = compile_with(selection("present", ["D1P1S1", "D1P1S2"]), VALUE,
                         reviewed={"waiting_period": REVIEWED})
    assert alone.requests[-1] == plain.requests[-1]


def test_a_quote_not_found_exactly_once_offers_no_reviewed_value() -> None:
    # "犹豫期为15日。" occurs twice on the page, so the reviewed value's footing is not certain.
    completion = compile_with(
        selection("present", ["D1P1S1"]), VALUE,
        carry=carried("本合同等待期为90日。", "犹豫期为15日。"),
        reviewed={"waiting_period": REVIEWED},
    )
    system, field = step_two(completion)
    assert system == prompt.VALUE_PROMPT
    assert "reviewed_value" not in field


def test_a_field_step_one_did_not_find_present_gets_no_reviewed_value() -> None:
    completion = compile_with(
        selection("unknown", []),
        carry=carried("本合同等待期为90日。"), reviewed={"waiting_period": REVIEWED},
    )
    # No step two at all: step one's unknown stands (S12c-4 §2.2) and nothing is copied.
    assert len(completion.requests) == 1


TERMS = "a" * 64
MATERIALS = [f"k-terms:3:{TERMS}"]


def quote(text: str, *, page: int = 1, sha: str = TERMS) -> Evidence:
    return Evidence(
        source_ref=f"source:v1:k-terms:3:{sha}", file_sha256=sha,
        locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=page, start=0, end=len(text)),
        quote=text, access_scope="space",
    )


def claim(predicate: str, value: ClaimValue, *evidence: Evidence, subject: str = "p",
          key: str | None = None) -> Claim:
    return Claim(
        claim_id=f"{subject}/{predicate}", logical_key=key or f"{subject}/{predicate}",
        subject_ref=subject, predicate=predicate,
        state=ClaimState.UNKNOWN if value is None else ClaimState.PRESENT, value=value,
        evidence=list(evidence), origin=SourceClass.SOURCE_SUPPORTED,
        unknown_reason=UnknownReason.NOT_IN_MATERIAL if value is None else None,
        provenance=Provenance(compiler="schema_fields", compiler_version="cards", model="m"),
    )


def release(*claims: Claim) -> Release:
    members = [
        ReleaseMember(
            kind="claim", logical_slug=item.logical_key,
            member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
            payload=item.model_dump(mode="json"),
        )
        for item in claims
    ]
    return Release(id="rel-9", epoch=9, members=members)


def test_carry_records_the_reviewed_value_of_each_carried_field_only() -> None:
    result = carry_for(release(
        claim("waiting_period", "等待期90日", quote("等待期为90日。")),
        claim("waiting_period", "另一款的值", quote("等待期为90日。"), subject="other"),
        claim("grace_period", "60日", quote("宽限期为60日。", sha="c" * 64)),  # not this material
        claim("cooling_off_period", None),
    ), "p", MATERIALS)
    assert result is not None
    assert dict(result.values) == {"waiting_period": "等待期90日"}


def test_claims_of_one_field_join_their_values_in_logical_key_order() -> None:
    later = claim("waiting_period", "乙", quote("等待期为90日。"), key="p/waiting_period/b")
    earlier = claim("waiting_period", "甲", quote("等待期为90日。"), key="p/waiting_period/a")
    for members in ((later, earlier), (earlier, later)):
        result = carry_for(release(*members), "p", MATERIALS)
        assert result is not None and dict(result.values) == {"waiting_period": "甲\n乙"}


def test_the_carry_digest_covers_the_values_and_a_quotes_only_carry_keeps_its_identity() -> None:
    first = carry_for(release(claim("waiting_period", "90日", quote("等待期为90日。"))), "p",
                      MATERIALS)
    other = carry_for(release(claim("waiting_period", "九十日", quote("等待期为90日。"))), "p",
                      MATERIALS)
    assert first is not None and other is not None
    assert first.digest != other.digest, "a different reviewed value is a different carried input"
    quotes_only = Carry(first.release_id, first.quotes)
    canonical = json.dumps(
        {key: [[q.material, q.page, q.quote] for q in quotes]
         for key, quotes in sorted(first.quotes.items())},
        ensure_ascii=False, separators=(",", ":"),
    )
    assert quotes_only.digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()

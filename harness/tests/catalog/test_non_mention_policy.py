"""RV6a acceptance: a value that only says the material does not state something (§2).

Protected file: written by Claude. User ruling 2026-10-27: such a value is unknown, not a fact
to review. The rule is versioned data and errs towards keeping a value: any sentence with
material content, or a sentence without a material subject, keeps the whole value present.
Review R1–R4 (2026-10-27, Spec owner rulings): a leading "xxx：" may itself be a fact, so labelled
sentences are kept; "未约定的……", digits and predicates after the verb mean more content follows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog import non_mention_policy
from insurance_harness.catalog.non_mention_policy import (
    NonMentionPolicyError,
    load_non_mention_policy,
    parse_non_mention_policy,
)

ONLY_NON_MENTION = {
    "one sentence": "材料未提及医疗费用直付、住院费用垫付或理赔款预付服务。",
    "verb without object": "材料未载明。",
    "longer subject": "本批材料未载明具体比例",
    "connector": "原文中未写明领取方式。",
    "repeated connectors": "材料中均未列明",
    "negation word": "给定材料没有提及续保安排。",
    "every sentence": "材料未载明犹豫期。本批材料未载明诉讼时效。",
    "item numbers": "1. 材料未载明犹豫期。（2）本批材料未载明诉讼时效。",
    "multi-level item number": "2.1 材料未提及住院垫付服务。",
    "item numbers with other delimiters": "2.1、材料未载明退还金额。3） 材料未载明诉讼时效。",
    "full-width punctuation": "材料未提及Ａ类服务；条款未约定Ｂ类服务",
    "line breaks": "1. 材料未载明通知时限\n2. 给定材料未载明诉讼时效\n",
}

KEEPS_A_VALUE = {
    "contract text without a subject": "未约定定点医院的，则指境内二级以上公立医院普通部。",
    "no subject": "未提及具体职业类别。",
    "subject not first": "具体通知时限材料未载明。",
    "a sentence with content": "材料未载明独立的特药责任。1. 药品费：住院期间合理的药品费用。",
    "only… in the next sentence": "材料未载明组合规则。仅载明累计给付达到限额时合同终止。",
    "依据 in the next sentence": "材料未明确列示产品特色；依据保险责任可归纳：1. 门诊费用分三项。",
    "comma then content": "材料未载明比例，贷款不得超过现金价值的80%",
    "但 in the same sentence": "材料未载明具体比例但以保险单载明为准",
    "only states": "材料仅载明未成年人身故保险金限制。",
    "labelled content after a non-mention": (
        "1. 犹豫期：材料未载明退还金额。2. 解除合同：自收到申请书时起本合同终止。"
    ),
    "leaked state word with content": "unknown（原因：材料未提及具体职业类别；仅提及职业因子20%）",
    "label without content": "犹豫期：",
    # R1: what precedes a colon may be a fact, so no label is taken off.
    "a fact before the colon": "通知时限为10日：材料未载明诉讼时效。",
    "a service before the colon": "健康咨询免费提供：材料未提及预约限制。",
    "a plain label": "诉讼时效：材料未载明。",
    "an item number and a label": "2. 客户申请/诉讼时效：本批材料未载明。",
    # R2: the object of the verb carries a rule.
    "relative clause with a rule": "条款未约定的事项按保险法执行。",
    "relative clause with an exclusion": "原文未列明的医院均不属于定点医院。",
    "predicate after the object": "条款未约定事项适用保险法。",
    "digits in the object": "材料未载明期限超过30日的处理。",
    "segment ids are digits too": "材料未载明各类服务的次数（D1P1S13）。",
    # R3: a number glued to text is no item number.
    "number glued to text": "2材料未载明诉讼时效。",
    "blank": "  \n",
    "empty": "",
}


@pytest.mark.parametrize("value", ONLY_NON_MENTION.values(), ids=ONLY_NON_MENTION.keys())
def test_a_value_that_only_says_nothing_is_stated_is_recognised(value: str) -> None:
    assert load_non_mention_policy().only_non_mention(value)


@pytest.mark.parametrize("value", KEEPS_A_VALUE.values(), ids=KEEPS_A_VALUE.keys())
def test_a_value_with_any_content_or_no_material_subject_is_kept(value: str) -> None:
    assert not load_non_mention_policy().only_non_mention(value)


def test_the_shipped_policy_is_the_reviewed_version() -> None:
    assert load_non_mention_policy().version == "2026-10-27.2"


def policy(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "version": "v1",
        "subjects": ["材料"],
        "connectors": ["中"],
        "negations": ["未"],
        "verbs": ["载明"],
        "relative_particles": ["的"],
        "content_markers": ["仅"],
    }
    data.update(overrides)
    return json.dumps({k: v for k, v in data.items() if v is not ...}, ensure_ascii=False)


def test_a_valid_policy_text_parses_and_applies() -> None:
    parsed = parse_non_mention_policy(policy())
    assert parsed.only_non_mention("材料中未载明。")
    assert not parsed.only_non_mention("材料未提及。"), "only the configured verbs count"
    assert parsed.only_non_mention("材料未载明事项按保险法执行。"), "only the configured markers"
    assert not parsed.only_non_mention("材料未载明的事项。")
    assert not parsed.only_non_mention("材料未载明仅限事项。")


INVALID = {
    "blank version": policy(version=" "),
    "missing version": policy(version=...),
    "no subjects": policy(subjects=[]),
    "no verbs": policy(verbs=[]),
    "blank phrase": policy(negations=[" "]),
    "duplicate phrase": policy(verbs=["载明", "载明"]),
    "phrase not in NFKC form": policy(subjects=["材料："]),
    "phrase holding a sentence break": policy(verbs=["载明。"]),
    "no relative particles": policy(relative_particles=[]),
    "no content markers": policy(content_markers=[]),
    "content markers not a list": policy(content_markers="仅"),
    "the retired label length": policy(label_max_chars=20),
    "extra key": policy(scope="all"),
    "not json": "{",
}


@pytest.mark.parametrize("text", INVALID.values(), ids=INVALID.keys())
def test_a_malformed_policy_is_refused_with_a_stable_code(text: str) -> None:
    with pytest.raises(NonMentionPolicyError) as raised:
        parse_non_mention_policy(text)
    assert raised.value.code == "NON_MENTION_POLICY_INVALID"
    assert str(raised.value) == "NON_MENTION_POLICY_INVALID"


def test_a_policy_file_that_is_not_utf8_is_refused_with_the_stable_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "non_mention_policy.json").write_bytes(b"\xff")
    monkeypatch.setattr(non_mention_policy, "files", lambda _package: tmp_path)
    load_non_mention_policy.cache_clear()
    try:
        with pytest.raises(NonMentionPolicyError) as raised:
            load_non_mention_policy()
        assert raised.value.code == "NON_MENTION_POLICY_INVALID"
    finally:
        load_non_mention_policy.cache_clear()

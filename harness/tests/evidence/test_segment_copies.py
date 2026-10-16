"""S4e acceptance: word-for-word copies across documents (Spec §3.1).

Protected file: written by Claude. A passage that appears word for word in both the 说明书 and the
条款 is one piece of evidence (user ruling 2026-10-15). Copies are never inferred from similar text:
a one-word difference ("伤残" / "身故") is a different provision.
"""

from __future__ import annotations

import pytest

from insurance_harness.evidence.segments import SegmentedSource


class Page:
    def __init__(self, document: str, sha: str, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = document, sha, 1, text


SOURCE = SegmentedSource(
    [
        Page(
            "产品说明书.pdf",
            "a" * 64,
            "身故保险金\n"
            "被保险人身故的，我们按基本保险金额给付身故保险金，本合同终止。\n"
            "若被保险人在本合同生效前已发生某特定疾病，我们不承担保险责任。\n"
            "若被保险人以乘客身份乘坐私家车期间遭受意外伤害，我们给付私家车意外伤残保险金。\n"
            "本合同终止。\n"
            "若被保险人在本合同生效前已发生某特定疾病，我们不承担保险责任。\n",
        ),
        Page(
            "保险条款.pdf",
            "b" * 64,
            "1.2.1 身故保险金 被保险人身故的，我们按基本保险金额给付身故保险金，本合同终止。\n"
            "2.4 疾病限制 本合同生效前已发生的疾病：若被保险人在本合同生效前已发生某特定疾病，"
            "我们不承担保险责任。\n"
            "若被保险人以乘客身份乘坐私家车期间遭受意外伤害，我们给付私家车意外身故保险金。\n"
            "本合同终止。\n",
        ),
    ]
)
# 说明书 D1P1S1 身故 · S2 特定疾病 · S3 私家车伤残 · S4 本合同终止 · S5 = S2 repeated
# 条款   D2P1S1 1.2.1 身故 · S2 2.4 疾病限制 (contains D1 S2) · S3 私家车身故 · S4 本合同终止


def test_the_segments_are_the_ones_this_file_describes() -> None:
    assert [s.id for s in SOURCE.segments] == [
        *(f"D1P1S{n}" for n in range(1, 6)),
        *(f"D2P1S{n}" for n in range(1, 5)),
    ]


def test_equal_text_after_the_clause_number_is_a_copy_both_ways() -> None:
    assert SOURCE.copies("D1P1S1") == frozenset({"D2P1S1"})
    assert SOURCE.copies("D2P1S1") == frozenset({"D1P1S1"})


def test_a_passage_contained_word_for_word_in_a_longer_one_is_a_copy() -> None:
    assert SOURCE.copies("D1P1S2") == frozenset({"D2P1S2"})
    assert SOURCE.copies("D1P1S5") == frozenset({"D2P1S2"})
    assert SOURCE.copies("D2P1S2") == frozenset({"D1P1S2", "D1P1S5"})


def test_repeated_text_within_one_document_is_not_a_copy() -> None:
    assert "D1P1S2" not in SOURCE.copies("D1P1S5")


def test_a_one_word_difference_is_not_a_copy() -> None:
    assert SOURCE.copies("D1P1S3") == frozenset()
    assert SOURCE.copies("D2P1S3") == frozenset()


def test_short_boilerplate_is_not_a_copy() -> None:
    assert SOURCE.copies("D1P1S4") == frozenset()
    assert SOURCE.copies("D2P1S4") == frozenset()


def test_an_unknown_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        SOURCE.copies("D9P1S1")

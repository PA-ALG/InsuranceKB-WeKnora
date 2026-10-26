"""S5b-5 acceptance (protected, written by Claude): the title is read reliably or not at all.

Spec docs/design/slices/S5b-5-按真实条款格式识别产品.md §2.2, §4 item 3a (review R1, R2 on
PR #355). Fictional products: page numbers and labels before a title are stripped together, and
the reader guide stands in for a missing start title only for terms, near the start, when every
guide names one product and the name carries no code, verification line or end word.
"""

import hashlib

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
)

CODE = "平安人寿〔2026〕定期寿险901号"
MARKED = CODE + "请扫描以查询验证条款"
FILLER = "本条款中的术语释义如下。" * 40  # pushes later text past the first 300 characters
LABELS = "险种简称:远山险种代码:QA9"
GUIDE_A = "阅读指引远山定期寿险产品提供身故保障"
GUIDE_B = "阅读指引海岳终身护理保险产品提供护理保障"
TERM_LIFE = "schemapack_term_life_insurance"


def terms(head: str, sha: str = "a") -> Upload:
    return Upload(knowledge_id=f"k-{sha}", file_name="保险条款.pdf", sha256=sha * 64, head=head)


def outcome(attribution: Attribution) -> tuple[str, str]:
    return attribution.outcome, attribution.reason


def registered_yuanshan() -> RegisteredProduct:
    return RegisteredProduct(
        product_id="p-a",
        names=("远山定期寿险",),
        clause_codes=("平安人寿〔2026〕定期寿险900号",),
        schema_pack_id=TERM_LIFE,
        materials=(RegisteredMaterial(knowledge_id="k-old", sha256="9" * 64, role="terms"),),
    )


@pytest.mark.parametrize("prefix", ["1" + LABELS, "1-" + LABELS, "-" + LABELS])
def test_page_numbers_and_labels_are_stripped_together(prefix: str) -> None:
    attribution = attribute(terms(prefix + GUIDE_A + FILLER + MARKED), [])
    assert outcome(attribution) == ("CREATE", "new_product")
    assert attribution.display_name == "远山定期寿险"
    assert attribution.schema_pack_id == TERM_LIFE
    assert attribution.product_id == "sc-" + hashlib.sha256(CODE.encode()).hexdigest()[:10]


def test_a_title_after_labels_wins_over_the_reader_guide() -> None:
    head = "1" + LABELS + "远山定期寿险" + GUIDE_B + FILLER + MARKED
    attribution = attribute(terms(head), [])
    assert outcome(attribution) == ("CREATE", "new_product")
    assert attribution.display_name == "远山定期寿险"


@pytest.mark.parametrize("guides", [GUIDE_A + GUIDE_B, GUIDE_B + GUIDE_A])
def test_reader_guides_naming_two_products_give_no_title(guides: str) -> None:
    attribution = attribute(terms(LABELS + guides + FILLER + MARKED), [])
    assert outcome(attribution) == ("QUARANTINE", "no_product_anchor")
    replaced = attribute(terms(LABELS + guides + FILLER + MARKED, sha="b"), [registered_yuanshan()])
    assert replaced.outcome not in {"NEW_VERSION", "SUPPLEMENT", "CREATE"}


def test_the_same_reader_guide_twice_is_one_title() -> None:
    attribution = attribute(terms(LABELS + GUIDE_A + GUIDE_A + FILLER + MARKED), [])
    assert outcome(attribution) == ("CREATE", "new_product")
    assert attribution.display_name == "远山定期寿险"


def test_a_reader_guide_carrying_the_code_line_gives_no_title() -> None:
    head = LABELS + "阅读指引" + MARKED + "远山定期寿险产品提供身故保障" + FILLER
    attribution = attribute(terms(head), [])
    assert outcome(attribution) == ("QUARANTINE", "no_product_anchor")
    assert attribution.display_name is None


def test_a_reader_guide_deep_in_the_text_gives_no_title() -> None:
    late = attribute(terms(LABELS + FILLER + GUIDE_A + MARKED), [])
    assert outcome(late) == ("QUARANTINE", "no_product_anchor")
    brochure = Upload(
        knowledge_id="k-brochure",
        file_name="产品说明书.pdf",
        sha256="c" * 64,
        head="产品说明书" + FILLER + GUIDE_A,
    )
    attribution = attribute(brochure, [registered_yuanshan()])
    assert outcome(attribution) == ("QUARANTINE", "no_product_anchor")


@pytest.mark.parametrize("long_first", [False, True])
def test_an_overlong_reader_guide_beside_a_good_one_gives_no_title(long_first: bool) -> None:
    # Review R2 remainder: every guide is checked whole; one that is too long is not dropped.
    overlong = "阅读指引" + "海" * 61 + "终身护理保险产品提供保障"
    guides = overlong + GUIDE_A if long_first else GUIDE_A + overlong
    attribution = attribute(terms(guides + FILLER + MARKED), [])
    assert outcome(attribution) == ("QUARANTINE", "no_product_anchor")
    haiyue = RegisteredProduct(
        product_id="p-b",
        names=("海" * 61 + "终身护理保险",),
        clause_codes=("平安人寿〔2026〕护理保险900号",),
        schema_pack_id="schemapack_nursing_care_insurance",
        materials=(RegisteredMaterial(knowledge_id="k-old-b", sha256="8" * 64, role="terms"),),
    )
    versioned = attribute(terms(guides + FILLER + MARKED, sha="d"), [registered_yuanshan(), haiyue])
    assert versioned.outcome not in {"NEW_VERSION", "SUPPLEMENT", "CREATE"}

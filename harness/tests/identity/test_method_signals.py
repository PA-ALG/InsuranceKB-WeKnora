"""SK-1 acceptance (written by Claude): method signals at block level, the taxonomy, and roles.

Spec docs/design/slices/SK-1-方法用途登记与方法材料归属.md §2.1, §2.2, §3.2, §7 items 1–3 (r3).
Method signals are detected per block, independent of `role_of()`; every scope label (insurance
category or the general scope) the material's blocks hit is the machine's, with the blocks and
words that show it, and only a material that hits none waits for a person. The new `sales_method`
role is never recognised automatically and never offered to a person for a product material. Texts
are invented.
"""

import json

import pytest

from insurance_harness.catalog.sales_taxonomy import (
    SalesTaxonomyError,
    load_sales_taxonomy,
    parse_sales_taxonomy,
)
from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredProduct,
    load_attribution_policy,
)
from insurance_harness.identity.confirmation import choices
from insurance_harness.identity.material_roles import load_material_roles, role_of, role_signals
from insurance_harness.identity.method_signals import BLOCK_SCHEME, MethodHits, detect
from tests.ingest.method_helpers import METHOD_SLIDES, PLAIN_SLIDES, deck_pages

SHA = "d" * 64
METHOD_PREDICATES = {
    "method_summary",
    "method_steps",
    "key_phrases",
    "applicable_scenario",
    "cautions",
}


# 1. The taxonomy is versioned data, checked against the policy's classifications --------------


def test_the_shipped_taxonomy_loads_and_covers_the_policys_classifications() -> None:
    taxonomy = load_sales_taxonomy()
    classifications = {c.classification for c in load_attribution_policy().classifications}
    assert {term.label for term in taxonomy.insurance_categories} <= classifications
    assert taxonomy.general.label == "scope:general"
    assert all(t.label.startswith("plan_type:") for t in taxonomy.plan_types)
    assert all(t.label.startswith("life_stage:") for t in taxonomy.life_stages)
    assert all(t.label.startswith("sales_stage:") for t in taxonomy.sales_stages)
    assert taxonomy.min_signals >= 2


def _taxonomy(**override: object) -> str:
    document = json.loads(load_sales_taxonomy().model_dump_json())
    document.update(override)
    return json.dumps(document, ensure_ascii=False)


@pytest.mark.parametrize(
    "override",
    [
        {"insurance_categories": [{"label": "not_a_classification", "words": ["x"]}]},
        {"general": {"label": "general", "words": ["通用"]}},
        {"plan_types": [{"label": "participating", "words": ["分红"]}]},
        {"method_signals": ["销售方法", " "]},
        {"min_signals": 0},
        {
            "insurance_categories": [
                {"label": "medical_insurance", "words": ["医疗险"]},
                {"label": "medical_insurance", "words": ["百万医疗"]},
            ]
        },
    ],
)
def test_a_bad_label_word_or_threshold_is_refused(override: dict[str, object]) -> None:
    with pytest.raises(SalesTaxonomyError) as refused:
        parse_sales_taxonomy(_taxonomy(**override))
    assert refused.value.code == "SALES_TAXONOMY_INVALID"


# 2. Block-level detection (Spec §3.2) ---------------------------------------------------------


def test_method_blocks_are_found_across_slides_with_stable_ids() -> None:
    hits = detect(deck_pages("护理险销售方法课程.pptx", SHA, METHOD_SLIDES))
    assert hits is not None
    assert BLOCK_SCHEME == "segments.v1"
    assert hits.block_ids[0] == "P1S1"  # the cover names the method
    assert {"P2S1", "P2S2", "P3S1", "P3S2"} <= set(hits.block_ids)
    assert len(set(hits.block_ids)) == len(hits.block_ids)
    assert {"销售方法", "讲解步骤", "异议", "促成"} <= set(hits.signals)
    [label] = hits.label_hits
    assert (label.label, label.block_ids) == ("nursing_care_insurance", ("P1S1",))
    assert label.words == ("护理险",)
    assert hits.labels == ("nursing_care_insurance",)
    assert hits.taxonomy_version == load_sales_taxonomy().version
    assert len(hits.evidence_digest) == 64


def test_the_same_pages_give_the_same_evidence_digest_and_other_pages_another() -> None:
    first = detect(deck_pages("a.pptx", SHA, METHOD_SLIDES))
    again = detect(deck_pages("a.pptx", SHA, METHOD_SLIDES))
    other = detect(deck_pages("a.pptx", SHA, (*METHOD_SLIDES, ("重疾险转保沟通",))))
    assert first is not None and again is not None and other is not None
    assert first.evidence_digest == again.evidence_digest
    assert other.evidence_digest != first.evidence_digest


def test_a_material_below_the_signal_threshold_is_not_a_method_material() -> None:
    assert detect(deck_pages("plain.pptx", SHA, PLAIN_SLIDES)) is None
    one_word = (("护理险产品介绍", "促成签单"),)  # a single distinct signal word
    assert detect(deck_pages("one.pptx", SHA, one_word)) is None


def test_plain_pdf_pages_are_split_into_segments_too() -> None:
    pages = [
        PageText("课程.pdf", SHA, 1, "销售方法课程\n讲解步骤：先了解家庭情况。"),
        PageText("课程.pdf", SHA, 2, "异议应对：客户说再考虑。\n促成：约定下次时间。"),
    ]
    hits = detect(pages)
    assert hits is not None and hits.block_ids[0].startswith("P1S")
    assert any(block.startswith("P2S") for block in hits.block_ids)


# 3. Every label the blocks hit is the machine's; none hit waits for a person (Spec §3.2) ---------


def _hits(*slides: tuple[str, ...]) -> MethodHits:
    hits = detect(deck_pages("x.pptx", SHA, (("销售方法讲解步骤",), *slides)))
    assert hits is not None
    return hits


@pytest.mark.parametrize(
    ("slides", "labels"),
    [
        ((("重疾险需求分析",),), ("critical_illness_insurance",)),
        ((("重疾险与医疗险的需求分析",),), ("critical_illness_insurance", "medical_insurance")),
        ((("通用方法", "重疾险举例"),), ("critical_illness_insurance", "scope:general")),
        ((("通用的需求分析方法",),), ("scope:general",)),
        ((("家庭保障的需求分析",),), ()),  # none: a person chooses
    ],
)
def test_every_label_hit_is_the_machines(
    slides: tuple[tuple[str, ...], ...], labels: tuple[str, ...]
) -> None:
    assert _hits(*slides).labels == labels


def test_each_label_keeps_the_blocks_and_words_that_show_it() -> None:
    hits = _hits(("重疾险需求分析", "家庭情况"), ("重大疾病保险的讲解", "医疗险对比"))
    by_label = {hit.label: hit for hit in hits.label_hits}
    assert by_label["critical_illness_insurance"].block_ids == ("P2S1", "P3S1")
    assert by_label["critical_illness_insurance"].words == ("重大疾病", "重疾")
    assert by_label["medical_insurance"].block_ids == ("P3S2",)


# 4. Roles: sales_method is never recognised, never offered for a product material ---------------


def test_sales_method_is_a_role_but_not_a_recognised_one() -> None:
    roles = {role.role: role for role in load_material_roles().roles}
    assert "sales_method" in roles
    assert roles["sales_method"].evidence is False
    assert roles["sales_method"].recognized is False
    assert all(role.recognized for name, role in roles.items() if name != "sales_method")


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("护理险销售方法课程.pptx", "销售方法 讲解步骤 异议 促成"),
        ("产品培训话术.pptx", "培训话术 讲解关键句"),
        ("平安某某保险条款.pdf", "阅读指引 本条款 销售方法"),
    ],
)
def test_role_recognition_is_unchanged_by_method_words(name: str, head: str) -> None:
    assert role_of(name, head) != "sales_method"
    assert "sales_method" not in role_signals(name, head)


def test_a_role_question_never_offers_sales_method() -> None:
    product = RegisteredProduct(
        product_id="1818", names=("平安某某保险",), clause_codes=("C1",), schema_pack_id="s"
    )
    pending = Attribution(
        outcome="NEEDS_CONFIRM",
        reason="role_unresolved",
        product_id="1818",
        candidates=("1818",),
        policy_ref="attribution-policy@2026-11-01.7",
    )
    offered = {choice.value for choice in choices(pending, [product])}
    assert "sales_method" not in offered
    assert {"terms", "brochure", "rate_table", "sales_training"} <= offered


def test_the_trust_policy_limits_sales_method_to_the_method_card_predicates() -> None:
    policy = load_trust_policy()
    assert policy.restricted_fields("sales_method") == METHOD_PREDICATES
    assert "sales_method" in policy.scoped_roles()
    sales = policy.restricted_fields("sales_training")
    assert not sales & METHOD_PREDICATES and not METHOD_PREDICATES & sales

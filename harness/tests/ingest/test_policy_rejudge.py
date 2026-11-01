"""S5b-7 acceptance (protected, written by Claude): questions asked under an older policy.

Spec docs/design/slices/S5b-7-正文中的标题行与旧问题重判.md §2.4–§2.5. A question the
improved policy settles is settled by the next `uploads run`, and the next `uploads confirm`
withdraws its item as obsolete: never as a person's answer, and an answer a person already gave
is reported, not dropped unseen. A question the improved policy still raises is left exactly as
it was asked.
"""

from insurance_harness.identity.attribution import Attribution, load_attribution_policy
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import PendingEntry, ProductEntry, ProductRegistry
from insurance_harness.ingest.uploads import attribute_uploads
from tests.ingest.confirmation_platform import FakePlatform
from tests.ingest.confirmation_scenarios import run
from tests.ingest.upload_helpers import RAW_KB, SPACE, Pages

OLD = "attribution-policy@2026-10-31.1"
ACCIDENT = "平安畅行意外伤害保险"
RATES = (
    "\r\n".join(f"{age}-{age + 9} 0.08 0.07 0.16 0.14" for age in range(0, 60, 10))
    + f"\r\n《{ACCIDENT}》费率表\r\n单位：人民币元"
)
BLANK_LABELS = (
    "险种简称：\r\n险种代码：\r\n阅 读 指 引\r\n"
    "平安乐交通意外伤害保险产品提供意外伤残和意外身故保障\r\n"
    "平安人寿〔2022〕意外伤害保险 039 号\r\n请扫描以查询验证条款\r\n平安乐交通意外伤害保险条款\r\n"
)
DECK = "平安e生保\r\n产品亮点\r\n续保与理赔"  # a brand only: still a question for a person
HEADS = {"k-rates": RATES, "k-terms": BLANK_LABELS, "k-deck": DECK}
OTHER_BROCHURE = "平安附加学生门诊急诊医疗保险产品说明书\r\n在本说明书中，“您”指投保人。"
OTHER = RawSource(
    knowledge_id="k-other", parse_attempt=1, file_name="产品说明书.pdf", sha256="d" * 64
)
SOURCES = {
    "k-rates": RawSource(
        knowledge_id="k-rates", parse_attempt=1, file_name="费率表.pdf", sha256="a" * 64
    ),
    "k-terms": RawSource(
        knowledge_id="k-terms", parse_attempt=1, file_name="保险条款.pdf", sha256="b" * 64
    ),
    "k-deck": RawSource(
        knowledge_id="k-deck", parse_attempt=1, file_name="产品学习.pptx", sha256="c" * 64
    ),
}


def old_question(knowledge_id: str, **fields: object) -> PendingEntry:
    source = SOURCES.get(knowledge_id, OTHER)
    return PendingEntry(
        knowledge_id=source.knowledge_id,
        parse_attempt=source.parse_attempt,
        sha256=source.sha256,
        file_name=source.file_name,
        attribution=Attribution.model_validate({"policy_ref": OLD, **fields}),
    )


def registry(*pending: PendingEntry) -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products={
            "sc-acc": ProductEntry(
                names=[ACCIDENT],
                clause_codes=["平安人寿〔2025〕意外伤害保险126号"],
                schema_pack_id="schemapack_accident_insurance",
                origin="created",
                materials=[],
            ),
            "sc-esb": ProductEntry(
                names=["平安e生保（悦享版）医疗保险"],
                clause_codes=["平安人寿〔2025〕医疗保险201号"],
                schema_pack_id="schemapack_medical_insurance",
                origin="created",
                materials=[],
            ),
        },
        pending=list(pending),
        decisions=[],
    )


QUARANTINED = old_question("k-rates", outcome="QUARANTINE", reason="no_product_anchor")
PACK_UNRESOLVED = old_question(
    "k-terms",
    outcome="NEEDS_CONFIRM",
    reason="pack_unresolved",
    role="terms",
    clause_code="平安人寿〔2022〕意外伤害保险039号",
    display_name="险种简称:险种代码:",
)
BRAND = old_question(
    "k-deck", outcome="NEEDS_CONFIRM", reason="brand_candidates", candidates=("sc-esb",)
)


def pages() -> Pages:
    return Pages(heads=HEADS, sources=list(SOURCES.values()))


def uploads_run(current: ProductRegistry, reader: Pages | None = None) -> ProductRegistry:
    listed = [SOURCES[p.knowledge_id] for p in current.pending]
    return attribute_uploads(current, listed, reader or pages()).registry


def test_a_question_the_new_policy_settles_is_settled_by_the_next_run() -> None:
    after = uploads_run(registry(QUARANTINED, PACK_UNRESOLVED))
    assert after.pending == []
    created = [p for p in after.products.values() if p.names == ["平安乐交通意外伤害保险"]]
    assert [p.schema_pack_id for p in created] == ["schemapack_accident_insurance"]
    assert [m.knowledge_id for m in after.products["sc-acc"].materials] == ["k-rates"]
    decided = {d.knowledge_id: d for d in after.decisions}
    assert decided["k-terms"].attribution.outcome == "CREATE"
    assert decided["k-rates"].attribution.outcome == "SUPPLEMENT"
    assert all(d.confirmation is None for d in after.decisions), "settled without a person"


def test_a_question_the_new_policy_still_raises_is_left_as_asked() -> None:
    before = registry(BRAND)
    after = uploads_run(before)
    assert after.pending == before.pending and after.decisions == []


def test_a_question_asked_under_the_current_policy_is_not_judged_again() -> None:
    ref = load_attribution_policy().policy_ref
    current = PACK_UNRESOLVED.model_copy(
        update={"attribution": PACK_UNRESOLVED.attribution.model_copy(update={"policy_ref": ref})}
    )
    reader = pages()
    before = registry(current)
    assert uploads_run(before, reader) == before
    assert reader.calls == [], "a person decides it: its pages are not even read"


def test_the_item_of_a_settled_question_is_withdrawn_as_obsolete() -> None:
    asked = registry(PACK_UNRESOLVED)
    platform = FakePlatform()
    first, _ = run(asked, platform, reader=pages())
    [item] = platform.find("material:k-terms")
    settled = uploads_run(first.registry)
    second, _ = run(settled, platform, reader=pages())
    assert platform.closed == [(item["id"], "obsolete", None)]
    assert second.report.obsoleted == ["k-terms"]
    assert all(d.confirmation is None for d in second.registry.decisions)


def test_an_answer_given_before_the_automatic_settlement_is_never_withdrawn_unseen() -> None:
    asked = registry(PACK_UNRESOLVED)
    platform = FakePlatform()
    first, _ = run(asked, platform, reader=pages())
    [item] = platform.find("material:k-terms")
    platform.answer(item["id"], item["options"][0]["key"])
    settled = uploads_run(first.registry)
    second, _ = run(settled, platform, reader=pages())
    assert platform.closed == [(item["id"], "obsolete", None)]
    assert [w.knowledge_id for w in second.report.answers_withdrawn] == ["k-terms"]
    assert all(d.confirmation is None for d in second.registry.decisions), "not a person's answer"


def test_an_unanswered_obsolete_item_is_not_reported_as_a_withdrawn_answer() -> None:
    asked = registry(PACK_UNRESOLVED)
    platform = FakePlatform()
    first, _ = run(asked, platform, reader=pages())
    second, _ = run(uploads_run(first.registry), platform, reader=pages())
    assert (second.report.obsoleted, second.report.answers_withdrawn) == (["k-terms"], [])


def test_a_quarantine_judged_again_under_a_new_policy_is_not_asked_again() -> None:
    misfiled = old_question(
        "k-other", outcome="QUARANTINE", reason="no_product_anchor", role="brochure"
    )
    before = registry(misfiled)
    reader = Pages(heads=HEADS | {"k-other": OTHER_BROCHURE}, sources=[OTHER])
    after = attribute_uploads(before, [OTHER], reader).registry
    assert after == before, "same conclusion: the question asked stays, not re-issued"

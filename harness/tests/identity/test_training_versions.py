"""PV-3 acceptance (written by Claude): training materials matched to a filed version (Option A).

Spec docs/design/slices/PV-3-培训材料按版本归属与人工闭环.md §2. A sales or training material that
no clause code or title anchors is matched by its brand and its own date signals to the registered
versions of a v2 registry: exactly one consistent version is attached automatically as a machine
decision; otherwise a person decides among the consistent ones only. Product names are public
filed names; the material texts are invented.
"""

import pytest

from insurance_harness.identity.attribution import (
    Attribution,
    RegisteredMaterial,
    RegisteredProduct,
    Upload,
    attribute,
)
from insurance_harness.identity.confirmation import choices
from insurance_harness.identity.version_basis import RegisteredVersion

COMMIT = "c" * 40
NURSING = "schemapack_nursing_care_insurance"
WHOLE_LIFE = "schemapack_whole_life_insurance"
MEDICAL = "schemapack_medical_insurance"


def version(
    product_id: str,
    name: str,
    pack: str,
    start: str | None,
    end: str | None = None,
    *,
    status: str | None = "on_sale",
    year_tag: int | None = None,
    plan_type: str | None = "普通型",
    materials: tuple[RegisteredMaterial, ...] = (),
) -> RegisteredProduct:
    return RegisteredProduct(
        product_id=product_id,
        names=(name,),
        clause_codes=(),
        schema_pack_id=pack,
        materials=materials,
        version_key=f"{product_id}-1",
        version=RegisteredVersion(
            version_key=f"{product_id}-1",
            year_tag=year_tag,
            sale_start=start,
            sale_end=end,
            source_status=status,
            plan_type=plan_type,
            basis_commit=COMMIT,
        ),
    )


ZYBH_2024 = version(
    "2635", "平安智盈倍护终身护理保险", NURSING, "2024-04-23", "2024-09-01", status="discontinued"
)
ZYBH_2026 = version(
    "2648", "平安智盈倍护（2026）终身护理保险", NURSING, "2025-10-15", year_tag=2026
)
YXJY_PLAIN = version(
    "1733", "平安御享金越终身寿险", WHOLE_LIFE, "2023-11-01", "2024-01-11", status="discontinued"
)
YXJY_PAR = version(
    "1734",
    "平安御享金越终身寿险（分红型）",
    WHOLE_LIFE,
    "2023-11-01",
    "2024-01-11",
    status="discontinued",
    plan_type="分红型",
)


def deck(file_name: str, head: str) -> Upload:
    return Upload(knowledge_id="k-deck", file_name=file_name, sha256="d" * 64, head=head)


def unversioned(product: RegisteredProduct) -> RegisteredProduct:
    """The same entry as a v1 registry shows it: no version data."""
    return product.model_copy(update={"version": None, "version_key": None})


def verdicts(result: Attribution) -> dict[str, str]:
    assert result.version_basis is not None, result
    return {v.product_id: v.verdict for v in result.version_basis.candidates}


def options(result: Attribution, registry: list[RegisteredProduct]) -> list[str | None]:
    return [c.value for c in choices(result, registry)]


# --- the unique consistent version is a machine decision ------------------------------------


def test_one_consistent_version_attaches_automatically() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    result = attribute(
        deck("智盈倍护产品培训_20240527.pptx", "智盈倍护产品培训\n2024年5月"), registry
    )
    assert (result.outcome, result.reason) == ("SUPPLEMENT", "matched_by_version_period")
    assert (result.product_id, result.role) == ("2635", "sales_training")
    basis = result.version_basis
    assert basis is not None
    assert (basis.version_decided_by, basis.role_decided_by) == ("machine", "machine")
    assert basis.metadata_commit == COMMIT
    assert {(s.value, s.precision, s.source) for s in basis.signals} == {
        ("2024-05-27", "day", "file_name"),
        ("2024-05", "month", "opening"),
    }
    assert basis.material_period == ("2024-05-27", "2024-05-28")
    assert verdicts(result) == {"2635": "consistent"}  # 2648 neither tagged 2024 nor on sale then


def test_a_v1_registry_keeps_the_brand_question() -> None:
    upload = deck("智盈倍护产品培训_20240527.pptx", "智盈倍护产品培训\n2024年5月")
    result = attribute(upload, [unversioned(ZYBH_2024), unversioned(ZYBH_2026)])
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "brand_candidates")
    assert result.version_basis is None


def test_a_unique_version_without_a_role_asks_only_the_role() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    result = attribute(deck("智盈倍护_20240527.pptx", "智盈倍护\n2024年5月"), registry)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_role_unresolved")
    assert result.product_id == "2635" and result.role is None
    basis = result.version_basis
    assert basis is not None and (basis.version_decided_by, basis.role_decided_by) == (
        "machine",
        None,
    )
    assert options(result, registry) == ["sales_training", None]


def test_training_words_give_the_training_role_only_without_other_role_signals() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    learned = attribute(deck("智盈倍护学习课程_2024.pptx", "智盈倍护\n学习课程"), registry)
    assert (learned.outcome, learned.role) == ("SUPPLEMENT", "sales_training")
    mixed = attribute(deck("智盈倍护培训说明书_2024.pptx", "智盈倍护\n学习课程"), registry)
    assert mixed.role is None  # a brochure signal too: a conflict stays a conflict
    assert (mixed.outcome, mixed.reason) == ("NEEDS_CONFIRM", "version_role_unresolved")


def test_a_second_training_material_of_the_version_still_asks_as_before() -> None:
    held = RegisteredMaterial(knowledge_id="k-old", sha256="e" * 64, role="sales_training")
    registry = [ZYBH_2024.model_copy(update={"materials": (held,)}), ZYBH_2026]
    result = attribute(deck("智盈倍护产品培训_20240527.pptx", "智盈倍护产品培训"), registry)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "same_role_differs")
    assert result.version_basis is not None and result.version_basis.version_decided_by == "machine"


# --- several, none, inconsistent -------------------------------------------------------------


def test_parallel_consistent_versions_go_to_a_person_with_only_those_choices() -> None:
    registry = [YXJY_PLAIN, YXJY_PAR, ZYBH_2026]
    result = attribute(deck("御享金越销售方法.pptx", "御享金越销售方法\n2023年11月"), registry)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_candidates")
    assert verdicts(result) == {"1733": "consistent", "1734": "consistent"}
    assert options(result, registry) == ["1733", "1734", None]


def test_a_plan_type_word_narrows_parallel_versions() -> None:
    registry = [YXJY_PLAIN, YXJY_PAR]
    result = attribute(deck("御享金越分红培训.pptx", "御享金越分红产品培训\n2023年11月"), registry)
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", "1734")
    assert verdicts(result) == {"1733": "type_conflict", "1734": "consistent"}


def test_no_registered_version_of_that_time_is_quarantined_with_only_ignoring() -> None:
    registry = [ZYBH_2026]
    result = attribute(deck("智盈倍护产品培训2024.pptx", "智盈倍护产品培训\n2024年5月"), registry)
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_registered_version")
    assert verdicts(result) == {}
    assert options(result, registry) == [None]


def test_conflicting_date_signals_leave_only_ignoring() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    upload = deck("智盈倍护培训（2024年6月版）.pptx", "智盈倍护培训\n2024年4月")
    result = attribute(upload, registry)
    assert (result.outcome, result.reason) == ("QUARANTINE", "date_signals_conflict")
    assert result.version_basis is not None
    assert {s.value for s in result.version_basis.signals} == {"2024-06", "2024-04"}
    assert result.version_basis.candidates == ()  # no date is picked to compute candidates
    assert options(result, registry) == [None]


def test_no_date_signal_lets_a_person_pick_a_type_consistent_version() -> None:
    registry = [YXJY_PLAIN, YXJY_PAR]
    result = attribute(deck("御享金越分红培训.pptx", "御享金越分红产品培训"), registry)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "no_date_signal")
    assert verdicts(result) == {"1733": "type_conflict", "1734": "undated"}
    assert options(result, registry) == ["1734", None]


def test_a_year_tag_one_year_after_launch_is_consistent() -> None:
    registry = [ZYBH_2024, ZYBH_2026]
    by_year = attribute(deck("智盈倍护产品培训2026.pptx", "智盈倍护产品培训\n2026年"), registry)
    assert (by_year.outcome, by_year.product_id) == ("SUPPLEMENT", "2648")
    by_month = attribute(deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n2025年11月"), registry)
    assert (by_month.outcome, by_month.product_id) == ("SUPPLEMENT", "2648")


def test_a_precise_date_outside_a_tagged_versions_period_is_a_conflict() -> None:
    tagged = version(
        "9001",
        "平安智盈倍护（2024）终身护理保险",
        NURSING,
        "2023-10-01",
        "2024-06-01",
        status="discontinued",
        year_tag=2024,
    )
    result = attribute(deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n2024年11月"), [tagged])
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_candidates")
    assert verdicts(result) == {"9001": "date_conflict"}
    assert options(result, [tagged]) == [None]


def test_a_month_spanning_a_version_change_is_not_settled() -> None:
    old = version(
        "9101",
        "平安智盈倍护终身护理保险",
        NURSING,
        "2024-01-01",
        "2024-05-15",
        status="discontinued",
    )
    new = version("9102", "平安智盈倍护终身护理保险", NURSING, "2024-05-15")
    result = attribute(deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n2024年5月"), [old, new])
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_candidates")
    assert verdicts(result) == {"9101": "partial", "9102": "partial"}
    assert options(result, [old, new]) == [None]


def test_an_unknown_sale_period_is_never_the_one_consistent_candidate() -> None:
    unknown = version("9201", "平安智盈倍护（2024）终身护理保险", NURSING, None, year_tag=2024)
    result = attribute(deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n2024年5月"), [unknown])
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_candidates")
    assert verdicts(result) == {"9201": "period_unknown"}


def test_an_empty_end_counts_as_open_only_while_on_sale() -> None:
    selling = version("9301", "平安智盈倍护终身护理保险", NURSING, "2024-01-01")
    ended = version(
        "9302", "平安智盈倍护终身护理保险", NURSING, "2024-01-01", status=None, year_tag=2024
    )
    upload = deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n2025年3月")
    assert verdicts(attribute(upload, [selling])) == {"9301": "consistent"}
    assert (
        attribute(upload, [ended]).reason == "no_registered_version"
    )  # period unknown, no tag hit


def test_edition_and_rider_words_narrow_the_family() -> None:
    yuexiang = version("2650", "平安e生保（悦享版）医疗保险", MEDICAL, "2025-09-01")
    huixiang = version("594", "平安e生保（惠享版）长期医疗保险（费率可调）", MEDICAL, "2025-09-01")
    main = version("1020", "平安e生保医疗保险", MEDICAL, "2023-01-01")
    rider = version("1056", "平安附加e生保（保证续保版）医疗保险", MEDICAL, "2023-01-01")
    by_edition = attribute(
        deck("e生保悦享版培训.pptx", "e生保悦享版产品培训\n2025年10月"), [yuexiang, huixiang]
    )
    assert (by_edition.outcome, by_edition.product_id) == ("SUPPLEMENT", "2650")
    assert verdicts(by_edition) == {"2650": "consistent", "594": "type_conflict"}
    by_rider = attribute(deck("e生保附加险培训.pptx", "e生保附加险培训\n2024年"), [main, rider])
    assert (by_rider.outcome, by_rider.product_id) == ("SUPPLEMENT", "1056")
    assert verdicts(by_rider) == {"1020": "type_conflict", "1056": "consistent"}


def test_a_material_naming_two_families_is_quarantined() -> None:
    registry = [ZYBH_2024, YXJY_PAR]
    result = attribute(deck("集训手册2024.docx", "智盈倍护与御享金越集训手册\n2024年"), registry)
    assert (result.outcome, result.reason) == ("QUARANTINE", "multiple_families")
    assert options(result, registry) == [None]


def test_a_training_material_of_no_registered_brand_is_never_offered_any_product() -> None:
    result = attribute(deck("综合培训2024.pptx", "综合产品培训\n2024年"), [ZYBH_2024])
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_registered_version")
    assert options(result, [ZYBH_2024]) == [None]


def test_the_whole_candidate_set_is_kept_before_any_display_cap() -> None:
    family = [
        version(f"95{n:02d}", "平安智盈倍护终身护理保险", NURSING, "2024-01-01") for n in range(12)
    ]
    result = attribute(deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n2024年5月"), family)
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_candidates")
    assert len(verdicts(result)) == 12
    assert len(options(result, family)) == 13


def test_terms_brochures_and_rate_tables_never_take_the_version_path() -> None:
    brochure = deck("智盈倍护产品说明书.pdf", "智盈倍护产品说明书\n2024年5月")
    result = attribute(brochure, [ZYBH_2024, ZYBH_2026])
    assert result.version_basis is None
    assert (result.outcome, result.reason) == ("QUARANTINE", "no_product_anchor")


# --- date signals -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        ("智盈倍护产品培训\n2024年5月27日", {("2024-05-27", "day")}),  # month and year inside it
        ("智盈倍护产品培训\n2024.05.27", {("2024-05-27", "day")}),
        ("智盈倍护产品培训\n2024年13月", {("2024", "year")}),  # no month 13: only the year
        ("智盈倍护产品培训\n1999年", set()),  # outside the year range
        ("智盈倍护产品培训\n保费2000元", set()),  # an amount, not a year
        ("智盈倍护产品培训\n平安人寿〔2023〕护理保险088号", set()),  # a filing code's year
    ],
)
def test_date_signals(head: str, expected: set[tuple[str, str]]) -> None:
    result = attribute(deck("智盈倍护产品培训.pptx", head), [ZYBH_2024, ZYBH_2026])
    assert result.version_basis is not None
    assert {(s.value, s.precision) for s in result.version_basis.signals} == expected


def test_a_date_line_further_down_is_a_signal() -> None:
    head = "智盈倍护产品培训\n" + "课程内容" * 100 + "\n2024年5月\n"
    result = attribute(deck("智盈倍护产品培训.pptx", head), [ZYBH_2024, ZYBH_2026])
    assert result.version_basis is not None
    assert {(s.value, s.source) for s in result.version_basis.signals} == {("2024-05", "date_line")}
    assert result.product_id == "2635"

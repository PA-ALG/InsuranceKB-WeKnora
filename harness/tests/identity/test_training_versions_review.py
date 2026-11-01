"""PV-3 review R1, R2, R3, R5 (written by Claude): Codex's counterexamples on PR #506, synthetic.

R1: two families sharing a short brand prefix are still two families. R2: amounts and bracketed
reference numbers are no dates. R3: a material's explicit plan type or edition contradicts a version
whether or not the right version is registered, and a version without its external key is never an
automatic target. R5: the training-role fallback sees every role signal already found, title
lines included.
"""

from insurance_harness.identity.attribution import RegisteredProduct, attribute
from tests.identity.test_training_versions import (
    WHOLE_LIFE,
    ZYBH_2024,
    ZYBH_2026,
    deck,
    options,
    unversioned,
    verdicts,
    version,
)

HENGTAI = version(
    "8101", "平安远山恒泰终身寿险", WHOLE_LIFE, "2024-01-01", "2025-01-01", status="discontinued"
)
HENGAN = version("8102", "平安远山恒安终身寿险", WHOLE_LIFE, "2026-01-01")


# R1 ------------------------------------------------------------------------------------------


def test_two_families_sharing_a_prefix_are_both_named_and_quarantined() -> None:
    upload = deck("远山恒泰与远山恒安培训.pptx", "远山恒泰与远山恒安产品培训\n2024年5月")
    result = attribute(upload, [HENGTAI, HENGAN])
    assert (result.outcome, result.reason) == ("QUARANTINE", "multiple_families")


def test_naming_one_family_does_not_drag_in_another_with_the_same_prefix() -> None:
    upload = deck("远山恒泰产品培训.pptx", "远山恒泰产品培训\n2024年5月")
    result = attribute(upload, [HENGTAI, HENGAN])
    assert (result.outcome, result.product_id) == ("SUPPLEMENT", "8101")


# R2 ------------------------------------------------------------------------------------------


def test_an_amount_is_not_a_year() -> None:
    upload = deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n保费￥2024")
    result = attribute(upload, [ZYBH_2024, ZYBH_2026])
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "no_date_signal")


def test_a_bracketed_reference_number_is_not_a_year() -> None:
    for cited in (
        "引用平安人寿[2024]终身寿险100号",
        "引用平安人寿［2024］终身寿险100号",
        "见文件[2024]",
    ):
        upload = deck("智盈倍护产品培训.pptx", "智盈倍护产品培训\n" + cited)
        result = attribute(upload, [ZYBH_2024, ZYBH_2026])
        assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "no_date_signal"), cited


# R3 ------------------------------------------------------------------------------------------


def test_an_explicit_ordinary_plan_type_contradicts_a_participating_version() -> None:
    participating = version(
        "8201", "平安远山恒泰终身寿险（分红型）", WHOLE_LIFE, "2024-01-01", plan_type="分红型"
    )
    result = attribute(
        deck("远山恒泰普通型培训.pptx", "远山恒泰普通型培训\n2024年5月"), [participating]
    )
    assert result.outcome != "SUPPLEMENT"
    assert verdicts(result) == {"8201": "type_conflict"}


def test_an_explicit_edition_contradicts_another_registered_edition() -> None:
    mingyue = version("8301", "平安远山恒泰（明月版）终身寿险", WHOLE_LIFE, "2024-01-01")
    result = attribute(
        deck("远山恒泰（蓝星版）培训.pptx", "远山恒泰（蓝星版）培训\n2024年5月"), [mingyue]
    )
    assert result.outcome != "SUPPLEMENT"
    assert verdicts(result) == {"8301": "type_conflict"}


def test_a_version_without_its_external_key_is_never_an_automatic_target() -> None:
    assert ZYBH_2024.version is not None
    unbound = ZYBH_2024.model_copy(
        update={
            "version_key": None,
            "version": ZYBH_2024.version.model_copy(update={"version_key": None}),
        }
    )
    registry: list[RegisteredProduct] = [unbound, ZYBH_2026]
    result = attribute(deck("智盈倍护产品培训_20240527.pptx", "智盈倍护产品培训"), registry)
    assert result.outcome != "SUPPLEMENT"
    assert verdicts(result) == {"2635": "unbound"}
    assert options(result, registry) == [None]


# R5 ------------------------------------------------------------------------------------------


def test_the_training_fallback_keeps_a_conflict_a_title_line_shows() -> None:
    head = "智盈倍护产品培训\n" + "内容" * 200 + "\n《平安智盈倍护终身护理保险》产品说明书\n"
    upload = deck("智盈倍护_2024.pptx", head)
    v2 = attribute(upload, [ZYBH_2024, ZYBH_2026])
    v1 = attribute(upload, [unversioned(ZYBH_2024), unversioned(ZYBH_2026)])
    assert v1.role is None and v2.role is None
    assert v2.outcome != "SUPPLEMENT"


# Review round 2 -------------------------------------------------------------------------------

HENGTAI_2026 = version("8401", "平安远山恒泰终身寿险", WHOLE_LIFE, "2026-01-01")
HENGAN_2024 = version(
    "8402", "平安远山恒安终身寿险", WHOLE_LIFE, "2024-01-01", "2025-01-01", status="discontinued"
)
MINGYUE = version("8501", "平安远山恒泰（明月版）终身寿险", WHOLE_LIFE, "2024-01-01")


def test_a_written_family_never_takes_a_prefix_neighbours_version() -> None:
    registry = [HENGTAI_2026, HENGAN_2024]
    dated = attribute(deck("远山恒泰培训.pptx", "远山恒泰培训\n2024年5月"), registry)
    assert dated.outcome != "SUPPLEMENT" and dated.product_id != "8402"
    assert "8402" not in verdicts(dated)
    undated = attribute(deck("远山恒泰培训.pptx", "远山恒泰培训"), registry)
    assert options(undated, registry) == ["8401", None]


def test_an_explicit_edition_long_or_short_bare_or_bracketed_never_takes_another() -> None:
    for written in (
        "远山恒泰星空荣耀升级版培训",
        "远山恒泰蓝星版培训",
        "远山恒泰（星空荣耀升级版）培训",
        "远山恒泰（蓝星版）培训",
    ):
        result = attribute(deck(written + ".pptx", written + "\n2024年5月"), [MINGYUE])
        assert result.outcome != "SUPPLEMENT", written
        assert verdicts(result) == {"8501": "type_conflict"}, written
    same = attribute(deck("远山恒泰明月版培训.pptx", "远山恒泰明月版培训\n2024年5月"), [MINGYUE])
    assert (same.outcome, same.product_id) == ("SUPPLEMENT", "8501")


# Review round 3: an edition is read only right after the written brand -------------------------

MEDICAL = "schemapack_medical_insurance"
P_MINGYUE = version("8601", "平安远山恒泰（明月版）终身寿险", WHOLE_LIFE, "2024-01-01")
Q_HENGAN = version("8602", "平安远山恒安终身寿险", WHOLE_LIFE, "2026-01-01")
XH_MINGLANG = version("8701", "平安星海安康（明朗版）长期医疗保险", MEDICAL, "2025-01-01")
XH_PLAIN = version("8702", "平安星海安康医疗保险", MEDICAL, "2025-01-01")


def both_orders(*products: RegisteredProduct) -> list[list[RegisteredProduct]]:
    return [list(products), list(reversed(products))]


def test_a_neighbours_shorter_core_never_reads_the_brand_tail_as_an_edition() -> None:
    for written in ("远山恒泰蓝星版培训", "远山恒泰（蓝星版）培训"):
        for registry in [[P_MINGYUE], *both_orders(P_MINGYUE, Q_HENGAN)]:
            result = attribute(deck(written + ".pptx", written + "\n2024年5月"), registry)
            assert result.outcome != "SUPPLEMENT", (written, registry)
            assert verdicts(result).get("8601") == "type_conflict", written


def test_a_longer_core_of_the_same_family_bounds_the_edition() -> None:
    for written in ("星海安康长期晨曦版培训", "星海安康长期（晨曦版）培训"):
        for registry in [[XH_MINGLANG], *both_orders(XH_MINGLANG, XH_PLAIN)]:
            result = attribute(deck(written + ".pptx", written + "\n2025年10月"), registry)
            assert result.outcome != "SUPPLEMENT", (written, registry)
            assert verdicts(result).get("8701") == "type_conflict", written


def test_the_right_edition_still_attaches_with_or_without_neighbours() -> None:
    for written in ("远山恒泰明月版培训", "远山恒泰（明月版）培训"):
        for registry in [[P_MINGYUE], *both_orders(P_MINGYUE, Q_HENGAN)]:
            result = attribute(deck(written + ".pptx", written + "\n2024年5月"), registry)
            assert (result.outcome, result.product_id) == ("SUPPLEMENT", "8601"), written
    for written in ("星海安康长期明朗版培训", "星海安康长期（明朗版）培训"):
        for registry in [[XH_MINGLANG], *both_orders(XH_MINGLANG, XH_PLAIN)]:
            result = attribute(deck(written + ".pptx", written + "\n2025年10月"), registry)
            assert (result.outcome, result.product_id) == ("SUPPLEMENT", "8701"), written


def test_two_named_editions_never_attach_automatically() -> None:
    written = "远山恒泰明月版与远山恒泰蓝星版对比培训"
    result = attribute(deck(written + ".pptx", written + "\n2024年5月"), [P_MINGYUE, Q_HENGAN])
    assert (result.outcome, result.reason) == ("NEEDS_CONFIRM", "version_candidates")
    assert options(result, [P_MINGYUE, Q_HENGAN]) == ["8601", None]

"""PV-5 acceptance (written by Claude): a year version of the same product line succeeds the one
that stopped selling before it began (Spec docs/design/slices/PV-5-问答销售状态与产品识别.md §4.1,
revising PV-0 appendix A §1.4). Versions sold side by side never succeed each other; the plan-code
rule still comes first; anything ambiguous is left unlinked."""

from insurance_harness.identity.attribution import load_attribution_policy
from insurance_harness.ingest.product_versions import (
    ProductVersion,
    line_of,
    predecessors,
    year_tag_of,
)
from insurance_harness.ingest.registry_migration import plan_migration
from tests.ingest.upload_helpers import entry, registry
from tests.ingest.version_helpers import catalog, of

POLICY = load_attribution_policy()
ROLES = ("terms", "brochure", "rate_table")


def filed(
    name: str, code: str, start: str | None, end: str | None = None, number: int = 1
) -> tuple[str, ProductVersion]:
    version = ProductVersion(
        version_key=f"{code}-{number}",
        plan_code=code,
        version_no=number,
        sale_start=start,
        sale_end=end,
        source_status="discontinued" if end else "on_sale",
        year_tag=year_tag_of(name, POLICY),
    )
    return name, version


def linked(**entries: tuple[str, ProductVersion]) -> dict[str, str | None]:
    versions = {pid: version for pid, (_, version) in entries.items()}
    lines = {pid: line_of(name, POLICY) for pid, (name, _) in entries.items()}
    return predecessors(versions, lines)


def same_line(left: str, right: str) -> bool:
    return line_of(left, POLICY) == line_of(right, POLICY)


def test_a_line_name_drops_only_the_year_mark() -> None:
    assert same_line("平安智盈倍护（2026）终身护理保险", "平安智盈倍护终身护理保险")
    assert same_line("平安附加（2026）失能收入损失保险", "平安附加失能收入损失保险")
    assert same_line("平安盛世金越（尊享版26）终身寿险", "平安盛世金越（尊享版）终身寿险")
    assert not same_line("平安创智盈倍护（2026）终身护理保险", "平安智盈倍护终身护理保险")
    assert not same_line("平安安佑福（全能版）重大疾病保险", "平安安佑福重大疾病保险")


def test_a_year_version_that_began_after_the_old_one_stopped_succeeds_it() -> None:
    assert linked(
        old=filed("平安智盈倍护终身护理保险", "2635", "2024-04-23", "2024-09-01"),
        new=filed("平安智盈倍护（2026）终身护理保险", "2648", "2025-10-22"),
    ) == {"old": None, "new": "old"}


def test_versions_sold_side_by_side_never_succeed_each_other() -> None:
    assert linked(
        old=filed("平安附加失能收入损失保险", "1806", "2025-04-29"),
        new=filed("平安附加（2026）失能收入损失保险", "1816", "2025-06-16"),
    ) == {"old": None, "new": None}
    assert linked(
        old=filed("甲护理保险", "3001", "2024-01-01", "2025-07-01"),
        new=filed("甲（2025）护理保险", "3002", "2025-06-16"),
    ) == {"old": None, "new": None}, "overlapping sale periods"
    assert linked(
        old=filed("甲护理保险", "3001", "2024-01-01", None),
        new=filed("甲（2026）护理保险", "3002", "2025-10-01"),
    ) == {"old": None, "new": None}, "an unknown end is no succession"


def test_the_plan_code_rule_comes_first() -> None:
    same_code = filed("甲护理保险", "3001", "2023-01-01", "2025-10-01")
    other_code = filed("甲护理保险", "3002", "2024-01-01", "2025-09-01")
    renewed = filed("甲（2026）护理保险", "3001", "2025-10-01", number=2)
    assert linked(a=same_code, b=other_code, c=renewed)["c"] == "a"


def test_the_latest_version_to_stop_is_the_one_succeeded() -> None:
    assert linked(
        y24=filed("甲（2024）护理保险", "3001", "2024-01-01", "2024-09-01"),
        y25=filed("甲（2025）护理保险", "3002", "2024-10-01", "2025-09-30"),
        y26=filed("甲（2026）护理保险", "3003", "2025-10-22"),
    ) == {"y24": None, "y25": "y24", "y26": "y25"}
    assert (
        linked(
            a=filed("甲（2024）护理保险", "3001", "2024-01-01", "2024-09-01"),
            b=filed("甲（2024）护理保险", "3002", "2024-02-01", "2024-09-01"),
            c=filed("甲（2026）护理保险", "3003", "2025-10-22"),
        )["c"]
        is None
    ), "two candidates stopped the same day"


def test_ambiguous_or_backward_lines_are_left_unlinked() -> None:
    assert linked(
        old=filed("甲护理保险", "3001", "2023-01-01", "2024-09-01"),
        one=filed("甲（2026）护理保险", "3002", "2025-10-01"),
        two=filed("甲（2026）护理保险", "3003", "2025-11-01"),
    ) == {"old": None, "one": None, "two": None}, "one predecessor for two successors"
    assert linked(
        old=filed("甲（2024）护理保险", "3001", "2024-01-01", "2024-09-01"),
        new=filed("甲护理保险", "3002", "2025-01-01"),
    ) == {"old": None, "new": None}, "a tagged version is not succeeded by an untagged one"


def test_a_migration_links_the_year_version_of_a_registered_line() -> None:
    value = registry(p1828=entry("1828", *ROLES), p1826=entry("1826", *ROLES))
    value.products["1828"].names = ["平安智盈倍护（2026）终身护理保险"]
    value.products["1826"].names = ["平安智盈倍护终身护理保险"]
    chained = catalog(
        of("1828", key="2648-1", start="2025-10-22"),
        of("1826", key="2635-1", start="2024-04-23", end="2024-09-01", status="discontinued"),
    )
    after, matches = plan_migration(value, chained)
    newer = after.products["1828"].version
    assert newer is not None and newer.predecessor == "1826"
    assert {m.product_id: m.predecessor for m in matches} == {"1828": "1826", "1826": None}

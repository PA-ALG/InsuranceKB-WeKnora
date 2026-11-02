"""PV-5 acceptance (written by Claude, #530 R2): a version the plan-code rule already gives a
successor is no product-line predecessor of another, so a line never forks (Spec
docs/design/slices/PV-5-问答销售状态与产品识别.md §4.1). The plan-code link stays."""

from insurance_harness.ingest.registry_migration import plan_migration
from tests.ingest.upload_helpers import entry, registry
from tests.ingest.version_helpers import catalog, of

ROLES = ("terms", "brochure", "rate_table")


def test_a_predecessor_taken_by_the_plan_code_rule_gets_no_line_successor() -> None:
    # O stops as its renewal A (same plan code) starts; B, the 2026 year version, starts later while
    # A is still on sale.
    value = registry(
        p1826=entry("1826", *ROLES), p1828=entry("1828", *ROLES), p1814=entry("1814", *ROLES)
    )
    value.products["1826"].names = ["甲护理保险"]
    value.products["1828"].names = ["甲护理保险"]
    value.products["1814"].names = ["甲（2026）护理保险"]
    forked = catalog(
        of("1826", key="3001-1", start="2023-01-01", end="2024-01-01", status="discontinued"),
        of("1828", key="3001-2", start="2024-01-01"),
        of("1814", key="3002-1", start="2025-01-01"),
    )
    after, matches = plan_migration(value, forked)
    assert {m.product_id: m.predecessor for m in matches} == {
        "1826": None,
        "1828": "1826",
        "1814": None,
    }
    renewal, year_version = after.products["1828"].version, after.products["1814"].version
    assert renewal is not None and renewal.predecessor == "1826"
    assert year_version is not None and year_version.predecessor is None

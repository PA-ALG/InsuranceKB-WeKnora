"""Only the exact two approved snapshots of these S12c-13a units are equivalent."""

from typing import Any

from tests.compilers.schema_fields.rule_alignment_scope import digest

UNITS = {
    "coverage_and_renewal_terms": ["includes", "absent_rule"],
    "covered_critical_specified_diseases": [
        "includes",
        "examples/0/pitfalls",
        "examples/1/pitfalls",
    ],
    "disease_definitions_and_criteria": ["includes"],
    "eligible_occupation_classes": ["unknown_rule", "bad"],
    "coverage_responsibilities": [
        "definition",
        "includes",
        "bad",
        "writing_rule",
        "examples/0/value",
        "examples/0/pitfalls",
        "examples/1/value",
        "examples/1/pitfalls",
        "examples/2/value",
        "examples/2/pitfalls",
        "examples/3/value",
        "examples/3/pitfalls",
    ],
    "coverage_summary": [
        "definition",
        "includes",
        "bad",
        "writing_rule",
        "examples/0/value",
        "examples/0/pitfalls",
        "examples/1/value",
        "examples/1/pitfalls",
        "examples/2/value",
        "examples/2/pitfalls",
        "examples/3/value",
        "examples/3/pitfalls",
    ],
    "exclusions": ["includes"],
}
NEW_CARD = "multiple_benefit_payment_rules"


def normalize_adjudication(data: dict[str, Any]) -> None:
    # Capture the actual values first: a partial change or an unapproved third value
    # remains visible even for attributes neutralized by an earlier slice.
    selected: dict[str, Any] = {NEW_CARD: data.pop(NEW_CARD, None)}
    for key, paths in UNITS.items():
        for path in paths:
            parent = data[key]
            *steps, leaf = path.split("/")
            for step in steps:
                parent = parent[int(step)] if isinstance(parent, list) else parent[step]
            selected[f"{key}/{path}"] = parent.get(leaf)
            parent[leaf] = "<S12c-13a>"
    fingerprint = digest(selected)
    data["S12c-13a units"] = "approved" if fingerprint in APPROVED else fingerprint


APPROVED = {
    "6c80ed10bb536b04418cd39df8489143e07a3eb5b0dc33fe09fb324645bc9ba0",
    "8fa95d2855f9276aaf51ad7502599c5869ffbc33187ead033057b2874386e960",
}

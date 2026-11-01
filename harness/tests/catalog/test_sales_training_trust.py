"""S11c acceptance: sales and training materials serve only the sales-type fields (Spec §2.4).

Protected file: written by Claude. The role catalogue gains `sales_training`, which is not
ordinary evidence; the TrustPolicy's scoped rule lets exactly the four sales-type fields of the
field cards cite it. Unlike a rate table's header, its pages are split whole. Every other field
is refused at compile (the reference is dropped) and at publish (EVIDENCE_ROLE_NOT_TRUSTED). The
new role changes no existing material's recognised role.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.catalog.trust_policy import (
    TrustPolicyError,
    load_trust_policy,
    parse_trust_policy,
    trusted_pages,
)
from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileOutput,
    FieldResult,
    SchemaFieldsCompiler,
)
from insurance_harness.eval.pdf_text import PageText, read_pdf
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity import material_roles
from insurance_harness.identity.material_roles import (
    MaterialRoles,
    document_roles,
    load_material_roles,
    role_of,
)

REPO = Path(__file__).resolve().parents[3]
SALES_FIELDS = frozenset(
    {"sales_pitch_script", "four_step_sales_script", "objection_handling_scripts", "product_faq"}
)
PITCH, AGE = "sales_pitch_script", "entry_age_range"
TERMS = PageText("保险条款.pdf", "a" * 64, 1, "阅读指引\n投保年龄为0周岁至55周岁。\n")
OBJECTION = "1、异议：保费贵怎么办？"
# Its numeric row would end a rate table's header block; a scoped role is split whole.
SALES_TEXT = f"产品培训\n开场：先问家庭保障。\n0 1 2\n{OBJECTION}\n"
SALES = PageText("产品培训.pdf", "c" * 64, 1, SALES_TEXT)
SCOPED = {"sales_training": [SALES]}
SOURCES = {"保险条款.pdf": SourceRevision("k-1", 1), "产品培训.pdf": SourceRevision("k-3", 3)}


# 1. The role and the policy -----------------------------------------------------------------------


def test_sales_training_is_a_non_evidence_role_of_the_shipped_catalogue() -> None:
    roles = load_material_roles()
    assert roles.version == "2026-11-01.1"  # SK-1 added the unrecognised sales_method role
    assert {r.role: r.evidence for r in roles.roles}["sales_training"] is False


def test_the_scoped_rule_names_exactly_the_four_sales_fields() -> None:
    policy = load_trust_policy()
    assert policy.version == "2026-11-01.1"  # SK-1 added the sales_method scoped rule
    assert policy.scoped_roles() == frozenset({"sales_training", "sales_method"})
    assert policy.restricted_fields("sales_training") == SALES_FIELDS
    assert policy.header_fields("sales_training") == frozenset()
    assert policy.header_roles() == frozenset({"rate_table"})
    assert policy.restricted_fields("rate_table") == frozenset({"premium_payment_term"})
    assert policy.restricted_fields("terms") == frozenset()


def policy_json(scoped: list[dict[str, object]], **extra: object) -> str:
    rate = {"role": "rate_table", "fields": ["premium_payment_term"]}
    body = {"version": "v1", "header_rules": [rate], "scoped_rules": scoped, **extra}
    return json.dumps(body, ensure_ascii=False)


def test_a_policy_without_scoped_rules_still_parses() -> None:
    parsed = parse_trust_policy(
        json.dumps({"version": "v1", "header_rules": [{"role": "rate_table", "fields": ["a"]}]})
    )
    assert parsed.scoped_roles() == frozenset()
    assert parsed.restricted_fields("sales_training") == frozenset()


@pytest.mark.parametrize(
    "text",
    [
        policy_json([{"role": "terms", "fields": ["a"]}]),  # an evidence role
        policy_json([{"role": "rate_table", "fields": ["a"]}]),  # also a header role
        policy_json([{"role": "posters", "fields": ["a"]}]),  # not a catalogue role
        policy_json([{"role": "sales_training", "fields": ["a"]}] * 2),
        policy_json([{"role": "sales_training", "fields": []}]),
        policy_json([{"role": "sales_training", "fields": ["a", "a"]}]),
        policy_json([{"role": "sales_training", "fields": ["a"], "scope": "page"}]),
        policy_json([{"role": "sales_training", "fields": [" "]}]),
    ],
)
def test_an_invalid_scoped_rule_is_refused(text: str) -> None:
    with pytest.raises(TrustPolicyError):
        parse_trust_policy(text)


# 2. Recognition -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("document", "head"),
    [
        ("产品培训.pptx", "产品培训\n开场"),
        ("销售逻辑.pptx", "某某产品销售逻辑"),
        ("异议处理话术.docx", "常见异议与话术"),
        ("常见问题.xlsx", "常见问题\t回答"),
    ],
)
def test_a_sales_material_with_both_signals_is_recognised(document: str, head: str) -> None:
    assert role_of(document, head) == "sales_training"


@pytest.mark.parametrize(
    ("document", "head"),
    [
        ("产品培训.pptx", "某某终身寿险"),  # name only
        ("附件.pptx", "产品培训"),  # text only
        ("产品说明书培训.pptx", "产品说明书培训"),  # a brochure signal as well
        ("条款培训.pdf", "阅读指引\n培训"),  # a terms signal as well
    ],
)
def test_otherwise_a_sales_material_is_left_to_a_person(document: str, head: str) -> None:
    assert role_of(document, head) is None


def test_no_dataset_material_changes_its_role(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = sorted((REPO / "dataset" / "shouxian_product").glob("*/*.pdf"))
    assert len(paths) >= 40
    pages = [page for path in paths for page in read_pdf(path)]
    # Products share file names; a directory part keeps them apart and leaves the stem as it was.
    keyed = [PageText(f"{p.document_sha256}/{p.document}", p.document_sha256, p.page, p.text)
             for p in pages]
    shipped = document_roles(keyed)
    roles = load_material_roles()
    without = MaterialRoles(
        version=roles.version, roles=tuple(r for r in roles.roles if r.role != "sales_training")
    )
    monkeypatch.setattr(material_roles, "load_material_roles", lambda: without)
    assert document_roles(keyed) == shipped
    assert "sales_training" not in shipped.values()


# 3. Pages, segments, compile and publish ----------------------------------------------------------


def test_sales_pages_are_read_apart_from_evidence() -> None:
    brochure = PageText("产品说明书.pdf", "b" * 64, 1, "某某终身寿险产品说明书\n本产品保障终身。")
    trusted = trusted_pages([TERMS, brochure, SALES])
    assert trusted.evidence == [TERMS, brochure]
    assert trusted.table_headers == SCOPED
    assert trusted.roles["产品培训.pdf"] == "sales_training"


def test_sales_pages_are_split_whole_not_clipped_to_a_header() -> None:
    source = SegmentedSource([TERMS], table_headers=SCOPED)
    assert source.header_role("产品培训.pdf") == "sales_training"
    sales = [s.text for s in source.segments if s.document == "产品培训.pdf"]
    assert sales == ["产品培训\n开场：先问家庭保障。", "0 1 2", OBJECTION]


class Replay:
    model = "offline-fixture"

    def __init__(self, *responses: str) -> None:
        self.responses = iter(responses)

    def complete(self, *, system: str, user: str) -> str:
        return next(self.responses)


def definition(key: str, ordinal: int) -> FieldDefinition:
    return FieldDefinition(field_key=key, short_title=key, description=key, ordinal=ordinal)


def answer(*rows: dict[str, object]) -> str:
    return json.dumps({"fields": list(rows)}, ensure_ascii=False)


def sales_id(source: SegmentedSource) -> str:
    return next(s.id for s in source.segments if s.text == OBJECTION)


def test_compile_keeps_a_sales_field_reference_and_drops_any_other() -> None:
    source = SegmentedSource([TERMS], table_headers=SCOPED)
    sales = sales_id(source)
    selection = answer(
        {"ordinal": 0, "field_key": PITCH, "state": "present", "segments": [sales]},
        {"ordinal": 1, "field_key": AGE, "state": "present", "segments": ["D1P1S1", sales]},
    )
    values = answer(
        {"ordinal": 0, "field_key": PITCH, "value": "异议：保费贵怎么办？"},
        {"ordinal": 1, "field_key": AGE, "value": "0周岁至55周岁"},
    )
    output = SchemaFieldsCompiler(Replay(selection, values)).compile(
        "p1", [definition(PITCH, 0), definition(AGE, 1)], [TERMS], table_headers=SCOPED
    )
    by_key = {field.field_key: field for field in output.fields}
    assert by_key[PITCH].segment_ids == [sales]
    assert {quote.document for quote in by_key[PITCH].evidence} == {"产品培训.pdf"}
    assert by_key[AGE].segment_ids == ["D1P1S1"]
    assert output.dropped_refs == 1


def cited(source: SegmentedSource, key: str) -> FieldResult:
    sales = sales_id(source)
    return FieldResult(
        field_key=key,
        state="present",
        value="异议：保费贵怎么办？",
        evidence=source.evidence([sales]),
        segment_ids=[sales],
    )


def output_of(*fields: FieldResult) -> CompileOutput:
    return CompileOutput(
        pack_id="pack", entity_id="p1", model="m", fields=list(fields), cards_version="cards-x"
    )


def test_publish_accepts_a_sales_field_and_refuses_any_other() -> None:
    source = SegmentedSource([TERMS], table_headers=SCOPED)
    claims = claims_from(output_of(cited(source, PITCH)), source, SOURCES)
    assert [claim.predicate for claim in claims] == [PITCH]
    [evidence] = claims[0].evidence
    assert evidence.file_sha256 == "c" * 64
    assert evidence.locator.kind == "PDF_TEXT_SPAN"
    with pytest.raises(BundleError) as refused:
        claims_from(output_of(cited(source, PITCH), cited(source, AGE)), source, SOURCES)
    assert (refused.value.reason, refused.value.field_index) == ("EVIDENCE_ROLE_NOT_TRUSTED", 1)

"""S4g acceptance: compile output becomes a verifiable candidate bundle (Spec §2.2).

Protected file: written by Claude. One claim member per field; evidence is cut from the page
text by the selected segment ids and carries a source:v1 reference and a PDF_TEXT_SPAN locator
whose code-point offsets reproduce the quote. Nothing is guessed: ids that do not reproduce the
saved evidence, or a document missing from the source map, stop the build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import jsonschema  # type: ignore[import-untyped]
import pytest

from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.publish.bundle import BundleError, SourceRevision, candidate_bundle
from insurance_harness.publish.canonical import member_digest
from insurance_harness.publish.client import Head

REPO = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((REPO / "contracts/candidate_bundle.schema.json").read_text(encoding="utf-8"))
SHA = "ab" * 32


class Page:
    def __init__(self, page: int, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = "保险条款.pdf", SHA, page, text


SOURCE = SegmentedSource(
    [
        Page(
            1,
            "1.4 等待期\n自本合同生效之日起90日内为等待期。\n"
            + "因意外伤害发生保险事故的，无等待期。\n",
        ),
        Page(2, "1.5 保险期间\n本合同保险期间为一年。\n本合同不设宽限期。\n"),
    ]
)
# D1P1S1 等待期 · D1P1S2 意外无等待期 · D1P2S1 保险期间 · D1P2S2 不设宽限期
SOURCES = {"保险条款.pdf": SourceRevision(knowledge_id="k-1", parse_attempt=2)}
REF = f"source:v1:k-1:2:{SHA}"
State = Literal["present", "absent_explicitly", "unknown"]


def field(key: str, state: State, ids: list[str], value: str | None = None) -> FieldResult:
    return FieldResult(
        field_key=key,
        state=state,
        value=value,
        evidence=SOURCE.evidence(ids),
        segment_ids=ids,
    )


OUTPUT = CompileOutput(
    pack_id="schemapack_critical_illness_insurance",
    entity_id="1828",
    model="deepseek-flash",
    fields=[
        field("waiting_period", "present", ["D1P1S1", "D1P1S2"], "90日；意外无等待期"),
        field("premium_grace_period", "absent_explicitly", ["D1P2S2"]),
        field("cooling_off_period", "unknown", []),
    ],
)


def build(output: CompileOutput = OUTPUT, base: Head | None = None) -> dict[str, Any]:
    bundle = candidate_bundle(
        output, SOURCE, SOURCES, compiler_identity="harness/schema_fields@test", base=base
    )
    return bundle.model_dump(mode="json")


def members(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["logical_slug"]: m for m in bundle["members"]}


def test_every_field_is_one_claim_member_with_a_matching_digest() -> None:
    bundle = build()
    jsonschema.validate(bundle, SCHEMA)
    assert bundle["contract_version"] == "1" and bundle["origin"] == "compile"
    assert bundle.get("base_release_id") is None and bundle["removals"] == []
    by_slug = members(bundle)
    assert set(by_slug) == {
        "1828/waiting_period",
        "1828/premium_grace_period",
        "1828/cooling_off_period",
    }
    for member in by_slug.values():
        assert member["kind"] == "claim" and member["access_scope"] == "space"
        assert member["member_digest"] == member_digest(member["payload"])


def test_present_evidence_is_cut_from_the_page_by_its_offsets() -> None:
    member = members(build())["1828/waiting_period"]
    claim = member["payload"]
    assert (claim["state"], claim["value"]) == ("present", "90日；意外无等待期")
    assert (claim["predicate"], claim["subject_ref"]) == ("waiting_period", "1828")
    assert member["evidence_refs"] == [REF]
    [evidence] = claim["evidence"]  # adjacent segments on one page merge into one span
    assert evidence["source_ref"] == REF and evidence["file_sha256"] == SHA
    locator = evidence["locator"]
    assert locator["kind"] == "PDF_TEXT_SPAN" and locator["page"] == 1
    page_text = SOURCE.pages[0].text
    assert page_text[locator["start"] : locator["end"]] == evidence["quote"]
    assert evidence["quote"].startswith("1.4 等待期") and evidence["quote"].endswith("无等待期。")


def test_absent_cites_its_clause_and_unknown_cites_nothing() -> None:
    by_slug = members(build())
    absent = by_slug["1828/premium_grace_period"]["payload"]
    assert absent["state"] == "absent_explicitly" and absent["value"] is None
    assert [e["quote"] for e in absent["evidence"]] == ["本合同不设宽限期。"]
    unknown = by_slug["1828/cooling_off_period"]
    assert unknown["payload"]["evidence"] == [] and unknown["evidence_refs"] == []
    assert unknown["payload"]["unknown_reason"] == "NOT_IN_MATERIAL"


def test_the_current_head_becomes_the_base() -> None:
    bundle = build(base=Head(release_id="rel_1", epoch=3))
    assert (bundle["base_release_id"], bundle["base_epoch"]) == ("rel_1", 3)


def test_ids_that_do_not_reproduce_the_evidence_stop_the_build() -> None:
    stale = FieldResult(
        field_key="waiting_period",
        state="present",
        value="90日",
        evidence=SOURCE.evidence(["D1P1S1"]),
        segment_ids=["D1P2S1"],
    )
    with pytest.raises(BundleError):
        build(OUTPUT.model_copy(update={"fields": [stale]}))


def test_a_document_missing_from_the_source_map_stops_the_build() -> None:
    with pytest.raises(BundleError):
        candidate_bundle(OUTPUT, SOURCE, {}, compiler_identity="harness/schema_fields@test")

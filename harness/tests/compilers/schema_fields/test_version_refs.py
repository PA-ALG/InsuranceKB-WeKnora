"""PV-4a acceptance: compiled claims name their product version (PV-4 Spec §3.2).

Protected file: written by Claude. A schema_fields claim's subject is a product version entity, so
`product_version_ref` equals `subject_ref` (appendix A §1.2). The three compile publish entry points
pass the registry's version metadata to the product page, so publishing after an identity refresh
never writes the entity back to its old shape.
"""

from __future__ import annotations

import ast
from pathlib import Path

from insurance_harness.compilers.schema_fields.claims import claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.source_ref import SourceRevision

SRC = Path(__file__).resolve().parents[3] / "src" / "insurance_harness"
TERMS = PageText("保险条款.pdf", "a" * 64, 1, "1.4 等待期\n自本合同生效之日起90日内为等待期。\n")
SOURCE = SegmentedSource([TERMS])
SOURCES = {"保险条款.pdf": SourceRevision("k-1", 1)}


def test_every_compiled_claim_names_its_subject_as_its_version() -> None:
    segment = next(s.id for s in SOURCE.segments if "90日" in s.text)
    present = FieldResult(
        field_key="waiting_period",
        state="present",
        value="90日",
        evidence=SOURCE.evidence([segment]),
        segment_ids=[segment],
    )
    unknown = FieldResult(field_key="grace_period", state="unknown", value=None)
    output = CompileOutput(
        pack_id="pack", entity_id="sc-abc", model="m", fields=[present, unknown], cards_version="c"
    )
    claims = claims_from(output, SOURCE, SOURCES)
    assert [claim.product_version_ref for claim in claims] == ["sc-abc", "sc-abc"]
    assert all(claim.product_version_ref == claim.subject_ref for claim in claims)


def _passes_metadata(module: str) -> bool:
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "product_page"
    ]
    return bool(calls) and all(any(k.arg == "metadata" for k in call.keywords) for call in calls)


def test_each_compile_publish_entry_point_passes_the_version_metadata() -> None:
    for module in (
        "compilers/schema_fields/publish.py",
        "compilers/schema_fields/publish_changes.py",
        "ingest/judge_batch/publishing.py",
    ):
        assert _passes_metadata(module), module

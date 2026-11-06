"""Exercise the actual output/replay, publication planner and registry seed boundaries offline."""

import json
from pathlib import Path

from insurance_harness.catalog.additions import shipped_revisions
from insurance_harness.compilers.schema_fields.claims import compiler_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval.compile_run import ProductRun, compile_products
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.publication import plan
from insurance_harness.ingest.registry import MaterialEntry, ProductEntry
from tests.ingest.test_publication import write_output
from tests.ingest.upload_helpers import registry

REPO = Path(__file__).resolve().parents[3]
PACK = "schemapack_medical_insurance"


class EmptyContract:
    model = "local-fixture"

    def complete(self, *, system: str, user: str) -> str:
        fields = json.loads(user)["schema_fields"]
        return json.dumps(
            {
                "fields": [
                    {
                        "field_key": f["field_key"],
                        "ordinal": f["ordinal"],
                        "state": "unknown",
                        "segments": [],
                    }
                    for f in fields
                ]
            }
        )


def test_compile_run_replaces_a_pre_overlay_output_then_reuses_current(tmp_path: Path) -> None:
    product = "synthetic"
    root = tmp_path / "run"

    def run() -> ProductRun:
        (result,) = compile_products(
            REPO,
            [product],
            run_root=root,
            max_sent=0,
            completion_factory=lambda _: EmptyContract(),
            facts=lambda _: ("合成合同", PACK),
            page_source=lambda _: [PageText("test.pdf", "a" * 64, 1, "这是一份合成文本。")],
        )
        return result

    assert not run().reused
    path = root / product / "output.json"
    new = CompileOutput.model_validate_json(path.read_bytes())
    assert new.catalog_revision == shipped_revisions()[PACK]
    assert "beneficiary_rules" in {f.field_key for f in new.fields}
    assert compiler_version(new).endswith(f"+catalog:{new.catalog_revision}")
    assert run().reused
    legacy = new.model_dump(exclude={"catalog_revision"})
    legacy["fields"] = [f for f in legacy["fields"] if f["field_key"] != "beneficiary_rules"]
    path.write_text(json.dumps(legacy))
    assert not run().reused and run().reused
    restored = CompileOutput.model_validate_json(path.read_bytes())
    assert restored == new


def test_plan_requeues_a_legacy_output_for_an_augmented_pack(tmp_path: Path) -> None:
    product = "synthetic"
    source = MaterialEntry(knowledge_id="source", parse_attempt=1, sha256="a" * 64,
                           role="terms", file_name="test.pdf")
    current = registry(synthetic=ProductEntry(
        names=["合成合同"], clause_codes=[], schema_pack_id=PACK, origin="created",
        materials=[source],
    ))
    root = tmp_path / "run"
    write_output(root / "compile", current, product)
    assert plan(current, root, [product]).compile == []
    path = root / "compile" / product / "output.json"
    data = json.loads(path.read_bytes())
    del data["catalog_revision"]
    path.write_text(json.dumps(data))
    assert plan(current, root, [product]).compile == [product]

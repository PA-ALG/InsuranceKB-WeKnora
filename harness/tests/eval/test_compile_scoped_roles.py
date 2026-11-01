"""S11c: a registry compile reads scoped (sales/training) pages beside header pages.

The revision read orders restricted pages by the TrustPolicy's roles; a scoped role is one of
them, so a product with a sales material compiles and records the material's role.
"""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.trust_policy import TrustedPages, load_trust_policy
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval.compile_run import compile_products
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision


def save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    save(root / "dataset/shouxian_product/product/product_meta.json",
         {"planCode": "p", "clauseName": "产品"})
    save(root / "dataset/golden/v2/manifest.json", {"products": {"p": {"pack_id": "pack"}}})
    save(root / SCHEMA_PACK_CATALOG, {
        "entries": [{"pack": {"schema_pack_id": "pack", "fields": [{
            "field_key": "sales_pitch_script", "short_title": "Pitch话术",
            "description": "Pitch话术", "formation_method": "原文抽取",
        }]}}],
    })
    return root


class Unknown:
    model = "offline"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        rows = [{"ordinal": f["ordinal"], "field_key": f["field_key"], "state": "unknown",
                 "segments": []} for f in json.loads(user)["schema_fields"]]
        return json.dumps({"fields": rows}, ensure_ascii=False)


def page(document: str, text: str) -> PageText:
    return PageText(document, hashlib.sha256(document.encode()).hexdigest(), 1, text)


def test_restricted_roles_list_header_roles_first() -> None:
    assert load_trust_policy().restricted_roles() == (  # SK-1 appended sales_method
        "rate_table",
        "sales_training",
        "sales_method",
    )


def test_a_product_with_a_sales_material_compiles_from_its_revisions(
    repo: Path, tmp_path: Path
) -> None:
    terms = page("保险条款.pdf", "阅读指引\n等待期为90日。")
    rates = page("费率表.pdf", "年交费率表\n交费期间\n10年交\n0 999")
    sales = page("产品培训.pdf", "产品培训\n开场：先问家庭保障。")
    revisions = {
        terms.document: SourceRevision("k-terms", 1),
        rates.document: SourceRevision("k-rates", 1),
        sales.document: SourceRevision("k-sales", 1),
    }
    read = TrustedPages(
        [terms],
        {"sales_training": [sales], "rate_table": [rates]},  # not in policy order
        {terms.document: "terms", rates.document: "rate_table", sales.document: "sales_training"},
    )
    model = Unknown()
    root = tmp_path / "run"
    [run] = compile_products(repo, ["p"], completion_factory=lambda _: model, run_root=root,
                             max_sent=0, revision_page_source=lambda _: (read, revisions))
    assert not run.reused and model.calls >= 1
    output = CompileOutput.model_validate_json((root / "p/output.json").read_text())
    assert output.material_roles is not None
    assert sorted(output.material_roles.values()) == ["rate_table", "sales_training", "terms"]

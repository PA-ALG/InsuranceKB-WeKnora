"""Exercise file workflow with synthetic sources; never call a real judge."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval import annotate
from insurance_harness.eval.judge import JudgeProtocolError
from insurance_harness.eval.pdf_text import PageText, read_pdf


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    source = repo / "dataset/shouxian_product/Product"
    write_json(source / "product_meta.json", {"planCode": "596"})
    (source / "terms.pdf").write_bytes(b"synthetic terms")
    write_json(repo / "internal/handler/schema_pack_catalog_830_g3.generated.json", {
        "entries": [{"pack": {"display_name": "Test", "schema_pack_id": "pack", "fields": [{
            "short_title": "期限", "field_key": "duration", "description": "Duration",
            "source_guidance": "terms", "formation_method": "原文抽取", "value_spec": None,
        }]}}],
    })
    golden = repo / "dataset/golden/v1"
    write_json(golden / "manifest.json", {"product_id": "596", "pack_id": "pack", "files": {}})
    write_json(golden / "596.jsonl", {
        "pack_id": "pack", "product_id": "596", "field_key": "duration", "state": "present",
        "value": "90日", "judged_by": "human:reference", "evidence": [{
            "document": "terms.pdf", "document_sha256": "b" * 64, "page": 1, "quote": "90日",
        }],
    })

    def pages(path: Path) -> list[PageText]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return [PageText(path.name, digest, 1, "期限为90日。")]

    monkeypatch.setattr(annotate, "read_pdf", pages)
    return repo, tmp_path / "runs"


def answer(run: Path, quote: str = "期限为90日", value: str = "90日") -> None:
    write_json(run / "responses/001.json", {"fields": [{
        "field_key": "duration", "state": "present", "value": value,
        "components": [], "evidence": [{"document": "terms.pdf", "page": 1, "quote": quote}],
    }]})


def prepare(repo: Path, root: Path, product: str = "596") -> dict[str, Any]:
    return annotate.prepare(repo, product, root, pack_id="pack")


def test_calibration_preserves_reference_and_unlocks_second_product(
    workspace: tuple[Path, Path],
) -> None:
    repo, root = workspace
    original = (repo / "dataset/golden/v1/596.jsonl").read_bytes()
    run = prepare(repo, root)
    assert len(run["request_sha256"]) == 1
    assert "不联网" in (root / "596/AGENTS.md").read_text()
    answer(root / "596")
    result = annotate.ingest(repo, "596", root, judge_model="fake", calibrate_only=True)
    assert result["passed"] is True
    assert result["state_agreement_rate"] == 1
    assert (repo / "dataset/golden/v1/596.jsonl").read_bytes() == original
    other = repo / "dataset/shouxian_product/Other"
    write_json(other / "product_meta.json", {"planCode": "other"})
    (other / "terms.pdf").write_bytes(b"other terms")
    prepare(repo, root, "other")
    answer(root / "other")
    annotate.ingest(repo, "other", root, judge_model="fake")
    row = json.loads((repo / "dataset/golden/v1/other.jsonl").read_text())
    assert row["judged_by"] == "model:fake"
    manifest = json.loads((repo / "dataset/golden/v1/manifest.json").read_text())
    assert manifest["products"]["other"]["judging_method"] == "codex-session-file-exchange"
    with pytest.raises(FileExistsError):
        annotate.ingest(repo, "other", root, judge_model="fake")


def test_failed_calibration_does_not_unlock_generation(workspace: tuple[Path, Path]) -> None:
    repo, root = workspace
    prepare(repo, root)
    answer(root / "596", value="180日")
    result = annotate.ingest(repo, "596", root, judge_model="fake", calibrate_only=True)
    assert result["passed"] is False
    assert result["disagreements"] == {"duration": "value"}
    with pytest.raises(ValueError, match="calibration"):
        prepare(repo, root, "other")


@pytest.mark.parametrize("mutation", ["pdf", "batch", "fields", "hash", "extra", "prompt"])
def test_ingest_rejects_changed_inputs(workspace: tuple[Path, Path], mutation: str) -> None:
    repo, root = workspace
    prepare(repo, root)
    answer(root / "596")
    path = root / "596/run.json"
    data = json.loads(path.read_text())
    if mutation == "pdf":
        (repo / "dataset/shouxian_product/Product/terms.pdf").write_bytes(b"changed")
    elif mutation == "extra":
        (root / "596/requests/002.json").write_text("{}")
    else:
        if mutation == "batch":
            data["batch_size"] = 0
        elif mutation == "fields":
            data["field_keys"] = []
        elif mutation == "hash":
            data["request_sha256"] = ["0" * 64]
        else:
            data["prompt_version"] = "changed"
        write_json(path, data)
    with pytest.raises((ValueError, JudgeProtocolError)):
        annotate.ingest(repo, "596", root, judge_model="fake", calibrate_only=True)
    assert not (root / "calibration.json").exists()


def test_prepare_refuses_existing_directory_and_repository(workspace: tuple[Path, Path]) -> None:
    repo, root = workspace
    prepare(repo, root)
    with pytest.raises(FileExistsError):
        prepare(repo, root)
    (repo / ".git").mkdir()
    with pytest.raises(ValueError, match="git"):
        prepare(repo, repo / "runs")


def test_zero_comparison_fails_closed(workspace: tuple[Path, Path]) -> None:
    repo, root = workspace
    prepare(repo, root)
    answer(root / "596", quote="fabricated")
    result = annotate.ingest(repo, "596", root, judge_model="fake", calibrate_only=True)
    assert result["passed"] is False
    assert result["state_agreement_rate"] is None
    assert result["evidence_not_verified_rate"] == 1


def test_pdf_snapshot_hash_and_physical_pages(tmp_path: Path) -> None:
    # Minimal real PDF, including an empty second page; no fixture/parser dependency.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R "
        b"/Resources << /Font << /F1 6 0 R >> >> >>",
        b"<< /Length 37 >>\nstream\nBT /F1 12 Tf 20 200 Td (Hello) Tj ET\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 7\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()
    path = tmp_path / "terms.pdf"
    path.write_bytes(data)
    pages = read_pdf(path)
    assert [page.page for page in pages] == [1, 2]
    assert pages[0].text == "Hello" and pages[1].text == ""
    assert {page.document_sha256 for page in pages} == {hashlib.sha256(data).hexdigest()}


def test_scheduled_products_have_declared_pack_inputs() -> None:
    repo = Path(__file__).resolve().parents[3]
    manifest = json.loads((repo / "dataset/golden/v1/manifest.json").read_text())
    expected = {
        "1826": "schemapack_endowment_insurance",
        "1824": "schemapack_whole_life_insurance",
        "1814": "schemapack_accident_insurance",
        "1816": "schemapack_disability_income_insurance",
        "1828": "schemapack_critical_illness_insurance",
    }
    assert {product: manifest["products"][product]["pack_id"] for product in expected} == expected

"""S12d acceptance (protected, written by Claude): a dataset folder may record its confirmed roles.

Spec docs/design/slices/S12d-数据集记录材料角色.md §2 and §5. A complete `material_roles.json`
binds each PDF's confirmed role to its bytes; without it, reading is exactly as before (S4i).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.product_sources import (
    material_pages,
    source_directory,
    source_pages,
    trusted_source_pages,
)
from insurance_harness.identity.material_roles import MaterialRoleError, evidence_pages

REPO = Path(__file__).resolve().parents[3]
PRODUCTS = "dataset/shouxian_product"
RECORD = "material_roles.json"


def real_folder(plan_code: str) -> Path:
    found = [
        path.parent
        for path in (REPO / PRODUCTS).glob("*/product_meta.json")
        if json.loads(path.read_text(encoding="utf-8")).get("planCode") == plan_code
    ]
    assert len(found) == 1
    return found[0]


def ascii_pdf(text: str) -> bytes:
    """A one-page PDF whose text layer is `text` (ASCII), so no role's opening signal matches."""
    stream = f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF"
    data += trailer.encode()
    return data


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def folder(tmp_path: Path, files: dict[str, Path | bytes], roles: dict[str, str] | None) -> Path:
    """A one-product dataset under tmp_path; `roles` writes a complete record for those files."""
    directory = tmp_path / PRODUCTS / "合成产品"
    directory.mkdir(parents=True)
    meta = {"planCode": "T1", "clauseName": "合成产品"}
    (directory / "product_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for name, content in files.items():
        if isinstance(content, Path):
            shutil.copyfile(content, directory / name)
        else:
            (directory / name).write_bytes(content)
    if roles is not None:
        write_record(directory, roles)
    return source_directory(tmp_path, "T1")


def write_record(directory: Path, recorded: dict[str, str], **override: Any) -> None:
    roles = {
        name: {"role": role, "sha256": sha(directory / name)} for name, role in recorded.items()
    }
    record: dict[str, Any] = {"basis": "合成测试：费率表开头认不出", "roles": roles}
    record.update(override)
    (directory / RECORD).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def stopped(call: Any, directory: Path) -> str:
    with pytest.raises(MaterialRoleError) as caught:
        call(directory)
    assert isinstance(caught.value, ValueError)
    return caught.value.code


TERMS = real_folder("1814") / "保险条款.pdf"
BROCHURE = real_folder("1814") / "产品说明书.pdf"
RATES = real_folder("1814") / "费率表.pdf"
UNRESOLVED_RATES = ascii_pdf("Annual premium per 10000 by age")
ALL_THREE = {"保险条款.pdf": "terms", "产品说明书.pdf": "brochure", "费率表.pdf": "rate_table"}


def test_an_unresolved_rate_table_reads_once_its_role_is_recorded(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    plain = folder(tmp_path / "plain", files, None)
    assert stopped(trusted_source_pages, plain) == "MATERIAL_ROLE_UNRESOLVED"

    recorded = folder(tmp_path / "recorded", files, ALL_THREE)
    trusted = trusted_source_pages(recorded)
    assert {p.document for p in trusted.evidence} == {"保险条款.pdf", "产品说明书.pdf"}
    assert {p.document for p in trusted.table_headers["rate_table"]} == {"费率表.pdf"}
    assert trusted.roles == ALL_THREE


def test_a_complete_record_may_leave_out_the_brochure(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {"保险条款.pdf": TERMS, "费率表.pdf": RATES}
    directory = folder(tmp_path, files, {"保险条款.pdf": "terms", "费率表.pdf": "rate_table"})
    trusted = trusted_source_pages(directory)
    assert {p.document for p in trusted.evidence} == {"保险条款.pdf"}
    assert trusted.roles == {"保险条款.pdf": "terms", "费率表.pdf": "rate_table"}
    assert {p.document for p in source_pages(directory)} == {"保险条款.pdf"}


def test_a_record_for_other_bytes_is_an_identity_mismatch(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    directory = folder(tmp_path, files, ALL_THREE)
    (directory / "费率表.pdf").write_bytes(ascii_pdf("Annual premium per 10000 by sex"))
    assert stopped(trusted_source_pages, directory) == "MATERIAL_IDENTITY_MISMATCH"
    assert stopped(source_pages, directory) == "MATERIAL_IDENTITY_MISMATCH"


def test_a_record_that_leaves_out_a_pdf_is_invalid(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    directory = folder(tmp_path, files, {"保险条款.pdf": "terms", "产品说明书.pdf": "brochure"})
    assert stopped(trusted_source_pages, directory) == "RECORDED_ROLES_INVALID"


def test_a_record_that_names_a_missing_file_is_invalid(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    directory = folder(tmp_path, files, ALL_THREE)
    record = json.loads((directory / RECORD).read_text(encoding="utf-8"))
    record["roles"]["附件.pdf"] = {"role": "brochure", "sha256": "a" * 64}
    (directory / RECORD).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    assert stopped(trusted_source_pages, directory) == "RECORDED_ROLES_INVALID"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda directory: (directory / RECORD).write_text("{not json", encoding="utf-8"),
        lambda directory: write_record(directory, ALL_THREE, basis=" "),
        lambda directory: write_record(directory, ALL_THREE, extra="x"),
        lambda directory: write_record(
            directory,
            ALL_THREE,
            roles={
                name: {"role": role, "sha256": sha(directory / name), "note": "x"}
                for name, role in ALL_THREE.items()
            },
        ),
        lambda directory: write_record(
            directory,
            ALL_THREE,
            roles={name: {"role": role, "sha256": "XYZ"} for name, role in ALL_THREE.items()},
        ),
    ],
)
def test_a_malformed_record_stops_the_product(tmp_path: Path, mutate: Any) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    directory = folder(tmp_path, files, None)
    mutate(directory)
    assert stopped(trusted_source_pages, directory) == "RECORDED_ROLES_INVALID"


def test_an_unknown_recorded_role_is_refused(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    directory = folder(tmp_path, files, {**ALL_THREE, "费率表.pdf": "conversion_table"})
    assert stopped(trusted_source_pages, directory) == "MATERIAL_ROLE_UNKNOWN"


def test_evidence_pages_use_the_same_record(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": UNRESOLVED_RATES,
    }
    plain = folder(tmp_path / "plain", files, None)
    assert stopped(source_pages, plain) == "MATERIAL_ROLE_UNRESOLVED"
    recorded = folder(tmp_path / "recorded", files, ALL_THREE)
    assert {p.document for p in source_pages(recorded)} == {"保险条款.pdf", "产品说明书.pdf"}


def test_a_folder_without_a_record_reads_exactly_as_before(tmp_path: Path) -> None:
    files: dict[str, Path | bytes] = {
        "保险条款.pdf": TERMS,
        "产品说明书.pdf": BROCHURE,
        "费率表.pdf": RATES,
    }
    directory = folder(tmp_path, files, None)
    raw = material_pages(directory)
    assert source_pages(directory) == evidence_pages(raw)
    trusted = trusted_source_pages(directory)
    assert trusted.evidence == evidence_pages(raw)
    assert trusted.roles == ALL_THREE

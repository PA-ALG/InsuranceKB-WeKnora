"""S12d round 2 (#424 review R1–R3; Spec §6): a role record is unambiguous, checked against the
folder's real files, and binds the very bytes that are parsed. Every failure is a safe code at the
public entry points: `source_pages`, `trusted_source_pages` and the `golden_remap` command.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval import golden_remap
from insurance_harness.eval.product_sources import (
    source_directory,
    source_pages,
    trusted_source_pages,
)
from insurance_harness.identity.material_roles import MaterialRoleError

REPO = Path(__file__).resolve().parents[3]
PRODUCTS = "dataset/shouxian_product"
RECORD = "material_roles.json"
ROLES = {"保险条款.pdf": "terms", "产品说明书.pdf": "brochure", "费率表.pdf": "rate_table"}
NOT_A_PDF = b"this is not a PDF file\n"
TWICE_NAMED = '"费率表.pdf": {"role": "terms", "sha256": "' + "0" * 64 + '"}'


def real_folder(plan_code: str) -> Path:
    found = [
        path.parent
        for path in (REPO / PRODUCTS).glob("*/product_meta.json")
        if json.loads(path.read_text(encoding="utf-8")).get("planCode") == plan_code
    ]
    assert len(found) == 1
    return found[0]


SOURCE = real_folder("1814")  # three materials that inference recognises


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """One product folder (planCode T1) with a valid, complete record, plus what the remap
    command needs to reach the materials: a manifest naming T1 and an empty previous export."""
    root = tmp_path / "repo"
    directory = root / PRODUCTS / "合成产品"
    directory.mkdir(parents=True)
    meta = {"planCode": "T1", "clauseName": "合成产品"}
    (directory / "product_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for name in ROLES:
        shutil.copyfile(SOURCE / name, directory / name)
    write_text(directory, record_text(directory, ROLES))
    gold = root / "dataset/golden/v2"
    gold.mkdir(parents=True)
    manifest = {"files": {}, "products": {"T1": {}}, "revisions": []}
    (gold / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    previous = tmp_path / "previous"
    previous.mkdir()
    export = {"baseline": "f" * 40, "pages": [], "segments": []}
    (previous / "T1.json").write_text(json.dumps(export), encoding="utf-8")
    return root


def folder(repo: Path) -> Path:
    return repo / PRODUCTS / "合成产品"


def record_text(directory: Path, roles: dict[str, str]) -> str:
    items = ",".join(
        f'"{name}": {{"role": "{role}", "sha256": "{sha(directory / name)}"}}'
        for name, role in roles.items()
    )
    return f'{{"basis": "合成测试", "roles": {{{items}}}}}'


def write_text(directory: Path, text: str) -> None:
    (directory / RECORD).write_text(text, encoding="utf-8")


def code_of(call: Callable[[Path], Any], directory: Path) -> str:
    with pytest.raises(MaterialRoleError) as caught:
        call(directory)
    return caught.value.code


def remap(repo: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    gold = repo / "dataset/golden/v2"
    before = {path.name: path.read_bytes() for path in sorted(gold.iterdir())}
    returned = golden_remap.main(
        [
            "--repo", str(repo),
            "--previous", str(repo.parent / "previous"),
            "--products", "T1",
            "--cards-version", "cards-test",
            "--basis", "测试",
            "--emptied-reason", "测试",
        ]
    )  # fmt: skip
    assert returned == 2
    assert {path.name: path.read_bytes() for path in sorted(gold.iterdir())} == before
    out = capsys.readouterr()
    assert "Traceback" not in out.err
    return dict(json.loads(out.out.strip()))


def stops_everywhere(repo: Path, capsys: pytest.CaptureFixture[str], code: str) -> None:
    directory = folder(repo)
    assert code_of(source_pages, directory) == code
    assert code_of(trusted_source_pages, directory) == code
    assert remap(repo, capsys) == {"stopped": code, "product": "T1"}


# Controls: the valid record reads; an unknown role keeps its own code.


def test_the_valid_record_reads(repo: Path) -> None:
    assert trusted_source_pages(source_directory(repo, "T1")).roles == ROLES


def test_an_unknown_recorded_role_keeps_its_code(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_text(folder(repo), record_text(folder(repo), {**ROLES, "费率表.pdf": "conversion"}))
    stops_everywhere(repo, capsys, "MATERIAL_ROLE_UNKNOWN")


# R1: duplicate keys at any level are ambiguous, never "the last one wins".


@pytest.mark.parametrize(
    "rewrite",
    [
        # one file item says rate_table, then terms
        lambda text: text.replace('"role": "rate_table"', '"role": "rate_table", "role": "terms"'),
        # one file named twice, first as terms, then as a rate table
        lambda text: text.replace('"roles": {', '"roles": {' + TWICE_NAMED + ", "),
        lambda text: text.replace('"basis": "合成测试"', '"basis": "合成测试", "basis": "另一个"'),
    ],
)
def test_duplicate_keys_are_invalid(
    repo: Path, capsys: pytest.CaptureFixture[str], rewrite: Callable[[str], str]
) -> None:
    path = folder(repo) / RECORD
    text = rewrite(path.read_text(encoding="utf-8"))
    assert text != path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    stops_everywhere(repo, capsys, "RECORDED_ROLES_INVALID")


# R2: completeness against the real files; a record that is there but unreadable is invalid.


def test_an_unrecorded_pdf_with_an_upper_case_extension_is_invalid(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copyfile(SOURCE / "保险条款.pdf", folder(repo) / "extra.PDF")
    stops_everywhere(repo, capsys, "RECORDED_ROLES_INVALID")


def test_a_record_naming_a_missing_file_is_invalid(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder(repo) / "产品说明书.pdf").unlink()
    stops_everywhere(repo, capsys, "RECORDED_ROLES_INVALID")


@pytest.mark.parametrize("form", ["dangling link", "directory", "not utf-8"])
def test_a_record_that_cannot_be_read_is_not_taken_as_no_record(
    repo: Path, capsys: pytest.CaptureFixture[str], form: str
) -> None:
    directory = folder(repo)
    assert source_pages(directory)  # control: all three materials are recognised without it
    path = directory / RECORD
    path.unlink()
    assert source_pages(directory)
    if form == "dangling link":
        path.symlink_to(directory / "absent.json")
    elif form == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"\xff\xfe{}")
    stops_everywhere(repo, capsys, "RECORDED_ROLES_INVALID")


def test_an_unreadable_record_is_invalid(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = folder(repo) / RECORD
    os.chmod(path, 0)
    try:
        stops_everywhere(repo, capsys, "RECORDED_ROLES_INVALID")
    finally:
        os.chmod(path, 0o644)


def test_a_linked_pdf_in_a_recorded_folder_is_invalid(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = folder(repo)
    target = repo.parent / "elsewhere.pdf"
    shutil.copyfile(directory / "产品说明书.pdf", target)
    (directory / "产品说明书.pdf").unlink()
    (directory / "产品说明书.pdf").symlink_to(target)
    stops_everywhere(repo, capsys, "RECORDED_ROLES_INVALID")


# R3: identity is checked on the bytes that are parsed, before parsing; failures are safe codes.


def test_non_pdf_bytes_under_a_recorded_name_are_an_identity_mismatch(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder(repo) / "费率表.pdf").write_bytes(NOT_A_PDF)
    stops_everywhere(repo, capsys, "MATERIAL_IDENTITY_MISMATCH")


def test_recorded_bytes_that_are_not_a_pdf_are_unreadable(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = folder(repo)
    (directory / "费率表.pdf").write_bytes(NOT_A_PDF)
    write_text(directory, record_text(directory, ROLES))
    stops_everywhere(repo, capsys, "MATERIAL_UNREADABLE")


def test_an_unreadable_recorded_pdf_is_unreadable(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = folder(repo) / "保险条款.pdf"
    os.chmod(path, 0)
    try:
        stops_everywhere(repo, capsys, "MATERIAL_UNREADABLE")
    finally:
        os.chmod(path, 0o644)


def test_a_broken_pdf_without_a_record_is_unreadable(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = folder(repo)
    (directory / RECORD).unlink()
    (directory / "产品说明书.pdf").write_bytes(NOT_A_PDF)
    stops_everywhere(repo, capsys, "MATERIAL_UNREADABLE")

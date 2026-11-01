"""PV-1 review R1–R5 (written by Claude): the counterexamples Codex reproduced on #505.

R1 one clause-code form everywhere; R2 a catalog only from the pinned commit's tracked files;
R3 recovery verifies the journal and the backup; R4 complete, verified writes before the commit
point; R5 a v1 registry refuses v2-only decision fields instead of dropping them on save.
"""

import json
import os
from pathlib import Path

import pytest

from insurance_harness.identity.attribution import Attribution, attribute
from insurance_harness.ingest.registry import (
    RegistryError,
    load_registry,
    record,
    save_registry,
)
from insurance_harness.ingest.registry_migration import MigrationError, migrate_registry
from insurance_harness.ingest.uploads import attribute_uploads, main
from insurance_harness.ingest.version_catalog import (
    CatalogError,
    catalog_from_checkout,
    load_catalog,
    save_catalog,
)
from tests.identity.test_attribution import PRODUCTS, registered, upload
from tests.ingest.manifest_repo import git, meta, repository, write_meta
from tests.ingest.upload_helpers import Pages, entry, material, raw, registry
from tests.ingest.version_helpers import POLICY, catalog, of, rich_v1

REAL_REPLACE, REAL_WRITE = os.replace, os.write
ASCII_CODE = PRODUCTS["1828"]["clause_code"].replace("〔", "[").replace("〕", "]")


class Crash(BaseException):
    """The process dies here."""


def files(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(path.parent.iterdir()) if p.is_file()}


def journal(path: Path) -> Path:
    return path.with_name(path.name + ".migration-journal.json")


def written(tmp_path: Path) -> Path:
    path = tmp_path / "registry.json"
    save_registry(rich_v1(), path)
    return path


def crashed_after_replace(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def replace_then_crash(source: str, target: str) -> None:
        REAL_REPLACE(source, target)
        raise Crash

    monkeypatch.setattr(os, "replace", replace_then_crash)
    with pytest.raises(Crash):
        migrate_registry(path, catalog(of("1828"), of("1814")))
    monkeypatch.setattr(os, "replace", REAL_REPLACE)
    assert journal(path).exists()


# R1 --------------------------------------------------------------------------------------------


def test_r1_an_ascii_bracket_code_is_the_same_code_everywhere() -> None:
    old = registered("1828", "terms").model_copy(
        update={"clause_codes": (ASCII_CODE,), "version_key": "1828-1"}
    )
    terms = upload("1828", "terms", sha256="e" * 64)
    for index in (catalog(of("1828")), None):
        result = attribute(terms, [old], catalog=index)
        assert (result.outcome, result.product_id) == ("NEEDS_CONFIRM", "1828"), result
        assert result.reason == "same_role_differs"


def test_r1_a_run_on_an_ascii_bracket_registry_does_not_abort() -> None:
    value = registry(p1828=entry("1828", "terms", "brochure"))
    value.products["1828"].clause_codes = [ASCII_CODE]
    source = raw("1828", "terms", knowledge_id="k-1828-terms2", sha256="e" * 64)
    reader = Pages(heads={"k-1828-terms2": material("1828", "terms")["head"]}, sources=[source])
    run = attribute_uploads(value, [source], reader, catalog=catalog(of("1828")))
    assert run.registry.products.keys() == {"1828"}  # no second entry for the same version
    assert run.registry.pending[-1].attribution.reason == "same_role_differs"


# R2 --------------------------------------------------------------------------------------------


def test_r2_only_files_tracked_at_the_pinned_commit_enter_the_catalog(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    commit = repository(
        root, ("在售", "A", meta("A1", 1, "甲产品", "平安人寿〔2025〕医疗保险001号"))
    )
    write_meta(
        root, "在售", "B", meta("B1", 1, "乙产品", "平安人寿〔2025〕医疗保险002号")
    )  # untracked
    (root / ".gitignore").write_text("在售/C/\n", encoding="utf-8")
    write_meta(
        root, "在售", "C", meta("C1", 1, "丙产品", "平安人寿〔2025〕医疗保险003号")
    )  # ignored
    changed = meta("A1", 1, "甲产品（改）", "平安人寿〔2025〕医疗保险001号")
    write_meta(root, "在售", "A", changed)  # a working-tree edit of a tracked file
    built = catalog_from_checkout(root, commit)
    assert [(v.version_key, v.name) for v in built.versions] == [("A1-1", "甲产品")]
    assert built.commit == commit


@pytest.mark.parametrize("breakage", ["duplicate-key", "symlink"])
def test_r2_a_repeated_key_or_a_symlink_refuses_the_catalog(tmp_path: Path, breakage: str) -> None:
    root = tmp_path / "repo"
    good = ("在售", "A", meta("A1", 1, "甲产品", "平安人寿〔2025〕医疗保险001号"))
    if breakage == "duplicate-key":
        text = json.dumps(
            meta("B1", 1, "乙产品", "平安人寿〔2025〕医疗保险002号"), ensure_ascii=False
        )
        text = text[:-1] + ', "versionNo": "B1-2"}'
        commit = repository(root, good, ("在售", "B", text))
    else:
        commit = repository(root, good)
        target = root / "在售" / "L" / "product_meta.json"
        target.parent.mkdir()
        target.symlink_to(root / "在售" / "A" / "product_meta.json")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "link")
        commit = git(root, "rev-parse", "HEAD")
    with pytest.raises(CatalogError) as caught:
        catalog_from_checkout(root, commit)
    assert caught.value.code == "CATALOG_INVALID"


def test_r2_a_catalog_whose_source_differs_from_the_basis_is_refused(tmp_path: Path) -> None:
    built = catalog(of("1828"))
    _, digest = save_catalog(built, tmp_path / "registry.json")
    path = tmp_path / "registry.json"
    assert load_catalog(path, digest, repository=built.repository, commit=built.commit) == built
    with pytest.raises(CatalogError) as caught:
        load_catalog(path, digest, repository=built.repository, commit="d" * 40)
    assert caught.value.code == "CATALOG_INVALID"


# R3 --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_r3_a_committed_target_with_a_bad_backup_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    path = written(tmp_path)
    crashed_after_replace(path, monkeypatch)
    [backup] = sorted(tmp_path.glob("registry.json.backup-*.json"))
    if damage == "changed":
        backup.write_bytes(backup.read_bytes() + b" ")  # still valid JSON, not the journal's
    else:
        backup.unlink()
    before = files(path)
    with pytest.raises(MigrationError) as caught:
        migrate_registry(path, catalog(of("1828"), of("1814")))
    assert caught.value.code == "MIGRATION_RECOVERY_UNSAFE"
    assert files(path) == before


@pytest.mark.parametrize(
    "journal_text",
    ['{"backup_file": "registry.json.backup-x.json"}', "not json", '{"backup_file": "../x"}'],
)
def test_r3_a_malformed_journal_is_a_typed_error_and_nothing_is_written(
    tmp_path: Path, journal_text: str
) -> None:
    path = written(tmp_path)
    journal(path).write_text(journal_text, encoding="utf-8")
    before = files(path)
    with pytest.raises(MigrationError) as caught:
        migrate_registry(path, catalog(of("1828"), of("1814")))
    assert caught.value.code == "MIGRATION_JOURNAL_INVALID"
    assert files(path) == before


def test_r3_the_command_prints_the_code_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = repository(
        tmp_path / "repo", ("在售", "A", meta("A1", 1, "甲产品", "平安人寿〔2025〕医疗保险001号"))
    )
    path = written(tmp_path)
    journal(path).write_text('{"backup_file": "registry.json.backup-x.json"}', encoding="utf-8")
    argv = ["migrate-registry", "--registry", str(path)]
    argv += ["--manifest-dir", str(tmp_path / "repo"), "--manifest-commit", commit]
    assert main(argv) == 1
    assert capsys.readouterr().err.strip() == "MIGRATION_JOURNAL_INVALID"


# R4 --------------------------------------------------------------------------------------------


def test_r4_short_writes_still_complete_the_backup_and_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = written(tmp_path)
    original = path.read_bytes()

    def half(descriptor: int, data: bytes) -> int:
        return REAL_WRITE(descriptor, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(os, "write", half)
    assert migrate_registry(path, catalog(of("1828"), of("1814"))).status == "committed"
    [backup] = sorted(tmp_path.glob("registry.json.backup-*.json"))
    assert backup.read_bytes() == original
    assert load_registry(path).contract == "product-registry.v2"


@pytest.mark.parametrize("failing_call", [1, 2, 3])  # the backup, the new content, the journal
def test_r4_a_failed_write_before_the_replace_leaves_the_original_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_call: int
) -> None:
    path = written(tmp_path)
    original = path.read_bytes()
    calls = 0

    def failing(descriptor: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == failing_call:
            raise OSError("disk full")
        return REAL_WRITE(descriptor, data)

    monkeypatch.setattr(os, "write", failing)
    with pytest.raises(OSError):
        migrate_registry(path, catalog(of("1828"), of("1814")))
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".registry.json.*.tmp"))
    assert not journal(path).exists()


# R5 --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["pending", "settlement", "decision"])
def test_r5_a_v1_registry_refuses_a_version_key_in_any_decision(tmp_path: Path, where: str) -> None:
    document = json.loads(rich_v1().model_dump_json())
    if where == "pending":
        document["pending"][0]["attribution"]["version_key"] = "SYNTH-1"
    elif where == "settlement":
        document["pending"][0]["settlement"]["conclusion"]["version_key"] = "SYNTH-1"
    else:
        document["decisions"][0]["attribution"]["version_key"] = "SYNTH-1"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RegistryError) as caught:
        load_registry(path)
    assert caught.value.code == "REGISTRY_INVALID"


def test_r5_recording_a_version_key_into_a_v1_registry_is_refused() -> None:
    value = registry(p1828=entry("1828", "terms"))
    source = raw("1828", "brochure")
    keyed = Attribution(
        outcome="SUPPLEMENT",
        reason="matched_by_name",
        product_id="1828",
        role="brochure",
        version_key="1828-1",
        policy_ref=POLICY,
    )
    with pytest.raises(RegistryError) as caught:
        record(value, source, keyed)
    assert caught.value.code == "RECORD_INVALID"

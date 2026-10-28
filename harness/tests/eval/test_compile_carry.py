"""S12c-4 acceptance (protected, written by Claude): the compile path records what it carried and
reuses an output under a carry request only when it carried the same quotes; the publication
orchestrator compiles with carry (Spec docs/design/slices/S12c-4-复用已审证据段.md §2.4–§2.5).
Offline; reuses the S8a compile fixtures and the publication command fakes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.compilers.schema_fields.carry import CarryRequest, carry_for
from insurance_harness.contracts.enums import ClaimState, LocatorKind, SourceClass
from insurance_harness.contracts.knowledge import Claim, Evidence, Locator, Provenance
from insurance_harness.eval.material_identity import material_identities
from tests.eval.test_compile_materials import compile_at, mapped, output_at, repo, save
from tests.ingest.test_publication import Active, Commands, publish_run, two_products

__all__ = ["repo"]  # the fixture is imported for pytest


def released(text: str, *, release_id: str = "rel-9") -> Release:
    item = Claim(
        claim_id="p/waiting_period", logical_key="p/waiting_period", subject_ref="p",
        predicate="waiting_period", state=ClaimState.PRESENT, value="90日",
        evidence=[Evidence(
            source_ref=f"source:v1:knowledge:7:{'a' * 64}", file_sha256="a" * 64,
            locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=len(text)),
            quote=text, access_scope="space",
        )],
        origin=SourceClass.SOURCE_SUPPORTED,
        provenance=Provenance(compiler="schema_fields", compiler_version="cards", model="m"),
    )
    return Release(id=release_id, epoch=9, members=[ReleaseMember(
        kind="claim", logical_slug=item.logical_key,
        member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
        payload=item.model_dump(mode="json"),
    )])


def expected_digest(active: Release) -> str | None:
    pages, revisions = mapped()
    identified = material_identities(pages.evidence, None, revisions)
    found = carry_for(active, "p", [identity for identity, _ in identified])
    return found.digest if found is not None else None


def compile_carrying(repo: Path, root: Path, sent: list[str], active: Release | None,
                     **options: Any) -> bool:
    runs = compile_at(repo, root, sent, revision_page_source=lambda product: mapped(),
                      carry=CarryRequest(active), **options)
    return runs[0].reused


def test_an_output_records_the_carry_and_is_reused_only_for_the_same_quotes(
    repo: Path, tmp_path: Path,
) -> None:
    root, sent = tmp_path / "run", list[str]()
    first = released("等待期为90日。")
    assert not compile_carrying(repo, root, sent, first)
    stored = output_at(root)
    assert stored["carry_release"] == "rel-9"
    assert stored["carry_digest"] == expected_digest(first) is not None

    newer = released("等待期为90日。", release_id="rel-10")
    assert compile_carrying(repo, root, sent, newer), "same quotes from a newer release: reused"

    changed = released("阅读指引")
    assert not compile_carrying(repo, root, sent, changed), "other quotes: recompiled"
    assert output_at(root)["carry_digest"] == expected_digest(changed)
    assert len(sent) == 2


def test_without_a_carry_request_a_carried_output_stays_reusable(
    repo: Path, tmp_path: Path,
) -> None:
    root, sent = tmp_path / "run", list[str]()
    compile_carrying(repo, root, sent, released("等待期为90日。"))
    runs = compile_at(repo, root, sent, revision_page_source=lambda product: mapped())
    assert runs[0].reused
    assert len(sent) == 1


def test_outputs_written_before_carry_load_and_recompile_only_when_carry_is_due(
    repo: Path, tmp_path: Path,
) -> None:
    root, sent = tmp_path / "run", list[str]()
    compile_at(repo, root, sent, revision_page_source=lambda product: mapped())
    older = output_at(root)
    older.pop("carry_release", None)
    older.pop("carry_digest", None)
    save(root / "p/output.json", older)
    assert compile_carrying(repo, root, sent, None), "nothing to carry: the old output stands"
    assert not compile_carrying(repo, root, sent, released("等待期为90日。")), "carry is due"
    assert output_at(root)["carry_digest"] == expected_digest(released("等待期为90日。"))


def test_a_carry_request_needs_fixed_revisions(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        compile_at(repo, tmp_path / "run", [], carry=CarryRequest(released("等待期为90日。")))


def test_the_publication_orchestrator_compiles_with_carry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = two_products()
    commands = Commands(monkeypatch, current)
    publish_run(tmp_path, current, Active(set()))
    [argv] = commands.named("compile")
    assert "--carry-active" in argv

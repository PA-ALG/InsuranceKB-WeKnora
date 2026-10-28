"""S12c-4 acceptance (protected, written by Claude): publication planning treats an output as
current only on the carry the current Active gives it, reads Active at most once, and stops the
run when Active cannot be read (Spec docs/design/slices/S12c-4-复用已审证据段.md §2.4; Codex R2
on #412). The release id is provenance only: the same quotes from a newer release keep an output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.compilers.schema_fields.carry import carry_for
from insurance_harness.contracts.enums import ClaimState, LocatorKind, SourceClass
from insurance_harness.contracts.knowledge import Claim, Evidence, Locator, Provenance
from insurance_harness.ingest.publication import PublicationError, plan
from insurance_harness.ingest.registry import ProductRegistry
from tests.ingest.test_publication import (
    Active,
    Commands,
    digest,
    materials_of,
    publish_run,
    record_published,
    two_products,
    values,
    write_output,
)


class Reviewed(Active):
    """An Active release holding reviewed claims, or a read route that fails."""

    def __init__(self, release: Release | None = None, *, failing: bool = False) -> None:
        super().__init__(set())
        self.release, self.failing = release, failing

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.failing:
            return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
        if self.release is None:
            return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
        data = self.release.model_dump(mode="json")
        return httpx.Response(200, json={"success": True, "data": data})


def reviewed(current: ProductRegistry, product: str, text: str, *, release_id: str = "rel-1",
             ) -> Release:
    """A release whose present claim of `product` cites its registered terms material."""
    [material] = current.products[product].materials
    item = Claim(
        claim_id=f"{product}/waiting_period", logical_key=f"{product}/waiting_period",
        subject_ref=product, predicate="waiting_period", state=ClaimState.PRESENT, value="90日",
        evidence=[Evidence(
            source_ref=f"source:v1:{material.knowledge_id}:{material.parse_attempt}:"
                       f"{material.sha256}",
            file_sha256=material.sha256,
            locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=len(text)),
            quote=text, access_scope="space",
        )],
        origin=SourceClass.SOURCE_SUPPORTED,
        provenance=Provenance(compiler="schema_fields", compiler_version="cards", model="m"),
    )
    return Release(id=release_id, epoch=1, members=[ReleaseMember(
        kind="claim", logical_slug=item.logical_key,
        member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
        payload=item.model_dump(mode="json"),
    )])


def compiled_on(run: Path, current: ProductRegistry, product: str, active: Release | None) -> None:
    """An output compiled with the carry `active` gave it (None: compiled without carry)."""
    write_output(run / "compile", current, product)
    path = run / "compile" / product / "output.json"
    found = carry_for(active, product, materials_of(current, product)) if active else None
    stored = json.loads(path.read_text(encoding="utf-8"))
    if found is not None and found.digest is not None:
        stored.update(carry_release=found.release_id, carry_digest=found.digest)
    path.write_text(json.dumps(stored), encoding="utf-8")


def published_all(run: Path, *products: str) -> None:
    record_published(run, {product: digest(run / "compile", product) for product in products})


def test_a_published_output_compiled_on_other_reviewed_quotes_is_recompiled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    compiled_on(run, current, "1828", reviewed(current, "1828", "等待期为90日。"))
    published_all(run, "1828")
    commands = Commands(monkeypatch, current)
    active = Reviewed(reviewed(current, "1828", "等待期为180日。", release_id="rel-2"))
    report = publish_run(tmp_path, current, active, products=["1828"])
    assert (report.planned_compile, report.reused) == (["1828"], [])
    [argv] = commands.named("compile")
    assert values(argv, "--products") == ["1828"]


def test_an_output_compiled_without_carry_is_recompiled_once_carry_is_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    compiled_on(run, current, "1828", None)
    published_all(run, "1828")
    commands = Commands(monkeypatch, current)
    active = Reviewed(reviewed(current, "1828", "等待期为90日。"))
    dry = publish_run(tmp_path, current, active, dry_run=True, products=["1828"])
    assert (dry.planned_compile, dry.planned_publish) == (["1828"], ["1828"])
    assert commands.calls == [] and len(active.requests) == 1
    # The local planner judges carry against the Active its caller already read.
    assert plan(current, run, ["1828"]).compile == []
    assert plan(current, run, ["1828"], active=active.release).compile == ["1828"]


def test_the_same_quotes_from_a_newer_release_keep_outputs_and_active_is_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    compiled_on(run, current, "1828", reviewed(current, "1828", "等待期为90日。"))
    compiled_on(run, current, "1818", None)
    published_all(run, "1818", "1828")
    commands = Commands(monkeypatch, current)
    active = Reviewed(reviewed(current, "1828", "等待期为90日。", release_id="rel-7"))
    report = publish_run(tmp_path, current, active)
    assert (report.planned_compile, report.planned_publish) == ([], [])
    assert commands.calls == [] and len(active.requests) == 1


def test_an_unreadable_active_stops_the_run_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, run = two_products(), tmp_path / "run"
    seed = tmp_path / "seed"
    write_output(seed, current, "1818")
    compiled_on(run, current, "1828", None)
    commands, active = Commands(monkeypatch, current), Reviewed(failing=True)
    for dry_run in (True, False):
        with pytest.raises(PublicationError, match="^ACTIVE_UNAVAILABLE$"):
            publish_run(tmp_path, current, active, dry_run=dry_run, seed_from=[seed])
    assert commands.calls == [] and len(active.requests) == 2
    assert not (run / "compile" / "1818").exists() and not (run / "published.json").exists()

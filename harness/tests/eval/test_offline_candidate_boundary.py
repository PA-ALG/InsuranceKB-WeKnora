"""H1 r2 RED, Owner 6571973652: pure conversion is not permission to publish."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.bundle.assemble import BundleError, assemble
from insurance_harness.bundle.client import DecisionInput
from insurance_harness.catalog.navigation import load_navigation
from insurance_harness.catalog.spot_check import load_spot_check_policy
from insurance_harness.compilers.schema_fields import publish, publish_changes
from insurance_harness.compilers.schema_fields.claims import candidate_bundle, claims_from
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.page import product_page
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.judge_batch import JudgeBatchError, ingest, records
from insurance_harness.review.routing import HUMAN_DECISION
from tests.compilers.schema_fields.test_publish_cli import CATALOG, SOURCE
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import approve_all, prepared
from tests.ingest.test_judge_batch import publish as publish_judged
from tests.ingest.test_judge_batch import world as prepared_world  # noqa: F401


@pytest.fixture
def world(request: pytest.FixtureRequest) -> dict[str, Any]:
    value: dict[str, Any] = request.getfixturevalue("prepared_world")
    return value


def output(root: Path, *, offline: bool = True) -> CompileOutput:
    result = CompileOutput.model_validate_json((root / "1828/output.json").read_bytes())
    return result.model_copy(update={"model": "offline/synthetic"}) if offline else result


def offline_bundle(root: Path) -> CandidateBundle:
    claims = claims_from(output(root, offline=False), SOURCE,
                         {"保险条款.pdf": SourceRevision("k-1", 2)})
    return assemble([c.model_copy(update={
        "provenance": c.provenance.model_copy(update={"model": "offline/synthetic"}),
    }) for c in claims], compiler_identity="synthetic")


def test_offline_pure_conversion_still_checks_source_locators(world: dict[str, Any]) -> None:
    claims = claims_from(output(world["compile_root"]), SOURCE,
                         {"保险条款.pdf": SourceRevision("k-1", 2)})
    assert claims and all(c.evidence for c in claims)
    assert claims[0].provenance.model == "offline/synthetic"


def test_candidate_bundle_rejects_offline_source(world: dict[str, Any]) -> None:
    with pytest.raises(BundleError) as caught:
        candidate_bundle(output(world["compile_root"]), SOURCE,
                         {"保险条款.pdf": SourceRevision("k-1", 2)}, compiler_identity="synthetic")
    assert caught.value.reason == "ANSWERS_UNVERIFIED"


@pytest.mark.parametrize("command", [publish, publish_changes])
def test_both_publication_clis_reject_before_platform_or_report(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], command: Any,
) -> None:
    root = world["compile_root"]
    (root / "1828/output.json").write_text(output(root).model_dump_json())

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("offline source reached the platform")

    monkeypatch.setattr(command, "PlatformClient", forbidden)
    code = command.main(["--run-root", str(root), "--product", "1828", "--registry",
                         str(world["registry"]), "--repo", str(world["repo"])])
    result = json.loads(capsys.readouterr().out)
    assert code == 2
    assert "ANSWERS_UNVERIFIED" in {result.get("reason"), result.get("stopped")}
    assert not list(root.glob("**/change-review*.json"))


def test_delta_bundle_library_cannot_bypass_cli(world: dict[str, Any]) -> None:
    claims = claims_from(output(world["compile_root"], offline=False), SOURCE,
                         {"保险条款.pdf": SourceRevision("k-1", 2)})
    offline = tuple(c.model_copy(update={
        "provenance": c.provenance.model_copy(update={"model": "offline/synthetic"}),
    }) for c in claims)
    page = product_page(world["repo"] / CATALOG, "pack", entity_id="1828", name="合成产品")
    with pytest.raises(BundleError) as caught:
        publish_changes.delta_bundle(offline, (), None, page, load_navigation(),
                                     HUMAN_DECISION, None, "synthetic")
    assert caught.value.reason == "ANSWERS_UNVERIFIED"


def test_judge_preparation_rejects_offline_output(world: dict[str, Any]) -> None:
    root = world["compile_root"]
    (root / "1828/output.json").write_text(output(root).model_dump_json())
    with pytest.raises(JudgeBatchError) as caught:
        prepared(world)
    assert caught.value.code == "ANSWERS_UNVERIFIED"
    assert not [row for row in world["server"].seen if row[0] == "POST"]


def test_judge_publication_rechecks_source_before_build(world: dict[str, Any]) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    root = world["compile_root"]
    (root / "1828/output.json").write_text(output(root).model_dump_json())
    result = publish_judged(world, live=True)
    assert result["stopped"]["code"] == "ANSWERS_UNVERIFIED"
    assert not [row for row in world["server"].seen if row[0] == "POST"]


def test_judge_freeze_refuses_offline_members(world: dict[str, Any]) -> None:
    with pytest.raises(JudgeBatchError) as caught:
        records.start(world["run_root"], "1828", offline_bundle(world["compile_root"]), {},
                      DecisionInput(outcome="approve", mode="human", reason="synthetic"))
    assert caught.value.code == "ANSWERS_UNVERIFIED"
    assert not list(world["run_root"].glob("publish/**/*.json"))


def test_judge_recovery_refuses_offline_frozen_candidate(world: dict[str, Any]) -> None:
    bundle = assemble(claims_from(output(world["compile_root"], offline=False), SOURCE,
                                  {"保险条款.pdf": SourceRevision("k-1", 2)}),
                      compiler_identity="synthetic")
    record = records.start(world["run_root"], "1828", bundle, {},
                           DecisionInput(outcome="approve", mode="human", reason="synthetic"))
    files = list((world["run_root"] / "publish/1828").glob("*.bundle.json"))
    assert len(files) == 1
    raw = offline_bundle(world["compile_root"]).model_dump_json().encode()
    files[0].write_bytes(raw)
    record.bundle_sha256 = hashlib.sha256(raw).hexdigest()
    with pytest.raises(JudgeBatchError) as caught:
        records.advance(world["run_root"], record, client=world["client"], space_id="space-1",
                        policy=load_spot_check_policy(world["spot"]))
    assert caught.value.code == "ANSWERS_UNVERIFIED"
    assert not world["server"].seen

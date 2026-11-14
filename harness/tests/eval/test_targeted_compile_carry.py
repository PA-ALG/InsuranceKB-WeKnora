"""Public carry reads by indexed subject and pins every page read to its revision."""

import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import PlatformClient
from insurance_harness.compilers.schema_fields import carry
from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.eval import compile_run
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models import CallLedger, StageModelConfig
from tests.eval.test_compile_carry import released
from tests.eval.test_compile_registry_boundaries import argv, registry_file
from tests.eval.test_compile_run import CONFIG, TEXT, factory
from tests.eval.test_compile_run import repo as repo
from tests.ingest.test_judge_batch_recovery import ok
from tests.ingest.test_targeted_batch_publish import header, index


@pytest.mark.parametrize("scenario", ["alias", "new", "wrong-version"])
def test_targeted_carry_uses_fixed_claims_without_full_active(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "https://platform.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")

    full = released("等待期为90日。").model_dump(mode="json")
    claim = full["members"][0]
    claim["logical_slug"] = "historic/alias"
    claim["payload"]["subject_ref"] = "other" if scenario == "new" else "created"
    claim["payload"]["evidence"][0]["source_ref"] = "source:v1:a:7:" + "a" * 64
    claim["member_digest"] = member_digest(claim["payload"])
    queried: list[str] = []

    def route(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/spaces/space/")[1]
        queried.append(path)
        if path == "releases/active/summary":
            return ok(header(full))
        if path == "releases/rel-9/member-index":
            return ok(header(full) | {"members": [index(claim)]})
        assert path == "releases/rel-9/member-lookup"
        assert json.loads(request.content) == {"slugs": ["historic/alias"]}
        wrong = {"id": "other-release"} if scenario == "wrong-version" else {}
        return ok(header(full) | wrong | {"members": [claim], "missing": []})

    def platform(url: str, key: str) -> PlatformClient:
        return PlatformClient(url, key, httpx.MockTransport(route))

    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            assert attempt == (7 if knowledge == "a" else 2)
            digest = ("a" if knowledge == "a" else "b") * 64
            return [PageText(f"{knowledge}-保险条款.pdf", digest, 1, TEXT)]

    build, sent = factory(["m"] * 2)

    def model(config: StageModelConfig, *, ledger: CallLedger) -> CompletionPort:
        assert scenario != "wrong-version"
        return build(ledger)

    monkeypatch.setattr(carry, "PlatformClient", platform)
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    monkeypatch.setattr(compile_run, "reader_from_env", Reader)
    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", model)
    root = tmp_path / "run"
    args = argv(
        repo,
        root,
        "--registry",
        str(registry_file(tmp_path)),
        "--carry-active",
        "--targeted-release-reads",
    )
    assert compile_run.main(args) == (2 if scenario == "wrong-version" else 0)
    expected = ["releases/active/summary", "releases/rel-9/member-index"]
    if scenario != "new":
        expected.append("releases/rel-9/member-lookup")
    assert queried == expected
    if scenario == "wrong-version":
        assert sent == [] and not root.exists()
        assert json.loads(capsys.readouterr().out)["stopped"] == "RELEASE_MISMATCH"
    else:
        output = json.loads((root / "created/output.json").read_bytes())
        assert bool(output["carry_digest"]) == (scenario == "alias")
        assert len(sent) == 2

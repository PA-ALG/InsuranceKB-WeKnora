"""The public compile command reads reviewed evidence through the bounded release client."""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

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


class _ActiveBody(httpx.SyncByteStream):
    def __init__(self, encoded: bytes, padding_mib: int) -> None:
        self.encoded = encoded
        self.padding_mib = padding_mib

    def __iter__(self) -> Iterator[bytes]:
        yield self.encoded
        block = b" " * (1 << 20)
        for _ in range(self.padding_mib):
            yield block


@pytest.mark.parametrize(
    ("limit", "padding_mib", "exit_code"),
    [(None, 0, 0), (None, 32, 2), ("33", 32, 0), ("33", 33, 2)],
)
def test_compile_carry_uses_full_release_budget(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    limit: str | None,
    padding_mib: int,
    exit_code: int,
) -> None:
    setting = "HARNESS_WEKNORA_RELEASE_MAX_RESPONSE_MIB"
    if limit is None:
        monkeypatch.delenv(setting, raising=False)
    else:
        monkeypatch.setenv(setting, limit)
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "https://platform.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "test-key")

    release = released("等待期为90日。").model_dump(mode="json")
    payload = release["members"][0]["payload"]
    payload["subject_ref"] = "created"
    payload["evidence"][0]["source_ref"] = "source:v1:a:7:" + "a" * 64
    response = json.dumps({"success": True, "data": release}).encode()
    requests: list[tuple[str, str]] = []

    def active(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(200, stream=_ActiveBody(response, padding_mib))

    def platform(url: str, key: str) -> PlatformClient:
        return PlatformClient(url, key, httpx.MockTransport(active))

    pages: list[tuple[str, str, int]] = []

    class Reader:
        def pages(self, space: str, knowledge: str, attempt: int) -> list[PageText]:
            pages.append((space, knowledge, attempt))
            digest = ("a" if knowledge == "a" else "b") * 64
            return [PageText(f"{knowledge}-保险条款.pdf", digest, 1, TEXT)]

    build, sent = factory(["m"] * 2)

    def model(config: StageModelConfig, *, ledger: CallLedger) -> CompletionPort:
        assert exit_code == 0, "an oversized Active must stop before creating the model client"
        return build(ledger)

    monkeypatch.setattr(carry, "PlatformClient", platform)
    monkeypatch.setattr(compile_run, "load_stage_config", lambda *_: CONFIG)
    monkeypatch.setattr(compile_run, "reader_from_env", Reader)
    monkeypatch.setattr(compile_run, "OpenAICompatibleCompletion", model)
    root = tmp_path / "run"
    args = argv(repo, root, "--registry", str(registry_file(tmp_path)), "--carry-active")

    assert compile_run.main(args) == exit_code
    output = capsys.readouterr()
    assert output.err == ""
    assert requests == [("GET", "/api/v1/enterprise/spaces/space/releases/active")]
    report = json.loads(output.out)
    if exit_code == 2:
        assert report == {"stopped": "INVALID_RESPONSE", "products": []}
        assert pages == [] and sent == []
        assert not root.exists()
    else:
        assert pages == [("space", "a", 7), ("space", "z", 2)]
        assert report["sent"] == len(sent) == 2
        compiled = json.loads((root / "created/output.json").read_bytes())
        assert compiled["carry_release"] == "rel-9"
        assert compiled["carry_digest"]

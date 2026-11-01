"""S5b-9 acceptance, review #511 R1 (written by Claude): automatic results and unknown states.

Spec docs/design/slices/S5b-9-撤回后的问题重判.md §2.1–§2.2, through the real `uploads run` with a
fake platform. When the platform's items cannot be read, an older question takes no part in the run
— not even an automatic result is recorded. When the state is known, an automatic result is
recorded through the S5b-7 channel; when the item was withdrawn, the material is also reported as
judged again.
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.identity.attribution import Attribution
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import (
    PendingEntry,
    ProductEntry,
    ProductRegistry,
    load_registry,
    save_registry,
)
from insurance_harness.ingest.uploads import main
from tests.ingest.confirmation_platform import PREFIX, FakePlatform
from tests.ingest.confirmation_scenarios import BASE, run
from tests.ingest.upload_helpers import RAW_KB, SPACE, Pages

OLD = "attribution-policy@2026-10-31.1"
BROCHURE = RawSource(
    knowledge_id="k-bro", parse_attempt=1, file_name="产品说明书.pdf", sha256="e" * 64
)
# Settled automatically under the current policy: the title names the registered product.
HEAD = "平安e生保（悦享版）医疗保险产品说明书\r\n在本说明书中，“您”指投保人。\r\n一、产品基本特征"


def asked() -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1",
        space_id=SPACE,
        raw_kb_id=RAW_KB,
        products={
            "sc-esb": ProductEntry(
                names=["平安e生保（悦享版）医疗保险"],
                clause_codes=["平安人寿〔2025〕医疗保险201号"],
                schema_pack_id="schemapack_medical_insurance",
                origin="created",
                materials=[],
            ),
        },
        pending=[
            PendingEntry(
                knowledge_id=BROCHURE.knowledge_id,
                parse_attempt=BROCHURE.parse_attempt,
                sha256=BROCHURE.sha256,
                file_name=BROCHURE.file_name,
                attribution=Attribution.model_validate({
                    "policy_ref": OLD,
                    "outcome": "NEEDS_CONFIRM",
                    "reason": "brand_candidates",
                    "candidates": ("sc-esb",),
                }),
            )
        ],
        decisions=[],
    )


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", BASE)
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def platform() -> FakePlatform:
    return FakePlatform(uploads={BROCHURE.knowledge_id: (HEAD, BROCHURE.sha256)})


def pushed(fake: FakePlatform) -> str:
    """`uploads confirm` pushes the old question; its item id."""
    reader = Pages(heads={BROCHURE.knowledge_id: HEAD}, sources=[BROCHURE])
    run(asked(), fake, reader=reader)
    [item] = fake.find("material:k-bro")
    return str(item["id"])


def command(
    tmp_path: Path,
    fake: FakePlatform,
    confirmations: Callable[[httpx.Request], httpx.Response] | None = None,
) -> tuple[int, Path, list[str]]:
    path = tmp_path / "registry.json"
    save_registry(asked(), path)
    seen: list[str] = []
    listing = [{
        "id": BROCHURE.knowledge_id, "parse_status": "completed", "current_parse_attempt": 1,
        "file_name": BROCHURE.file_name, "file_sha256": BROCHURE.sha256,
    }]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == f"/api/v1/knowledge-bases/{RAW_KB}/knowledge":
            return httpx.Response(200, json={"success": True, "data": listing, "total": 1})
        if request.url.path == PREFIX and confirmations is not None:
            return confirmations(request)
        return fake.handle(request)

    code = main(["run", "--registry", str(path)], transport=httpx.MockTransport(handler))
    return code, path, seen


def report_of(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return dict(json.loads(capsys.readouterr().out))


def attached(path: Path) -> list[str]:
    return [m.knowledge_id for m in load_registry(path).products["sc-esb"].materials]


def refused(_: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})


def malformed(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": {"items": "not-a-list"}})


@pytest.mark.parametrize("confirmations", [refused, malformed], ids=["503", "malformed"])
def test_an_unknown_state_keeps_the_question_even_when_the_policy_settles_it(
    tmp_path: Path,
    environment: None,
    capsys: pytest.CaptureFixture[str],
    confirmations: Callable[[httpx.Request], httpx.Response],
) -> None:
    fake = platform()
    path = tmp_path / "registry.json"
    save_registry(asked(), path)
    before = path.read_bytes()
    code, path, seen = command(tmp_path, fake, confirmations)
    report = report_of(capsys)
    assert code == 0
    assert path.read_bytes() == before, "nothing recorded, the question kept as asked"
    assert report["question_state_unknown"] == ["k-bro"]
    assert report["counts"] == {} and report["withdrawn_rejudged"] == []
    assert not any("/sources/k-bro/" in p for p in seen), "not even judged"


@pytest.mark.parametrize("state", ["never_pushed", "open", "answered", "applied"])
def test_a_known_state_records_an_automatic_result_through_the_s5b7_channel(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    fake = platform()
    if state != "never_pushed":
        item_id = pushed(fake)
        if state in {"answered", "applied"}:
            answer = fake.answer(item_id, fake.view(item_id)["options"][0]["key"])
        if state == "applied":
            PlatformClient(BASE, "key", transport=fake.transport()).close_confirmation(
                SPACE, item_id, "applied", answer
            )
    code, path, _ = command(tmp_path, fake)
    report = report_of(capsys)
    assert code == 0 and attached(path) == ["k-bro"]
    assert report["counts"] == {"SUPPLEMENT": 1}
    assert (report["withdrawn_rejudged"], report["question_state_unknown"]) == ([], [])
    assert all(d.confirmation is None for d in load_registry(path).decisions)


def test_a_withdrawn_question_settled_automatically_is_reported_as_judged_again(
    tmp_path: Path, environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = platform()
    item_id = pushed(fake)
    fake.answer(item_id, fake.view(item_id)["options"][0]["key"])
    PlatformClient(BASE, "key", transport=fake.transport()).close_confirmation(
        SPACE, item_id, "obsolete"
    )
    code, path, _ = command(tmp_path, fake)
    report = report_of(capsys)
    assert code == 0 and attached(path) == ["k-bro"]
    assert report["withdrawn_rejudged"] == ["k-bro"]
    assert all(d.confirmation is None for d in load_registry(path).decisions)

"""The publish command: compile output + the same WeKnora pages -> submitted, decided, activated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.compilers.schema_fields import publish as command
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.ingest import source_map as source_map_module

SHA = "ab" * 32
COMPILED_WITH = "draft-compiled"
SECRET = "SECRET-MARKER-保险条款原文"
PAGES = [
    PageText(
        "保险条款.pdf",
        SHA,
        1,
        "1.4 等待期\n自本合同生效之日起90日内为等待期。\n本合同不设宽限期。\n",
    )
]
SOURCE = SegmentedSource(PAGES)


class Reader:
    def __init__(self, base_url: str, api_key: str) -> None:
        assert (base_url, api_key) == ("https://weknora.test", "key-123")

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        assert (space_id, knowledge_id, attempt) == ("space-1", "k-1", 2)
        return PAGES


class Platform:
    """Records requests; activation publishes exactly the members that were submitted."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, Any]] = []
        self.members: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.removeprefix("/api/v1/enterprise/spaces/space-1/")
        self.seen.append((request.method, path, body))
        if path == "releases/active":
            return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
        if path == "candidates":
            assert isinstance(body, dict)
            self.members = body["members"]
            return ok({"id": "cand_1", "status": "created"}, 201)
        if path == "candidates/cand_1/decisions":
            return ok(
                {"id": "dec_1", "candidate_id": "cand_1", "outcome": "approve", "digest": "e" * 64}
            )
        release = {"id": "rel_1", "epoch": 1, "candidate_id": "cand_1", "members": self.members}
        return ok(release)


def ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


@pytest.fixture
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Platform:
    fields = [
        FieldResult(
            field_key="waiting_period",
            state="present",
            value="90日",
            evidence=SOURCE.evidence(["D1P1S1"]),
            segment_ids=["D1P1S1"],
        ),
        FieldResult(
            field_key="premium_grace_period",
            state="absent_explicitly",
            evidence=SOURCE.evidence(["D1P1S2"]),
            segment_ids=["D1P1S2"],
        ),
    ]
    output = CompileOutput(
        pack_id="pack",
        entity_id="1828",
        model="deepseek-flash",
        fields=fields,
        cards_version=COMPILED_WITH,
    )
    (tmp_path / "1828").mkdir()
    (tmp_path / "1828" / "output.json").write_text(output.model_dump_json(), encoding="utf-8")
    (tmp_path / "map.json").write_text(
        json.dumps(
            {
                "space_id": "space-1",
                "products": {"1828": [{"knowledge_id": "k-1", "parse_attempt": 2}]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(source_map_module.BASE_URL_ENV, "https://weknora.test")
    monkeypatch.setenv(source_map_module.API_KEY_ENV, "key-123")
    monkeypatch.setattr(source_map_module, "WeKnoraSourcePages", Reader)
    server = Platform()
    monkeypatch.setattr(
        command,
        "PlatformClient",
        lambda base, key: PlatformClient(base, key, transport=httpx.MockTransport(server)),
    )
    return server


def test_publish_submits_decides_and_activates(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    code = command.main(
        [
            "--run-root",
            str(tmp_path),
            "--product",
            "1828",
            "--source-map",
            str(tmp_path / "map.json"),
            "--decide",
            "human",
            "--reason",
            "spot-checked",
            "--activate",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert code == 0
    assert summary == {
        "product": "1828",
        "space_id": "space-1",
        "cards_version": COMPILED_WITH,
        "members": 2,
        "candidate_id": "cand_1",
        "candidate_status": "created",
        "decision_id": "dec_1",
        "release_id": "rel_1",
        "epoch": 1,
    }
    assert [(method, path) for method, path, _ in platform.seen] == [
        ("GET", "releases/active"),
        ("POST", "candidates"),
        ("POST", "candidates/cand_1/decisions"),
        ("POST", "candidates/cand_1/activations"),
        ("GET", "releases/rel_1"),
    ]
    submitted = platform.seen[1][2]
    assert submitted["base_release_id"] is None
    assert {m["logical_slug"] for m in submitted["members"]} == {
        "1828/waiting_period",
        "1828/premium_grace_period",
    }
    assert all(m["evidence_refs"] == [f"source:v1:k-1:2:{SHA}"] for m in submitted["members"])
    assert platform.seen[2][2] == {"outcome": "approve", "mode": "human", "reason": "spot-checked"}


def test_without_a_decision_only_the_candidate_is_submitted(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    code = command.main(
        [
            "--run-root",
            str(tmp_path),
            "--product",
            "1828",
            "--source-map",
            str(tmp_path / "map.json"),
        ]
    )
    assert code == 0 and json.loads(capsys.readouterr().out)["release_id"] is None
    assert [path for _, path, _ in platform.seen] == ["releases/active", "candidates"]


@pytest.mark.parametrize(
    ("extra", "stopped"),
    [
        (["--activate"], "INVALID_REQUEST"),
        (["--decide", "human"], "INVALID_ARGUMENTS"),
        (["--decide", "machine", "--reason", "x"], "INVALID_ARGUMENTS"),
    ],
)
def test_invalid_decisions_stop_before_anything_is_sent(
    tmp_path: Path,
    platform: Platform,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    stopped: str,
) -> None:
    argv = [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--source-map",
        str(tmp_path / "map.json"),
        *extra,
    ]
    assert command.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["stopped"] == stopped
    assert platform.seen == []


def argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--source-map",
        str(tmp_path / "map.json"),
        *extra,
    ]


def test_the_card_version_is_the_one_the_output_was_compiled_with(
    tmp_path: Path,
    platform: Platform,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cards updated after compiling must not relabel the old output (PR #169 review item 1)."""
    from insurance_harness.compilers.schema_fields import cards

    monkeypatch.setattr(cards, "cards_version", lambda: "draft-updated-since")
    assert command.main(argv(tmp_path)) == 0
    submitted = platform.seen[1][2]
    assert submitted["compiler_identity"] == f"harness/schema_fields@{COMPILED_WITH}"
    assert {m["payload"]["provenance"]["compiler_version"] for m in submitted["members"]} == {
        COMPILED_WITH
    }
    assert json.loads(capsys.readouterr().out)["cards_version"] == COMPILED_WITH


def test_an_output_without_a_card_version_is_not_published(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "1828" / "output.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    del stored["cards_version"]
    path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    assert command.main(argv(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "CARDS_VERSION_UNKNOWN"}
    assert platform.seen == []


@pytest.mark.parametrize("broken", ["missing output", "invalid output", "invalid map"])
def test_failures_print_codes_without_paths_or_input(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str], broken: str
) -> None:
    """PR #169 review item 2: no local path, exception text or input content leaves the command."""
    output = tmp_path / "1828" / "output.json"
    if broken == "missing output":
        output.unlink()
    elif broken == "invalid output":
        output.write_text(json.dumps({"entity_id": "1828", "model": SECRET}), encoding="utf-8")
    else:
        (tmp_path / "map.json").write_text(
            json.dumps({"space_id": SECRET, "products": {}}), encoding="utf-8"
        )
    assert command.main(argv(tmp_path)) == 2
    captured = capsys.readouterr()
    expected = "SOURCE_MAP_INVALID" if broken == "invalid map" else "OUTPUT_UNREADABLE"
    assert json.loads(captured.out) == {"stopped": expected}
    for text in (captured.out, captured.err):
        assert str(tmp_path) not in text and "SECRET-MARKER" not in text


def rewrite_output(
    tmp_path: Path, change: dict[str, Any] | None = None, field: dict[str, Any] | None = None
) -> None:
    path = tmp_path / "1828" / "output.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored.update(change or {})
    if field is not None:
        stored["fields"][0].update(field)
    path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")


def test_a_blank_card_version_is_refused_before_any_request(
    tmp_path: Path, platform: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    rewrite_output(tmp_path, {"cards_version": "   "})
    assert command.main(argv(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "CARDS_VERSION_UNKNOWN"}
    assert platform.seen == []


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ({"field_key": SECRET, "value": None}, "CLAIM_INVALID"),
        ({"field_key": SECRET, "segment_ids": ["D9P9S9"]}, "EVIDENCE_MISMATCH"),
    ],
)
def test_conversion_failures_print_a_position_not_the_input(
    tmp_path: Path,
    platform: Platform,
    capsys: pytest.CaptureFixture[str],
    field: dict[str, Any],
    reason: str,
) -> None:
    rewrite_output(tmp_path, field=field)
    assert command.main(argv(tmp_path)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "stopped": "BUNDLE_INVALID",
        "reason": reason,
        "field_index": 0,
    }
    for text in (captured.out, captured.err):
        assert "SECRET-MARKER" not in text and str(tmp_path) not in text and "Traceback" not in text

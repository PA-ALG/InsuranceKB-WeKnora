"""S2b acceptance: file-exchange judge (blueprint 1001 §7.7). Protected file: written by Claude.

The judge is a separate Codex session (GPT-6.1 sol), not an API. `prepare` writes each blind
prompt to a request file; the judge session writes the answer to the matching response file;
`ingest` rebuilds the same prompts and replays them through JudgeAnnotator, so parsing,
evidence verification and the three-state rules are identical to any other judge client.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.judge import (
    AnnotationResult,
    JudgeAnnotator,
    JudgeProtocolError,
    JudgeRequest,
)
from insurance_harness.eval.judge_files import FileJudgeClient, write_requests
from insurance_harness.eval.pdf_text import PageText

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / "internal/handler/schema_pack_catalog_830_g3.generated.json"
PACK = "schemapack_medical_insurance"
SHA = "c" * 64
PAGES = [PageText(document="保险条款.pdf", document_sha256=SHA, page=3, text="等待期为90日。")]
CHANGED = [PageText(document="保险条款.pdf", document_sha256=SHA, page=3, text="等待期为180日。")]
FIELDS = ["waiting_period"]
ANSWER = json.dumps(
    {
        "fields": [
            {
                "field_key": "waiting_period",
                "state": "present",
                "value": "90日",
                "components": [],
                "evidence": [{"document": "保险条款.pdf", "page": 3, "quote": "等待期为90日"}],
            }
        ]
    },
    ensure_ascii=False,
)


class NoCallJudge:
    """Only used to build prompts; any call is a test failure."""

    @property
    def model_id(self) -> str:
        return "unused"

    def complete(self, request: JudgeRequest) -> str:
        raise AssertionError("building requests must not call the judge")


def prompts(
    fields: Sequence[str] = FIELDS, pages: Sequence[PageText] = PAGES, batch_size: int = 10
) -> list[JudgeRequest]:
    builder = JudgeAnnotator(
        NoCallJudge(), load_catalog(CATALOG), max_calls=5, batch_size=batch_size
    )
    return builder.build_requests("596", PACK, list(fields), pages)


def answer_all(run_dir: Path) -> None:
    for path in sorted((run_dir / "requests").glob("*.json")):
        (run_dir / "responses" / path.name).write_text(ANSWER, encoding="utf-8")


def ingest(
    run_dir: Path, pages: Sequence[PageText] = PAGES
) -> tuple[AnnotationResult, FileJudgeClient]:
    client = FileJudgeClient(run_dir, model_id="gpt-6.1-sol")
    annotator = JudgeAnnotator(client, load_catalog(CATALOG), max_calls=5, batch_size=10)
    return annotator.annotate("596", PACK, FIELDS, pages), client


# ---- prepare ----------------------------------------------------------------------------------


def test_request_files_carry_the_exact_prompt_and_its_hash(tmp_path: Path) -> None:
    requests = prompts()
    paths = write_requests(requests, tmp_path)
    assert paths == [tmp_path / "requests" / "001.json"]
    assert (tmp_path / "responses").is_dir()
    stored = json.loads(paths[0].read_text(encoding="utf-8"))
    assert stored["request_sha256"] == requests[0].sha256
    assert "\n".join(stored["system_lines"]) == requests[0].system
    assert "\n".join(stored["user_lines"]) == requests[0].user
    assert "[page 3]" in stored["user_lines"]  # page markers sit on their own line for grep
    for word in ("prediction", "candidate", "epoch"):
        assert word not in requests[0].user.lower()


def test_request_hash_is_deterministic() -> None:
    assert prompts()[0].sha256 == prompts()[0].sha256
    assert prompts(pages=CHANGED)[0].sha256 != prompts()[0].sha256


def test_request_files_are_not_overwritten(tmp_path: Path) -> None:
    write_requests(prompts(), tmp_path)
    with pytest.raises(FileExistsError):
        write_requests(prompts(), tmp_path)


def test_run_dir_inside_a_git_repository_is_refused(tmp_path: Path) -> None:
    # A judge session opened inside a repo can see Golden, candidates and AGENTS.md: not blind.
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="git"):
        write_requests(prompts(), tmp_path / "judge-run")


# ---- ingest -----------------------------------------------------------------------------------


def test_ingest_replays_prompts_and_records_the_judge_model(tmp_path: Path) -> None:
    write_requests(prompts(), tmp_path)
    answer_all(tmp_path)
    result, client = ingest(tmp_path)
    assert [i.judged_by for i in result.items] == ["model:gpt-6.1-sol"]
    assert result.model_id == "gpt-6.1-sol"
    assert result.calls == 1
    assert client.unconsumed() == []


def test_missing_response_names_the_request_file(tmp_path: Path) -> None:
    write_requests(prompts(), tmp_path)
    with pytest.raises(JudgeProtocolError, match="001"):
        ingest(tmp_path)


def test_prompt_changed_since_prepare_is_rejected(tmp_path: Path) -> None:
    write_requests(prompts(), tmp_path)
    answer_all(tmp_path)
    with pytest.raises(JudgeProtocolError, match="changed"):
        ingest(tmp_path, CHANGED)


def test_edited_request_file_is_rejected(tmp_path: Path) -> None:
    (path,) = write_requests(prompts(), tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["user_lines"] = [line.replace("90日", "180日") for line in stored["user_lines"]]
    path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    answer_all(tmp_path)
    with pytest.raises(JudgeProtocolError, match="changed"):
        ingest(tmp_path)


def test_unconsumed_request_files_are_reported(tmp_path: Path) -> None:
    write_requests(prompts(["waiting_period", "deductible_rules"], batch_size=1), tmp_path)
    answer_all(tmp_path)
    _, client = ingest(tmp_path)  # replays only the waiting_period batch
    assert client.unconsumed() == ["002"]

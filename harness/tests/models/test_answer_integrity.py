"""H1 frozen RED: common SK-2c safety remains effective after it moves below compilers."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from insurance_harness.compilers.methods.responses import (
    ResponsesError,
    SavedResponses,
    check_value_directory,
)
from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest
from insurance_harness.models import CallLedger, OpenAICompatibleCompletion, TruncatedCompletion
from tests.eval.test_compile_run import CONFIG


@pytest.mark.parametrize("entry", ["answer", "raw", "root"])
def test_saved_path_links_are_refused(tmp_path: Path, entry: str) -> None:
    root, outside = tmp_path / "run", tmp_path / "outside"
    outside.mkdir()
    if entry == "root":
        root.symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir()
        (outside / "answer.txt").write_text("safe")
        if entry == "raw":
            (root / "raw").symlink_to(outside, target_is_directory=True)
        else:
            (root / "answer.txt").symlink_to(outside / "answer.txt")
    with pytest.raises(ResponsesError):
        check_value_directory(root)


def test_fifo_saved_answer_fails_without_waiting_for_a_writer(tmp_path: Path) -> None:
    request = JudgeLikeRequest(system="s", user="u")
    os.mkfifo(tmp_path / f"{request.sha256}.txt")
    code = """
from pathlib import Path
import sys
from insurance_harness.compilers.methods.responses import SavedResponses, ResponsesError
try:
    SavedResponses(Path(sys.argv[1]), 'm').complete(system='s', user='u')
except ResponsesError as exc:
    assert exc.code == 'RUN_ROOT_INVALID'
    print('refused')
else:
    raise AssertionError('FIFO accepted')
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True,
                            text=True, timeout=5, check=True)
    assert result.stdout.strip() == "refused"


def test_plain_saved_answers_remain_explicitly_offline(tmp_path: Path) -> None:
    request = JudgeLikeRequest(system="s", user="u")
    (tmp_path / f"{request.sha256}.txt").write_text("中文原文")
    assert SavedResponses(tmp_path, "offline-model").complete(system="s", user="u") == "中文原文"


def test_adapter_records_exact_bytes_and_keep_sees_truncation() -> None:
    kept: list[str] = []
    ledger = CallLedger(max_sent=2)
    finishes = iter(["stop", "length"])

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "served-v1", "choices": [{
            "message": {"content": "中文\r\n原文"}, "finish_reason": next(finishes),
        }]})

    client = OpenAICompatibleCompletion(CONFIG, ledger=ledger, keep=kept.append,
                                        environ={"TEST_KEY": "k"},
                                        transport=httpx.MockTransport(respond))
    try:
        assert client.complete(system="s", user="u") == "中文\r\n原文"
        with pytest.raises(TruncatedCompletion):
            client.complete(system="s", user="u")
    finally:
        client.close()
    assert kept == ["中文\r\n原文"] * 2
    assert ledger.records[0].response_sha256 == hashlib.sha256(kept[0].encode()).hexdigest()
    assert ledger.sent == 2

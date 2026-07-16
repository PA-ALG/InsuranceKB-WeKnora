#!/usr/bin/env python3
"""Explicit controller entrypoint for one trusted exact-SHA GitHub live run."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TextIO

from insurance_harness.live_env.compose import read_runtime_environment
from insurance_harness.live_env.github_backend import ConcreteLiveBackend
from insurance_harness.live_env.github_live import (
    LiveRunRequest,
    PersistentLiveState,
    RunnerPackageLock,
    run_github_live,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHA = re.compile(r"[0-9a-f]{40}")
_NONCE = re.compile(r"[0-9a-f]{16}")


class GitHubLiveAdapter(Protocol):
    def run(self, request: LiveRunRequest) -> object: ...


class DefaultGitHubLiveAdapter:
    def run(self, request: LiveRunRequest) -> object:
        runtime_path = REPO_ROOT / ".env.local-live.runtime"
        runtime = read_runtime_environment(runtime_path)
        state = PersistentLiveState(
            base_url="http://app:8080",
            space_id=runtime["LOCAL_LIVE_SPACE_ID"],
            knowledge_id=runtime["LOCAL_LIVE_KNOWLEDGE_ID"],
            parser_fingerprint=runtime["LOCAL_LIVE_PARSER_FINGERPRINT"],
            kb_id=runtime["LOCAL_LIVE_WIKI_KB_ID"],
        )
        lock = RunnerPackageLock.load(
            REPO_ROOT / "deploy/local-live/runner/runner.lock"
        )
        result = run_github_live(
            ConcreteLiveBackend(
                repo_root=REPO_ROOT,
                runtime_path=runtime_path,
            ),
            request=request,
            state=state,
            lock=lock,
        )
        return {
            "status": "passed",
            "url": result.url,
            "conclusion": result.conclusion,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the trusted GitHub live gate")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--runner-nonce", required=True)
    parser.add_argument("--confirm-dispatch", action="store_true")
    return parser


def main(
    arguments: Sequence[str] | None = None,
    *,
    adapter: GitHubLiveAdapter | None = None,
    output: TextIO | None = None,
    error: TextIO | None = None,
) -> int:
    output_stream = sys.stdout if output is None else output
    error_stream = sys.stderr if error is None else error
    namespace = _parser().parse_args(arguments)
    if not namespace.confirm_dispatch:
        print("github-live: explicit confirmation required", file=error_stream)
        return 2
    if (
        namespace.pr_number <= 0
        or _SHA.fullmatch(namespace.head_sha) is None
        or _NONCE.fullmatch(namespace.runner_nonce) is None
    ):
        print("github-live: invalid exact-SHA request", file=error_stream)
        return 2
    request = LiveRunRequest(
        repository="PA-ALG/InsuranceKB-WeKnora",
        pr_number=namespace.pr_number,
        head_sha=namespace.head_sha,
        nonce=namespace.runner_nonce,
    )
    selected = DefaultGitHubLiveAdapter() if adapter is None else adapter
    try:
        result = selected.run(request)
    except BaseException as failure:
        cleanup_notes = tuple(getattr(failure, "__notes__", ()))
        if cleanup_notes:
            print("github-live: run failed; cleanup incomplete", file=error_stream)
        else:
            print("github-live: run failed", file=error_stream)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=output_stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

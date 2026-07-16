"""Run the frozen five-node local gate with a minimal derived environment."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

from insurance_harness.live_env.compose import read_runtime_environment


class GateRequest(Protocol):
    phase: str


class GateRunner(Protocol):
    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


def _run_gate(
    arguments: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
    )


def _live_values(runtime: Mapping[str, str]) -> dict[str, str]:
    password = quote_plus(runtime["HARNESS_POSTGRES_PASSWORD"])
    return {
        "HARNESS_LIVE_API_KEY": runtime["LOCAL_LIVE_API_KEY"],
        "HARNESS_LIVE_DB_URL": (
            "postgresql+psycopg://harness:"
            f"{password}@127.0.0.1:5442/insurance_kb"
        ),
        "HARNESS_LIVE_BASE_URL": "http://127.0.0.1:8080",
        "HARNESS_LIVE_SPACE_ID": runtime["LOCAL_LIVE_SPACE_ID"],
        "HARNESS_LIVE_KNOWLEDGE_ID": runtime["LOCAL_LIVE_KNOWLEDGE_ID"],
        "HARNESS_LIVE_PARSER_FINGERPRINT": runtime[
            "LOCAL_LIVE_PARSER_FINGERPRINT"
        ],
        "HARNESS_LIVE_KB_ID": runtime["LOCAL_LIVE_WIKI_KB_ID"],
    }


def _clean_environment() -> dict[str, str]:
    forbidden_prefixes = (
        "HARNESS_LIVE_",
        "HARNESS_LLM_",
        "LOCAL_LIVE_",
        "WEKNORA_ADMIN_",
    )
    forbidden_names = {
        "DB_PASSWORD",
        "HARNESS_POSTGRES_PASSWORD",
        "JWT_SECRET",
        "REDIS_PASSWORD",
        "SYSTEM_AES_KEY",
    }
    return {
        name: value
        for name, value in os.environ.items()
        if name not in forbidden_names
        and not any(name.startswith(prefix) for prefix in forbidden_prefixes)
    }


class LocalGateCollaborator:
    """Inject exactly seven live values into the trusted frozen gate."""

    def __init__(
        self,
        *,
        harness_root: Path,
        runtime_path: Path,
        runner: GateRunner | None = None,
    ) -> None:
        self._harness_root = harness_root
        self._runtime_path = runtime_path
        self._runner = _run_gate if runner is None else runner

    def run(self, request: GateRequest) -> object:
        if request.phase != "run-local":
            raise ValueError("unsupported local gate phase")
        runtime = read_runtime_environment(self._runtime_path)
        environment = _clean_environment()
        environment.update(_live_values(runtime))
        result = self._runner(
            (
                sys.executable,
                "scripts/run_live_gate.py",
                "--manifest",
                "live-nodes.txt",
                "--report",
                "reports/local-live.xml",
            ),
            cwd=self._harness_root,
            environment=environment,
        )
        if result.returncode != 0:
            raise RuntimeError("local five-node live gate failed")
        return {"status": "passed", "tests": 5}

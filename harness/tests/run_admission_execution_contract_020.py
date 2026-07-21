"""Typed test contract for OpenSpec 020 D1.5 execution artifacts.

The production implementation deliberately lives behind a versioned module instead of
private helpers in ``run_020``.  Keeping discovery here gives TDD one precise module RED
while allowing every semantic test to describe an independent invariant once that public
boundary exists.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from importlib import import_module, util
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest

from insurance_harness.compiler.pipeline import RunResult
from insurance_harness.goldenset.admission_artifacts import CanaryArtifactBundle
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import GoldenRecord

EXECUTION_ARTIFACT_MODULE = (
    "insurance_harness.goldenset.execution_artifacts_020"
)

type PageLoader = Callable[[str, bytes], list[PageText]]
type InstalledVersion = Callable[[str], str]


class ExecutionArtifacts020(Protocol):
    """Public D1.5 behavior; concrete schema types remain production-owned."""

    def render_annotation_artifacts(
        self,
        *,
        document: object,
        configuration: object,
        product_id: str,
        records: Sequence[GoldenRecord],
        cache_dir: Path,
        page_loader: PageLoader,
        started_at: datetime,
        finished_at: datetime,
        execution_plan_hash: str,
    ) -> CanaryArtifactBundle: ...

    def directory_parser_fingerprint(
        self,
        *,
        document: object,
        configuration: object,
        installed_version: InstalledVersion,
    ) -> str: ...

    def validate_annotation_bundle(
        self,
        *,
        document: object,
        configuration: object,
        product_id: str,
        bundle: CanaryArtifactBundle,
        cache_dir: Path,
        page_loader: PageLoader,
        execution_plan_hash: str,
    ) -> CanaryArtifactBundle: ...

    def validate_baseline_result(
        self,
        *,
        result: RunResult,
        run_root: Path,
        expected_source_root: Path,
        expected_product_dir: Path,
        expected_run_id: str,
        expected_run_dir: Path,
        expected_product_id: str,
        expected_product_name: str,
        expected_line_key: str,
        expected_schema_version: str,
        expected_model_id: str,
        expected_judge_mode: str,
    ) -> RunResult: ...


def execution_artifact_module_exists() -> bool:
    return util.find_spec(EXECUTION_ARTIFACT_MODULE) is not None


def execution_artifacts_or_skip() -> tuple[ExecutionArtifacts020, ModuleType]:
    if not execution_artifact_module_exists():
        pytest.skip("D1.5 versioned execution-artifact module is the current RED")
    module = import_module(EXECUTION_ARTIFACT_MODULE)
    return cast(ExecutionArtifacts020, module), module

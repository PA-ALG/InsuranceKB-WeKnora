"""S5b-5 acceptance (protected, written by Claude): the publication report names the candidates it
left for people (Spec docs/design/slices/S5b-5-按真实条款格式识别产品.md §2a), so the review queue
(RV5) can find them. Reuses the fakes of test_publication.
"""

import json
from pathlib import Path

import pytest

from insurance_harness.ingest.registry import ProductRegistry
from tests.ingest.test_publication import Active, Commands, publish_run, two_products


class CandidateCommands(Commands):
    """Publishing prints the candidate it submitted, as the real commands do."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, current: ProductRegistry, missing: set[str]
    ) -> None:
        super().__init__(monkeypatch, current)
        self.missing = missing

    def publish(self, kind: str, argv: list[str]) -> int:
        product = argv[argv.index("--product") + 1]
        if "--dry-run" in argv:
            return super().publish(kind, argv)
        self.calls.append((kind, argv))
        summary: dict[str, object] = {
            "product": product,
            "review": self.routes.get(product, "human"),
        }
        if product not in self.missing:
            summary["candidate_id"] = f"cand_{product}"
        print(json.dumps(summary))
        return 0


def test_human_routed_products_report_their_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    commands = CandidateCommands(monkeypatch, current, missing=set())
    commands.routes = {"1818": "human", "1828": "machine"}
    report = publish_run(tmp_path, current, Active(set()))
    assert report.routes == {"1818": "human", "1828": "machine"}
    assert report.candidates == {"1818": "cand_1818"}


def test_a_missing_candidate_id_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    commands = CandidateCommands(monkeypatch, current, missing={"1818"})
    commands.routes = {"1818": "human", "1828": "human"}
    report = publish_run(tmp_path, current, Active(set()))
    assert report.candidates == {"1828": "cand_1828"}
    assert report.failed == {}
    assert set(report.routes) == {"1818", "1828"}

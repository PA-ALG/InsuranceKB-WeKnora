"""S12c-1 acceptance (protected, written by Claude): the evaluation compile path reuses only an
output of the current value protocol (Spec docs/design/slices/S12c-1-取值协议v2.md §4).
Offline; reuses the S8a compile fixtures."""

from pathlib import Path

from insurance_harness.compilers.schema_fields.prompt import VALUE_PROTOCOL_VERSION
from tests.eval.test_compile_materials import compile_at, output_at, repo, save

__all__ = ["repo"]  # the fixture is imported for pytest


def test_an_output_of_an_older_value_protocol_recompiles(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "run"
    sent: list[str] = []
    compile_at(repo, root, sent)
    assert output_at(root)["value_protocol"] == VALUE_PROTOCOL_VERSION
    assert compile_at(repo, root, sent)[0].reused
    for older in (None, "2026-10-01.0"):
        previous = output_at(root)
        previous["value_protocol"] = older
        save(root / "p/output.json", previous)
        assert not compile_at(repo, root, sent)[0].reused
        assert output_at(root)["value_protocol"] == VALUE_PROTOCOL_VERSION
    assert len(sent) == 3

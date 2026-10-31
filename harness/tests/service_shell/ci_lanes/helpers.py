"""CI lane and zero-skip evidence contracts: shared paths and workflow parsers."""

from collections.abc import Mapping
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
HARNESS_ROOT = REPO_ROOT / "harness"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-ci.yml"


def _workflow(path: Path) -> Mapping[str, object]:
    document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return value


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _named_step(job: Mapping[str, object], name: str) -> Mapping[str, object]:
    steps = job["steps"]
    assert isinstance(steps, list)
    for step in steps:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    raise AssertionError(f"workflow step is missing: {name}")


def _level_two_section(document: str, title: str) -> str:
    lines = document.splitlines()
    start = lines.index(f"## {title}") + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])

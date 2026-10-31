"""CI lanes: the single documented default gate and its parser."""

import shlex

import pytest

from tests.service_shell.ci_lanes.helpers import (
    CI_WORKFLOW,
    REPO_ROOT,
    _mapping,
    _named_step,
    _string,
    _workflow,
)


def _bash_blocks(section: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for line in section.splitlines():
        if line == "```bash":
            assert current is None
            current = []
        elif line == "```" and current is not None:
            blocks.append("\n".join(current))
            current = None
        elif current is not None:
            current.append(line)
    assert current is None
    return blocks


def _shell_segments(script: str) -> list[list[str]]:
    segments: list[list[str]] = []
    for line in script.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars="&|;")
        lexer.whitespace_split = True
        current: list[str] = []
        for token in lexer:
            if token in {"&&", "||", ";"}:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
    return segments


def _pytest_commands(section: str) -> list[list[str]]:
    return [
        segment
        for block in _bash_blocks(section)
        for segment in _shell_segments(block)
        if "pytest" in segment
    ]


def _prose_text(section: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in section.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            lines.append(line)
    return " ".join(" ".join(lines).split())


def _terms_in_order(text: str, *terms: str) -> bool:
    offset = 0
    for term in terms:
        position = text.find(term, offset)
        if position < 0:
            return False
        offset = position + len(term)
    return True


def test_rh6_1_claude_points_to_single_authority_and_ci_defaults_deterministic() -> None:
    # Since PR #1 CLAUDE.md only imports AGENTS.md (the single authority).
    document = (REPO_ROOT / "CLAUDE.md").read_text()
    assert _pytest_commands(document) == []
    assert document.strip() == "@AGENTS.md"

    workflow = _workflow(CI_WORKFLOW)
    deterministic = _mapping(_mapping(workflow["jobs"])["deterministic"])
    command = _string(_named_step(deterministic, "Tests (deterministic)")["run"])
    assert shlex.split(command) == [
        "uv",
        "run",
        "pytest",
        "-m",
        "not live and not integration_postgres",
        "-q",
    ]


@pytest.mark.parametrize(
    ("separator", "alternative"),
    [
        ("\n", "pytest -q"),
        (" && ", "python -m pytest -q"),
        ("\n", "uv run python -m pytest -q"),
    ],
)
def test_rh6_1_parser_detects_alternative_pytest_invocation(
    separator: str,
    alternative: str,
) -> None:
    canonical = 'uv run pytest -m "not live and not integration_postgres" -q'
    section = f"```bash\n{canonical}{separator}{alternative}\n```"

    assert _pytest_commands(section) == [
        shlex.split(canonical),
        shlex.split(alternative),
    ]


def test_rh6_1_prose_pairing_tolerates_markdown_line_wrapping() -> None:
    section = """
PostgreSQL `integration_postgres`
由 `.github/workflows/harness-ci.yml` 的 PostgreSQL 16 job 验证。
"""

    assert _terms_in_order(
        _prose_text(section),
        "`integration_postgres`",
        "`.github/workflows/harness-ci.yml`",
        "PostgreSQL 16",
    )

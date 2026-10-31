"""App build: one docker build authority and no hidden build bypasses."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from tests.service_shell.app_build.helpers import CONTEXT, REPO_ROOT, _executable_text

MAKEFILE_PATH = REPO_ROOT / "Makefile"
BUILD_IMAGES_PATH = REPO_ROOT / "scripts/build_images.sh"


def _shell_function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}\(\)\s*\{{\s*\n(?P<body>.*?)^\}}",
        source,
    )
    assert match is not None, f"missing shell function {name}"
    return _executable_text(match.group("body"))


def _shell_command_tokens(source: str, *, preserve_wrappers: bool = False) -> list[list[str]]:
    cleaned = "\n".join(
        line.lstrip().lstrip("@+-").strip()
        for line in _executable_text(source).replace("\\\n", " ").splitlines()
    )
    lexer = shlex.shlex(cleaned.replace("\n", " ; "), posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token and set(token) <= {";", "&", "|"}:
            if current:
                commands.append(current)
                current = []
        else:
            current.append(token)
    if current:
        commands.append(current)

    normalized: list[list[str]] = []
    for command in commands:
        if not preserve_wrappers:
            if command[:1] == ["env"]:
                command = command[1:]
            while command and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", command[0]):
                command = command[1:]
        if command:
            normalized.append(command)
    return normalized


def _tokens_are_docker_build(tokens: list[str]) -> bool:
    if not tokens or Path(tokens[0]).name != "docker":
        return False
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] in {"--context", "-c", "--host", "-H", "--config"}:
            index += 2
        else:
            index += 1
    return tokens[index : index + 1] == ["build"] or tokens[index : index + 2] == [
        "buildx",
        "build",
    ]


def _assert_no_docker_build_commands(source: str) -> None:
    executable = _executable_text(source)
    hidden = re.compile(
        r"(?:`[^`]*|\$\$?\([^)]*)\bdocker\b[^;|&`)\n]*"
        r"\b(?:buildx\s+build|build)\b",
        re.S,
    )
    assert hidden.search(executable) is None, (
        "docker build cannot be hidden in command or make-shell substitution"
    )
    assert all(
        not _tokens_are_docker_build(tokens) for tokens in _shell_command_tokens(executable)
    ), "direct docker build/buildx build is forbidden"


def _assert_no_docker_authority(source: str) -> None:
    executable = _executable_text(source)
    hidden = re.compile(
        r"(?:`[^`]*\bdocker\b[^`]*`|\$\$?\([^)]*\bdocker\b[^)]*\))",
        re.S,
    )
    assert hidden.search(executable) is None, (
        "docker authority cannot be hidden in command or make-shell substitution"
    )
    for tokens in _shell_command_tokens(executable, preserve_wrappers=True):
        while tokens:
            if tokens[0] in {"if", "then", "elif", "while", "until", "do", "!"}:
                tokens = tokens[1:]
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
                tokens = tokens[1:]
                continue
            wrapper = Path(tokens[0]).name
            if wrapper == "env":
                tokens = tokens[1:]
                while tokens:
                    option = tokens[0]
                    if option == "--":
                        tokens = tokens[1:]
                        break
                    if option in {"-S", "--split-string"} or option.startswith("--split-string="):
                        raise AssertionError("Docker authority guard forbids env split-string")
                    if option in {"-i", "--ignore-environment"}:
                        tokens = tokens[1:]
                    elif option in {"-u", "--unset", "-C", "--chdir"}:
                        assert len(tokens) >= 2, f"env {option} lacks a value"
                        tokens = tokens[2:]
                    elif option.startswith(("--unset=", "--chdir=")):
                        tokens = tokens[1:]
                    elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", option):
                        tokens = tokens[1:]
                    elif option.startswith("-"):
                        raise AssertionError(
                            f"Docker authority guard rejects unsupported env option {option}"
                        )
                    else:
                        break
                continue
            if wrapper not in {"command", "exec"}:
                break
            tokens = tokens[1:]
            while tokens:
                if tokens[0] == "--":
                    tokens = tokens[1:]
                    break
                takes_value = (
                    wrapper == "env"
                    and tokens[0] in {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
                ) or (wrapper == "exec" and tokens[0] == "-a")
                if takes_value:
                    tokens = tokens[2:]
                elif tokens[0].startswith("-") or re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]
                ):
                    tokens = tokens[1:]
                else:
                    break
        if tokens and Path(tokens[0]).name in {"sh", "bash", "zsh"}:
            assert not any(
                re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", option) for option in tokens[1:]
            ), "Docker authority guard forbids secondary shell -c"
        assert not tokens or Path(tokens[0]).name not in {"docker", "sudo"}, (
            "public app build entry must not hold direct Docker authority"
        )


def test_shell_guard_rejects_hidden_docker_build_bypasses() -> None:
    for bypass in (
        "`docker build .`",
        "$(docker --context shadow-context buildx build .)",
        "$$(docker build .)",
        "$(shell docker buildx build .)",
    ):
        with pytest.raises(AssertionError, match="substitution"):
            _assert_no_docker_build_commands(bypass)
    for bypass in (
        "command docker image inspect sha256:deadbeef",
        'printf "$$(docker image inspect sha256:deadbeef)"',
        "docker --log-level debug --context shadow-context buildx build .",
        "env -- docker image inspect sha256:deadbeef",
        "env -i docker image inspect sha256:deadbeef",
        "env -u NAME docker image inspect sha256:deadbeef",
        "env -S 'docker image inspect sha256:deadbeef'",
        "sh -c 'docker image inspect sha256:deadbeef'",
    ):
        with pytest.raises(AssertionError, match="Docker authority|substitution"):
            _assert_no_docker_authority(bypass)


def test_public_app_build_entry_has_one_authority_and_makefile_has_no_naked_build() -> None:
    script = BUILD_IMAGES_PATH.read_text(encoding="utf-8")
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    app_body = _shell_function_body(script, "build_app_image")

    assert "--build-source-head" in app_body
    assert "--evidence-out" in app_body
    assert "scripts/app_artifact.py" in app_body
    assert CONTEXT in app_body
    _assert_no_docker_build_commands(app_body)
    _assert_no_docker_authority(app_body)

    executable_script = _executable_text(script)
    app_branch = re.search(
        r'(?ms)if \[ "\$BUILD_APP" = true \]; then(?P<body>.*?)^fi$',
        executable_script,
    )
    assert app_branch is not None
    branch_body = app_branch.group("body")
    _assert_no_docker_build_commands(branch_body)
    _assert_no_docker_authority(branch_body)
    branch_commands = _shell_command_tokens(branch_body)
    branch_delegates = [tokens for tokens in branch_commands if tokens == ["build_app_image"]]
    assert len(branch_delegates) == 1
    harmless_setup = {
        "set",
        "export",
        "test",
        "[",
        ":",
        "cd",
        "umask",
        "printf",
        "echo",
    }
    assert all(
        tokens in branch_delegates or tokens[0] in harmless_setup for tokens in branch_commands
    ), "BUILD_APP branch may only delegate once plus harmless shell setup"

    app_target = re.search(r"(?ms)^docker-build-app:\n(?P<body>(?:\t.*\n)+)", makefile)
    assert app_target is not None
    target_body = _executable_text(app_target.group("body")).replace("\\\n", " ")
    _assert_no_docker_build_commands(target_body)
    _assert_no_docker_authority(target_body)
    recipe_commands = _shell_command_tokens(target_body)
    delegates = [tokens for tokens in recipe_commands if tokens[0] == "./scripts/build_images.sh"]
    assert len(delegates) == 1 and "--app" in delegates[0]
    assert all(tokens in delegates or tokens[0] in harmless_setup for tokens in recipe_commands), (
        "docker-build-app may only delegate once plus harmless shell setup"
    )

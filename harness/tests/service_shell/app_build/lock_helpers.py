"""App build contracts: how Dockerfile instructions consume the external dependency lock."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tests.service_shell.app_build.helpers import (
    _dockerfile_instructions,
    _executable_text,
    _sha256_bytes,
)


@dataclass(frozen=True)
class LockUse:
    paths: tuple[str, ...]
    values: tuple[str, ...]
    consumer: str
    operation: str
    description: str


def _dependency_lock_uses(lock: Mapping[str, Any]) -> tuple[LockUse, ...]:
    repositories = lock["debian"]["repositories"]
    packages = lock["debian"]["packages"]
    python_tools = lock["python_tools"]
    downloads = lock["downloads"]
    migrate = downloads["go_tools"]["migrate"]
    duckdb = downloads["duckdb"]
    anydoc = downloads["anydoc"]
    browserskill = downloads["browserskill"]
    pnpm = downloads["pnpm"]

    def use(
        items: list[tuple[str, object]],
        consumer: str,
        operation: str,
        description: str,
    ) -> LockUse:
        return LockUse(
            paths=tuple(path for path, _ in items),
            values=tuple(str(value) for _, value in items),
            consumer=consumer,
            operation=operation,
            description=description,
        )

    return (
        use(
            [
                ("schema_version", lock["schema_version"]),
                ("platform.os", lock["platform"]["os"]),
                ("platform.arch", lock["platform"]["arch"]),
            ],
            "validate",
            r"\btest\b",
            "lock schema and target platform",
        ),
        use(
            [("base_images.builder.reference", lock["base_images"]["builder"]["reference"])],
            "from-builder",
            r"^FROM\b",
            "builder base image",
        ),
        use(
            [
                (
                    "base_images.browserskill.reference",
                    lock["base_images"]["browserskill"]["reference"],
                )
            ],
            "from-browserskill",
            r"^FROM\b",
            "BrowserSkill base image",
        ),
        use(
            [("base_images.rust.reference", lock["base_images"]["rust"]["reference"])],
            "from-rust",
            r"^FROM\b",
            "Rust base image",
        ),
        use(
            [("base_images.runtime.reference", lock["base_images"]["runtime"]["reference"])],
            "from-runtime",
            r"^FROM\b",
            "runtime base image",
        ),
        use(
            [
                (f"debian.repositories.{name}.snapshot", repository["snapshot"])
                for name, repository in repositories.items()
            ],
            "apt-source",
            r"\b(?:printf|echo|sed|tee)\b",
            "Debian snapshots",
        ),
        use(
            [
                (
                    f"debian.repositories.{name}.release_sha256",
                    repository["release_sha256"],
                )
                for name, repository in repositories.items()
            ],
            "sha256",
            r"\b(?:printf|echo)\b(?=[^;&]*\|\s*sha256sum\s+-c\b)",
            "Debian Release SHA256",
        ),
        use(
            [(f"debian.packages.{name}", value) for name, value in packages.items()],
            "apt",
            r"\bapt-get\s+install\b",
            "Debian package versions",
        ),
        use(
            [
                (f"python_tools.{name}.version", tool["version"])
                for name, tool in python_tools.items()
            ],
            "pip",
            r"\bpip3?\s+install\b",
            "Python tool versions",
        ),
        use(
            [
                (f"python_tools.{name}.origin", tool["origin"])
                for name, tool in python_tools.items()
            ],
            "download",
            r"\b(?:curl|wget|pip3?\s+download)\b",
            "Python tool origins",
        ),
        use(
            [
                (f"python_tools.{name}.sha256", tool["sha256"])
                for name, tool in python_tools.items()
            ],
            "sha256",
            r"\b(?:printf|echo)\b(?=[^;&]*\|\s*sha256sum\s+-c\b)",
            "Python tool SHA256 values",
        ),
        use(
            [
                (f"downloads.uv.{name}", downloads["uv"][name])
                for name in ("version", "platform", "origin")
            ],
            "download",
            r"\b(?:curl|wget)\b",
            "uv download coordinates",
        ),
        use(
            [("downloads.uv.sha256", downloads["uv"]["sha256"])],
            "sha256",
            r"\b(?:printf|echo)\b(?=[^;&]*\|\s*sha256sum\s+-c\b)",
            "uv SHA256",
        ),
        use(
            [
                (f"downloads.go_tools.migrate.{name}", migrate[name])
                for name in ("module", "version")
            ],
            "go-install",
            r"\bgo\s+install\b",
            "migrate module and version",
        ),
        use(
            [("downloads.go_tools.migrate.go_sum", migrate["go_sum"])],
            "go-sum",
            r"\bgrep\b",
            "migrate go_sum",
        ),
        use(
            [("toolchains.rust", lock["toolchains"]["rust"])]
            + [(f"downloads.anydoc.{name}", anydoc[name]) for name in sorted(anydoc)],
            "component-build",
            r"\benv\b",
            "AnyDoc locked source and Rust toolchain",
        ),
        use(
            [
                (f"downloads.browserskill.{name}", browserskill[name])
                for name in sorted(browserskill)
            ]
            + [(f"downloads.pnpm.{name}", pnpm[name]) for name in sorted(pnpm)],
            "component-build",
            r"\benv\b",
            "BrowserSkill locked source and pnpm",
        ),
        use(
            [
                ("platform.duckdb", lock["platform"]["duckdb"]),
                ("downloads.duckdb.version", duckdb["version"]),
            ]
            + [
                (f"downloads.duckdb.extensions.{extension}.{name}", item[name])
                for extension, item in duckdb["extensions"].items()
                for name in ("platform", "origin", "sha256")
            ],
            "duckdb-download",
            r"\bgo\s+run\s+cmd/download/duckdb/duckdb\.go\b",
            "DuckDB locked download plan",
        ),
    )


def _has_ignored_failure(command: str) -> bool:
    return re.search(r"\|\|\s*(?::(?:\s|$)|true\b)", command) is not None


def _variable_is_operation_operand(command: str, operation: str, name: str) -> bool:
    operation_match = re.search(operation, command, re.I)
    if operation_match is None or _has_ignored_failure(command):
        return False
    variable_match = re.search(
        rf"\$(?:\{{{re.escape(name)}\}}|{re.escape(name)})(?![A-Za-z0-9_])",
        command,
    )
    return variable_match is not None and variable_match.start() >= operation_match.end()


def _lock_shell_segments(instructions: list[str]) -> list[str]:
    return [
        segment.strip()
        for instruction in instructions
        for segment in re.split(r"\s*(?:&&|;)\s*", instruction)
        if segment.strip()
    ]


def _assert_no_floating_or_ignored_installs(instructions: list[str]) -> None:
    for segment in _lock_shell_segments(instructions):
        operation = re.search(
            r"\b(?:apt-get\s+install|pip3?\s+install|go\s+install)\b",
            segment,
            re.I,
        )
        if operation is None:
            continue
        assert not _has_ignored_failure(segment), "locked install failure cannot be ignored"
        operands = segment[operation.end() :]
        assert "latest" not in operands.lower()
        if re.match(r"\bapt-get\s+install\b", operation.group(), re.I):
            assert "$" in operands or "=" in operands, "apt install must consume a pin"
        elif re.match(r"\bpip", operation.group(), re.I):
            assert "--upgrade" not in operands
            assert "$" in operands or "==" in operands or ".whl" in operands
        else:
            assert "$" in operands or re.search(r"@v?\d", operands)


def _build_args_cover_lock_uses(uses: tuple[LockUse, ...], build_args: Mapping[str, str]) -> bool:
    return all(
        any(value in argument for argument in build_args.values())
        for use in uses
        for value in use.values
    )


def _assert_build_arg_lock_dataflow(
    uses: tuple[LockUse, ...],
    build_args: Mapping[str, str],
    instructions: list[str],
) -> None:
    segments = _lock_shell_segments(instructions)
    for use in uses:
        for value in use.values:
            names = {name for name, argument in build_args.items() if value in argument}
            assert names, f"{use.description} was not mapped to a build arg"
            assert all(
                any(
                    _variable_is_operation_operand(segment, use.operation, name)
                    for segment in segments
                )
                for name in names
            ), f"{use.description} build args are not real operation operands"


def _assert_copied_lock_dataflow(
    lock: Mapping[str, Any],
    uses: tuple[LockUse, ...],
    dependency_plan: Mapping[str, object],
    instructions: list[str],
) -> None:
    lock_relative = "deploy/local-build/app-external-dependencies.v1.json"
    copies = [
        (index, instruction)
        for index, instruction in enumerate(instructions)
        if instruction.startswith("COPY ") and lock_relative in instruction
    ]
    assert len(copies) == 1, "Dockerfile must COPY the exact versioned lock"
    copy_index, copy_instruction = copies[0]
    lock_destination = copy_instruction.split()[-1]

    output_path = dependency_plan.get("output_path")
    bindings = dependency_plan.get("bindings")
    assert isinstance(output_path, str) and output_path
    assert isinstance(bindings, list) and bindings
    canonical_lock = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()
    assert dependency_plan.get("lock_sha256") == _sha256_bytes(canonical_lock)

    expected_facts = {
        path: (use.consumer, value)
        for use in uses
        if not use.consumer.startswith("from-")
        for path, value in zip(use.paths, use.values, strict=True)
    }
    bound_paths: set[str] = set()
    bound_names: set[str] = set()
    normalized_bindings: list[tuple[str, str, str, str]] = []
    for raw_binding in bindings:
        assert isinstance(raw_binding, Mapping)
        name = raw_binding.get("name")
        consumer = raw_binding.get("consumer")
        fact_path = raw_binding.get("fact_path")
        value = raw_binding.get("value")
        assert isinstance(name, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        assert isinstance(consumer, str)
        assert isinstance(fact_path, str) and fact_path in expected_facts
        assert isinstance(value, str)
        expected_consumer, expected_value = expected_facts[fact_path]
        assert consumer == expected_consumer
        assert value == expected_value, f"wrong lock value for {fact_path}"
        assert fact_path not in bound_paths, "plan fact bound twice"
        assert name not in bound_names, "plan output name reused"
        bound_paths.add(fact_path)
        bound_names.add(name)
        normalized_bindings.append((name, consumer, fact_path, value))
    assert bound_paths == set(expected_facts), "plan must cover every lock fact"
    assert [binding[2] for binding in normalized_bindings] == sorted(expected_facts), (
        "dependency plan bindings must be deterministically ordered by fact path"
    )
    expected_output = "".join(
        f"{name}={json.dumps(value, ensure_ascii=False)}\n"
        for name, _, _, value in normalized_bindings
    ).encode()
    assert dependency_plan.get("output_bytes") == expected_output, (
        "dependency plan output_bytes do not match its bindings"
    )

    expected_parser_argv = [
        "python3",
        "scripts/app_artifact.py",
        "dependency-plan",
        "--lock",
        lock_destination,
        "--output",
        output_path,
    ]
    parser_indexes: list[int] = []
    for index, instruction in enumerate(instructions):
        if index <= copy_index or not instruction.startswith("RUN "):
            continue
        try:
            argv = shlex.split(instruction.removeprefix("RUN ").strip())
        except ValueError:
            continue
        if argv == expected_parser_argv:
            parser_indexes.append(index)
    assert parser_indexes, "exact dependency-plan parser argv required; -c is forbidden"
    parser_index = parser_indexes[0]
    operation_by_consumer = {use.consumer: use.operation for use in uses}
    for name, consumer, _, _ in normalized_bindings:
        operation = operation_by_consumer[consumer]
        assert any(
            index > parser_index
            and re.search(
                rf"(?:\bsource|\.)\s+['\"]?{re.escape(output_path)}['\"]?",
                instruction,
            )
            and any(
                _variable_is_operation_operand(segment, operation, name)
                for segment in _lock_shell_segments([instruction])
            )
            for index, instruction in enumerate(instructions)
        ), f"plan output {name} is not consumed by {consumer}"


def _assert_dependency_lock_dataflow(
    lock: Mapping[str, Any],
    build_args: Mapping[str, str],
    dockerfile_source: str,
    dependency_plan: Mapping[str, object] | None = None,
) -> None:
    instructions = [_executable_text(item) for item in _dockerfile_instructions(dockerfile_source)]
    uses = _dependency_lock_uses(lock)
    _assert_no_floating_or_ignored_installs(instructions)
    assert any(
        re.search(r"\buv\b", instruction, re.I)
        and re.search(r"\b(?:sh|bash)\b", instruction)
        and not _has_ignored_failure(instruction)
        for instruction in instructions
    ), "the verified uv payload must actually be installed"
    base_uses = tuple(use for use in uses if use.consumer.startswith("from-"))
    _assert_build_arg_lock_dataflow(base_uses, build_args, instructions)
    dependency_uses = tuple(use for use in uses if not use.consumer.startswith("from-"))
    if _build_args_cover_lock_uses(dependency_uses, build_args):
        _assert_build_arg_lock_dataflow(dependency_uses, build_args, instructions)
    else:
        assert dependency_plan is not None, "copied-lock path requires a dependency plan"
        _assert_copied_lock_dataflow(lock, uses, dependency_plan, instructions)

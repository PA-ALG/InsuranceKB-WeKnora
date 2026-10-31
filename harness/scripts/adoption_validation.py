"""Strict value checks shared by the WeKnora adoption tools.

Every failure is an ``AdoptionTargetError``; YAML and JSON readers reject duplicate keys.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn

import yaml

_SHA_RE = re.compile(r"[0-9a-f]{40}")


_RELEASE_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")


_SQL_IDENTIFIER_RE = re.compile(r"[a-z][a-z0-9_]*")


REPOSITORY_REF_RE = re.compile(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))[a-zA-Z0-9_./-]+")


class AdoptionTargetError(ValueError):
    """Raised when an adoption identity cannot be trusted."""


def fail(message: str) -> NoReturn:
    raise AdoptionTargetError(message)


def expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        fail(f"{label} must be an object")
    return value


def expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{label} must be a non-empty string")
    if any(character in value for character in ("\n", "\r", "\x00")):
        fail(f"{label} must be a single-line string")
    return value


def expect_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        fail(f"{label} must be a boolean")
    return value


def expect_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty list")
    return value


def expect_closed_keys(data: dict[str, object], expected: set[str], label: str) -> None:
    if set(data) != expected:
        fail(f"{label} keys do not match the closed schema")


def expect_identifier(value: object, label: str) -> str:
    identifier = expect_string(value, label)
    if _SQL_IDENTIFIER_RE.fullmatch(identifier) is None:
        fail(f"{label} must be a normalized SQL identifier")
    return identifier


def expect_string_tuple(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        fail(f"{label} must be a {'possibly empty ' if allow_empty else ''}list")
    result = tuple(expect_string(item, label) for item in value)
    if len(set(result)) != len(result):
        fail(f"{label} must contain unique values")
    return result


def expect_sha(value: object, label: str) -> str:
    identity = expect_string(value, label)
    if _SHA_RE.fullmatch(identity) is None:
        fail(f"{label} must be a full lowercase Git SHA")
    return identity


def expect_release_tag(value: object) -> str:
    tag = expect_string(value, "release_ancestor.tag")
    if _RELEASE_TAG_RE.fullmatch(tag) is None:
        fail("release_ancestor.tag must be an immutable normalized release tag")
    return tag


class DuplicateKeyError(ValueError):
    pass


def reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            fail("YAML mapping keys must be strings")
        if key in result:
            raise DuplicateKeyError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml(path: Path, label: str) -> object:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except DuplicateKeyError as exc:
        raise AdoptionTargetError(str(exc)) from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AdoptionTargetError(f"{label} is unreadable") from exc

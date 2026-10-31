"""The immutable WeKnora adoption target manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.adoption_validation import (
    AdoptionTargetError,
    DuplicateKeyError,
    expect_object,
    expect_release_tag,
    expect_sha,
    expect_string,
    fail,
    reject_duplicate_keys,
)

REPOSITORY = "https://github.com/Tencent/WeKnora.git"


_MANIFEST_KEYS = {
    "schema_version",
    "repository",
    "commit",
    "tree",
    "release_ancestor",
    "required_capability_commits",
    "official_migration_head",
}


_RELEASE_KEYS = {"tag", "commit"}


@dataclass(frozen=True)
class ReleaseAncestor:
    tag: str
    commit: str


@dataclass(frozen=True)
class AdoptionTarget:
    schema_version: int
    repository: str
    commit: str
    tree: str
    release_ancestor: ReleaseAncestor
    required_capability_commits: tuple[str, ...]
    official_migration_head: int


@dataclass(frozen=True)
class DiscoveryRevision:
    commit: str
    tree: str
    official_migration_head: int

    def __post_init__(self) -> None:
        expect_sha(self.commit, "discovered commit")
        expect_sha(self.tree, "discovered tree")
        if (
            type(self.official_migration_head) is not int
            or self.official_migration_head < 1
            or self.official_migration_head > 2_147_483_647
        ):
            fail("discovered migration head must be a positive 32-bit integer")


def _parse_target(value: object) -> AdoptionTarget:
    data = expect_object(value, "adoption target")
    if set(data) != _MANIFEST_KEYS:
        fail("adoption target keys do not match the closed schema")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        fail("schema_version must be 1")

    repository = expect_string(data.get("repository"), "repository")
    if repository != REPOSITORY:
        fail("repository must be the reviewed Tencent upstream HTTPS URL")

    release_data = expect_object(data.get("release_ancestor"), "release_ancestor")
    if set(release_data) != _RELEASE_KEYS:
        fail("release_ancestor keys do not match the closed schema")
    release = ReleaseAncestor(
        tag=expect_release_tag(release_data.get("tag")),
        commit=expect_sha(release_data.get("commit"), "release_ancestor.commit"),
    )

    capabilities_value = data.get("required_capability_commits")
    if not isinstance(capabilities_value, list) or not capabilities_value:
        fail("required_capability_commits must be a non-empty list")
    capabilities = tuple(
        expect_sha(item, "required capability commit") for item in capabilities_value
    )
    if len(set(capabilities)) != len(capabilities):
        fail("required_capability_commits must be unique")

    migration_head = data.get("official_migration_head")
    if type(migration_head) is not int or migration_head < 1 or migration_head > 2_147_483_647:
        fail("official_migration_head must be a positive 32-bit integer")

    return AdoptionTarget(
        schema_version=1,
        repository=repository,
        commit=expect_sha(data.get("commit"), "commit"),
        tree=expect_sha(data.get("tree"), "tree"),
        release_ancestor=release,
        required_capability_commits=capabilities,
        official_migration_head=migration_head,
    )


def load_adoption_target(path: Path) -> AdoptionTarget:
    """Read and fail-closed validate an immutable adoption target manifest."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except DuplicateKeyError as exc:
        raise AdoptionTargetError(str(exc)) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdoptionTargetError("adoption target manifest is unreadable") from exc
    return _parse_target(value)

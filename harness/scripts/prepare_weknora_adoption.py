#!/usr/bin/env python3
"""Validate and discover immutable WeKnora adoption targets."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NoReturn, Protocol

_REPOSITORY = "https://github.com/Tencent/WeKnora.git"
_CAPABILITY_COMMIT = "80a5003cc99a427098afe184eee6601916d3d156"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_RELEASE_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_MIGRATION_PATH_RE = re.compile(
    r"migrations/versioned/(?P<head>[0-9]+)_[^/]+\.(?:up|down)\.sql"
)
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
_CHANNELS = ("latest-stable", "mainline-head")
_GITHUB_API = "https://api.github.com/repos/Tencent/WeKnora"


class AdoptionTargetError(ValueError):
    """Raised when an adoption identity cannot be trusted."""


def _fail(message: str) -> NoReturn:
    raise AdoptionTargetError(message)


def _expect_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be an object")
    return value


def _expect_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    if any(character in value for character in ("\n", "\r", "\x00")):
        _fail(f"{label} must be a single-line string")
    return value


def _expect_sha(value: object, label: str) -> str:
    identity = _expect_string(value, label)
    if _SHA_RE.fullmatch(identity) is None:
        _fail(f"{label} must be a full lowercase Git SHA")
    return identity


def _expect_release_tag(value: object) -> str:
    tag = _expect_string(value, "release_ancestor.tag")
    if _RELEASE_TAG_RE.fullmatch(tag) is None:
        _fail("release_ancestor.tag must be an immutable normalized release tag")
    return tag


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
        _expect_sha(self.commit, "discovered commit")
        _expect_sha(self.tree, "discovered tree")
        if (
            type(self.official_migration_head) is not int
            or self.official_migration_head < 1
            or self.official_migration_head > 2_147_483_647
        ):
            _fail("discovered migration head must be a positive 32-bit integer")


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_target(value: object) -> AdoptionTarget:
    data = _expect_object(value, "adoption target")
    if set(data) != _MANIFEST_KEYS:
        _fail("adoption target keys do not match the closed schema")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        _fail("schema_version must be 1")

    repository = _expect_string(data.get("repository"), "repository")
    if repository != _REPOSITORY:
        _fail("repository must be the reviewed Tencent upstream HTTPS URL")

    release_data = _expect_object(data.get("release_ancestor"), "release_ancestor")
    if set(release_data) != _RELEASE_KEYS:
        _fail("release_ancestor keys do not match the closed schema")
    release = ReleaseAncestor(
        tag=_expect_release_tag(release_data.get("tag")),
        commit=_expect_sha(release_data.get("commit"), "release_ancestor.commit"),
    )

    capabilities_value = data.get("required_capability_commits")
    if not isinstance(capabilities_value, list) or not capabilities_value:
        _fail("required_capability_commits must be a non-empty list")
    capabilities = tuple(
        _expect_sha(item, "required capability commit") for item in capabilities_value
    )
    if len(set(capabilities)) != len(capabilities):
        _fail("required_capability_commits must be unique")

    migration_head = data.get("official_migration_head")
    if (
        type(migration_head) is not int
        or migration_head < 1
        or migration_head > 2_147_483_647
    ):
        _fail("official_migration_head must be a positive 32-bit integer")

    return AdoptionTarget(
        schema_version=1,
        repository=repository,
        commit=_expect_sha(data.get("commit"), "commit"),
        tree=_expect_sha(data.get("tree"), "tree"),
        release_ancestor=release,
        required_capability_commits=capabilities,
        official_migration_head=migration_head,
    )


def load_adoption_target(path: Path) -> AdoptionTarget:
    """Read and fail-closed validate an immutable adoption target manifest."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except _DuplicateKeyError as exc:
        raise AdoptionTargetError(str(exc)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AdoptionTargetError("adoption target manifest is unreadable") from exc
    return _parse_target(value)


class DiscoveryResolver(Protocol):
    """Read-only interface used to resolve mutable discovery channels."""

    def latest_release_tag(self, repository: str) -> str: ...

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision: ...

    def is_ancestor(
        self, repository: str, ancestor: str, descendant: str
    ) -> bool: ...


class GitHubDiscoveryResolver:
    """Resolve WeKnora identities through read-only GitHub API requests."""

    def _fetch_json(self, endpoint: str) -> object:
        request = urllib.request.Request(
            f"{_GITHUB_API}{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "weknora-adoption-discovery",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (
            OSError,
            ValueError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as exc:
            raise AdoptionTargetError("GitHub discovery request failed") from exc

    def _check_repository(self, repository: str) -> None:
        if repository != _REPOSITORY:
            _fail("discovery repository is not the reviewed upstream")

    def latest_release_tag(self, repository: str) -> str:
        self._check_repository(repository)
        data = _expect_object(self._fetch_json("/releases/latest"), "latest release")
        return _expect_release_tag(data.get("tag_name"))

    def _migration_head(self, tree: str) -> int:
        tree_data = _expect_object(
            self._fetch_json(f"/git/trees/{tree}?recursive=1"),
            "resolved revision tree listing",
        )
        if tree_data.get("truncated") is True:
            _fail("resolved revision tree listing is truncated")
        entries = tree_data.get("tree")
        if not isinstance(entries, list):
            _fail("resolved revision tree listing must contain entries")

        versions: list[int] = []
        for raw_entry in entries:
            entry = _expect_object(raw_entry, "resolved revision tree entry")
            path = entry.get("path")
            if entry.get("type") != "blob" or not isinstance(path, str):
                continue
            match = _MIGRATION_PATH_RE.fullmatch(path)
            if match is not None:
                versions.append(int(match.group("head")))
        if not versions:
            _fail("resolved revision has no official versioned migrations")
        return max(versions)

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision:
        self._check_repository(repository)
        encoded_ref = urllib.parse.quote(ref, safe="")
        data = _expect_object(
            self._fetch_json(f"/commits/{encoded_ref}"), "resolved revision"
        )
        commit_data = _expect_object(data.get("commit"), "resolved revision.commit")
        tree_data = _expect_object(commit_data.get("tree"), "resolved revision tree")
        tree = _expect_sha(tree_data.get("sha"), "resolved tree")
        return DiscoveryRevision(
            commit=_expect_sha(data.get("sha"), "resolved commit"),
            tree=tree,
            official_migration_head=self._migration_head(tree),
        )

    def is_ancestor(
        self, repository: str, ancestor: str, descendant: str
    ) -> bool:
        self._check_repository(repository)
        ancestor = _expect_sha(ancestor, "ancestor")
        descendant = _expect_sha(descendant, "descendant")
        data = _expect_object(
            self._fetch_json(f"/compare/{ancestor}...{descendant}"),
            "commit comparison",
        )
        return data.get("status") in {"ahead", "identical"}


def _proposal(
    channel: str,
    resolver: DiscoveryResolver,
) -> AdoptionTarget:
    if channel not in _CHANNELS:
        _fail("discovery channel must be latest-stable or mainline-head")

    release_tag = _expect_release_tag(resolver.latest_release_tag(_REPOSITORY))
    release_revision = resolver.resolve_revision(
        _REPOSITORY, f"refs/tags/{release_tag}"
    )
    target_revision = (
        release_revision
        if channel == "latest-stable"
        else resolver.resolve_revision(_REPOSITORY, "refs/heads/main")
    )

    if not resolver.is_ancestor(
        _REPOSITORY, release_revision.commit, target_revision.commit
    ):
        _fail("latest stable release is not an ancestor of the discovered target")
    if not resolver.is_ancestor(
        _REPOSITORY, _CAPABILITY_COMMIT, target_revision.commit
    ):
        _fail("reviewed capability commit is not an ancestor of the discovered target")

    return AdoptionTarget(
        schema_version=1,
        repository=_REPOSITORY,
        commit=target_revision.commit,
        tree=target_revision.tree,
        release_ancestor=ReleaseAncestor(
            tag=release_tag,
            commit=release_revision.commit,
        ),
        required_capability_commits=(_CAPABILITY_COMMIT,),
        official_migration_head=target_revision.official_migration_head,
    )


def render_discovery_proposal(
    channel: str, *, resolver: DiscoveryResolver | None = None
) -> str:
    """Return a deterministic immutable proposal without writing any state."""

    target = _proposal(channel, resolver or GitHubDiscoveryResolver())
    value = asdict(target)
    value["required_capability_commits"] = list(
        target.required_capability_commits
    )
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


class _UsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    discover = subparsers.add_parser("discover")
    discover.add_argument("--channel", choices=_CHANNELS)
    return parser


def main(
    argv: list[str] | None = None, *, resolver: DiscoveryResolver | None = None
) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _UsageError as exc:
        parser.print_usage(sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command is None or args.channel is None:
        parser.print_usage(sys.stderr)
        print("error: discover and --channel are required", file=sys.stderr)
        return 2

    try:
        rendered = render_discovery_proposal(args.channel, resolver=resolver)
    except AdoptionTargetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Discover the next WeKnora adoption target from the official GitHub repository."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from typing import Protocol

from scripts.adoption_target import REPOSITORY, AdoptionTarget, DiscoveryRevision, ReleaseAncestor
from scripts.adoption_validation import (
    AdoptionTargetError,
    expect_object,
    expect_release_tag,
    expect_sha,
    fail,
)

_CAPABILITY_COMMIT = "80a5003cc99a427098afe184eee6601916d3d156"


_MIGRATION_PATH_RE = re.compile(r"migrations/versioned/(?P<head>[0-9]+)_[^/]+\.(?:up|down)\.sql")


CHANNELS = ("latest-stable", "mainline-head")


_GITHUB_API = "https://api.github.com/repos/Tencent/WeKnora"


class DiscoveryResolver(Protocol):
    """Read-only interface used to resolve mutable discovery channels."""

    def latest_release_tag(self, repository: str) -> str: ...

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision: ...

    def is_ancestor(self, repository: str, ancestor: str, descendant: str) -> bool: ...


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
        if repository != REPOSITORY:
            fail("discovery repository is not the reviewed upstream")

    def latest_release_tag(self, repository: str) -> str:
        self._check_repository(repository)
        data = expect_object(self._fetch_json("/releases/latest"), "latest release")
        return expect_release_tag(data.get("tag_name"))

    def _migration_head(self, tree: str) -> int:
        tree_data = expect_object(
            self._fetch_json(f"/git/trees/{tree}?recursive=1"),
            "resolved revision tree listing",
        )
        if tree_data.get("truncated") is True:
            fail("resolved revision tree listing is truncated")
        entries = tree_data.get("tree")
        if not isinstance(entries, list):
            fail("resolved revision tree listing must contain entries")

        versions: list[int] = []
        for raw_entry in entries:
            entry = expect_object(raw_entry, "resolved revision tree entry")
            path = entry.get("path")
            if entry.get("type") != "blob" or not isinstance(path, str):
                continue
            match = _MIGRATION_PATH_RE.fullmatch(path)
            if match is not None:
                versions.append(int(match.group("head")))
        if not versions:
            fail("resolved revision has no official versioned migrations")
        return max(versions)

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision:
        self._check_repository(repository)
        encoded_ref = urllib.parse.quote(ref, safe="")
        data = expect_object(self._fetch_json(f"/commits/{encoded_ref}"), "resolved revision")
        commit_data = expect_object(data.get("commit"), "resolved revision.commit")
        tree_data = expect_object(commit_data.get("tree"), "resolved revision tree")
        tree = expect_sha(tree_data.get("sha"), "resolved tree")
        return DiscoveryRevision(
            commit=expect_sha(data.get("sha"), "resolved commit"),
            tree=tree,
            official_migration_head=self._migration_head(tree),
        )

    def is_ancestor(self, repository: str, ancestor: str, descendant: str) -> bool:
        self._check_repository(repository)
        ancestor = expect_sha(ancestor, "ancestor")
        descendant = expect_sha(descendant, "descendant")
        data = expect_object(
            self._fetch_json(f"/compare/{ancestor}...{descendant}"),
            "commit comparison",
        )
        return data.get("status") in {"ahead", "identical"}


def _proposal(
    channel: str,
    resolver: DiscoveryResolver,
) -> AdoptionTarget:
    if channel not in CHANNELS:
        fail("discovery channel must be latest-stable or mainline-head")

    release_tag = expect_release_tag(resolver.latest_release_tag(REPOSITORY))
    release_revision = resolver.resolve_revision(REPOSITORY, f"refs/tags/{release_tag}")
    target_revision = (
        release_revision
        if channel == "latest-stable"
        else resolver.resolve_revision(REPOSITORY, "refs/heads/main")
    )

    if not resolver.is_ancestor(REPOSITORY, release_revision.commit, target_revision.commit):
        fail("latest stable release is not an ancestor of the discovered target")
    if not resolver.is_ancestor(REPOSITORY, _CAPABILITY_COMMIT, target_revision.commit):
        fail("reviewed capability commit is not an ancestor of the discovered target")

    return AdoptionTarget(
        schema_version=1,
        repository=REPOSITORY,
        commit=target_revision.commit,
        tree=target_revision.tree,
        release_ancestor=ReleaseAncestor(
            tag=release_tag,
            commit=release_revision.commit,
        ),
        required_capability_commits=(_CAPABILITY_COMMIT,),
        official_migration_head=target_revision.official_migration_head,
    )


def render_discovery_proposal(channel: str, *, resolver: DiscoveryResolver | None = None) -> str:
    """Return a deterministic immutable proposal without writing any state."""

    target = _proposal(channel, resolver or GitHubDiscoveryResolver())
    value = asdict(target)
    value["required_capability_commits"] = list(target.required_capability_commits)
    return json.dumps(value, indent=2, sort_keys=True) + "\n"

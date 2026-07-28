from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from scripts import prepare_weknora_adoption as adoption
from scripts.prepare_weknora_adoption import (
    AdoptionTargetError,
    DiscoveryRevision,
    GitHubDiscoveryResolver,
    load_adoption_target,
    main,
    render_discovery_proposal,
)

REPOSITORY = "https://github.com/Tencent/WeKnora.git"
TARGET_COMMIT = "80a5003cc99a427098afe184eee6601916d3d156"
TARGET_TREE = "18fcf68e7a008ce69929e32233f0b6914040c223"
RELEASE_COMMIT = "c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb"
MANIFEST = {
    "schema_version": 1,
    "repository": REPOSITORY,
    "commit": TARGET_COMMIT,
    "tree": TARGET_TREE,
    "release_ancestor": {"tag": "v0.7.1", "commit": RELEASE_COMMIT},
    "required_capability_commits": [TARGET_COMMIT],
    "official_migration_head": 75,
}
COMMITTED_MANIFEST = (
    Path(__file__).resolve().parents[2] / "deploy" / "upstream" / "weknora-adoption-target.json"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_CONTRACT = REPOSITORY_ROOT / "deploy" / "upstream" / "weknora-plugin-contract.yaml"
CHECK_TARGET = "a" * 40
CHECK_TREE = "b" * 40
CHECK_RELEASE = "c" * 40
CHECK_CAPABILITY = "d" * 40
CHECK_RUNTIME = "e" * 40
CHECK_RUNTIME_TREE = "f" * 40
CHECK_PROJECT_HEAD = "1" * 40
CHECK_MERGE_BASE = "2" * 40


def _write_manifest(tmp_path: Path, value: object = MANIFEST) -> Path:
    path = tmp_path / "target.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _replace(value: dict[str, object], **changes: object) -> dict[str, object]:
    return {**value, **changes}


def _snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _write_yaml(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _write_check_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    manifest = _write_manifest(
        tmp_path,
        _replace(
            MANIFEST,
            commit=CHECK_TARGET,
            tree=CHECK_TREE,
            release_ancestor={"tag": "v1.2.3", "commit": CHECK_RELEASE},
            required_capability_commits=[CHECK_CAPABILITY],
            official_migration_head=2,
        ),
    )
    target_checkout = tmp_path / "target"
    migrations = target_checkout / "migrations" / "versioned"
    migrations.mkdir(parents=True)
    for version in (0, 1, 2):
        for direction in ("up", "down"):
            (migrations / f"{version:06d}_migration_{version}.{direction}.sql").write_text(
                f"-- {version} {direction}\n",
                encoding="utf-8",
            )
    runtime_lock = tmp_path / "runtime-lock.json"
    runtime_lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": REPOSITORY,
                "commit": CHECK_RUNTIME,
                "tree": CHECK_RUNTIME_TREE,
                "ignored_v1_field": {"does_not_affect_check": True},
            }
        ),
        encoding="utf-8",
    )
    inventory = REPOSITORY_ROOT / "deploy" / "patches" / "enterprise-llm-wiki-patch-inventory.yaml"
    return manifest, target_checkout, runtime_lock, inventory


class FakeResolver:
    def __init__(self) -> None:
        self.release_tag = "v1.2.3"
        self.release = DiscoveryRevision(
            commit="1" * 40,
            tree="2" * 40,
            official_migration_head=75,
        )
        self.mainline = DiscoveryRevision(
            commit="3" * 40,
            tree="4" * 40,
            official_migration_head=80,
        )
        self.calls: list[tuple[str, ...]] = []

    def latest_release_tag(self, repository: str) -> str:
        self.calls.append(("latest_release_tag", repository))
        return self.release_tag

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision:
        self.calls.append(("resolve_revision", repository, ref))
        if ref == f"refs/tags/{self.release_tag}":
            return self.release
        assert ref == "refs/heads/main"
        return self.mainline

    def is_ancestor(self, repository: str, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", repository, ancestor, descendant))
        return True


def test_manifest_exact_target_passes_and_is_immutable(tmp_path: Path) -> None:
    target = load_adoption_target(_write_manifest(tmp_path))

    assert target.schema_version == 1
    assert target.repository == REPOSITORY
    assert target.commit == TARGET_COMMIT
    assert target.tree == TARGET_TREE
    assert target.release_ancestor.tag == "v0.7.1"
    assert target.release_ancestor.commit == RELEASE_COMMIT
    assert target.required_capability_commits == (TARGET_COMMIT,)
    assert target.official_migration_head == 75
    with pytest.raises(FrozenInstanceError):
        target.commit = "0" * 40  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        target.release_ancestor.tag = "v9.9.9"  # type: ignore[misc]


def test_committed_manifest_matches_approved_exact_target() -> None:
    target = load_adoption_target(COMMITTED_MANIFEST)

    assert json.loads(COMMITTED_MANIFEST.read_text(encoding="utf-8")) == MANIFEST
    assert target.commit == TARGET_COMMIT
    assert target.tree == TARGET_TREE
    assert target.release_ancestor.commit == RELEASE_COMMIT


def test_manifest_accepts_future_approved_immutable_target(tmp_path: Path) -> None:
    future = _replace(
        MANIFEST,
        commit="1" * 40,
        tree="2" * 40,
        release_ancestor={"tag": "v1.2.3", "commit": "3" * 40},
        required_capability_commits=["4" * 40],
        official_migration_head=80,
    )

    target = load_adoption_target(_write_manifest(tmp_path, future))

    assert target.commit == "1" * 40
    assert target.tree == "2" * 40
    assert target.release_ancestor.commit == "3" * 40
    assert target.required_capability_commits == ("4" * 40,)
    assert target.official_migration_head == 80


@pytest.mark.parametrize(
    "serialized",
    [
        json.dumps(MANIFEST).replace(
            f'"commit": "{TARGET_COMMIT}"',
            f'"commit": "{TARGET_COMMIT}", "commit": "{"0" * 40}"',
            1,
        ),
        json.dumps(MANIFEST).replace(
            '"tag": "v0.7.1"',
            '"tag": "v0.7.1", "tag": "v9.9.9"',
            1,
        ),
    ],
)
def test_manifest_rejects_duplicate_json_keys(tmp_path: Path, serialized: str) -> None:
    path = tmp_path / "duplicate-target.json"
    path.write_text(serialized, encoding="utf-8")

    with pytest.raises(AdoptionTargetError, match="duplicate"):
        load_adoption_target(path)


@pytest.mark.parametrize(
    "value",
    [
        _replace(MANIFEST, extra=True),
        {key: item for key, item in MANIFEST.items() if key != "tree"},
        _replace(
            MANIFEST,
            release_ancestor={
                "tag": "v0.7.1",
                "commit": RELEASE_COMMIT,
                "extra": True,
            },
        ),
        _replace(MANIFEST, release_ancestor={"tag": "v0.7.1"}),
        _replace(MANIFEST, commit="main"),
        _replace(MANIFEST, commit="master"),
        _replace(MANIFEST, tree="main"),
        _replace(
            MANIFEST,
            release_ancestor={"tag": "v0.7.1", "commit": "master"},
        ),
        _replace(MANIFEST, required_capability_commits=["main"]),
        _replace(MANIFEST, commit=TARGET_COMMIT[:12]),
        _replace(MANIFEST, tree="g" * 40),
        _replace(
            MANIFEST,
            release_ancestor={"tag": "v0.7.1", "commit": "f" * 39},
        ),
        _replace(MANIFEST, repository="https://github.com/evil/WeKnora.git"),
        _replace(
            MANIFEST,
            required_capability_commits=[TARGET_COMMIT, TARGET_COMMIT],
        ),
        _replace(MANIFEST, commit="../refs/heads/main"),
        _replace(
            MANIFEST,
            release_ancestor={"tag": "../v0.7.1", "commit": RELEASE_COMMIT},
        ),
        _replace(MANIFEST, required_capability_commits=["refs/heads/main"]),
    ],
)
def test_manifest_rejects_invalid_or_mutable_identity(
    tmp_path: Path, value: dict[str, object]
) -> None:
    with pytest.raises(AdoptionTargetError):
        load_adoption_target(_write_manifest(tmp_path, value))


@pytest.mark.parametrize(
    "channel, expected_revision",
    [
        (
            "latest-stable",
            DiscoveryRevision(
                commit="1" * 40,
                tree="2" * 40,
                official_migration_head=75,
            ),
        ),
        (
            "mainline-head",
            DiscoveryRevision(
                commit="3" * 40,
                tree="4" * 40,
                official_migration_head=80,
            ),
        ),
    ],
)
def test_discover_resolves_full_immutable_proposal_with_fakes(
    channel: str, expected_revision: DiscoveryRevision
) -> None:
    resolver = FakeResolver()

    rendered = render_discovery_proposal(channel, resolver=resolver)
    proposal = json.loads(rendered)

    assert proposal == {
        "schema_version": 1,
        "repository": REPOSITORY,
        "commit": expected_revision.commit,
        "tree": expected_revision.tree,
        "release_ancestor": {"tag": "v1.2.3", "commit": "1" * 40},
        "required_capability_commits": [TARGET_COMMIT],
        "official_migration_head": expected_revision.official_migration_head,
    }
    assert "refs/" not in rendered
    assert "mainline-head" not in rendered
    assert "latest-stable" not in rendered


def test_discover_repeated_output_is_byte_identical() -> None:
    first = render_discovery_proposal("mainline-head", resolver=FakeResolver())
    second = render_discovery_proposal("mainline-head", resolver=FakeResolver())

    assert first.encode("utf-8") == second.encode("utf-8")
    assert first.endswith("\n")


def test_discover_uses_migration_head_from_resolved_immutable_revision() -> None:
    resolver = FakeResolver()
    resolver.mainline = DiscoveryRevision(
        commit="3" * 40,
        tree="4" * 40,
        official_migration_head=80,
    )

    proposal = json.loads(render_discovery_proposal("mainline-head", resolver=resolver))

    assert proposal["official_migration_head"] == 80


def test_resolver_derives_head_from_official_versioned_migration_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = GitHubDiscoveryResolver()
    tree = "a" * 40

    def fake_fetch(endpoint: str) -> object:
        assert endpoint == f"/git/trees/{tree}?recursive=1"
        return {
            "truncated": False,
            "tree": [
                {
                    "path": ("migrations/versioned/000075_wiki_page_revisions.up.sql"),
                    "type": "blob",
                },
                {
                    "path": "migrations/versioned/000080_x.up.sql",
                    "type": "blob",
                },
                {
                    "path": "migrations/versioned/000080_x.down.sql",
                    "type": "blob",
                },
                {
                    "path": "migrations/999999_unrelated.sql",
                    "type": "blob",
                },
                {
                    "path": "examples/migrations/versioned/000100_demo.up.sql",
                    "type": "blob",
                },
            ],
        }

    monkeypatch.setattr(resolver, "_fetch_json", fake_fetch)

    assert resolver._migration_head(tree) == 80


def test_discover_writes_nothing_to_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    before = _snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["discover", "--channel", "mainline-head"], resolver=FakeResolver()) == 0

    assert _snapshot(tmp_path) == before
    assert json.loads(capsys.readouterr().out)["commit"] == "3" * 40


def test_discover_rejects_nonancestor_release() -> None:
    resolver = FakeResolver()
    resolver.is_ancestor = lambda *_args: False  # type: ignore[method-assign]

    with pytest.raises(AdoptionTargetError, match="ancestor"):
        render_discovery_proposal("mainline-head", resolver=resolver)


def test_cli_explicit_help_is_successful_and_prints_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(["--help"], resolver=FakeResolver())
    captured = capsys.readouterr()

    assert status == 0
    assert "usage:" in captured.out
    assert captured.err == ""


def test_cli_invalid_channel_is_usage_error_without_traceback_or_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        ["discover", "--channel", "nightly"],
        resolver=FakeResolver(),
    )
    captured = capsys.readouterr()

    assert status == 2
    assert "Traceback" not in captured.err
    assert TARGET_COMMIT not in captured.err


def test_plugin_contract_freezes_approved_refs_transports_and_independent_states() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)

    assert contract.schema_version == 1
    assert contract.contract_id == "harness-weknora-w1-plugin"
    assert contract.contract_version == 1
    assert contract.adoption_target_ref == ("deploy/upstream/weknora-adoption-target.json")
    assert contract.patch_inventory_ref == (
        "deploy/patches/enterprise-llm-wiki-patch-inventory.yaml"
    )
    assert contract.transports.allowed == ("versioned_rest", "lifecycle_poll")
    assert contract.transports.forbidden == (
        "shared_database",
        "redis",
        "asynq",
        "internal_queue",
        "mcp_control_plane",
    )
    assert contract.states.w1_runtime == adoption.ContractState(
        available=False, status="available_after_replay"
    )
    assert contract.states.consumer_adapted == adoption.ContractState(
        available=False, status="pre_w1"
    )
    assert contract.states.source_reader_authority == adoption.ContractState(
        available=False,
        status="blocked_on_p3_acl_inspection_authority",
    )
    assert contract.states.artifact_gate == adoption.ContractState(
        available=False,
        status="planned_nodes_pending_artifact_pr",
    )
    with pytest.raises(FrozenInstanceError):
        contract.contract_version = 2  # type: ignore[misc]


def test_plugin_contract_source_reader_is_space_bound_read_only_and_not_elevated() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    reader = contract.principals.source_reader

    assert reader.service == "source_reader"
    assert reader.authentication.header == "Authorization"
    assert reader.authentication.scheme == "Bearer"
    assert reader.authentication.capabilities == ("retrieve",)
    assert reader.space_binding.authority == "harness_persisted_space_binding"
    assert reader.space_binding.identity_fields == (
        "tenant_id",
        "raw_knowledge_base_id",
    )
    assert reader.space_binding.acl_basis == (
        "current_tenant_scope",
        "current_raw_knowledge_base_viewer_acl",
    )
    assert reader.space_binding.exact_knowledge_base_scope == ("bound_raw_knowledge_base_only")
    assert reader.allowed_operations == (
        "knowledge_list",
        "knowledge_get",
        "revision_get",
        "revision_chunks_get",
    )
    assert reader.denied_methods == ("POST", "PUT", "PATCH", "DELETE")
    assert reader.zero_write == "required"
    assert reader.download_authority == "blocked"

    writer = contract.principals.test_writer
    assert writer.service == "w1_contract_test_writer"
    assert writer.purpose == "bounded_race_stimuli"
    assert writer.allowed_operations == ("knowledge_reparse", "knowledge_delete")
    assert writer.auto_retry is False
    assert writer.bounded_to_test_runs is True


def test_plugin_contract_freezes_public_envelopes_and_stimulus_mutations() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    endpoints = {endpoint.endpoint_id: endpoint for endpoint in contract.endpoints}

    assert tuple(endpoints) == (
        "knowledge_list",
        "knowledge_get",
        "revision_get",
        "revision_chunks_get",
        "knowledge_download",
        "knowledge_reparse",
        "knowledge_delete",
    )
    assert endpoints["knowledge_list"].authority == "discovery_only"
    assert endpoints["knowledge_get"].path == "/api/v1/knowledge/{knowledge_id}"
    assert endpoints["revision_get"].path == ("/api/v1/knowledge/{knowledge_id}/revision")
    chunks = endpoints["revision_chunks_get"]
    assert chunks.method == "GET"
    assert chunks.path == ("/api/v1/knowledge/{knowledge_id}/revisions/{parse_attempt}/chunks")
    assert chunks.success.envelope == "root"
    assert chunks.success.required_fields == (
        "success",
        "data",
        "total",
        "page",
        "page_size",
        "revision",
    )
    assert chunks.success.revision_required_fields == (
        "knowledge_id",
        "parse_attempt",
        "manifest_digest",
        "chunk_count",
    )
    assert tuple(parameter.name for parameter in chunks.request.query_parameters) == (
        "page",
        "page_size",
    )
    assert endpoints["knowledge_download"].authority == (
        "blocked_pending_source_reader_acl_authority"
    )
    assert endpoints["knowledge_download"].success.available is False
    assert endpoints["knowledge_download"].principal == "source_reader"
    for endpoint_id, endpoint in endpoints.items():
        assert endpoint.timeout_policy_ref == "w1_public_contract_timeout_v1"
        if endpoint_id != "knowledge_download":
            assert endpoint.success.available is True
            assert endpoint.success.root_success is True
            assert "success" in endpoint.success.required_fields
            assert "data" in endpoint.success.required_fields
    for endpoint_id in ("knowledge_reparse", "knowledge_delete"):
        endpoint = endpoints[endpoint_id]
        assert endpoint.authority == "stimulus_only"
        assert endpoint.principal == "test_writer"
        assert endpoint.retry.mode == "never"


def test_plugin_contract_typed_dispositions_retries_and_source_head_rules() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    errors = {(item.code, item.reason): item for item in contract.typed_errors}

    assert errors[("revision_not_committed", "attempt_in_progress")].disposition == (
        "bounded_get_retry"
    )
    assert errors[("revision_superseded", "any")].disposition == (
        "restart_revision_and_discard_pages"
    )
    assert errors[("revision_superseded", "any")].error_required_fields == (
        "code",
        "current_parse_attempt",
        "parse_status",
    )
    assert errors[("knowledge_deleted", "any")].disposition == "record_tombstone"
    assert errors[("revision_manifest_incomplete", "any")].disposition == ("block_without_fallback")
    assert errors[("revision_not_found", "any")].disposition == ("fail_without_fallback")
    assert errors[("knowledge_not_found", "authorized_probe_only")].disposition == (
        "accept_absence_after_authorized_probe"
    )
    for status in (401, 403, 404):
        assert errors[("acl_denied", str(status))].disposition == (
            "fail_closed_without_lifecycle_inference"
        )
    for error in contract.typed_errors:
        assert error.root_success is False
        assert error.envelope == "root"
        assert error.required_fields == ("success", "error")
        assert "code" in error.error_required_fields
    lifecycle = dict(contract.lifecycle_dispositions)
    assert lifecycle["failed"] == "preserve_prior_source_head"
    assert lifecycle["cancelled"] == "preserve_prior_source_head"

    assert contract.retry_policy.allowed_methods == ("GET",)
    assert contract.retry_policy.bounded_attempts == 3
    assert contract.retry_policy.mutation_auto_retry is False
    assert contract.timeout_policy == adoption.TimeoutPolicy(
        policy_id="w1_public_contract_timeout_v1",
        connect_seconds=5,
        read_seconds=15,
        overall_seconds=60,
    )
    assert contract.idempotency_identities["revision_chunks_get"] == (
        "space_binding",
        "knowledge_id",
        "parse_attempt",
        "page",
        "page_size",
        "manifest_digest",
    )


def test_plugin_contract_matches_actual_terminal_reason_and_conditional_envelope() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    errors = {(item.code, item.reason): item for item in contract.typed_errors}

    assert ("revision_not_committed", "failed") not in errors
    assert ("revision_not_committed", "cancelled") not in errors
    assert ("revision_not_committed", "non_parser_completed") not in errors
    assert ("revision_not_committed", "non_parse_completed") in errors
    prior_commit_reasons = {"attempt_in_progress", "attempt_terminal"}
    assert errors[("revision_not_committed", "attempt_terminal")].disposition == (
        "preserve_prior_source_head"
    )
    for error in contract.typed_errors:
        if error.code == "revision_not_committed" and error.reason in prior_commit_reasons:
            assert error.last_committed == "required_when_prior_committed"
            assert error.last_committed_required_fields == (
                "parse_attempt",
                "manifest_digest",
                "completed_at",
            )
        else:
            assert error.last_committed == "forbidden"
            assert error.last_committed_required_fields == ()


def test_plugin_contract_registers_existing_not_committed_reason_matrix_node() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    nodes = {node.node_id: node for lane in contract.validation_lanes for node in lane.nodes}

    descriptor = nodes["compatibility.w1_revision_descriptor"]
    assert descriptor.proves == ("current_committed_revision_descriptor",)
    matrix = nodes["compatibility.w1_not_committed_error_matrix"]
    assert matrix.test_ref == (
        "internal/handler/knowledge_revision_test.go::"
        "TestGetKnowledgeRevisionNotCommittedReasonMatrix"
    )
    assert matrix.status == "existing"
    assert matrix.required_by == "code_pr"
    assert matrix.proves == (
        "revision_not_committed_reason_matrix",
        "terminal_last_committed_envelope",
    )


def test_plugin_contract_keeps_in_progress_prior_commit_evidence_planned() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    nodes = {node.node_id: node for lane in contract.validation_lanes for node in lane.nodes}

    node = nodes["compatibility.w1_in_progress_last_committed"]
    assert node.test_ref == (
        "internal/handler/knowledge_revision_test.go::"
        "TestGetKnowledgeRevisionInProgressIncludesLastCommitted"
    )
    assert node.status == "planned"
    assert node.required_by == "code_pr"
    assert node.proves == ("in_progress_with_prior_last_committed_envelope",)
    assert contract.states.w1_runtime.available is False
    assert contract.states.consumer_adapted.available is False
    assert contract.states.artifact_gate.available is False


def test_plugin_contract_separates_readiness_lanes_and_excludes_unowned_work() -> None:
    contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)

    assert tuple(signal.signal_id for signal in contract.readiness_signals) == (
        "weknora_runtime",
        "harness_process",
        "w1_consumer_capability",
    )
    assert tuple(lane.lane_id for lane in contract.validation_lanes) == (
        "planner",
        "compatibility_ci",
        "artifact_probe",
    )
    assert all(lane.nodes for lane in contract.validation_lanes)
    existing = tuple(
        node
        for lane in contract.validation_lanes
        for node in lane.nodes
        if node.status == "existing"
    )
    planned = tuple(
        node
        for lane in contract.validation_lanes
        for node in lane.nodes
        if node.status == "planned"
    )
    assert existing
    assert all(node.required_by == "code_pr" for node in existing)
    assert planned
    planned_code_pr = tuple(node for node in planned if node.required_by == "code_pr")
    assert tuple(node.node_id for node in planned_code_pr) == (
        "compatibility.w1_in_progress_last_committed",
    )
    assert all(node.required_by == "artifact_pr" for node in planned if node not in planned_code_pr)
    assert all(node.status != "existing" for node in planned)
    assert contract.states.artifact_gate.available is False
    assert contract.exclusions.ordinary_wiki_operations == (
        "history",
        "diff",
        "edit",
        "revert",
    )
    assert contract.exclusions.missions == (
        "P4a",
        "P4c",
        "P2d",
        "P11",
        "P13",
        "P14",
        "provider",
        "full",
    )


def test_plugin_contract_schema_v1_requires_version_bump_for_future_target_refs(
    tmp_path: Path,
) -> None:
    value = yaml.safe_load(PLUGIN_CONTRACT.read_text(encoding="utf-8"))
    value["adoption_target_ref"] = "deploy/upstream/future-adoption-target.json"
    value["patch_inventory_ref"] = "deploy/patches/future-patch-inventory.yaml"

    with pytest.raises(AdoptionTargetError, match="schema-version-1.*digest"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "future-contract.yaml", value))


def test_plugin_contract_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "contract.yaml"
    path.write_text(
        PLUGIN_CONTRACT.read_text(encoding="utf-8").replace(
            "contract_version: 1",
            "contract_version: 1\ncontract_version: 2",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(AdoptionTargetError, match="duplicate"):
        adoption.load_plugin_contract(path)


def _contract_value() -> dict[str, object]:
    return yaml.safe_load(PLUGIN_CONTRACT.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["principals"]["source_reader"].pop("space_binding"),
        lambda value: value["principals"]["source_reader"]["allowed_operations"].append(
            "knowledge_reparse"
        ),
        lambda value: value["principals"]["source_reader"].update(
            {"download_authority": "available"}
        ),
        lambda value: value["states"]["source_reader_authority"].update(
            {"available": True, "status": "available"}
        ),
        lambda value: value["transports"]["forbidden"].remove("shared_database"),
        lambda value: value["transports"]["forbidden"].append("grpc"),
        lambda value: value["endpoints"][0].update({"go_symbol": "handler.ListKnowledge"}),
        lambda value: value["endpoints"].append(
            {
                **copy.deepcopy(value["endpoints"][0]),
                "endpoint_id": "wiki_history",
                "path": "/api/v1/wiki/{id}/history",
            }
        ),
        lambda value: value["validation_lanes"].pop(),
        lambda value: value["validation_lanes"][1]["nodes"].append(
            copy.deepcopy(value["validation_lanes"][0]["nodes"][0])
        ),
    ],
)
def test_plugin_contract_rejects_security_coupling_private_wiki_and_lane_mutations(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "invalid-contract.yaml", value))


def test_plugin_contract_rejects_consumer_adapted_without_required_w1_surface(
    tmp_path: Path,
) -> None:
    value = _contract_value()
    value["states"]["consumer_adapted"] = {"available": True, "status": "adapted"}
    value["endpoints"] = [
        endpoint
        for endpoint in value["endpoints"]
        if endpoint["endpoint_id"] != "revision_chunks_get"
    ]

    with pytest.raises(AdoptionTargetError, match="consumer"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "invalid-contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["validation_lanes"][0]["nodes"][0].update(
            {"test_ref": "harness/tests/test_prepare_weknora_adoption_045.py::not_a_test"}
        ),
        lambda value: value["validation_lanes"][2]["nodes"][0].update({"required_by": "code_pr"}),
        lambda value: value["validation_lanes"][2]["nodes"][0].update({"status": "existing"}),
        lambda value: value["validation_lanes"][0]["nodes"][0].pop("status"),
        lambda value: value["validation_lanes"][0]["nodes"][0].pop("required_by"),
        lambda value: value["validation_lanes"][1]["nodes"].pop(2),
        lambda value: value["validation_lanes"][1]["nodes"][2].update(
            {
                "test_ref": (
                    "internal/handler/knowledge_revision_test.go::"
                    "TestGetKnowledgeRevisionFuturePlaceholder"
                )
            }
        ),
        lambda value: value["validation_lanes"][1]["nodes"][2].update(
            {"proves": ["in_progress_last_committed"]}
        ),
        lambda value: value["validation_lanes"][1]["nodes"][2].update({"status": "existing"}),
        lambda value: value["validation_lanes"][1]["nodes"][2].update(
            {"required_by": "artifact_pr"}
        ),
    ],
)
def test_plugin_contract_rejects_unresolved_or_untruthful_validation_nodes(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["endpoints"][0]["success"].pop("root_success"),
        lambda value: value["endpoints"][0]["success"].update({"root_success": False}),
        lambda value: value["endpoints"][0]["success"]["required_fields"].remove("success"),
        lambda value: value["typed_errors"][0].pop("root_success"),
        lambda value: value["typed_errors"][0].update({"root_success": True}),
        lambda value: value["typed_errors"][0]["required_fields"].remove("error"),
        lambda value: value["typed_errors"][0]["error_required_fields"].remove("code"),
        lambda value: value["typed_errors"][0].update(
            {"last_committed": "forbidden", "last_committed_required_fields": []}
        ),
        lambda value: value["typed_errors"][1].update(
            {"last_committed": "forbidden", "last_committed_required_fields": []}
        ),
        lambda value: value["typed_errors"][2].update(
            {
                "last_committed": "required_when_prior_committed",
                "last_committed_required_fields": [
                    "parse_attempt",
                    "manifest_digest",
                    "completed_at",
                ],
            }
        ),
    ],
)
def test_plugin_contract_rejects_incomplete_or_false_response_envelopes(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("timeout_policy"),
        lambda value: value["timeout_policy"].update({"connect_seconds": 0}),
        lambda value: value["timeout_policy"].update({"overall_seconds": 301}),
        lambda value: value["endpoints"][0].pop("timeout_policy_ref"),
        lambda value: value["endpoints"][0].update({"timeout_policy_ref": "unknown_timeout"}),
    ],
)
def test_plugin_contract_rejects_missing_invalid_or_unbound_timeout_policy(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["endpoints"].append(
            {
                **copy.deepcopy(value["endpoints"][0]),
                "endpoint_id": "knowledge_search",
                "path": "/api/v1/knowledge/search",
                "request": {
                    **copy.deepcopy(value["endpoints"][0]["request"]),
                    "path_parameters": [],
                },
            }
        ),
        lambda value: value["typed_errors"].append(
            {
                **copy.deepcopy(value["typed_errors"][0]),
                "code": "unexpected_error",
            }
        ),
        lambda value: value["typed_errors"].append(copy.deepcopy(value["typed_errors"][0])),
        lambda value: value["idempotency_identities"].update({"unexpected_get": ["space_binding"]}),
        lambda value: value["readiness_signals"].append(
            copy.deepcopy(value["readiness_signals"][0])
        ),
        lambda value: value["typed_errors"].reverse(),
        lambda value: value.update({"contract_version": 2}),
        lambda value: value["states"]["consumer_adapted"].update({"available": True}),
        lambda value: value["states"]["consumer_adapted"].update({"status": "adapted"}),
        lambda value: value["states"]["w1_runtime"].update({"available": True}),
        lambda value: value["states"]["source_reader_authority"].update({"available": True}),
        lambda value: value["states"]["artifact_gate"].update({"available": True}),
    ],
)
def test_plugin_contract_schema_v1_rejects_extras_version_and_conflated_states(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["endpoints"][1].update(
            {"path": "/api/v1/knowledge/{knowledge_id}/detail"}
        ),
        lambda value: value["endpoints"][2]["success"].update({"revision_required_fields": []}),
        lambda value: value["typed_errors"][5].update(
            {"status": 409, "disposition": "bounded_get_retry"}
        ),
        lambda value: value["readiness_signals"][2]["requires"].remove("source_reader_authority"),
        lambda value: value["idempotency_identities"]["knowledge_get"].remove("knowledge_id"),
    ],
    ids=[
        "knowledge-get-path",
        "revision-descriptor-envelope",
        "revision-superseded-semantics",
        "w1-readiness-authority",
        "knowledge-get-idempotency",
    ],
)
def test_plugin_contract_schema_v1_rejects_public_contract_value_drift(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError, match="schema-version-1"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


def test_plugin_contract_canonical_json_ignores_mapping_order_comments_and_formatting(
    tmp_path: Path,
) -> None:
    value = _contract_value()
    reordered = {key: value[key] for key in reversed(value)}
    path = tmp_path / "reformatted-contract.yaml"
    path.write_text(
        "# mapping order and formatting are not semantic\n"
        + yaml.safe_dump(reordered, sort_keys=True, width=40),
        encoding="utf-8",
    )

    contract = adoption.load_plugin_contract(path)

    assert contract.schema_version == 1


def test_plugin_contract_schema_v1_digest_is_single_lowercase_sha256(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256 == (
        adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256.lower()
    )
    assert len(adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256) == 64
    assert set(adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256) <= set("0123456789abcdef")

    monkeypatch.setattr(adoption, "PLUGIN_CONTRACT_SCHEMA_V1_SHA256", "not-a-sha256")
    with pytest.raises(AdoptionTargetError, match="trust anchor"):
        adoption.load_plugin_contract(PLUGIN_CONTRACT)


def test_plugin_contract_canonical_json_is_fixed_and_utf8() -> None:
    value = {"z": [1, True, None], "a": "合同"}

    assert adoption._canonical_semantic_json(value) == ('{"a":"合同","z":[1,true,null]}'.encode())


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        float("nan"),
        datetime(2026, 7, 28, 12, 0),
        {1: "non-string-key"},
        b"custom-type",
    ],
    ids=["float", "nan", "timestamp", "non-string-key", "custom-type"],
)
def test_plugin_contract_canonical_json_rejects_nonsemantic_types(value: object) -> None:
    with pytest.raises(AdoptionTargetError, match="semantic JSON"):
        adoption._canonical_semantic_json(value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["validation_lanes"][1]["nodes"].pop(0),
        lambda value: value["validation_lanes"][1]["nodes"].append(
            {
                **copy.deepcopy(value["validation_lanes"][1]["nodes"][0]),
                "node_id": "compatibility.extra_existing",
            }
        ),
        lambda value: value["validation_lanes"][1]["nodes"].reverse(),
        lambda value: value["validation_lanes"][2]["nodes"].pop(0),
        lambda value: value["validation_lanes"][2]["nodes"].append(
            {
                **copy.deepcopy(value["validation_lanes"][2]["nodes"][0]),
                "node_id": "artifact.extra_probe",
                "test_ref": ".github/workflows/weknora-app-local-live-image.yml::extra_probe",
            }
        ),
        lambda value: value["validation_lanes"][2]["nodes"].reverse(),
    ],
    ids=[
        "existing-delete",
        "existing-add",
        "existing-reorder",
        "artifact-delete",
        "artifact-add",
        "artifact-reorder",
    ],
)
def test_plugin_contract_digest_rejects_validation_node_set_or_order_mutation(
    tmp_path: Path, mutation: object
) -> None:
    value = _contract_value()
    mutation(value)  # type: ignore[operator]

    with pytest.raises(AdoptionTargetError, match="schema-version-1"):
        adoption.load_plugin_contract(_write_yaml(tmp_path, "contract.yaml", value))


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("dirty", "target_dirty"),
        ("wrong_head", "target_head_mismatch"),
        ("missing_ancestor", "target_ancestor_missing"),
    ],
)
def test_check_blocks_sanitized_target_identity_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_code: str,
) -> None:
    manifest, target_checkout, runtime_lock, inventory = _write_check_inputs(tmp_path)

    def fake_git(cwd: Path, *args: str) -> str:
        assert cwd == target_checkout
        command = tuple(args)
        if command == ("status", "--porcelain"):
            return " M secret-path" if failure == "dirty" else ""
        if command == ("remote", "get-url", "origin"):
            return REPOSITORY
        if command == ("rev-parse", "HEAD"):
            return "0" * 40 if failure == "wrong_head" else CHECK_TARGET
        if command == ("rev-parse", "HEAD^{tree}"):
            return CHECK_TREE
        if command[:2] == ("merge-base", "--is-ancestor"):
            if failure == "missing_ancestor":
                raise AdoptionTargetError("untrusted git stderr")
            return ""
        raise AssertionError(command)

    monkeypatch.setattr(adoption, "_run_git", fake_git)
    result = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=REPOSITORY_ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=inventory,
        plugin_contract=PLUGIN_CONTRACT,
    )

    assert result["verdict"] == "block"
    assert result["hard_checks"] == {"code": expected_code, "status": "block"}
    serialized = json.dumps(result, sort_keys=True)
    assert "secret-path" not in serialized
    assert str(target_checkout) not in serialized
    assert "untrusted git stderr" not in serialized


def test_check_uses_true_merge_base_and_runtime_as_separate_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, target_checkout, runtime_lock, inventory = _write_check_inputs(tmp_path)
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_git(cwd: Path, *args: str) -> str:
        command = tuple(args)
        calls.append((cwd, command))
        if cwd == target_checkout:
            if command == ("status", "--porcelain"):
                return ""
            if command == ("remote", "get-url", "origin"):
                return REPOSITORY.removesuffix(".git")
            if command == ("rev-parse", "HEAD"):
                return CHECK_TARGET
            if command == ("rev-parse", "HEAD^{tree}"):
                return CHECK_TREE
            if command[:2] == ("merge-base", "--is-ancestor"):
                return ""
        if cwd == REPOSITORY_ROOT:
            if command == ("cat-file", "-e", f"{CHECK_RUNTIME}^{{commit}}"):
                return ""
            if command == ("rev-parse", f"{CHECK_RUNTIME}^{{tree}}"):
                return CHECK_RUNTIME_TREE
            if command == ("rev-parse", "HEAD"):
                return CHECK_PROJECT_HEAD
            if command == ("merge-base", CHECK_PROJECT_HEAD, CHECK_TARGET):
                return CHECK_MERGE_BASE
            if command == (
                "diff",
                "--name-only",
                f"{CHECK_MERGE_BASE}..{CHECK_TARGET}",
            ):
                return "internal/handler/knowledge.go\nother/project.go\n"
            if command == ("diff", "--name-only", f"{CHECK_RUNTIME}..{CHECK_TARGET}"):
                return "other/runtime.go\ninternal/types/knowledge.go\n"
            if command == (
                "merge-base",
                "--is-ancestor",
                CHECK_TARGET,
                CHECK_PROJECT_HEAD,
            ):
                raise AdoptionTargetError("not an ancestor")
        raise AssertionError((cwd, command))

    monkeypatch.setattr(adoption, "_run_git", fake_git)
    result = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=REPOSITORY_ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=inventory,
        plugin_contract=PLUGIN_CONTRACT,
    )

    assert result["verdict"] == "manual_review_required"
    assert result["overlaps"] == {
        "project_merge_base_to_target": ["internal/handler/knowledge.go"],
        "runtime_to_target": ["internal/types/knowledge.go"],
    }
    official_migrations = result["official_migrations"]
    assert isinstance(official_migrations, dict)
    assert official_migrations["status"] == "pre_merge"
    assert official_migrations["head"] == 2
    assert len(official_migrations["files"]) == 6
    parsed_contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    nodes = [node for lane in parsed_contract.validation_lanes for node in lane.nodes]
    assert result["plugin_contract"] == {
        "digest": adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256,
        "existing": sum(node.status == "existing" for node in nodes),
        "planned_artifact": sum(
            node.status == "planned" and node.required_by == "artifact_pr" for node in nodes
        ),
        "planned_code": sum(
            node.status == "planned" and node.required_by == "code_pr" for node in nodes
        ),
        "status": "valid",
    }
    assert (REPOSITORY_ROOT, ("merge-base", CHECK_PROJECT_HEAD, CHECK_TARGET)) in calls
    assert (REPOSITORY_ROOT, ("merge-base", CHECK_RUNTIME, CHECK_TARGET)) not in calls
    substitute = tmp_path / "same-inventory.yaml"
    substitute.write_bytes(inventory.read_bytes())
    substituted = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=REPOSITORY_ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=substitute,
        plugin_contract=PLUGIN_CONTRACT,
    )
    assert substituted["verdict"] == "block"
    assert substituted["hard_checks"] == {
        "code": "inventory_path_mismatch",
        "status": "block",
    }


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("pair", "official_migrations_invalid"),
        ("head", "official_migrations_invalid"),
        ("mismatch", "project_migrations_mismatch"),
        ("extra", "project_migrations_mismatch"),
    ],
)
def test_check_blocks_migration_pair_head_and_postmerge_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_code: str,
) -> None:
    manifest, target_checkout, runtime_lock, inventory = _write_check_inputs(tmp_path)
    target_migrations = target_checkout / "migrations" / "versioned"
    project_checkout = tmp_path / "project"
    project_migrations = project_checkout / "migrations" / "versioned"
    project_migrations.mkdir(parents=True)
    for source in target_migrations.iterdir():
        (project_migrations / source.name).write_bytes(source.read_bytes())
    if case == "pair":
        (target_migrations / "000002_migration_2.down.sql").unlink()
    elif case == "head":
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["official_migration_head"] = 3
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif case == "mismatch":
        (project_migrations / "000001_migration_1.up.sql").write_text(
            "-- changed\n", encoding="utf-8"
        )
    else:
        for direction in ("up", "down"):
            (project_migrations / f"000003_extra.{direction}.sql").write_text(
                "-- extra\n", encoding="utf-8"
            )

    parsed_contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    canonical_inventory = project_checkout / parsed_contract.patch_inventory_ref
    canonical_inventory.parent.mkdir(parents=True)
    canonical_inventory.write_bytes(inventory.read_bytes())
    inventory = canonical_inventory
    monkeypatch.setattr(
        adoption,
        "load_plugin_contract",
        lambda *_args, **_kwargs: parsed_contract,
    )

    def fake_git(cwd: Path, *args: str) -> str:
        command = tuple(args)
        if cwd == target_checkout:
            if command == ("status", "--porcelain"):
                return ""
            if command == ("remote", "get-url", "origin"):
                return REPOSITORY
            if command == ("rev-parse", "HEAD"):
                return CHECK_TARGET
            if command == ("rev-parse", "HEAD^{tree}"):
                return CHECK_TREE
            if command[:2] == ("merge-base", "--is-ancestor"):
                return ""
        if cwd == project_checkout:
            if command == ("cat-file", "-e", f"{CHECK_RUNTIME}^{{commit}}"):
                return ""
            if command == ("rev-parse", f"{CHECK_RUNTIME}^{{tree}}"):
                return CHECK_RUNTIME_TREE
            if command == ("rev-parse", "HEAD"):
                return CHECK_PROJECT_HEAD
            if command == ("merge-base", CHECK_PROJECT_HEAD, CHECK_TARGET):
                return CHECK_MERGE_BASE
            if command[0] == "diff":
                return ""
            if command == (
                "merge-base",
                "--is-ancestor",
                CHECK_TARGET,
                CHECK_PROJECT_HEAD,
            ):
                return ""
        raise AssertionError((cwd, command))

    monkeypatch.setattr(adoption, "_run_git", fake_git)
    result = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=project_checkout,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=inventory,
        plugin_contract=PLUGIN_CONTRACT,
    )

    assert result["verdict"] == "block"
    hard_checks = result["hard_checks"]
    assert isinstance(hard_checks, dict)
    assert hard_checks["code"] == expected_code


def test_check_runtime_lock_and_inventory_are_closed_but_format_invariant(
    tmp_path: Path,
) -> None:
    _, _, runtime_lock, inventory = _write_check_inputs(tmp_path)
    assert adoption._load_runtime_source_lock(runtime_lock) == (
        REPOSITORY,
        CHECK_RUNTIME,
        CHECK_RUNTIME_TREE,
    )
    reordered = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    reformatted = tmp_path / "inventory-reformatted.yaml"
    reformatted.write_text(
        "# formatting is not semantic\n" + yaml.safe_dump(reordered, sort_keys=True),
        encoding="utf-8",
    )
    assert adoption._load_w1_paths(inventory) == adoption._load_w1_paths(reformatted)

    invalid = json.loads(runtime_lock.read_text(encoding="utf-8"))
    invalid["repository"] = "https://example.invalid/private.git"
    runtime_lock.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(AdoptionTargetError):
        adoption._load_runtime_source_lock(runtime_lock)


@pytest.mark.parametrize(
    "bad_path",
    [
        "internal/./handler.go",
        "internal//handler.go",
        ".",
        "/internal/handler.go",
        "internal/",
        r"internal\handler.go",
    ],
)
def test_check_inventory_rejects_noncanonical_paths(tmp_path: Path, bad_path: str) -> None:
    inventory = _write_yaml(
        tmp_path,
        "bad-inventory.yaml",
        {"patches": [{"patch_id": "W1", "file_path": [bad_path]}]},
    )
    with pytest.raises(AdoptionTargetError):
        adoption._load_w1_paths(inventory)


@pytest.mark.parametrize(
    "loader",
    [adoption.load_adoption_target, adoption._load_runtime_source_lock, adoption._load_w1_paths],
)
def test_check_loaders_sanitize_invalid_utf8(tmp_path: Path, loader: object) -> None:
    path = tmp_path / "invalid"
    path.write_bytes(b"\xff")
    with pytest.raises(AdoptionTargetError):
        loader(path)  # type: ignore[operator]


def test_check_cli_sanitizes_invalid_utf8_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["check"]
    for name in (
        "target-manifest",
        "project-checkout",
        "target-checkout",
        "runtime-source-lock",
        "inventory",
        "plugin-contract",
    ):
        args.extend((f"--{name}", str(tmp_path / name)))
    (tmp_path / "target-manifest").write_bytes(b"\xff")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["hard_checks"]["code"] == "target_manifest_invalid"
    assert str(tmp_path) not in captured.out


@pytest.mark.parametrize(
    ("verdict", "expected_status"), [("pass", 0), ("manual_review_required", 0), ("block", 1)]
)
def test_check_cli_renders_deterministic_json_and_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verdict: str,
    expected_status: int,
) -> None:
    result = {
        "schema_version": 1,
        "verdict": verdict,
        "target": {},
        "hard_checks": {"code": "ok", "status": "pass"},
        "overlaps": {},
        "official_migrations": {},
        "plugin_contract": {},
    }
    monkeypatch.setattr(adoption, "run_adoption_check", lambda **_kwargs: result)
    args = [
        "check",
        "--target-manifest",
        str(tmp_path / "manifest"),
        "--project-checkout",
        str(tmp_path / "project"),
        "--target-checkout",
        str(tmp_path / "target"),
        "--runtime-source-lock",
        str(tmp_path / "lock"),
        "--inventory",
        str(tmp_path / "inventory"),
        "--plugin-contract",
        str(tmp_path / "plugin"),
    ]

    assert main(args) == expected_status
    captured = capsys.readouterr()
    assert captured.err == ""
    assert (
        captured.out
        == json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    )


def test_check_cli_missing_arguments_is_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["check"]) == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert captured.out == ""

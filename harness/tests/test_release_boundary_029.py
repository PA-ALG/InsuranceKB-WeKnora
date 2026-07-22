"""OpenSpec 029 RA6: staging-only legacy publisher and P-1 fail-closed boundary."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import textwrap
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

import tests.support.legacy_publisher_007 as legacy_publisher_module
import tests.support.release_publisher_018 as release_publisher_module
from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.pages import RenderedPage, render_snapshot_pages
from insurance_harness.knowledge.release_boundary import (
    P1CapabilityMissing,
    ProductionWikiPublishRequest,
    build_staging_candidate_manifest,
    request_production_wiki_publish,
)
from insurance_harness.knowledge.release_manifest import ReleaseManifest
from insurance_harness.knowledge.serving import ServingFailure
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseApproval,
    ReleaseSnapshot,
    SnapshotFact,
)
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)
from tests.support.release_plan_018 import (
    PublishAction,
    PublishPlan,
    ReleasePlanExecutor,
    StagingCapabilityRequired,
    WikiPageClient,
    _issue_test_staging_capability,
)
from tests.support.release_publisher_018 import (
    LegacyStagingReleasePublisher,
    ReleasePublisher,
)
from tests.test_serving_reader_029 import _approved_release, _reader

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _building_frozen_candidate(
    session: Session,
    suffix: str,
) -> tuple[KnowledgeScope, str]:
    scope = release_scope(session, suffix)
    _product, version = release_product(session, scope, code=f"STAGE-{suffix}")
    release_claim(
        session,
        scope,
        version,
        claim_id=f"claim-stage-{suffix}",
        predicate="waiting_period",
    )
    snapshot_id = f"snapshot-stage-{suffix}"
    facts = [
        fact.model_copy(
            update={
                "evidence": tuple(
                    evidence.model_copy(
                        update={
                            "extracted_at": NOW,
                            "created_at": NOW,
                            "updated_at": NOW,
                        }
                    )
                    for evidence in fact.evidence
                )
            }
        )
        for fact in build_snapshot_facts(session, scope, snapshot_id=snapshot_id)
    ]
    pages = [
        page.model_dump(mode="json")
        for page in render_snapshot_pages(
            facts,
            space_id=scope.space_id,
            snapshot_id=snapshot_id,
            compiled_at=NOW,
        )
    ]
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=snapshot_id,
        rendered_pages=pages,
        status="building",
        read_model_version=1,
        projection_frozen_at=None,
        published_at=None,
        published_by="staging-test",
    )
    session.add(snapshot)
    session.flush()
    for index, fact in enumerate(facts):
        session.add(
            SnapshotFact(
                id=f"fact-stage-{suffix}-{index}",
                space_id=fact.space_id,
                snapshot_id=snapshot_id,
                claim_id=fact.claim_id,
                revision_no=fact.revision_no,
                product_id=fact.product_id,
                product_version_id=fact.product_version_id,
                product_code=fact.product_code,
                product_name=fact.product_name,
                version_label=fact.version_label,
                predicate=fact.predicate,
                field_name=fact.field_name,
                field_group=fact.field_group,
                value_state=fact.value_state,
                value=fact.value,
                effective_from=fact.effective_from,
                effective_to=fact.effective_to,
                confidence=fact.confidence,
                schema_version=fact.schema_version,
                evidence=[item.model_dump(mode="json") for item in fact.evidence],
            )
        )
    session.flush()
    snapshot.projection_frozen_at = NOW
    session.commit()
    return scope, snapshot_id


def test_ra6_building_frozen_candidate_isolated_from_release_and_wiki(
    session: Session,
) -> None:
    scope, snapshot_id = _building_frozen_candidate(session, "candidate")

    before_approvals = session.scalar(select(func.count()).select_from(ReleaseApproval))
    manifest = build_staging_candidate_manifest(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version="v1.1+release",
        template_hashes=(_A, _B),
        model_plan_hash=_C,
    )

    assert isinstance(manifest, ReleaseManifest)
    assert manifest.snapshot_id == snapshot_id
    assert session.get(CurrentRelease, (scope.space_id, "current")) is None
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == (
        before_approvals
    )
    serving = _reader(session).read_current(scope)
    assert isinstance(serving, ServingFailure)
    assert serving.code == "no_release"


def test_ra6_production_wiki_request_is_typed_blocked_and_preserves_serving(
    session: Session,
) -> None:
    approved = _approved_release(session, "p1-blocked")
    reader = _reader(session)
    before = reader.read_current(approved.scope)
    pointer_before = session.get(
        CurrentRelease,
        (approved.scope.space_id, "current"),
    )
    assert pointer_before is not None
    approval_count = session.scalar(select(func.count()).select_from(ReleaseApproval))
    request = ProductionWikiPublishRequest(
        scope=approved.scope,
        snapshot_id=approved.manifest.snapshot_id,
        manifest_hash=approved.manifest.manifest_sha256,
        principal="release.owner@example.com",
        reason="request ordinary-user production Wiki publication",
    )

    blocked = request_production_wiki_publish(request)

    assert blocked == P1CapabilityMissing(
        status="blocked",
        code="p1_capability_missing",
    )
    pointer_after = session.get(
        CurrentRelease,
        (approved.scope.space_id, "current"),
    )
    assert pointer_after is not None
    assert pointer_after.snapshot_id == pointer_before.snapshot_id
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == approval_count
    assert reader.read_current(approved.scope) == before


def test_ra6_production_request_has_no_silent_identity_defaults() -> None:
    with pytest.raises(ValidationError):
        ProductionWikiPublishRequest.model_validate({})
    for field, value in (
        ("snapshot_id", ""),
        ("manifest_hash", "not-a-hash"),
        ("principal", " model "),
        ("reason", ""),
    ):
        payload = {
            "scope": {
                "space_id": "space",
                "tenant_id": "tenant",
                "raw_kb_id": "raw",
                "wiki_kb_id": "wiki",
            },
            "snapshot_id": "snapshot",
            "manifest_hash": "a" * 64,
            "principal": "human@example.com",
            "reason": "reviewed",
        }
        payload[field] = value
        with pytest.raises(ValidationError):
            ProductionWikiPublishRequest.model_validate(payload)


def test_ra6_package_exports_production_boundary_not_legacy_publisher() -> None:
    from insurance_harness import knowledge

    assert knowledge.ProductionWikiPublishRequest is ProductionWikiPublishRequest
    assert knowledge.P1CapabilityMissing is P1CapabilityMissing
    assert knowledge.build_staging_candidate_manifest is build_staging_candidate_manifest
    assert knowledge.request_production_wiki_publish is request_production_wiki_publish
    for legacy in (
        "ReleasePublisher",
        "PublishResult",
        "RollbackResult",
        "ReleasePlanExecutor",
        "WikiPageClient",
        "PublishPlan",
        "PublishAction",
        "ActionExecution",
        "LegacyPageOwnership",
        "PageOwnershipCollision",
        "WikiWriteVerificationError",
    ):
        assert not hasattr(knowledge, legacy)
        assert legacy not in knowledge.__all__


def test_ra6_production_package_has_no_legacy_wiki_execution_modules() -> None:
    for module_name in (
        "insurance_harness.knowledge.publisher",
        "insurance_harness.knowledge.release_plan",
    ):
        assert importlib.util.find_spec(module_name) is None
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)


def test_ra6_legacy_publisher_remains_direct_module_characterization_only() -> None:
    assert LegacyStagingReleasePublisher is ReleasePublisher
    assert "staging/test-only" in (ReleasePublisher.__doc__ or "")


def test_ra6_executor_and_publisher_require_opaque_capability_before_side_effects() -> None:
    class ExplodingWiki:
        calls = 0

        def __getattribute__(self, name: str) -> object:
            if name != "calls":
                object.__setattr__(self, "calls", self.calls + 1)
                raise AssertionError("Wiki client surface must not be inspected")
            return object.__getattribute__(self, name)

    exploding_wiki = ExplodingWiki()
    wiki = cast(WikiPageClient, exploding_wiki)
    with pytest.raises(StagingCapabilityRequired):
        ReleasePlanExecutor(wiki)
    with pytest.raises(StagingCapabilityRequired):
        ReleasePlanExecutor(wiki, staging_capability=object())

    factory_calls = 0

    def exploding_factory() -> Session:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("session factory must not be opened")

    with pytest.raises(StagingCapabilityRequired):
        ReleasePublisher(exploding_factory, wiki)
    with pytest.raises(StagingCapabilityRequired):
        ReleasePublisher(
            exploding_factory,
            wiki,
            staging_capability=object(),
        )
    assert factory_calls == 0
    assert exploding_wiki.calls == 0


@pytest.mark.asyncio
async def test_ra6_capability_is_exact_for_every_executor_entrypoint(
    session: Session,
) -> None:
    scope_a = release_scope(session, "capability-a")
    scope_b = release_scope(session, "capability-b")
    session.commit()
    capability = _issue_test_staging_capability(scope_a)

    class ExplodingWiki:
        calls = 0

        async def get_wiki_page(self, *_args: object) -> object:
            self.calls += 1
            raise AssertionError("wrong-scope execution reached Wiki")

    exploding_wiki = ExplodingWiki()
    wiki = cast(WikiPageClient, exploding_wiki)
    executor = ReleasePlanExecutor(wiki, staging_capability=capability)
    plan = PublishPlan(
        base_snapshot_id=None,
        target_snapshot_id="target",
        actions=(),
        compensation_actions=(),
    )

    with pytest.raises(StagingCapabilityRequired):
        executor.space_lock(scope_b)
    with pytest.raises(StagingCapabilityRequired):
        await executor.execute(scope_b, plan)
    with pytest.raises(StagingCapabilityRequired):
        await executor._execute_locked(scope_b, plan)
    action = PublishAction(kind="delete", slug="never-touch")
    with pytest.raises(StagingCapabilityRequired):
        await executor._execute_action(scope_b, action, None)
    page = RenderedPage(
        slug="never-touch",
        title="Never touch",
        content="# Never touch",
        page_metadata={
            "managed_by": "insurance-harness",
            "space_id": scope_b.space_id,
            "snapshot_id": "target",
        },
    )
    with pytest.raises(StagingCapabilityRequired):
        await executor._verify_upsert(
            scope_b,
            page,
            created_new=False,
            legacy_ownership=None,
        )

    object.__setattr__(executor, "_staging_capability", object())
    with pytest.raises(StagingCapabilityRequired):
        await executor._execute_action(scope_a, action, None)
    assert exploding_wiki.calls == 0


@pytest.mark.asyncio
async def test_ra6_publisher_wrong_scope_capability_blocks_before_db_mutation_or_client(
    session: Session,
) -> None:
    scope_a = release_scope(session, "publisher-cap-a")
    scope_b = release_scope(session, "publisher-cap-b")
    _product, version_b = release_product(session, scope_b, code="CAP-B")
    session.commit()
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    capability = _issue_test_staging_capability(scope_a)

    class ExplodingWiki:
        calls = 0

        def __getattribute__(self, name: str) -> object:
            if name != "calls":
                object.__setattr__(self, "calls", self.calls + 1)
                raise AssertionError("wrong-scope publisher reached Wiki")
            return object.__getattribute__(self, name)

    exploding_wiki = ExplodingWiki()
    wiki = cast(WikiPageClient, exploding_wiki)
    publisher = ReleasePublisher(
        session_factory=lambda: Session(bind),
        wiki_client=wiki,
        staging_capability=capability,
    )
    before = {
        table: session.scalar(select(func.count()).select_from(table))
        for table in (ReleaseSnapshot, CurrentRelease)
    }

    with pytest.raises(StagingCapabilityRequired):
        await publisher.publish_product_version(
            scope_b,
            product_version_id=version_b.id,
            label="capability-boundary",
        )

    session.expire_all()
    assert {
        table: session.scalar(select(func.count()).select_from(table))
        for table in (ReleaseSnapshot, CurrentRelease)
    } == before
    assert exploding_wiki.calls == 0


@pytest.mark.asyncio
async def test_ra6_publisher_private_io_entrypoints_recheck_capability_first(
    session: Session,
) -> None:
    scope_a = release_scope(session, "publisher-private-a")
    scope_b = release_scope(session, "publisher-private-b")
    _product, version_b = release_product(session, scope_b, code="PRIVATE-B")
    session.commit()
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    factory_calls = 0

    def counted_factory() -> Session:
        nonlocal factory_calls
        factory_calls += 1
        return Session(bind)

    publisher = ReleasePublisher(
        counted_factory,
        cast(WikiPageClient, object()),
        staging_capability=_issue_test_staging_capability(scope_a),
    )
    factory_calls = 0

    with pytest.raises(StagingCapabilityRequired):
        await publisher._publish_product_version_locked(
            scope_b,
            product_version_id=version_b.id,
            label="private-boundary",
            published_by="reviewer",
            registry=None,
            field_names=None,
            doc_titles=None,
            notes=None,
        )
    assert factory_calls == 0

    object.__setattr__(publisher, "_staging_capability", object())
    with pytest.raises(StagingCapabilityRequired):
        await publisher._publish_product_version_locked(
            scope_a,
            product_version_id=version_b.id,
            label="forged-boundary",
            published_by="reviewer",
            registry=None,
            field_names=None,
            doc_titles=None,
            notes=None,
        )
    assert factory_calls == 0


def test_ra6_production_blocked_signature_and_ast_have_no_client_surface() -> None:
    parameters = inspect.signature(request_production_wiki_publish).parameters
    assert tuple(parameters) == ("request",)
    assert not {
        "client",
        "wiki_client",
        "executor",
        "release_publisher",
    } & set(parameters)


def test_ra6_test_only_private_io_entrypoints_recheck_capability_first() -> None:
    required = {
        ReleasePlanExecutor: {
            "_execute_action",
            "_execute_locked",
            "_verify_upsert",
        },
        ReleasePublisher: {
            "_activate",
            "_attempt_finished",
            "_attempt_started",
            "_build_operation",
            "_build_rollback_operation",
            "_current_id",
            "_execute_active",
            "_fail_reconcile",
            "_finalize",
            "_finalize_reconcile",
            "_legacy_ownership",
            "_load_operation",
            "_mark_failed",
            "_operation_may_have_mutated",
            "_prepare_reconcile",
            "_publish_product_version_locked",
            "_reconcile_operation_locked",
            "_recover_expired_locked",
            "_retry_operation_locked",
            "_rollback_to_snapshot_locked",
        },
    }
    for owner, method_names in required.items():
        for method_name in method_names:
            tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(owner, method_name))))
            method = tree.body[0]
            assert isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            first = method.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                first = method.body[1]
            assert isinstance(first, ast.Expr), f"{owner.__name__}.{method_name}"
            assert isinstance(first.value, ast.Call), f"{owner.__name__}.{method_name}"
            assert (
                isinstance(first.value.func, ast.Name)
                and first.value.func.id == "_require_staging_capability"
            ), f"{owner.__name__}.{method_name}"


def test_ra6_test_only_module_io_entrypoints_require_capability_first() -> None:
    io_methods = {
        "add",
        "begin_nested",
        "commit",
        "create_wiki_page",
        "execute",
        "flush",
        "get",
        "get_wiki_page",
        "scalar",
        "scalars",
        "update_wiki_page",
    }
    indirect_io_helpers = {"require_current_scope"}
    discovered: set[str] = set()
    for module in (release_publisher_module, legacy_publisher_module):
        tree = ast.parse(inspect.getsource(module))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            touches_io = any(
                isinstance(child, ast.Call)
                and (
                    (
                        isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id in {"client", "session"}
                        and child.func.attr in io_methods
                    )
                    or (
                        isinstance(child.func, ast.Name)
                        and child.func.id in indirect_io_helpers
                        and len(child.args) >= 2
                        and isinstance(child.args[0], ast.Name)
                        and child.args[0].id == "session"
                        and isinstance(child.args[1], ast.Name)
                        and child.args[1].id == "scope"
                    )
                )
                for child in ast.walk(node)
            )
            if not touches_io:
                continue
            qualified_name = f"{module.__name__}.{node.name}"
            discovered.add(qualified_name)
            parameter_names = {
                argument.arg
                for argument in (*node.args.args, *node.args.kwonlyargs)
            }
            assert "staging_capability" in parameter_names, qualified_name
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                first = node.body[1]
            assert isinstance(first, ast.Expr), qualified_name
            assert isinstance(first.value, ast.Call), qualified_name
            assert (
                isinstance(first.value.func, ast.Name)
                and first.value.func.id == "_require_staging_capability"
            ), qualified_name
    assert discovered == {
        "tests.support.legacy_publisher_007._move_pointer",
        "tests.support.legacy_publisher_007._snapshot_claims_for_publish",
        "tests.support.legacy_publisher_007._validate_rollback_pages",
        "tests.support.legacy_publisher_007.legacy_publish_product_version",
        "tests.support.legacy_publisher_007.legacy_rollback_to_snapshot",
        "tests.support.release_publisher_018._require_label_available",
        "tests.support.release_publisher_018._require_scoped_product_version",
        "tests.support.release_publisher_018._require_scoped_snapshot",
        "tests.support.release_publisher_018._upsert_page",
        "tests.support.release_publisher_018._validate_scope",
    }


@pytest.mark.asyncio
async def test_ra6_test_only_module_io_rejects_no_forged_and_wrong_capability(
    session: Session,
) -> None:
    scope_a = release_scope(session, "module-cap-a")
    scope_b = release_scope(session, "module-cap-b")
    session.commit()
    valid_for_a = _issue_test_staging_capability(scope_a)

    class ExplodingIO:
        calls = 0

        def __getattribute__(self, name: str) -> object:
            if name != "calls":
                object.__setattr__(self, "calls", self.calls + 1)
                raise AssertionError("module entrypoint reached DB/Wiki I/O")
            return object.__getattribute__(self, name)

    raw_session = ExplodingIO()
    raw_client = ExplodingIO()
    exploding_session = cast(Session, raw_session)
    exploding_client = cast(WeKnoraClient, raw_client)
    page = RenderedPage(
        slug="never-touch",
        title="Never touch",
        content="# Never touch",
        page_metadata={
            "managed_by": "insurance-harness",
            "space_id": scope_b.space_id,
            "snapshot_id": "target",
        },
    )

    for invalid_capability in (None, object(), valid_for_a):
        with pytest.raises(StagingCapabilityRequired):
            release_publisher_module._validate_scope(
                exploding_session,
                scope_b,
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            release_publisher_module._require_scoped_product_version(
                exploding_session,
                scope_b,
                "never-touch",
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            release_publisher_module._require_scoped_snapshot(
                exploding_session,
                scope_b,
                "never-touch",
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            release_publisher_module._require_label_available(
                exploding_session,
                scope_b,
                "never-touch",
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            await release_publisher_module._upsert_page(
                exploding_client,
                scope_b,
                page,
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            legacy_publisher_module._snapshot_claims_for_publish(
                exploding_session,
                scope_b,
                "never-touch",
                [],
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            legacy_publisher_module._validate_rollback_pages(
                exploding_session,
                scope_b,
                cast(ReleaseSnapshot, object()),
                [],
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            legacy_publisher_module._move_pointer(
                exploding_session,
                scope_b,
                "never-touch",
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            await legacy_publisher_module.legacy_publish_product_version(
                exploding_session,
                exploding_client,
                scope_b,
                product_version_id="never-touch",
                label="never-touch",
                staging_capability=invalid_capability,
            )
        with pytest.raises(StagingCapabilityRequired):
            await legacy_publisher_module.legacy_rollback_to_snapshot(
                exploding_session,
                exploding_client,
                scope_b,
                snapshot_id="never-touch",
                staging_capability=invalid_capability,
            )

    assert raw_session.calls == 0
    assert raw_client.calls == 0


def test_ra6_boundary_and_production_src_have_no_publish_bypass() -> None:
    import insurance_harness.knowledge.release_boundary as boundary_module

    boundary_path = Path(boundary_module.__file__)
    boundary_tree = ast.parse(boundary_path.read_text(encoding="utf-8"))
    boundary_modules = {
        node.module or ""
        for node in ast.walk(boundary_tree)
        if isinstance(node, ast.ImportFrom)
    }
    forbidden = {
        "publisher",
        "release_plan",
        "weknora",
        "runtime",
        "model",
        "provider",
    }
    assert not any(forbidden & set(module.split(".")) for module in boundary_modules)

    src_root = boundary_path.parents[2]
    bypasses: list[str] = []
    for path in src_root.rglob("*.py"):
        if path.name == "publisher.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_publisher = any(
            isinstance(node, ast.ImportFrom)
            and (node.module or "") == "insurance_harness.knowledge.publisher"
            and {alias.name for alias in node.names}
            & {
                "ReleasePublisher",
                "LegacyStagingReleasePublisher",
                "PublishResult",
                "RollbackResult",
            }
            for node in ast.walk(tree)
        )
        imports_legacy_name = any(
            isinstance(node, (ast.Name, ast.Attribute))
            and getattr(node, "id", getattr(node, "attr", None))
            in {"ReleasePublisher", "LegacyStagingReleasePublisher"}
            for node in ast.walk(tree)
        )
        if imports_publisher or imports_legacy_name:
            bypasses.append(str(path.relative_to(src_root)))
    assert bypasses == []

    issuer_calls = []
    for path in src_root.rglob("*.py"):
        if path.name == "release_plan.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
            and getattr(node.func, "id", getattr(node.func, "attr", None))
            == "_issue_test_staging_capability"
            for node in ast.walk(tree)
        ):
            issuer_calls.append(str(path.relative_to(src_root)))
    assert issuer_calls == []

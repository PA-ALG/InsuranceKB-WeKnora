"""Persisted workflow identity; no inference from stage names or error text."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import importlib.util
import typing
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import Table, create_engine, inspect, text

import insurance_harness
from insurance_harness.product_ingestion.tables import ProductRun
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_recovery import failed_capture
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401
from tests.product_ingestion.test_store import (
    _failed,
    _make_store,
    _reserve_and_record,
    _run_with_uploads,
    _scope,
    _start_window,
    _task,
    api,  # noqa: F401
    factory,  # noqa: F401
)


def test_new_upload_is_v3_and_idempotent_legacy_run_stays_v1(
    api: typing.Any, factory: typing.Any
) -> None:
    store, _ = _make_store(api, factory)
    scope = _scope(api)
    run = store.create_run(scope=scope, idempotency_key="workflow")
    assert run.workflow_version == 3
    with factory() as session, session.begin():
        row = session.get(ProductRun, run.run_id)
        row.workflow_version = 1
        original_version = row.version
    repeated = store.create_run(scope=scope, idempotency_key="workflow")
    assert repeated.run_id == run.run_id
    assert repeated.workflow_version == 1
    assert repeated.version == original_version


def test_direct_old_writer_defaults_to_v1_and_null_is_forbidden(
    api: typing.Any, factory: typing.Any
) -> None:
    from sqlalchemy.exc import IntegrityError

    column = ProductRun.__table__.c.get("workflow_version")
    assert column is not None, "persisted workflow version is missing"
    assert not column.nullable
    assert str(column.server_default.arg) == "1"
    store, _ = _make_store(api, factory)
    run = store.create_run(scope=_scope(api), idempotency_key="original")
    table = typing.cast(Table, ProductRun.__table__)
    with factory() as session, session.begin():
        row = session.get(ProductRun, run.run_id)
        assert row is not None
        values = {c.name: getattr(row, c.name) for c in table.columns}
        values.pop("workflow_version")
        values.update(id="old-writer", idempotency_key="old-writer")
        session.execute(table.insert().values(**values))
    assert store.get_run(scope=_scope(api), run_id="old-writer").workflow_version == 1
    with pytest.raises(IntegrityError), factory() as session, session.begin():
        session.execute(
            text("UPDATE product_ingestion_runs SET workflow_version=NULL WHERE id=:id"),
            {"id": run.run_id},
        )


@pytest.mark.parametrize("version", (1, 2))
def test_legacy_processing_child_inherits_persisted_workflow(
    stage_runtime: typing.Any, version: typing.Any
) -> None:
    scope, store, *_ = stage_runtime
    origin = failed_capture(stage_runtime)
    with store._session_factory() as session, session.begin():
        row = session.get(ProductRun, origin.run_id)
        row.workflow_version = version
    child = store._legacy_retry_processing(
        scope=scope, run_id=origin.run_id, expected_version=origin.version
    )
    assert child.workflow_version == version
    assert store.get_run(scope=scope, run_id=origin.run_id).workflow_version == version


@pytest.mark.parametrize("version", (1, 2))
def test_field_retry_child_inherits_persisted_workflow(
    api: typing.Any, factory: typing.Any, version: typing.Any
) -> None:
    store, jobs = _make_store(api, factory)
    run, _ = _run_with_uploads(api, store)
    with factory() as session, session.begin():
        session.get(ProductRun, run.run_id).workflow_version = version
    task = _task(api, "beta")
    _, running = _start_window(
        api, store, jobs, run_id=run.run_id, window_key="retry", tasks=(task,)
    )
    call = _reserve_and_record(
        api,  # noqa: F401
        store,
        running,
        run_id=run.run_id,
        window_key="retry",
        tasks=(task,),
        raw=b'{"mixed":true}',
    )
    store.settle_window(
        scope=_scope(api),
        run_id=run.run_id,
        job_id=running.id,
        generation=running.lease_generation,
        outcomes=(_failed(api, task, raw_ref=call.raw_ref, reason="missing_evidence"),),
    )
    before = store.list_field_attempts(scope=_scope(api), run_id=run.run_id)
    child = store.retry_fields(
        scope=_scope(api),
        run_id=run.run_id,
        failed_attempt_ids=(before[0].attempt_id,),
        idempotency_key="retry",
    )
    assert child.workflow_version == version
    assert store.list_field_attempts(scope=_scope(api), run_id=run.run_id) == before


def test_migration_preserves_existing_bytes_and_defaults_only_new_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = (
        Path(insurance_harness.__file__).resolve().parents[2]
        / "migrations/versions/0018_product_workflow_version.py"
    )
    assert path.is_file(), "workflow migration is missing"
    spec = importlib.util.spec_from_file_location("workflow_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0018" and module.down_revision == "0017"
    config = Config()
    config.set_main_option("script_location", str(path.parents[1]))
    script = ScriptDirectory.from_config(config)
    engine = create_engine(f"sqlite:///{tmp_path}/migration.db")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE product_ingestion_runs "
                "(id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload BLOB NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO product_ingestion_runs VALUES ('old', 29, X'00FF1234')")
        )
        before = connection.execute(
            text("SELECT id,version,payload FROM product_ingestion_runs")
        ).all()
        with EnvironmentContext(
            config, script, destination_rev="0017"
        ) as environment_context:
            environment_context.configure(connection=connection)
            monkeypatch.setattr(
                module, "op", Operations(environment_context.get_context())
            )
            module.upgrade()
            assert (
                connection.execute(
                    text("SELECT id,version,payload FROM product_ingestion_runs")
                ).all()
                == before
            )
            assert (
                connection.execute(
                    text("SELECT workflow_version FROM product_ingestion_runs")
                ).scalar_one()
                == 1
            )
            assert not next(
                c
                for c in inspect(connection).get_columns("product_ingestion_runs")
                if c["name"] == "workflow_version"
            )["nullable"]
            module.downgrade()
            assert (
                connection.execute(
                    text("SELECT id,version,payload FROM product_ingestion_runs")
                ).all()
                == before
            )
    engine.dispose()

"""Stable database guard DDL for OpenSpec 018 release read models.

This module is deliberately versioned in its name because Alembic revision 0005
imports it.  Changing these statements later requires a new migration.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import DDL, MetaData, event

SQLITE_CREATE_GUARDS = (
    """
    CREATE TRIGGER trg_snapshot_facts_insert_guard_018
    BEFORE INSERT ON snapshot_facts
    FOR EACH ROW
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM release_snapshots
            WHERE id = NEW.snapshot_id
              AND space_id = NEW.space_id
              AND status = 'building'
              AND projection_frozen_at IS NULL
        ) THEN RAISE(ABORT, 'snapshot projection is frozen') END;
    END
    """,
    """
    CREATE TRIGGER trg_snapshot_facts_update_guard_018
    BEFORE UPDATE ON snapshot_facts
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'snapshot facts are immutable');
    END
    """,
    """
    CREATE TRIGGER trg_snapshot_facts_delete_guard_018
    BEFORE DELETE ON snapshot_facts
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'snapshot facts are immutable');
    END
    """,
    """
    CREATE TRIGGER trg_release_snapshots_projection_guard_018
    BEFORE UPDATE ON release_snapshots
    FOR EACH ROW
    WHEN (
        OLD.projection_frozen_at IS NOT NULL
        AND NEW.projection_frozen_at IS NOT OLD.projection_frozen_at
    ) OR (
        (OLD.projection_frozen_at IS NOT NULL OR OLD.status = 'published')
        AND NEW.rendered_pages IS NOT OLD.rendered_pages
    )
    BEGIN
        SELECT RAISE(ABORT, 'snapshot projection is frozen');
    END
    """,
    """
    CREATE TRIGGER trg_release_operations_plan_guard_018
    BEFORE UPDATE ON release_operations
    FOR EACH ROW
    WHEN OLD.plan_frozen_at IS NOT NULL AND (
        NEW.plan_frozen_at IS NOT OLD.plan_frozen_at
        OR NEW.publish_plan IS NOT OLD.publish_plan
        OR NEW.plan_digest IS NOT OLD.plan_digest
    )
    BEGIN
        SELECT RAISE(ABORT, 'publish plan is frozen');
    END
    """,
    """
    CREATE TRIGGER trg_current_release_insert_guard_018
    BEFORE INSERT ON current_release
    FOR EACH ROW
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM release_snapshots
            WHERE id = NEW.snapshot_id
              AND space_id = NEW.space_id
              AND status = 'published'
              AND read_model_version = 1
              AND projection_frozen_at IS NOT NULL
        ) THEN RAISE(ABORT, 'current release target is unavailable') END;
    END
    """,
    """
    CREATE TRIGGER trg_current_release_update_guard_018
    BEFORE UPDATE OF space_id, snapshot_id ON current_release
    FOR EACH ROW
    BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM release_snapshots
            WHERE id = NEW.snapshot_id
              AND space_id = NEW.space_id
              AND status = 'published'
              AND read_model_version = 1
              AND projection_frozen_at IS NOT NULL
        ) THEN RAISE(ABORT, 'current release target is unavailable') END;
    END
    """,
)

SQLITE_DROP_GUARDS = (
    "DROP TRIGGER IF EXISTS trg_current_release_update_guard_018",
    "DROP TRIGGER IF EXISTS trg_current_release_insert_guard_018",
    "DROP TRIGGER IF EXISTS trg_release_operations_plan_guard_018",
    "DROP TRIGGER IF EXISTS trg_release_snapshots_projection_guard_018",
    "DROP TRIGGER IF EXISTS trg_snapshot_facts_delete_guard_018",
    "DROP TRIGGER IF EXISTS trg_snapshot_facts_update_guard_018",
    "DROP TRIGGER IF EXISTS trg_snapshot_facts_insert_guard_018",
)

POSTGRESQL_CREATE_GUARDS = (
    """
    CREATE FUNCTION guard_snapshot_fact_insert_018() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM release_snapshots
            WHERE id = NEW.snapshot_id
              AND space_id = NEW.space_id
              AND status = 'building'
              AND projection_frozen_at IS NULL
        ) THEN
            RAISE EXCEPTION 'snapshot projection is frozen'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $guard$
    """,
    """
    CREATE TRIGGER trg_snapshot_facts_insert_guard_018
    BEFORE INSERT ON snapshot_facts
    FOR EACH ROW EXECUTE FUNCTION guard_snapshot_fact_insert_018()
    """,
    """
    CREATE FUNCTION guard_snapshot_fact_immutable_018() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
    BEGIN
        RAISE EXCEPTION 'snapshot facts are immutable'
            USING ERRCODE = '23514';
    END;
    $guard$
    """,
    """
    CREATE TRIGGER trg_snapshot_facts_update_guard_018
    BEFORE UPDATE ON snapshot_facts
    FOR EACH ROW EXECUTE FUNCTION guard_snapshot_fact_immutable_018()
    """,
    """
    CREATE TRIGGER trg_snapshot_facts_delete_guard_018
    BEFORE DELETE ON snapshot_facts
    FOR EACH ROW EXECUTE FUNCTION guard_snapshot_fact_immutable_018()
    """,
    """
    CREATE FUNCTION guard_release_snapshot_projection_018() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
    BEGIN
        IF (
            OLD.projection_frozen_at IS NOT NULL
            AND NEW.projection_frozen_at IS DISTINCT FROM OLD.projection_frozen_at
        ) OR (
            (OLD.projection_frozen_at IS NOT NULL OR OLD.status = 'published')
            AND NEW.rendered_pages::text IS DISTINCT FROM OLD.rendered_pages::text
        ) THEN
            RAISE EXCEPTION 'snapshot projection is frozen'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $guard$
    """,
    """
    CREATE TRIGGER trg_release_snapshots_projection_guard_018
    BEFORE UPDATE ON release_snapshots
    FOR EACH ROW EXECUTE FUNCTION guard_release_snapshot_projection_018()
    """,
    """
    CREATE FUNCTION guard_release_operation_plan_018() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
    BEGIN
        IF OLD.plan_frozen_at IS NOT NULL AND (
            NEW.plan_frozen_at IS DISTINCT FROM OLD.plan_frozen_at
            OR NEW.publish_plan::text IS DISTINCT FROM OLD.publish_plan::text
            OR NEW.plan_digest IS DISTINCT FROM OLD.plan_digest
        ) THEN
            RAISE EXCEPTION 'publish plan is frozen'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $guard$
    """,
    """
    CREATE TRIGGER trg_release_operations_plan_guard_018
    BEFORE UPDATE ON release_operations
    FOR EACH ROW EXECUTE FUNCTION guard_release_operation_plan_018()
    """,
    """
    CREATE FUNCTION guard_current_release_target_018() RETURNS trigger
    LANGUAGE plpgsql AS $guard$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM release_snapshots
            WHERE id = NEW.snapshot_id
              AND space_id = NEW.space_id
              AND status = 'published'
              AND read_model_version = 1
              AND projection_frozen_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'current release target is unavailable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $guard$
    """,
    """
    CREATE TRIGGER trg_current_release_insert_guard_018
    BEFORE INSERT ON current_release
    FOR EACH ROW EXECUTE FUNCTION guard_current_release_target_018()
    """,
    """
    CREATE TRIGGER trg_current_release_update_guard_018
    BEFORE UPDATE OF space_id, snapshot_id ON current_release
    FOR EACH ROW EXECUTE FUNCTION guard_current_release_target_018()
    """,
)

POSTGRESQL_DROP_GUARDS = (
    "DROP TRIGGER IF EXISTS trg_current_release_update_guard_018 ON current_release",
    "DROP TRIGGER IF EXISTS trg_current_release_insert_guard_018 ON current_release",
    ("DROP TRIGGER IF EXISTS trg_release_operations_plan_guard_018 ON release_operations"),
    ("DROP TRIGGER IF EXISTS trg_release_snapshots_projection_guard_018 ON release_snapshots"),
    "DROP TRIGGER IF EXISTS trg_snapshot_facts_delete_guard_018 ON snapshot_facts",
    "DROP TRIGGER IF EXISTS trg_snapshot_facts_update_guard_018 ON snapshot_facts",
    "DROP TRIGGER IF EXISTS trg_snapshot_facts_insert_guard_018 ON snapshot_facts",
    "DROP FUNCTION IF EXISTS guard_current_release_target_018()",
    "DROP FUNCTION IF EXISTS guard_release_operation_plan_018()",
    "DROP FUNCTION IF EXISTS guard_release_snapshot_projection_018()",
    "DROP FUNCTION IF EXISTS guard_snapshot_fact_immutable_018()",
    "DROP FUNCTION IF EXISTS guard_snapshot_fact_insert_018()",
)

CREATE_GUARDS: Mapping[str, Sequence[str]] = {
    "sqlite": SQLITE_CREATE_GUARDS,
    "postgresql": POSTGRESQL_CREATE_GUARDS,
}
DROP_GUARDS: Mapping[str, Sequence[str]] = {
    "sqlite": SQLITE_DROP_GUARDS,
    "postgresql": POSTGRESQL_DROP_GUARDS,
}

METADATA_CREATE_GUARDS: Mapping[str, Mapping[str, Sequence[str]]] = {
    "sqlite": {
        "snapshot_facts": SQLITE_CREATE_GUARDS[0:3],
        "release_snapshots": SQLITE_CREATE_GUARDS[3:4],
        "release_operations": SQLITE_CREATE_GUARDS[4:5],
        "current_release": SQLITE_CREATE_GUARDS[5:7],
    },
    "postgresql": {
        "snapshot_facts": POSTGRESQL_CREATE_GUARDS[0:5],
        "release_snapshots": POSTGRESQL_CREATE_GUARDS[5:7],
        "release_operations": POSTGRESQL_CREATE_GUARDS[7:9],
        "current_release": POSTGRESQL_CREATE_GUARDS[9:12],
    },
}

METADATA_DROP_GUARDS: Mapping[str, Mapping[str, Sequence[str]]] = {
    "sqlite": {
        "current_release": SQLITE_DROP_GUARDS[0:2],
        "release_operations": SQLITE_DROP_GUARDS[2:3],
        "release_snapshots": SQLITE_DROP_GUARDS[3:4],
        "snapshot_facts": SQLITE_DROP_GUARDS[4:7],
    },
    "postgresql": {
        "current_release": (
            POSTGRESQL_DROP_GUARDS[0],
            POSTGRESQL_DROP_GUARDS[1],
            POSTGRESQL_DROP_GUARDS[7],
        ),
        "release_operations": (
            POSTGRESQL_DROP_GUARDS[2],
            POSTGRESQL_DROP_GUARDS[8],
        ),
        "release_snapshots": (
            POSTGRESQL_DROP_GUARDS[3],
            POSTGRESQL_DROP_GUARDS[9],
        ),
        "snapshot_facts": (
            POSTGRESQL_DROP_GUARDS[4],
            POSTGRESQL_DROP_GUARDS[5],
            POSTGRESQL_DROP_GUARDS[6],
            POSTGRESQL_DROP_GUARDS[10],
            POSTGRESQL_DROP_GUARDS[11],
        ),
    },
}


def create_guard_statements(dialect_name: str) -> Sequence[str]:
    """Return guard creation statements for a supported database dialect."""

    return CREATE_GUARDS.get(dialect_name, ())


def drop_guard_statements(dialect_name: str) -> Sequence[str]:
    """Return guard removal statements for a supported database dialect."""

    return DROP_GUARDS.get(dialect_name, ())


def register_metadata_guards(metadata: MetaData) -> None:
    """Install the same guards when tests/applications use ``create_all``."""

    for dialect_name, table_statements in METADATA_CREATE_GUARDS.items():
        for table_name, statements in table_statements.items():
            table = metadata.tables[table_name]
            for statement in statements:
                event.listen(
                    table,
                    "after_create",
                    DDL(statement).execute_if(  # type: ignore[no-untyped-call]
                        dialect=dialect_name
                    ),
                )
    for dialect_name, table_statements in METADATA_DROP_GUARDS.items():
        for table_name, statements in table_statements.items():
            table = metadata.tables[table_name]
            for statement in statements:
                event.listen(
                    table,
                    "before_drop",
                    DDL(statement).execute_if(  # type: ignore[no-untyped-call]
                        dialect=dialect_name
                    ),
                )

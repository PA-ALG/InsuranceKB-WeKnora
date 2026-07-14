"""OpenSpec 017 T6: source-aware ClaimEvidence migration contract."""

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

HARNESS_ROOT = Path(__file__).resolve().parents[1]
AUDIT_COLUMNS = {
    "raw_kb_id",
    "source_revision",
    "file_hash",
    "original_digest",
    "parser_version",
    "chunk_hash",
    "lineage_status",
    "stale_at",
}


def _cfg(url: str, *, output: StringIO | None = None) -> Config:
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"), output_buffer=output)
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _db(tmp_path: Path, name: str) -> tuple[str, Engine]:
    url = f"sqlite:///{tmp_path}/{name}.db"
    return url, create_engine(url)


def _seed_legacy_evidence(engine: Engine) -> None:
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO knowledge_spaces
                    (id, tenant_id, raw_kb_id, wiki_kb_id, name, binding_status,
                     created_at, updated_at)
                VALUES ('space-1', 'tenant-1', 'raw-1', 'wiki-1', 'Space', 'bound',
                        :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO claims
                    (id, space_id, subject_type, predicate, value_state, status,
                     confidence, extraction_method, schema_version, current_revision,
                     pending_judge, created_at, updated_at)
                VALUES ('claim-1', 'space-1', 'concept', 'waiting_period', 'present',
                        'draft', 0.9, 'llm', 'v1', 0, 0, :now, :now)
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO claim_evidence
                    (id, claim_id, knowledge_id, chunk_id, quote, page, authority_level,
                     doc_role, extraction_method, extracted_at, created_at, updated_at)
                VALUES ('evidence-1', 'claim-1', 'legacy-policy.pdf', 'legacy-chunk',
                        '等待期为90天', 3, 1, 'terms', 'llm', :now, :now, :now)
                """
            ),
            {"now": now},
        )


def test_0004_upgrade_from_0003_keeps_legacy_evidence_readable(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "legacy-upgrade")
    command.upgrade(_cfg(url), "0003")
    _seed_legacy_evidence(engine)

    command.upgrade(_cfg(url), "0004")

    columns = {column["name"] for column in inspect(engine).get_columns("claim_evidence")}
    assert AUDIT_COLUMNS <= columns
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT knowledge_id, chunk_id, quote, raw_kb_id, source_revision, "
                "lineage_status, stale_at FROM claim_evidence WHERE id='evidence-1'"
            )
        ).one()
    assert tuple(row[:3]) == ("legacy-policy.pdf", "legacy-chunk", "等待期为90天")
    assert tuple(row[3:]) == (None, None, None, None)


@pytest.mark.parametrize(
    ("partial_column", "partial_value"),
    [
        ("lineage_status", "linked"),
        ("raw_kb_id", "raw-1"),
        ("stale_at", "2026-07-14 00:00:00+00:00"),
    ],
)
def test_0004_database_constraints_reject_partial_source_audit(
    tmp_path: Path,
    partial_column: str,
    partial_value: str,
) -> None:
    url, engine = _db(tmp_path, f"shape-constraints-{partial_column}")
    command.upgrade(_cfg(url), "0003")
    _seed_legacy_evidence(engine)
    command.upgrade(_cfg(url), "0004")

    now = datetime.now(UTC)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        f"""
                        INSERT INTO claim_evidence
                            (id, claim_id, knowledge_id, quote, page, authority_level,
                             doc_role, extraction_method, extracted_at, {partial_column},
                             created_at, updated_at)
                        VALUES ('partial', 'claim-1', 'knowledge-1', 'quote', 1, 1,
                                'terms', 'llm', :now, :partial_value, :now, :now)
                        """
                    ),
                    {"now": now, "partial_value": partial_value},
                )


def test_0004_downgrade_preserves_legacy_fields_and_drops_audit(tmp_path: Path) -> None:
    url, engine = _db(tmp_path, "downgrade")
    command.upgrade(_cfg(url), "0003")
    _seed_legacy_evidence(engine)
    command.upgrade(_cfg(url), "0004")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE claim_evidence
                SET knowledge_id='knowledge-1', chunk_id='chunk-1',
                    raw_kb_id='raw-1', source_revision=:revision,
                    file_hash=:file_hash, original_digest=:digest,
                    parser_version='pdfplumber@0.11:text-v1', chunk_hash=:chunk_hash,
                    lineage_status='linked'
                WHERE id='evidence-1'
                """
            ),
            {
                "revision": "a" * 64,
                "file_hash": "b" * 32,
                "digest": "c" * 64,
                "chunk_hash": "d" * 64,
            },
        )

    command.downgrade(_cfg(url), "0003")

    assert AUDIT_COLUMNS.isdisjoint(
        {column["name"] for column in inspect(engine).get_columns("claim_evidence")}
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT knowledge_id, chunk_id, quote FROM claim_evidence")
        ).one() == ("knowledge-1", "chunk-1", "等待期为90天")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"


def test_0004_metadata_matches_head_and_alembic_check(tmp_path: Path) -> None:
    url, _engine = _db(tmp_path, "alembic-check")
    command.upgrade(_cfg(url), "head")
    command.check(_cfg(url))


def test_0004_postgresql_offline_ddl_compiles() -> None:
    output = StringIO()
    command.upgrade(
        _cfg("postgresql://user:password@localhost/insurance", output=output),
        "0003:0004",
        sql=True,
    )

    ddl = output.getvalue().lower()
    assert "claim_evidence" in ddl
    assert "raw_kb_id" in ddl and "source_revision" in ddl and "stale_at" in ddl
    assert "ix_evidence_source_revision" in ddl and "ix_evidence_stale" in ddl
    assert "ck_evidence_source_audit" in ddl
    assert "raw_kb_id is null" in ddl and "stale_at is null" in ddl

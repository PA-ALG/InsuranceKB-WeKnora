"""Fail-closed administrative CLI for existing KnowledgeSpace rows."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Never

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from insurance_harness.db import make_engine
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import bind_space


class _CliError(Exception):
    """Internal marker for errors safe to collapse at the CLI boundary."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _CliError("invalid arguments")


def _resolve_db_url(argument: str | None) -> str:
    if argument is not None:
        if argument.strip():
            return argument
        raise _CliError("database unavailable")
    environment_url = os.environ.get("HARNESS_DB_URL")
    if environment_url and environment_url.strip():
        return environment_url
    raise _CliError("database unavailable")


def _migrate(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    harness_root = Path(__file__).resolve().parents[3]
    config = Config(str(harness_root / "alembic.ini"))
    config.set_main_option("script_location", str(harness_root / "migrations"))
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    config.cmd_opts = argparse.Namespace(x=[f"db_url={db_url}"])
    command.upgrade(config, "head")


def _space_record(row: KnowledgeSpace) -> dict[str, str | None]:
    return {
        "id": row.id,
        "name": row.name,
        "binding_status": row.binding_status,
        "tenant_id": row.tenant_id,
        "raw_kb_id": row.raw_kb_id,
        "wiki_kb_id": row.wiki_kb_id,
    }


def _serialize(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write(serialized: str) -> None:
    print(serialized)


def _emit(payload: object) -> None:
    _write(_serialize(payload))


def _dispose_safely(engine: Engine) -> None:
    try:
        engine.dispose()
    except Exception:
        pass


def _run_bind(args: argparse.Namespace, engine: Engine) -> int:
    committed = False
    serialized = ""
    try:
        with Session(engine) as session:
            with session.begin():
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(text("BEGIN"))
                bind_space(
                    session,
                    args.space_id,
                    tenant_id=args.tenant_id,
                    raw_kb_id=args.raw_kb_id,
                    wiki_kb_id=args.wiki_kb_id,
                )
                row = session.get(KnowledgeSpace, args.space_id)
                if row is None:
                    raise _CliError("space unavailable")
                serialized = _serialize(_space_record(row))
            committed = True
    except Exception:
        _dispose_safely(engine)
        if committed:
            return 0
        raise

    _dispose_safely(engine)
    try:
        _write(serialized)
    except Exception:
        return 0
    return 0


def _run(args: argparse.Namespace) -> int:
    db_url = _resolve_db_url(args.db_url)
    _migrate(db_url)
    engine = make_engine(db_url)
    if args.command == "bind":
        return _run_bind(args, engine)
    try:
        with Session(engine) as session:
            if args.command == "list":
                rows = session.scalars(
                    select(KnowledgeSpace).order_by(KnowledgeSpace.id)
                ).all()
                _emit([_space_record(row) for row in rows])
                return 0

            if args.command == "show":
                row = session.get(KnowledgeSpace, args.space_id)
                if row is None:
                    raise _CliError("space unavailable")
                _emit(_space_record(row))
                return 0

            raise _CliError("invalid command")
    finally:
        engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="insurance_harness.db.scope_cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list KnowledgeSpaces")
    list_parser.add_argument("--db-url", default=None)

    show_parser = subparsers.add_parser("show", help="show one KnowledgeSpace")
    show_parser.add_argument("space_id")
    show_parser.add_argument("--db-url", default=None)

    bind_parser = subparsers.add_parser("bind", help="bind an existing unbound Space")
    bind_parser.add_argument("space_id")
    bind_parser.add_argument("--tenant-id", required=True)
    bind_parser.add_argument("--raw-kb-id", required=True)
    bind_parser.add_argument("--wiki-kb-id", required=True)
    bind_parser.add_argument("--db-url", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        return _run(args)
    except Exception:
        print("scope command failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

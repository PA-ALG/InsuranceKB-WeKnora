"""016 S3.2: fail-closed KnowledgeSpace administration CLI."""

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

import insurance_harness.db.scope_cli as scope_cli
from insurance_harness.db import make_engine as real_make_engine
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope_cli import main

HARNESS_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/scope-cli.db"


def _migrate(db_url: str) -> None:
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


def _seed_space(db_url: str, *, space_id: str, name: str = "待绑定") -> None:
    _migrate(db_url)
    engine = create_engine(db_url)
    with Session(engine) as session:
        session.add(
            KnowledgeSpace(
                id=space_id,
                name=name,
                binding_status="unbound",
            )
        )
        session.commit()
    engine.dispose()


def test_s3_3_scope_cli_list_on_empty_database_creates_no_default_space(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["list", "--db-url", db_url]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert captured.err == ""


def test_s3_2_scope_cli_list_show_and_bind_real_database_round_trip(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_space(db_url, space_id="space-z", name="最后")
    engine = create_engine(db_url)
    with Session(engine) as session:
        session.add(
            KnowledgeSpace(
                id="space-a",
                name="最先",
                binding_status="unbound",
            )
        )
        session.commit()
    engine.dispose()

    assert main(["list", "--db-url", db_url]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in listed] == ["space-a", "space-z"]
    assert listed[0] == {
        "binding_status": "unbound",
        "id": "space-a",
        "name": "最先",
        "raw_kb_id": None,
        "tenant_id": None,
        "wiki_kb_id": None,
    }

    assert main(["show", "space-z", "--db-url", db_url]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == "space-z"
    assert shown["binding_status"] == "unbound"

    assert (
        main(
            [
                "bind",
                "space-z",
                "--tenant-id",
                "tenant-z",
                "--raw-kb-id",
                "raw-z",
                "--wiki-kb-id",
                "wiki-z",
                "--db-url",
                db_url,
            ]
        )
        == 0
    )
    bound = json.loads(capsys.readouterr().out)
    assert bound == {
        "binding_status": "bound",
        "id": "space-z",
        "name": "最后",
        "raw_kb_id": "raw-z",
        "tenant_id": "tenant-z",
        "wiki_kb_id": "wiki-z",
    }

    assert main(["show", "space-z", "--db-url", db_url]) == 0
    assert json.loads(capsys.readouterr().out) == bound


def test_s3_2_scope_cli_uses_harness_db_url_when_flag_is_omitted(
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HARNESS_DB_URL", db_url)

    assert main(["list"]) == 0

    assert json.loads(capsys.readouterr().out) == []


def test_s3_2_scope_cli_without_explicit_or_environment_db_url_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HARNESS_DB_URL", raising=False)

    assert main(["list"]) != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    assert "sqlite" not in captured.err.lower()


def test_s3_2_scope_cli_missing_binding_argument_is_generic_nonzero(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "bind",
                "private-space",
                "--tenant-id",
                "private-tenant",
                "--raw-kb-id",
                "private-raw",
                "--db-url",
                db_url,
            ]
        )
        != 0
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    assert "private" not in captured.err
    assert not Path(db_url.removeprefix("sqlite:///")).exists()


def test_s3_2_scope_cli_database_failure_does_not_echo_dsn_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "private-password"
    invalid_url = f"unknown-driver://user:{secret}@invalid.example/db"

    assert main(["list", "--db-url", invalid_url]) != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    assert secret not in captured.err
    assert "traceback" not in captured.err.lower()


def test_s3_2_scope_cli_show_missing_fails_without_disclosing_requested_id(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = "private-missing-space"

    assert main(["show", missing, "--db-url", db_url]) != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    assert missing not in captured.err
    assert "traceback" not in captured.err.lower()


def test_s3_2_scope_cli_duplicate_binding_is_nonzero_and_leaves_target_unbound(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_space(db_url, space_id="space-bound")
    engine = create_engine(db_url)
    with Session(engine) as session:
        bound = session.get(KnowledgeSpace, "space-bound")
        assert bound is not None
        bound.binding_status = "bound"
        bound.tenant_id = "private-tenant"
        bound.raw_kb_id = "private-raw"
        bound.wiki_kb_id = "private-wiki"
        session.add(
            KnowledgeSpace(
                id="space-target",
                name="target",
                binding_status="unbound",
            )
        )
        session.commit()
    engine.dispose()

    assert (
        main(
            [
                "bind",
                "space-target",
                "--tenant-id",
                "private-tenant",
                "--raw-kb-id",
                "private-raw",
                "--wiki-kb-id",
                "private-new-wiki",
                "--db-url",
                db_url,
            ]
        )
        != 0
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    assert "private" not in captured.err
    engine = create_engine(db_url)
    with Session(engine) as session:
        target = session.get(KnowledgeSpace, "space-target")
        assert target is not None
        assert target.binding_status == "unbound"
        assert target.tenant_id is None
        assert target.raw_kb_id is None
        assert target.wiki_kb_id is None
    engine.dispose()


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--tenant-id", " "),
        ("--raw-kb-id", ""),
        ("--wiki-kb-id", "w" * 256),
    ],
)
def test_s3_2_scope_cli_invalid_binding_input_is_nonzero_and_zero_write(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    value: str,
) -> None:
    _seed_space(db_url, space_id="space-target")
    arguments = {
        "--tenant-id": "tenant-a",
        "--raw-kb-id": "raw-a",
        "--wiki-kb-id": "wiki-a",
    }
    arguments[flag] = value
    argv = ["bind", "space-target"]
    for name, item in arguments.items():
        argv.extend([name, item])
    argv.extend(["--db-url", db_url])

    assert main(argv) != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    engine = create_engine(db_url)
    with Session(engine) as session:
        target = session.get(KnowledgeSpace, "space-target")
        assert target is not None
        assert target.binding_status == "unbound"
        assert target.tenant_id is None
        assert target.raw_kb_id is None
        assert target.wiki_kb_id is None
    engine.dispose()


def test_s3_2_scope_cli_bind_output_failure_after_commit_returns_success(
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_space(db_url, space_id="space-target")

    def fail_write(serialized: str) -> None:
        raise OSError("private stdout failure")

    monkeypatch.setattr(scope_cli, "_write", fail_write)
    assert (
        main(
            [
                "bind",
                "space-target",
                "--tenant-id",
                "tenant-a",
                "--raw-kb-id",
                "raw-a",
                "--wiki-kb-id",
                "wiki-a",
                "--db-url",
                db_url,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    engine = create_engine(db_url)
    with Session(engine) as session:
        target = session.get(KnowledgeSpace, "space-target")
        assert target is not None
        assert target.binding_status == "bound"
    engine.dispose()


def test_s3_2_scope_cli_bind_serialization_failure_before_commit_rolls_back(
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_space(db_url, space_id="space-target")

    def fail_serialize(payload: object) -> str:
        raise ValueError("private serialization failure")

    monkeypatch.setattr(scope_cli, "_serialize", fail_serialize)
    assert (
        main(
            [
                "bind",
                "space-target",
                "--tenant-id",
                "tenant-a",
                "--raw-kb-id",
                "raw-a",
                "--wiki-kb-id",
                "wiki-a",
                "--db-url",
                db_url,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"
    engine = create_engine(db_url)
    with Session(engine) as session:
        target = session.get(KnowledgeSpace, "space-target")
        assert target is not None
        assert target.binding_status == "unbound"
    engine.dispose()


def test_s3_2_scope_cli_list_output_failure_remains_nonzero(
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_write(serialized: str) -> None:
        raise OSError("private stdout failure")

    monkeypatch.setattr(scope_cli, "_write", fail_write)

    assert main(["list", "--db-url", db_url]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "scope command failed\n"


@pytest.mark.parametrize("source", ["flag", "environment"])
def test_s3_2_scope_cli_percent_encoded_db_url_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str,
) -> None:
    database_path = tmp_path / f"scope%20{source}.db"
    db_url = f"sqlite:///{database_path}"
    wrong_path = tmp_path / "wrong-environment.db"
    seen_urls: list[str] = []

    def recording_make_engine(url: str, *, echo: bool = False) -> Engine:
        seen_urls.append(url)
        return real_make_engine(url, echo=echo)

    monkeypatch.setattr(scope_cli, "make_engine", recording_make_engine)
    if source == "flag":
        monkeypatch.setenv("HARNESS_DB_URL", f"sqlite:///{wrong_path}")
        argv = ["list", "--db-url", db_url]
    else:
        monkeypatch.setenv("HARNESS_DB_URL", db_url)
        argv = ["list"]

    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert seen_urls == [db_url]
    assert database_path.exists()
    assert not wrong_path.exists()

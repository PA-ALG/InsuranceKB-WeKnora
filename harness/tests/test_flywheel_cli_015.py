"""015 F3.3 CLI `flywheel pull`——dry-run 报表端到端 + `--open-tickets` 受阻诚实退出。"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, KnowledgeSpace, ProductAlias
from insurance_harness.flywheel.cli import main
from insurance_harness.flywheel.models import Trace
from insurance_harness.flywheel.tables import (
    FlywheelCheckpoint,
    FlywheelObservation,
    KnowledgeGapRow,
)
from insurance_harness.product.aliases import generate_aliases

HARNESS_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_A = ("1824", "平安盛世金越尊享版终身寿险", "平保寿发〔2025〕366号")
SOURCE_ID = "offline-export"


def _base_args(traces_file: Path, db_url: str, space_id: str) -> list[str]:
    return [
        "pull",
        "--traces-file",
        str(traces_file),
        "--db-url",
        db_url,
        "--space-id",
        space_id,
        "--source-id",
        SOURCE_ID,
    ]


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/flywheel_cli.db"


@pytest.fixture()
def space_id(db_url: str) -> str:
    cfg = Config(str(HARNESS_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(HARNESS_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    with Session(engine) as session:
        space = KnowledgeSpace(
            name="flywheel-cli",
            binding_status="bound",
            tenant_id="tenant-flywheel-cli",
            raw_kb_id="raw-flywheel-cli",
            wiki_kb_id="wiki-flywheel-cli",
        )
        session.add(space)
        session.flush()
        code, name, filing = PRODUCT_A
        product = InsuranceProduct(
            space_id=space.id,
            product_code=code,
            canonical_name=name,
            category="whole-life",
            status="在售",
            filing_no=filing,
        )
        session.add(product)
        session.flush()
        for alias, alias_type in generate_aliases(name):
            session.add(ProductAlias(product_id=product.id, alias=alias, alias_type=alias_type))
        session.commit()
        value = space.id
    engine.dispose()
    return value


@pytest.fixture()
def traces_file(tmp_path: Path) -> Path:
    path = tmp_path / "traces.jsonl"
    traces = [
        Trace(
            trace_id="t1",
            timestamp="2026-07-01T10:00:00",
            question=f"{PRODUCT_A[1]} 的等待期是多久？",
            answer="抱歉，无法确定。",
        ),
        Trace(
            trace_id="t2",
            timestamp="2026-07-01T11:00:00",
            question="这类保险怎么退保？",
            answer="抱歉，无法回答。",
        ),
    ]
    path.write_text("\n".join(t.model_dump_json() for t in traces) + "\n", encoding="utf-8")
    return path


def test_f3_3_cli_dry_run_prints_report(
    db_url: str, space_id: str, traces_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(_base_args(traces_file, db_url, space_id))
    out = capsys.readouterr().out
    assert rc == 0
    assert "本轮处理新 trace：2" in out
    assert "缺口总数：1" in out  # 仅 t1 对齐成 A 缺口
    assert "有信号但未对齐（观察队列，未开单）：1" in out  # t2 未对齐


def test_f3_3_cli_report_declares_empty_knowledge_evaluated_from_database(
    db_url: str, space_id: str, traces_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(_base_args(traces_file, db_url, space_id))
    out = capsys.readouterr().out
    assert rc == 0
    assert "空知识信号未评估" not in out


def test_f3_3_cli_open_tickets_is_gated_nonzero(
    db_url: str, space_id: str, traces_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [*_base_args(traces_file, db_url, space_id), "--open-tickets"]
    )
    captured = capsys.readouterr()
    assert rc == 2  # 受阻：非零退出，绝不假装成功
    assert "受阻" in captured.err
    assert "未开任何单" in captured.err


def test_f3_3_cli_dry_run_does_not_write_database_state(
    db_url: str, space_id: str, traces_file: Path
) -> None:
    rc = main(_base_args(traces_file, db_url, space_id))
    assert rc == 0
    with Session(create_engine(db_url)) as session:
        assert session.scalar(select(func.count()).select_from(FlywheelCheckpoint)) == 0
        assert session.scalar(select(func.count()).select_from(FlywheelObservation)) == 0
        assert session.scalar(select(func.count()).select_from(KnowledgeGapRow)) == 0


# ---------------------------------------------------------------------------
# codex PR#18 复审收口：dry-run 零副作用 / fail-closed 配置 / --apply 持久化
# ---------------------------------------------------------------------------


def test_f3_3_cli_missing_db_config_fail_closed(
    traces_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """codex 阻断3：缺 DB 配置必须 fail-closed 非零退出，不静默回退本地 SQLite。"""
    monkeypatch.chdir(tmp_path)  # 无 .env
    monkeypatch.delenv("HARNESS_DB_URL", raising=False)
    rc = main(
        [
            "pull",
            "--traces-file",
            str(traces_file),
            "--space-id",
            "s1",
            "--source-id",
            SOURCE_ID,
        ]
    )
    assert rc == 1
    out = capsys.readouterr()
    assert "数据库" in (out.out + out.err)
    assert not (tmp_path / "harness_flywheel.db").exists()  # 零本地库回退


def test_f3_3_cli_dry_run_creates_no_db_file_no_schema(
    traces_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """codex 阻断3：dry-run 不建 DB 文件、不跑迁移——全新路径直接诚实非零退出。"""
    fresh_db = tmp_path / "never-created.db"
    rc = main(
        [
            "pull", "--traces-file", str(traces_file),
            "--db-url", f"sqlite:///{fresh_db}", "--space-id", "s1",
            "--source-id", SOURCE_ID,
        ]
    )
    assert rc == 1
    assert not fresh_db.exists()  # 迁移属部署流程；预览不改状态（含建库）


def test_f3_3_cli_open_tickets_gate_precedes_all_io(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """codex 阻断3：受阻参数在任何文件/DB I/O 之前校验——traces 文件不存在也应先报受阻。"""
    rc = main(
        [
            "pull", "--traces-file", str(tmp_path / "no-such.jsonl"),
            "--db-url", "sqlite:///unused.db", "--space-id", "s1",
            "--source-id", SOURCE_ID, "--open-tickets",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2  # gate 前置：未尝试读不存在的文件（否则会崩 FileNotFoundError）
    assert "受阻" in captured.err
    assert not Path("unused.db").exists()


def test_f3_3_cli_missing_space_fail_closed_constant_response(
    db_url: str, space_id: str, traces_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """space 不存在 → fail-closed 非零退出、不堆栈崩出、不回显被查询标识（016 语义）。

    库已就位（space_id 夹具建库迁移），但查询一个不存在的 space 标识。
    """
    rc = main(
        [
            "pull", "--traces-file", str(traces_file),
            "--db-url", db_url, "--space-id", "no-such-space",
            "--source-id", SOURCE_ID,
        ]
    )
    assert rc == 1
    out = capsys.readouterr()
    assert "no-such-space" not in (out.out + out.err)
    assert "校验未通过" in (out.out + out.err)


def test_f3_3_cli_apply_persists_database_state_for_next_cycle(
    db_url: str, space_id: str, traces_file: Path, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F3.3 --apply 闭环：DB checkpoint+gap 跨周期累计。"""
    rc1 = main([*_base_args(traces_file, db_url, space_id), "--apply"])
    assert rc1 == 0
    with Session(create_engine(db_url)) as session:
        checkpoint = session.scalar(select(FlywheelCheckpoint))
        assert checkpoint is not None and checkpoint.cursor.endswith("|t2")

    # 第二轮：新增一条对齐到同产品的 trace → 同缺口跨周期累计 hit_count
    t3 = Trace(
        trace_id="t3", timestamp="2026-07-02T09:00:00Z",
        question=f"{PRODUCT_A[1]} 的等待期到底多久？", answer="抱歉，没有找到。",
    )
    round2 = tmp_path / "traces2.jsonl"
    round2.write_text(t3.model_dump_json() + "\n", encoding="utf-8")
    capsys.readouterr()  # 清缓冲
    rc2 = main([*_base_args(round2, db_url, space_id), "--apply"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "×2" in out2  # 上一轮 1 次 + 本轮 1 次 = 跨周期累计 hit_count=2
    with Session(create_engine(db_url)) as session:
        checkpoint = session.scalar(select(FlywheelCheckpoint))
        gap = session.scalar(select(KnowledgeGapRow))
        assert checkpoint is not None and checkpoint.cursor.endswith("|t3")
        assert gap is not None and gap.hit_count == 2


def test_f3_3_cli_observations_persisted_only_on_apply(
    db_url: str, space_id: str, traces_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F2.1 processed ledger/观察队列只在 --apply 进入数据库。"""
    assert main(_base_args(traces_file, db_url, space_id)) == 0
    with Session(create_engine(db_url)) as session:
        assert session.scalar(select(func.count()).select_from(FlywheelObservation)) == 0

    assert main([*_base_args(traces_file, db_url, space_id), "--apply"]) == 0
    with Session(create_engine(db_url)) as session:
        rows = tuple(session.scalars(select(FlywheelObservation)))
        assert len(rows) == 2  # every fresh trace is processed-ledger state
        unaligned = [row for row in rows if row.alignment_reason != "aligned"]
        assert len(unaligned) == 1
        assert unaligned[0].trace_id == "t2"
        assert "退保" in unaligned[0].question

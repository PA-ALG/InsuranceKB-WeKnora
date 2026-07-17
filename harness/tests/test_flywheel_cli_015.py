"""015 F3.3 CLI `flywheel pull`——dry-run 报表端到端 + `--open-tickets` 受阻诚实退出。"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, KnowledgeSpace, ProductAlias
from insurance_harness.flywheel.cli import main
from insurance_harness.flywheel.models import Trace
from insurance_harness.product.aliases import generate_aliases

HARNESS_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_A = ("1824", "平安盛世金越尊享版终身寿险", "平保寿发〔2025〕366号")


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
    rc = main(
        ["pull", "--traces-file", str(traces_file), "--db-url", db_url, "--space-id", space_id]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "本轮处理新 trace：2" in out
    assert "缺口总数：1" in out  # 仅 t1 对齐成 A 缺口
    assert "有信号但未对齐（观察队列，未开单）：1" in out  # t2 未对齐


def test_f3_3_cli_report_declares_empty_knowledge_not_evaluated(
    db_url: str, space_id: str, traces_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 红队#3：CLI 未接 claim 源 → 报表须诚实披露空知识信号未评估，不静默少报。
    rc = main(
        ["pull", "--traces-file", str(traces_file), "--db-url", db_url, "--space-id", space_id]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "空知识" in out and "未评估" in out


def test_f3_3_cli_open_tickets_is_gated_nonzero(
    db_url: str, space_id: str, traces_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "pull",
            "--traces-file",
            str(traces_file),
            "--db-url",
            db_url,
            "--space-id",
            space_id,
            "--open-tickets",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2  # 受阻：非零退出，绝不假装成功
    assert "受阻" in captured.err
    assert "未开任何单" in captured.err


def test_f3_3_cli_dry_run_does_not_write_cursor(
    db_url: str, space_id: str, traces_file: Path, tmp_path: Path
) -> None:
    cursor_file = tmp_path / "cursor.txt"
    rc = main(
        [
            "pull",
            "--traces-file",
            str(traces_file),
            "--db-url",
            db_url,
            "--space-id",
            space_id,
            "--cursor-file",
            str(cursor_file),
        ]
    )
    assert rc == 0
    assert not cursor_file.exists()  # 预览不改状态：dry-run 不推进游标

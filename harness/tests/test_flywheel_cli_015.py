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
    rc = main(["pull", "--traces-file", str(traces_file), "--space-id", "s1"])
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
        ["pull", "--traces-file", str(traces_file),
         "--db-url", f"sqlite:///{fresh_db}", "--space-id", "s1"]
    )
    assert rc == 1
    assert not fresh_db.exists()  # 迁移属部署流程；预览不改状态（含建库）


def test_f3_3_cli_open_tickets_gate_precedes_all_io(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """codex 阻断3：受阻参数在任何文件/DB I/O 之前校验——traces 文件不存在也应先报受阻。"""
    rc = main(
        ["pull", "--traces-file", str(tmp_path / "no-such.jsonl"),
         "--db-url", "sqlite:///unused.db", "--space-id", "s1", "--open-tickets"]
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
        ["pull", "--traces-file", str(traces_file),
         "--db-url", db_url, "--space-id", "no-such-space"]
    )
    assert rc == 1
    out = capsys.readouterr()
    assert "no-such-space" not in (out.out + out.err)
    assert "校验未通过" in (out.out + out.err)


def test_f3_3_cli_apply_persists_cursor_and_gaps_for_next_cycle(
    db_url: str, space_id: str, traces_file: Path, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F3.3 --apply 闭环：写游标+缺口状态；下一轮以其为输入跨周期累计（codex 阻断4）。"""
    cursor_file = tmp_path / "cursor.txt"
    gaps_file = tmp_path / "gaps.json"
    rc1 = main(
        ["pull", "--traces-file", str(traces_file), "--db-url", db_url,
         "--space-id", space_id, "--cursor-file", str(cursor_file),
         "--gaps-file", str(gaps_file), "--apply"]
    )
    assert rc1 == 0
    assert cursor_file.exists() and gaps_file.exists()  # F1.1a 游标持久化
    cursor_1 = cursor_file.read_text(encoding="utf-8").strip()
    assert cursor_1.endswith("|t2")

    # 第二轮：新增一条对齐到同产品的 trace → 同缺口跨周期累计 hit_count
    t3 = Trace(
        trace_id="t3", timestamp="2026-07-02T09:00:00Z",
        question=f"{PRODUCT_A[1]} 的等待期到底多久？", answer="抱歉，没有找到。",
    )
    round2 = tmp_path / "traces2.jsonl"
    round2.write_text(t3.model_dump_json() + "\n", encoding="utf-8")
    capsys.readouterr()  # 清缓冲
    rc2 = main(
        ["pull", "--traces-file", str(round2), "--db-url", db_url,
         "--space-id", space_id, "--cursor-file", str(cursor_file),
         "--gaps-file", str(gaps_file), "--apply"]
    )
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "×2" in out2  # 上一轮 1 次 + 本轮 1 次 = 跨周期累计 hit_count=2
    assert cursor_file.read_text(encoding="utf-8").strip().endswith("|t3")  # 游标续位


def test_f3_3_cli_observations_exported_only_on_apply(
    db_url: str, space_id: str, traces_file: Path, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F2.1 观察队列可消费：--apply 时按指定路径导出明细 JSONL；dry-run 不建文件。"""
    obs_file = tmp_path / "obs.jsonl"
    rc_dry = main(
        ["pull", "--traces-file", str(traces_file), "--db-url", db_url,
         "--space-id", space_id, "--observations-out", str(obs_file)]
    )
    assert rc_dry == 0 and not obs_file.exists()  # dry-run 零文件写入
    rc_apply = main(
        ["pull", "--traces-file", str(traces_file), "--db-url", db_url,
         "--space-id", space_id, "--observations-out", str(obs_file), "--apply"]
    )
    assert rc_apply == 0 and obs_file.exists()
    import json as _json

    rows = [_json.loads(line) for line in obs_file.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1  # t2 未对齐
    assert rows[0]["trace_id"] == "t2"
    assert "退保" in rows[0]["question"]
    assert rows[0]["reason"] == "no_actionable_match"

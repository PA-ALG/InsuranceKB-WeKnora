"""F3.3 CLI：反馈飞轮 pull——编排 F1(信号)→F2(对齐/聚合)→F3(报表)。

    python -m insurance_harness.flywheel.cli pull \
        --traces-file traces.jsonl --db-url URL --space-id ID \
        [--cursor-file cur.txt] [--field-vocab vocab.json] [--open-tickets]

默认 **dry-run**：只产出报表，不落任何单据、不推进游标（预览不改状态）。
`--open-tickets` 为**受阻能力**：ReviewItem(knowledge_gap) 投影候 PR#9 + knowledge 域
subject 形态协调；当前仅诚实告警并以非零码退出，**绝不假装开单**（fail-honest）。
离线源用 `--traces-file`（JSONL，每行一条 Trace）；Langfuse 直连候补（F1.1 客户端已就位）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db import make_engine
from insurance_harness.db.scope import load_scope
from insurance_harness.product.routing import MatchIndex

from .models import Trace
from .pull import PullResult, run_pull

_DEFAULT_SQLITE = "sqlite:///harness_flywheel.db"


def _resolve_db_url(arg: str | None) -> str:
    """--db-url > HarnessSettings.db_url（HARNESS_DB_URL）> 本地 SQLite（仅测试用）。"""
    if arg:
        return arg
    try:
        settings_url = HarnessSettings().db_url  # type: ignore[call-arg]  # 必填项来自环境
    except ValidationError:
        settings_url = os.environ.get("HARNESS_DB_URL")
    if settings_url:
        return settings_url
    print(f"[提示] 未配置数据库连接串，使用本地 SQLite（仅测试用）：{_DEFAULT_SQLITE}")
    return _DEFAULT_SQLITE


def _migrate(db_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    harness_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(harness_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(harness_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    cfg.cmd_opts = argparse.Namespace(x=[f"db_url={db_url}"])
    command.upgrade(cfg, "head")


def _load_traces(path: Path) -> list[Trace]:
    """从 JSONL 读 Trace（每行一条）；空行跳过。"""
    traces: list[Trace] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                traces.append(Trace.model_validate_json(stripped))
    return traces


def _load_vocab(path: Path) -> dict[str, str]:
    """字段词表 JSON：{显示名: field_id}。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def _read_cursor(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _render(res: PullResult) -> str:
    r = res.report
    lines = [
        "# 015 反馈飞轮 pull 报表（dry-run）",
        "",
        f"- 本轮处理新 trace：{res.processed}",
        f"- 缺口总数：{r.total}"
        f"（open={r.open_count} reopened={r.reopened_count} resolved={r.resolved_count}）",
        f"- 本轮新增缺口：{r.new_count}",
        f"- 有信号但未对齐（观察队列，未开单）：{res.unaligned_signals}",
        f"- 游标（next）：{res.next_cursor or '(无新 trace)'}",
    ]
    if not res.empty_knowledge_active:
        # 诚实披露覆盖面：CLI 未接 claim 数据源 → 空知识信号未评估（其余 3 类已评估）。
        lines.append("- ⚠ 空知识信号未评估（未接 claim 数据源；无引用/低置信/负反馈 3 类已评估）")
    lines += ["", "## 最答不上（TopN，按命中数降序）"]
    lines += (
        [f"- {key} ×{hits}" for key, hits in r.top_unanswered]
        if r.top_unanswered
        else ["- （无）"]
    )
    lines += ["", "## 产品分布"]
    lines += (
        [
            f"- {pid}：{n}"
            for pid, n in sorted(r.by_product.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        if r.by_product
        else ["- （无）"]
    )
    return "\n".join(lines)


def cmd_pull(args: argparse.Namespace) -> int:
    traces = _load_traces(Path(args.traces_file))
    field_names = _load_vocab(Path(args.field_vocab)) if args.field_vocab else None
    cursor = _read_cursor(Path(args.cursor_file)) if args.cursor_file else None

    db_url = _resolve_db_url(args.db_url)
    _migrate(db_url)
    engine = make_engine(db_url)
    try:
        with Session(engine) as session:
            scope = load_scope(session, args.space_id)
            index = MatchIndex.from_session(session, scope)
    finally:
        engine.dispose()

    result = run_pull(traces, index, field_names=field_names, cursor=cursor)
    print(_render(result))

    if args.open_tickets:
        # 受阻：投影未就位——诚实告警 + 非零码；绝不假装开单、绝不推进游标。
        print(
            "\n[受阻] --open-tickets 暂不可用：ReviewItem(knowledge_gap) 投影候 PR#9 "
            "+ knowledge 域 subject 形态协调；本版仅 dry-run 报表，未开任何单、未推进游标。",
            file=sys.stderr,
        )
        return 2

    # dry-run 是预览：不推进游标（下轮可复现同报表）。游标仅在真正开单后才前移。
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurance_harness.flywheel")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="拉取 trace → 信号 → 对齐/聚合 → 报表（默认 dry-run）")
    p_pull.add_argument("--traces-file", required=True, help="JSONL：每行一条 Trace")
    p_pull.add_argument("--db-url", default=None)
    p_pull.add_argument("--space-id", required=True)
    p_pull.add_argument("--cursor-file", default=None, help="增量游标文件（预览不写）")
    p_pull.add_argument("--field-vocab", default=None, help="字段词表 JSON：{显示名: field_id}")
    p_pull.add_argument(
        "--open-tickets",
        action="store_true",
        help="开单（受阻：候 PR#9 + 域协调，当前非零退出不开单）",
    )
    p_pull.set_defaults(func=cmd_pull)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

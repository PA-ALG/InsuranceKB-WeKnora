"""F3.3 CLI：反馈飞轮 pull——编排 F1(信号)→F2(对齐/聚合)→F3(报表)。

    python -m insurance_harness.flywheel.cli pull \
        --traces-file traces.jsonl --db-url URL --space-id ID --source-id SOURCE \
        [--field-vocab vocab.json] \
        [--apply] [--open-tickets]

默认 **dry-run 零副作用**：只产出报表——不写游标/状态/导出文件、不执行 schema 迁移
（迁移属部署流程；schema 缺失/过旧 → 诚实非零退出）、DB 只读。缺 DB 配置 fail-closed
非零退出，**不**回退本地 SQLite（codex PR#18 阻断3）。`--apply` 才在 caller-owned
DB 事务中原子持久化 Space/source checkpoint、processed ledger 与 gap 聚合；文件不充当状态源。
`--open-tickets` 为**受阻能力**（F2.4 投影候 knowledge_gap subject 形态协调；
PR#9 已合入，剩余依赖是 subject 设计）：在任何 I/O 之前立即非零退出，绝不假装开单。
离线源用 `--traces-file`（JSONL）；Langfuse 直连候生产者合同落地（spec F1.1b，gated）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db import make_engine
from insurance_harness.db.scope import ScopeViolation, UnboundKnowledgeSpace, load_scope

from .models import Trace
from .pull import PullResult
from .repository import FlywheelRepositoryError, apply_pull, preview_pull


def _resolve_db_url(arg: str | None) -> str | None:
    """--db-url > HarnessSettings.db_url（HARNESS_DB_URL）；缺配置 → None（fail-closed）。"""
    if arg:
        return arg
    try:
        settings_url = HarnessSettings().db_url  # type: ignore[call-arg]  # 必填项来自环境
    except ValidationError:
        settings_url = os.environ.get("HARNESS_DB_URL")
    return settings_url or None


def _sqlite_path(db_url: str) -> Path | None:
    prefix = "sqlite:///"
    if db_url.startswith(prefix) and db_url != "sqlite:///:memory:":
        return Path(db_url[len(prefix) :])
    return None


def _load_traces(path: Path) -> list[Trace]:
    """从 JSONL 读 Trace（每行一条）；空行跳过。question 在构造边界脱敏（F1.3）。"""
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


def _render(res: PullResult) -> str:
    r = res.report
    lines = [
        "# 015 反馈飞轮 pull 报表",
        "",
        f"- 本轮处理新 trace：{res.processed}",
        f"- 缺口总数：{r.total}"
        f"（open={r.open_count} reopened={r.reopened_count} resolved={r.resolved_count}）",
        f"- 本轮新增缺口：{r.new_count}",
        f"- 有信号但未对齐（观察队列，未开单）：{res.unaligned_signals}",
        "- 缺口→闭环平均周期："
        + (
            f"{r.avg_closure_days:.1f} 天"
            if r.avg_closure_days is not None
            else "（无已闭环缺口）"
        ),
        f"- 游标（next）：{res.next_cursor or '(无新 trace)'}",
    ]
    if not res.empty_knowledge_active:
        # 诚实披露覆盖面：空知识识别未激活（未接 claim 源或已配置关闭）→ 未评估。
        lines.append(
            "- ⚠ 空知识信号未评估（识别器关闭或未接 claim 数据源；其余已启用类别正常评估）"
        )
    lines += ["", "## 最答不上（TopN，按命中数降序）"]
    lines += (
        [
            f"- {t.sample_question or '（无样例）'} ×{t.hit_count}（{t.gap_key}）"
            for t in r.top_unanswered
        ]
        if r.top_unanswered
        else ["- （无）"]
    )
    if res.observations:
        lines += ["", "## 观察队列（未对齐，供人工归属）"]
        lines += [
            f"- [{o.reason}] {o.question}（trace={o.trace_id}；{'/'.join(o.signal_types)}）"
            for o in res.observations
        ]
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
    # 受阻能力前置校验：在任何文件/DB/网络 I/O 之前（codex 阻断3）。
    if args.open_tickets:
        print(
            "[受阻] --open-tickets 暂不可用：ReviewItem(knowledge_gap) 投影候 "
            "knowledge 域 subject 形态协调（F2.4）；未执行任何读取/写入、未开任何单。",
            file=sys.stderr,
        )
        return 2

    # 缺 DB 配置 fail-closed：不回退本地 SQLite（企业多租户命令无隐式本地库）。
    db_url = _resolve_db_url(args.db_url)
    if db_url is None:
        print(
            "[fail-closed] 未配置数据库连接串（--db-url 或 HARNESS_DB_URL），未执行任何操作",
            file=sys.stderr,
        )
        return 1
    # sqlite 隐式建库防护：目标文件不存在即 fail-closed（迁移属部署流程，预览不建库）。
    sqlite_file = _sqlite_path(db_url)
    if sqlite_file is not None and not sqlite_file.exists():
        print("[fail-closed] 数据库不存在（迁移属部署流程，本命令不建库/不迁移）", file=sys.stderr)
        return 1

    traces = _load_traces(Path(args.traces_file))
    field_names = _load_vocab(Path(args.field_vocab)) if args.field_vocab else None

    engine = make_engine(db_url)
    try:
        try:
            if args.apply:
                with Session(engine) as session, session.begin():
                    scope = load_scope(session, args.space_id)
                    result = apply_pull(
                        session,
                        scope,
                        args.source_id,
                        traces,
                        field_names=field_names,
                    )
            else:
                with Session(engine) as session:
                    # Session close rolls back the read transaction; preview_pull has
                    # no write path and therefore leaves all durable state untouched.
                    scope = load_scope(session, args.space_id)
                    result = preview_pull(
                        session,
                        scope,
                        args.source_id,
                        traces,
                        field_names=field_names,
                    )
        except (UnboundKnowledgeSpace, ScopeViolation):
            # fail-closed：不泄露 space 存在性/绑定细节（016 语义）
            print("[fail-closed] KnowledgeSpace 校验未通过，未执行任何操作")
            return 1
        except (OperationalError, ProgrammingError):
            print(
                "[fail-closed] 数据库 schema 缺失/过旧（迁移属部署流程，本命令不迁移）",
                file=sys.stderr,
            )
            return 1
        except (FlywheelRepositoryError, IntegrityError):
            print("[fail-closed] 飞轮批次校验或持久化失败，事务已回滚", file=sys.stderr)
            return 1
    finally:
        engine.dispose()

    print(_render(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurance_harness.flywheel")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="拉取 trace → 信号 → 对齐/聚合 → 报表（默认 dry-run）")
    p_pull.add_argument("--traces-file", required=True, help="JSONL：每行一条 Trace")
    p_pull.add_argument("--db-url", default=None)
    p_pull.add_argument("--space-id", required=True)
    p_pull.add_argument(
        "--source-id",
        required=True,
        help="稳定 trace 源标识（Space 内 checkpoint 键）",
    )
    p_pull.add_argument("--field-vocab", default=None, help="字段词表 JSON：{显示名: field_id}")
    p_pull.add_argument(
        "--apply", action="store_true", help="在数据库单事务持久化本批（缺省 dry-run 零写入）"
    )
    p_pull.add_argument(
        "--open-tickets",
        action="store_true",
        help="开单（受阻：候 F2.4 subject 形态协调，当前立即非零退出不开单）",
    )
    p_pull.set_defaults(func=cmd_pull)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

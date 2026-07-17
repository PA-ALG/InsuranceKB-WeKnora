"""F3.3 CLI：反馈飞轮 pull——编排 F1(信号)→F2(对齐/聚合)→F3(报表)。

    python -m insurance_harness.flywheel.cli pull \
        --traces-file traces.jsonl --db-url URL --space-id ID \
        [--cursor-file cur.txt] [--gaps-file gaps.json] \
        [--observations-out obs.jsonl] [--field-vocab vocab.json] \
        [--apply] [--open-tickets]

默认 **dry-run 零副作用**：只产出报表——不写游标/状态/导出文件、不执行 schema 迁移
（迁移属部署流程；schema 缺失/过旧 → 诚实非零退出）、DB 只读（产品索引）。缺 DB 配置
fail-closed 非零退出，**不**回退本地 SQLite（codex PR#18 阻断3）。`--apply` 才持久化：
推进游标文件、写缺口状态文件（跨周期累计/reopened 的依据：上轮输出=下轮输入）、导出
观察队列。`--open-tickets` 为**受阻能力**（F2.4 投影候 knowledge_gap subject 形态协调；
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
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db import make_engine
from insurance_harness.db.scope import ScopeViolation, UnboundKnowledgeSpace, load_scope
from insurance_harness.product.routing import MatchIndex

from .gaps import KnowledgeGap
from .models import Trace
from .pull import PullResult, run_pull


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


def _read_cursor(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _read_gaps(path: Path) -> list[KnowledgeGap]:
    """缺口状态文件（JSON 数组）：上轮 --apply 的输出=本轮跨周期累计的输入。"""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [KnowledgeGap.model_validate(item) for item in raw]


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
    cursor = _read_cursor(Path(args.cursor_file)) if args.cursor_file else None
    existing_gaps = _read_gaps(Path(args.gaps_file)) if args.gaps_file else []

    engine = make_engine(db_url)
    try:
        with Session(engine) as session:
            try:
                scope = load_scope(session, args.space_id)
                index = MatchIndex.from_session(session, scope)
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
    finally:
        engine.dispose()

    result = run_pull(
        traces, index, field_names=field_names, cursor=cursor, existing_gaps=existing_gaps
    )
    print(_render(result))

    if args.apply:
        # 持久化（F3.3）：游标推进 + 缺口状态（跨周期累计依据）+ 观察队列导出。
        if args.cursor_file and result.next_cursor:
            Path(args.cursor_file).write_text(result.next_cursor + "\n", encoding="utf-8")
        if args.gaps_file:
            Path(args.gaps_file).write_text(
                json.dumps(
                    [g.model_dump(mode="json") for g in result.gaps],
                    ensure_ascii=False, indent=1,
                ),
                encoding="utf-8",
            )
        if args.observations_out:
            with Path(args.observations_out).open("w", encoding="utf-8") as f:
                for obs in result.observations:
                    f.write(obs.model_dump_json() + "\n")
    # dry-run（默认）：预览不改状态——零文件写入、零游标推进（下轮可复现同报表）。
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurance_harness.flywheel")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="拉取 trace → 信号 → 对齐/聚合 → 报表（默认 dry-run）")
    p_pull.add_argument("--traces-file", required=True, help="JSONL：每行一条 Trace")
    p_pull.add_argument("--db-url", default=None)
    p_pull.add_argument("--space-id", required=True)
    p_pull.add_argument("--cursor-file", default=None, help="增量游标文件（--apply 才写）")
    p_pull.add_argument(
        "--gaps-file", default=None, help="缺口状态文件（跨周期累计；--apply 才写）"
    )
    p_pull.add_argument(
        "--observations-out", default=None, help="观察队列导出 JSONL（--apply 才写）"
    )
    p_pull.add_argument("--field-vocab", default=None, help="字段词表 JSON：{显示名: field_id}")
    p_pull.add_argument(
        "--apply", action="store_true", help="持久化游标/缺口状态/观察队列（缺省 dry-run 零写入）"
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

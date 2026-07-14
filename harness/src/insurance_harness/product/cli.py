"""CLI（spec P5）：

    python -m insurance_harness.product.cli register-products <dir> --space-id ID \
        [--db-url URL]
    python -m insurance_harness.product.cli classify <dir> --report out.md \
        --space-id ID [--db-url URL] [--unassigned-out out.jsonl]

连接串解析顺序：--db-url > HarnessSettings.db_url（HARNESS_DB_URL）> sqlite 本地文件（提示测试用）。
classify 对样本目录自动评分：文档类型以文件名为真值、产品归属以所在目录为真值（P4.5）。
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.config import HarnessSettings
from insurance_harness.db import make_engine
from insurance_harness.db.scope import load_scope
from insurance_harness.goldenset.pdf import extract_pages
from insurance_harness.product.classify import (
    DocumentType,
    classify_document,
    doc_type_from_filename,
)
from insurance_harness.product.register import register_products
from insurance_harness.product.routing import MatchIndex, persist_unassigned, route_document

_DEFAULT_SQLITE = "sqlite:///harness_product.db"


def _resolve_db_url(arg: str | None) -> str:
    """--db-url > HarnessSettings.db_url（即 HARNESS_DB_URL）> 本地 SQLite。"""
    if arg:
        return arg
    try:
        settings_url = HarnessSettings().db_url  # type: ignore[call-arg]  # 必填项来自环境变量
    except ValidationError:  # WeKnora 必填项未配置时仍允许纯 DB 场景
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


def cmd_register(args: argparse.Namespace) -> int:
    db_url = _resolve_db_url(args.db_url)
    _migrate(db_url)
    engine = make_engine(db_url)
    with Session(engine) as session:
        scope = load_scope(session, args.space_id)
        report = register_products(session, Path(args.directory), scope=scope)
    print(report.summary)
    for line in report.skipped:
        print(f"  skipped: {line}")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    db_url = _resolve_db_url(args.db_url)
    _migrate(db_url)
    engine = make_engine(db_url)
    root = Path(args.directory)

    rows: list[dict[str, object]] = []
    unassigned_rows: list[dict[str, object]] = []
    with Session(engine) as session:
        scope = load_scope(session, args.space_id)
        index = MatchIndex.from_session(session, scope)
        for pdf in sorted(root.rglob("*.pdf")):
            pages = extract_pages(pdf)
            cls = asyncio.run(classify_document(pdf.name, pages))
            route = route_document(index, str(pdf), pages)
            truth_dir = pdf.parent.name
            exact_hit = any(
                c.confidence == "exact" and c.canonical_name == truth_dir
                for c in route.candidates
            )
            truth_type = doc_type_from_filename(pdf.name)
            rows.append(
                {
                    "pdf": str(pdf.relative_to(root)),
                    "doc_type": cls.doc_type.value,
                    "type_confidence": cls.confidence,
                    "type_basis": "；".join(cls.basis),
                    "truth_type": truth_type.value if truth_type else None,
                    "type_correct": (truth_type is not None and cls.doc_type is truth_type),
                    "used_llm": cls.used_llm,
                    "truth_product": truth_dir,
                    "exact_hit": exact_hit,
                    "candidates": [
                        f"{c.canonical_name}[{c.confidence}] p{c.page_first}-{c.page_last}"
                        for c in route.candidates
                    ],
                }
            )
            # P4.4：unassigned 落池表 + 导出 JSONL
            persist_unassigned(session, scope, route.unassigned)
            for u in route.unassigned:
                unassigned_rows.append(json.loads(u.model_dump_json()))
        session.commit()

    _write_report(Path(args.report), rows, len(unassigned_rows))
    if args.unassigned_out:
        with Path(args.unassigned_out).open("w", encoding="utf-8") as f:
            for row in unassigned_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    n = len(rows)
    exact = sum(1 for r in rows if r["exact_hit"])
    type_ok = sum(1 for r in rows if r["type_correct"])
    llm_used = sum(1 for r in rows if r["used_llm"])
    print(
        f"PDF={n} 类型正确={type_ok} ({type_ok / n:.1%}) exact命中={exact} ({exact / n:.1%}) "
        f"LLM调用={llm_used} 未归属={len(unassigned_rows)}"
    )
    return 0


def _write_report(path: Path, rows: list[dict[str, object]], n_unassigned: int) -> None:
    n = len(rows)
    exact = sum(1 for r in rows if r["exact_hit"])
    type_ok = sum(1 for r in rows if r["type_correct"])
    type_known = sum(1 for r in rows if r["doc_type"] != DocumentType.UNKNOWN.value)
    lines = [
        "# 003 分类与路由验证报告",
        "",
        f"- PDF 总数：{n}",
        f"- 文档类型正确（以文件名关键词为真值）：{type_ok}/{n}（{type_ok / n:.1%}）",
        f"- 文档类型判定非未知：{type_known}/{n}",
        f"- 产品 exact 命中（以所在目录为真值）：{exact}/{n}（{exact / n:.1%}，门槛 ≥90%）",
        f"- LLM 调用次数：{sum(1 for r in rows if r['used_llm'])}（P3.2 要求 0）",
        f"- unassigned 草稿：{n_unassigned}",
        "",
        "| PDF | 类型 | 真值类型 | 类型✓ | 置信 | exact | 候选 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['pdf']} | {r['doc_type']} | {r['truth_type'] or '—'} "
            f"| {'✅' if r['type_correct'] else '❌'} | {r['type_confidence']} "
            f"| {'✅' if r['exact_hit'] else '❌'} | {'；'.join(r['candidates'])} |"  # type: ignore[arg-type]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurance_harness.product")
    sub = parser.add_subparsers(dest="command", required=True)

    p_reg = sub.add_parser("register-products", help="注册产品主数据（幂等）")
    p_reg.add_argument("directory")
    p_reg.add_argument("--db-url", default=None)
    p_reg.add_argument("--space-id", required=True)
    p_reg.set_defaults(func=cmd_register)

    p_cls = sub.add_parser("classify", help="分类+路由并产出验证报告")
    p_cls.add_argument("directory")
    p_cls.add_argument("--report", required=True)
    p_cls.add_argument("--db-url", default=None)
    p_cls.add_argument("--space-id", required=True)
    p_cls.add_argument("--unassigned-out", default=None)
    p_cls.set_defaults(func=cmd_classify)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

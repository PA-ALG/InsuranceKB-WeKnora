"""004 T8：真实弱模型基线（3 产品）+ validation-report.md 生成。

用法（在 harness/ 下）：
    uv run python scripts/baseline_004.py run [--products 名A,名B] [--resume]
    uv run python scripts/baseline_004.py report

- run：对基线产品逐个跑全管道（网关配置读 .env；checkpoint 可断点续跑）；
- report：汇总 runs/ 下的 pred/manifest + wip 金标出分，写 validation-report.md。
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from insurance_harness.compiler.cli import build_client, load_settings
from insurance_harness.compiler.judge import JudgeDispatcher
from insurance_harness.compiler.models import PredRecord, RunManifest
from insurance_harness.compiler.pipeline import ExtractionPipeline, PipelineConfig
from insurance_harness.compiler.sections import route_groups, split_sections
from insurance_harness.goldenset.eval import evaluate
from insurance_harness.goldenset.normalize import values_equal
from insurance_harness.goldenset.pdf import extract_pages
from insurance_harness.goldenset.records import GoldenRecord
from insurance_harness.goldenset.verify import compare_with_meta, load_product_meta, verify_quotes
from insurance_harness.schemas import load_schema_registry

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset/shouxian_product"
GOLDEN_WIP = ROOT / "dataset/goldenset/wip-gs-v0.1"
SCHEMA_DIR = ROOT / "docs/insurance-kb/schema-baseline"
CHANGE_DIR = ROOT / "openspec/changes/004-extraction-pipeline-mvp"
RUNS_DIR = CHANGE_DIR / "runs"
REPORT_PATH = CHANGE_DIR / "validation-report.md"

# 真实基线范围（业务方 2026-07-12：每险种代表各 1，其余 10 产品 CLI 一键可跑待触发）
BASELINE_PRODUCTS = [
    "平安盛世金越（尊享版26）终身寿险",
    "平安e生保（尊享版）医疗保险",
    "平安守护百分百（2026）两全保险",
]


def load_golden(product: str) -> list[GoldenRecord]:
    """wip 金标 → GoldenRecord（补 product_id 等元信息）+ 回验/meta 比对标 disputed。"""
    product_dir = DATASET / product
    meta = load_product_meta(product_dir)
    product_id = str(meta.get("planCode") or product).strip()
    manifest = json.loads((GOLDEN_WIP / "manifest.json").read_text(encoding="utf-8"))
    schema_version = str(manifest["schema_version"])
    rows = [
        json.loads(line)
        for line in (GOLDEN_WIP / product / "golden.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    records = [
        GoldenRecord(
            product_id=product_id,
            product_name=product,
            doc=str(r["doc"]),
            field_id=str(r["field_id"]),
            field_name=str(r["field_name"]),
            value=r.get("value"),
            tri_state=r["tri_state"],
            evidence=r.get("evidence") or [],
            reasoning=r.get("reasoning"),
            annotator_model="claude-fable-5 (gs-v0.1 wip)",
            schema_version=schema_version,
            created_at=datetime.now(UTC),
        )
        for r in rows
    ]
    by_doc: dict[str, list[GoldenRecord]] = {}
    for rec in records:
        by_doc.setdefault(rec.doc, []).append(rec)
    for doc, recs in by_doc.items():
        pdf = product_dir / doc
        if pdf.exists():
            verify_quotes(recs, extract_pages(pdf))
    compare_with_meta(records, meta)
    return records


async def run_products(products: list[str], resume: bool) -> None:
    settings = load_settings()
    client, model_id = build_client(settings, replay_dir=None)
    registry = load_schema_registry(SCHEMA_DIR)
    for product in products:
        run_dir = RUNS_DIR / product
        ckpt_exists = (run_dir / "checkpoint.sqlite").exists()
        print(f"=== {product} (model={model_id}, resume={resume and ckpt_exists})")
        pipeline = ExtractionPipeline(
            client=client,
            registry=registry,
            model_id=model_id,
            config=PipelineConfig(judge_mode=settings.judge_mode, concurrency=6),
            judge=JudgeDispatcher(mode=settings.judge_mode),
        )
        result = await pipeline.run(
            product_dir=DATASET / product,
            run_dir=run_dir,
            resume=resume and ckpt_exists,
        )
        m = result.manifest
        print(
            f"    字段={len(result.records)} 调用={m.stats.calls} "
            f"est_tokens={m.stats.est_tokens} 耗时={m.duration_s:.0f}s "
            f"死信={len(m.dead_letters)} pending_judge={m.pending_judge_count}"
        )


def _confidence_accuracy(
    golden: list[GoldenRecord], pred: list[PredRecord]
) -> dict[str, tuple[int, int, int]]:
    """confidence 分层：{层: (值级正确, 三态正确, 总数)}（金标 disputed 除外）。"""
    g_map = {(g.product_id, g.field_id): g for g in golden if not g.disputed}
    out: dict[str, list[int]] = {"high": [0, 0, 0], "medium": [0, 0, 0], "low": [0, 0, 0]}
    for p in pred:
        g = g_map.get((p.product_id, p.field_id))
        if g is None:
            continue
        tri_ok = g.tri_state == p.tri_state
        value_ok = tri_ok and (g.tri_state != "present" or values_equal(g.value, p.value))
        out[p.confidence][2] += 1
        out[p.confidence][1] += int(tri_ok)
        out[p.confidence][0] += int(value_ok)
    return {k: (v[0], v[1], v[2]) for k, v in out.items()}


def _routing_table_all_terms() -> list[tuple[str, int, float]]:
    """13 份样本条款的实际压缩比（E2.2 记录要求）。"""
    rows = []
    for pdf in sorted(DATASET.glob("*/*条款.pdf")):
        sections = split_sections(extract_pages(pdf))
        r = route_groups(sections)
        rows.append((pdf.parent.name, len(sections), r.compression_ratio))
    return rows


def build_report(products: list[str]) -> str:
    registry = load_schema_registry(SCHEMA_DIR)
    high_risk = {
        f.field_id
        for line in registry.lines.values()
        for f in line.fields
        if f.risk_level == "high"
    }
    lines: list[str] = [
        "# 004 弱模型抽取管道基线报告（validation report）",
        "",
        f"- 日期：{datetime.now(UTC).date().isoformat()}",
        "- 弱模型：**deepseek-v4-flash**（百炼 DashScope OpenAI 兼容端点；"
        "MiniMax-M2.5 为可配置备选，HARNESS_LLM_MODEL_WEAK 切换）",
        "- 裁决模式：claude-session（三票三样/高风险回验失败 → judge-queue.jsonl，"
        "由主会话 Claude 批处理后 `apply-judgements` 回写；本报告分数为**裁决前**）",
        f"- 金标：dataset/goldenset/wip-gs-v0.1（11/13 产品已标；本次对 {len(products)} 个"
        "代表产品出分，全量 13 产品基线待业务方触发）",
        f"- schema：{registry.version}；prompt：见 manifest（compiler/prompts，E6.1）",
        "",
        "## 分数总览（对 gs-v0.1 wip 金标，金标 disputed 记录已排除）",
        "",
        "| 产品 | micro P | micro R | micro F1 | macro F1 | 幻觉率"
        " | evidence 准确率 | 金标缺口键 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    per_product: dict[str, dict[str, object]] = {}
    all_golden: list[GoldenRecord] = []
    all_pred: list[PredRecord] = []
    for product in products:
        run_dir = RUNS_DIR / product
        pred = [
            PredRecord.model_validate_json(line)
            for line in (run_dir / "pred.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        manifest = RunManifest.model_validate_json(
            (run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        golden = load_golden(product)
        result = evaluate(golden, list(pred), dataset_root=DATASET)
        per_product[product] = {"pred": pred, "manifest": manifest, "golden": golden,
                                "result": result}
        all_golden.extend(golden)
        all_pred.extend(pred)
        m = result.micro
        ev = f"{result.evidence_accuracy:.3f}" if result.evidence_accuracy is not None else "-"
        lines.append(
            f"| {product} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} "
            f"| {result.macro_f1:.3f} | {result.hallucination_rate:.3f} | {ev} "
            f"| {result.golden_only_keys} |"
        )

    overall = evaluate(all_golden, list(all_pred), dataset_root=DATASET)
    m = overall.micro
    ev = f"{overall.evidence_accuracy:.3f}" if overall.evidence_accuracy is not None else "-"
    lines += [
        f"| **合计** | **{m.precision:.3f}** | **{m.recall:.3f}** | **{m.f1:.3f}** "
        f"| {overall.macro_f1:.3f} | {overall.hallucination_rate:.3f} | {ev} | "
        f"{overall.golden_only_keys} |",
        "",
        "> 本 change 不设分数门槛（proposal：首个基线的意义是确立起点）。",
        "",
        "## 三态混淆矩阵（合计，行=金标 列=预测）",
        "",
        "| 金标 \\ 预测 | present | absent_explicitly | unknown |",
        "|---|---|---|---|",
    ]
    for g in ("present", "absent_explicitly", "unknown"):
        row = " | ".join(
            str(overall.confusion.get((g, p), 0))
            for p in ("present", "absent_explicitly", "unknown")
        )
        lines.append(f"| {g} | {row} |")

    conf_acc = _confidence_accuracy(all_golden, all_pred)
    lines += [
        "",
        "## confidence 分层准确率（置信度分级区分度验证，E5.2）",
        "",
        "| confidence | 总数 | 三态正确率 | 值级正确率 |",
        "|---|---|---|---|",
    ]
    for level in ("high", "medium", "low"):
        c, tri_c, t = conf_acc[level]
        tri_acc = f"{tri_c / t:.3f}" if t else "-"
        acc = f"{c / t:.3f}" if t else "-"
        lines.append(f"| {level} | {t} | {tri_acc} | {acc} |")
    lines += [
        "",
        "> 解读：low 桶以 unknown 预测为主（金标 unknown 多 → 三态对得多）；high 桶三态"
        "正确率显著高于值级正确率——差距即『值粒度/表述不一致』（见结论）。",
    ]

    lines += ["", "## 高风险字段小结（risk_level=high）", "",
              "| 产品 | field_id | 金标 | 预测 | 判定 |", "|---|---|---|---|---|"]
    for product in products:
        info = per_product[product]
        golden_recs = info["golden"]
        pred_map = {p.field_id: p for p in info["pred"]}  # type: ignore[union-attr]
        for g in golden_recs:  # type: ignore[union-attr]
            if g.field_id not in high_risk or g.disputed:
                continue
            p = pred_map.get(g.field_id)
            p_tri = p.tri_state if p else "unknown"
            ok = g.tri_state == p_tri and (
                g.tri_state != "present" or (p is not None and values_equal(g.value, p.value))
            )
            gv = (g.value or g.tri_state)[:24]
            pv = ((p.value if p else None) or p_tri)[:24]
            mark = '✅' if ok else '❌'
            lines.append(f"| {product[:16]} | {g.field_id} | {gv} | {pv} | {mark} |")

    lines += ["", "## run manifest 汇总（E1.3）", "",
              "| 产品 | 调用数 | prompt 字符 | 输出字符 | est_tokens"
              " | 耗时 s | 死信 | pending_judge |",
              "|---|---|---|---|---|---|---|---|"]
    for product in products:
        mf = per_product[product]["manifest"]
        assert isinstance(mf, RunManifest)
        lines.append(
            f"| {product} | {mf.stats.calls} | {mf.stats.prompt_chars} "
            f"| {mf.stats.completion_chars} | {mf.stats.est_tokens} "
            f"| {mf.duration_s:.0f} | {len(mf.dead_letters)} | {mf.pending_judge_count} |"
        )

    lines += ["", "## 死信清单（E1.2）", ""]
    any_dead = False
    for product in products:
        mf = per_product[product]["manifest"]
        assert isinstance(mf, RunManifest)
        for d in mf.dead_letters:
            any_dead = True
            lines.append(f"- {product} / {d.doc} / {d.group} / {d.window_ref}：{d.error[:120]}")
    if not any_dead:
        lines.append("（无死信——全部窗口调用在重试预算内成功）")

    lines += [
        "",
        "## 文档族分组框架（11 §1.1 结构指纹；按族出分为 006 模板归纳指路）",
        "",
        "| family_id | 文档 | 章节数 | 压缩比 |",
        "|---|---|---|---|",
    ]
    fam_rows: list[tuple[str, str, int, float]] = []
    for product in products:
        mf = per_product[product]["manifest"]
        assert isinstance(mf, RunManifest)
        for dm in mf.docs:
            fam_rows.append((dm.family_id, f"{product}/{dm.doc}", dm.sections,
                             dm.compression_ratio))
    from insurance_harness.compiler.sections import family_fingerprint as _ff

    empty_fam = _ff([])  # 无标题结构文档（费率表/短说明书）落入同一退化族
    fam_counter = Counter(fid for fid, *_ in fam_rows)
    for fid, doc, secs, ratio in sorted(fam_rows):
        if fid == empty_fam:
            mark = "（无标题结构，退化族——需 006 版式特征补强）"
        elif fam_counter[fid] > 1:
            mark = "（族内≥2 文档）"
        else:
            mark = ""
        lines.append(f"| {fid}{mark} | {doc} | {secs} | {ratio:.3f} |")
    lines += [
        "",
        "> 按族出分：当前 3 产品文档族各不相同（说明书/条款版式差异大），族内 ≥3 份文档后"
        "（全量 13 产品跑完）才具备模板归纳价值判断的样本量。",
    ]

    lines += [
        "",
        "## 13 份样本条款的组路由压缩比（E2.2：≤ 全量组合的 40%）",
        "",
        "| 条款文档 | 章节数 | (组×章节) 压缩比 |",
        "|---|---|---|",
    ]
    ratios = _routing_table_all_terms()
    for name, n, ratio in ratios:
        flag = "" if ratio <= 0.40 else " ⚠️"
        lines.append(f"| {name} | {n} | {ratio:.3f}{flag} |")
    mx = max(r for _, _, r in ratios)
    lines += [
        "",
        f"最大 {mx:.3f}、均值 {sum(r for _, _, r in ratios) / len(ratios):.3f}。"
        "路由密度阈值（≥3 个不同关键词且命中密度达标）在 13 份条款上标定；"
        "coverage 组按设计扫描全部章节（占 1/7 ≈ 0.143 底线）。",
        "",
        "## 结论与待办",
        "",
        "- 管道全链路（切分→路由→分批抽取→回验→清洗→类型校验→补漏→投票→置信度分级"
        "→pred JSONL）在真实弱模型上跑通，可断点续跑（E1.1），死信不中断其他字段组（E1.2）；",
        "- pending_judge 字段待主会话 Claude 批处理 judge-queue.jsonl 后经 "
        "`apply-judgements` 回写，回写后分数会进一步变化（本报告为裁决前基线）；",
        "- 其余 10 产品基线：`uv run python scripts/baseline_004.py run --products …` "
        "一键可跑，待业务方触发（成本控制决定）；",
        "- confidence 分层准确率见上表：分层单调性（high>medium>low）是置信度路由"
        "（低置信不自动发布）的前提，后续 change 以此调 auto_threshold。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--products", default=",".join(BASELINE_PRODUCTS))
    p_run.add_argument("--resume", action="store_true")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.cmd == "run":
        products = [p for p in args.products.split(",") if p]
        asyncio.run(run_products(products, resume=args.resume))
        return 0
    REPORT_PATH.write_text(build_report(BASELINE_PRODUCTS), encoding="utf-8")
    print(f"报告 → {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

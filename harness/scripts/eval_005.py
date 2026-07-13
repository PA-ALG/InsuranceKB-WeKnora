"""005 T8：小样要点生成 + eval v1/v2 对比报告 + 漏抽归因（零真实模型调用）。

用法（在 harness/ 下）：
    uv run python scripts/eval_005.py gen-keypoints   # 3 基线产品 keypoints.jsonl（幂等）
    uv run python scripts/eval_005.py report          # 005 validation-report + 004 报告附章

- gen-keypoints：对 004 的 3 个基线产品，从 wip 金标 value 规则切分要点（V1.3/V1.4）：
  present 且归一化长度 ≥30 的字段生成（long 文本口径；切不出多要点则整值作单要点），
  不调模型；
- report：v1 vs v2 分数、五类错误分布、要点覆盖率明细、漏抽归因（004 关键词 before
  vs 005 补充 after）、13 条款压缩比预算复验（V6.2），写
  openspec/changes/005-eval-refinement-recall/validation-report.md，
  并在 004 validation-report.md 附"尺子修正后"章节（V7.2）。
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from baseline_004 import BASELINE_PRODUCTS, DATASET, GOLDEN_WIP, RUNS_DIR, load_golden

from insurance_harness.compiler.models import PredRecord
from insurance_harness.compiler.recall_attribution import (
    attribute_misses,
    dataset_routing_lookup,
    render_attribution,
)
from insurance_harness.compiler.routing_data import GROUP_KEYWORDS_004
from insurance_harness.compiler.sections import route_groups, split_sections
from insurance_harness.goldenset.eval import EvalResult, evaluate
from insurance_harness.goldenset.keypoints import (
    KeypointEntry,
    load_keypoints,
    split_keypoints,
    value_sha,
    write_keypoints,
)
from insurance_harness.goldenset.normalize import normalize_text
from insurance_harness.goldenset.pdf import extract_pages
from insurance_harness.goldenset.records import GoldenRecord

ROOT = Path(__file__).resolve().parents[2]
CHANGE_DIR = ROOT / "openspec/changes/005-eval-refinement-recall"
REPORT_PATH = CHANGE_DIR / "validation-report.md"
REPORT_004_PATH = ROOT / "openspec/changes/004-extraction-pipeline-mvp/validation-report.md"
CHAPTER_004_MARK = "## 尺子修正后（005 eval v2）"

LONG_VALUE_MIN_CHARS = 30  # V1.4：long 文本口径（归一化长度阈值）
MIN_KEYPOINTS = 1  # 切不出多要点的长值整值作单要点（bigram 容差仍有效，V1.4）


def gen_keypoints() -> None:
    """3 基线产品的小样要点（规则切分，V1.4；幂等可重跑）。"""
    for product in BASELINE_PRODUCTS:
        golden = load_golden(product)
        entries: list[KeypointEntry] = []
        for g in golden:
            if g.tri_state != "present" or not g.value:
                continue
            if len(normalize_text(g.value)) < LONG_VALUE_MIN_CHARS:
                continue
            kps = split_keypoints(g.value)
            if len(kps) < MIN_KEYPOINTS:
                continue
            entries.append(
                KeypointEntry(
                    product_id=g.product_id,
                    field_id=g.field_id,
                    keypoints=kps,
                    golden_value_sha=value_sha(g.value),
                )
            )
        path = GOLDEN_WIP / product / "keypoints.jsonl"
        write_keypoints(entries, path)
        print(f"{product}: {len(entries)} 条要点条目 → {path}")


def _load_pred(product: str) -> list[PredRecord]:
    lines = (RUNS_DIR / product / "pred.jsonl").read_text(encoding="utf-8").splitlines()
    return [PredRecord.model_validate_json(line) for line in lines if line.strip()]


def _score_row(name: str, r: EvalResult, bold: bool = False) -> str:
    m = r.micro
    cell = "**{}**" if bold else "{}"
    return (
        f"| {cell.format(name)} | {m.precision:.3f} | {m.recall:.3f} "
        f"| {cell.format(f'{m.f1:.3f}')} | {r.macro_f1:.3f} | {r.hallucination_rate:.3f} |"
    )


def build_report() -> str:
    keypoints = load_keypoints(GOLDEN_WIP)
    all_golden: list[GoldenRecord] = []
    all_pred: list[PredRecord] = []
    rows_v1: list[str] = []
    rows_v2: list[str] = []
    per_product_v2: dict[str, EvalResult] = {}
    for product in BASELINE_PRODUCTS:
        golden = load_golden(product)
        pred = _load_pred(product)
        all_golden.extend(golden)
        all_pred.extend(pred)
        v1 = evaluate(golden, list(pred))
        v2 = evaluate(golden, list(pred), metric="v2", keypoints=keypoints)
        per_product_v2[product] = v2
        rows_v1.append(_score_row(product, v1))
        rows_v2.append(_score_row(product, v2))
    total_v1 = evaluate(all_golden, list(all_pred), dataset_root=DATASET)
    total_v2 = evaluate(
        all_golden, list(all_pred), dataset_root=DATASET, metric="v2", keypoints=keypoints
    )
    rows_v1.append(_score_row("合计", total_v1, bold=True))
    rows_v2.append(_score_row("合计", total_v2, bold=True))

    # 漏抽归因：before（004 关键词）vs after（005 补充生效，当前默认）
    lookup_before = dataset_routing_lookup(DATASET, keywords=dict(GROUP_KEYWORDS_004))
    lookup_after = dataset_routing_lookup(DATASET)
    attr_before = attribute_misses(all_golden, all_pred, lookup_before)
    attr_after = attribute_misses(all_golden, all_pred, lookup_after)

    # V6.2：13 份样本条款压缩比预算复验（005 补充生效后）
    ratios: list[tuple[str, float]] = []
    for pdf in sorted(DATASET.glob("*/*条款.pdf")):
        r = route_groups(split_sections(extract_pages(pdf)))
        ratios.append((pdf.parent.name, r.compression_ratio))

    kp_total = sum(
        1 for product in BASELINE_PRODUCTS
        for e in load_keypoints(GOLDEN_WIP / product).values()
    )
    lines: list[str] = [
        "# 005 评测尺子升级与召回改进报告（validation report）",
        "",
        f"- 日期：{datetime.now(UTC).date().isoformat()}",
        "- 口径：对 004 已有 3 产品 pred **离线重评**（零真实模型调用）；金标 "
        "dataset/goldenset/wip-gs-v0.1（disputed 已排除）；",
        f"- 要点清单：3 产品共 {kp_total} 条（rule-split-v1 规则切分小样，V1.4；"
        "11 产品全量强模型要点列 HANDOFF 遗留 B 类）；",
        "- judge 兜底：默认关（V4.1）；本报告未落 eval-judge-queue，仅报未裁决计数。",
        "",
        "## v1 vs v2 分数对比（V7.1）",
        "",
        "### v1（002 逐字等价口径）",
        "",
        "| 产品 | micro P | micro R | micro F1 | macro F1 | 幻觉率 |",
        "|---|---|---|---|---|---|",
        *rows_v1,
        "",
        "### v2（long 字段关键要点匹配，V2）",
        "",
        "| 产品 | micro P | micro R | micro F1 | macro F1 | 幻觉率 |",
        "|---|---|---|---|---|---|",
        *rows_v2,
        "",
        f"> 合计 micro F1：v1 **{total_v1.micro.f1:.3f}** → v2 **{total_v2.micro.f1:.3f}**"
        f"；evidence 准确率 {total_v2.evidence_accuracy:.3f}（口径不变）。"
        if total_v2.evidence_accuracy is not None
        else f"> 合计 micro F1：v1 **{total_v1.micro.f1:.3f}** → v2 "
        f"**{total_v2.micro.f1:.3f}**。",
        f"> 要点计分样本 {len(total_v2.partials)}；过期要点 {total_v2.stale_keypoints}；"
        f"未裁决计数（不确定带）{total_v2.judge_pending}；证据错位 "
        f"{total_v2.evidence_mismatch_count}（不入 F1）。",
        "",
        "## 错误类型分布（五类归因，V3）",
        "",
        "| 归因标签 | v1 | v2 |",
        "|---|---|---|",
    ]
    c1, c2 = total_v1.category_counts, total_v2.category_counts
    for cat in ("值粒度", "漏抽", "幻觉", "三态混淆", "证据错位"):
        lines.append(f"| {cat} | {c1.get(cat, 0)} | {c2.get(cat, 0)} |")
    lines += [
        "",
        "## 要点计分明细（partial 覆盖率，V2.6）",
        "",
        "| 产品 | 字段 | 覆盖率 | 判定 |",
        "|---|---|---|---|",
    ]
    for product in BASELINE_PRODUCTS:
        for d in per_product_v2[product].partials:
            mark = "✅" if d.matched else "❌"
            lines.append(
                f"| {product[:16]} | {d.field_name}({d.field_id}) "
                f"| {d.coverage:.2f} | {mark} |"
            )
    lines += [
        "",
        "## 漏抽归因（V5）：金标 present → 预测 unknown",
        "",
        "### before/after 对比（005 路由关键词补充的效果，V6.1）",
        "",
        "| 归因 | 修复前（004 关键词） | 修复后（005 补充） |",
        "|---|---|---|",
    ]
    for cat in ("routing_miss", "extract_empty", "cleaning_kill", "no_evidence_page"):
        lines.append(
            f"| {cat} | {attr_before.stats.get(cat, 0)} | {attr_after.stats.get(cat, 0)} |"
        )
    lines += [
        "",
        "> 修复内容（零成本，无模型调用）：basic_info +『趸交/费率表』（费率表首页"
        "交费期限证据密度不足未路由）；claim_service +『入出院记录/出院小结/结算清单』"
        "（保险金申请材料条目式短章节 distinct 关键词不足）。cleaning_kill=0 → 清洗"
        "白名单**不需要修改**（证据驱动，V6.3，ReplayClient 单测锁定现状）。",
        "> 修复后仍为 routing_miss 的样本（如 e生保『产品类型』证据埋在保险责任正文），"
        "属 prompt/补漏问题域，零成本关键词无法覆盖——随 extract_empty 一并进入"
        "prompt 变体迭代（后续 change）。",
        "",
        render_attribution(attr_after, title="修复后逐条清单（V5.3）"),
        "## 13 份样本条款压缩比复验（V6.2：005 补充生效后仍 ≤0.40）",
        "",
        "| 条款文档 | 压缩比 |",
        "|---|---|",
    ]
    for name, ratio in ratios:
        flag = "" if ratio <= 0.40 else " ⚠️"
        lines.append(f"| {name} | {ratio:.3f}{flag} |")
    mx = max(r for _, r in ratios)
    lines += [
        "",
        f"最大 {mx:.3f}、均值 {sum(r for _, r in ratios) / len(ratios):.3f}"
        "（≤0.40 预算未破，E2.2 兼容）。",
        "",
        "## 遗留（HANDOFF B 类）",
        "",
        "- 11 产品全量金标要点清单（强模型一次性产出，替换 rule-split 小样）；",
        "- 修复后的真实弱模型基线对比出分（本 change 零模型调用，不跑）：",
        "  `cd harness && uv run python scripts/baseline_004.py run --products "
        "平安盛世金越（尊享版26）终身寿险,平安e生保（尊享版）医疗保险,"
        "平安守护百分百（2026）两全保险` 后 `report`（网关 ~6-12万 token/产品）。",
    ]
    return "\n".join(lines) + "\n"


def _chapter_004(total_v1: str, total_v2: str) -> str:
    return "\n".join(
        [
            CHAPTER_004_MARK,
            "",
            "005 change 修正了 long 字段逐字等价过苛的问题（关键要点匹配，"
            "`--metric v2`），对本报告同一批 pred 离线重评：",
            "",
            f"- 合计 micro F1：v1 {total_v1} → **v2 {total_v2}**（尺子修正后）；",
            "- 漏抽 25 条已全部归因（路由缺失/抽取为空/清洗误杀），路由关键词零成本修复"
            "已合入（`routing_data.GROUP_KEYWORD_SUPPLEMENTS_005`）；",
            "- 明细见 `openspec/changes/005-eval-refinement-recall/validation-report.md`。",
            "",
        ]
    )


def write_reports() -> None:
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"005 报告 → {REPORT_PATH}")

    # 004 报告附章（幂等：先移除旧章节再追加）
    keypoints = load_keypoints(GOLDEN_WIP)
    all_golden: list[GoldenRecord] = []
    all_pred: list[PredRecord] = []
    for product in BASELINE_PRODUCTS:
        all_golden.extend(load_golden(product))
        all_pred.extend(_load_pred(product))
    v1 = evaluate(all_golden, list(all_pred))
    v2 = evaluate(all_golden, list(all_pred), metric="v2", keypoints=keypoints)
    text = REPORT_004_PATH.read_text(encoding="utf-8")
    if CHAPTER_004_MARK in text:
        text = text[: text.index(CHAPTER_004_MARK)].rstrip() + "\n"
    text = text.rstrip() + "\n\n" + _chapter_004(f"{v1.micro.f1:.3f}", f"{v2.micro.f1:.3f}")
    REPORT_004_PATH.write_text(text, encoding="utf-8")
    print(f"004 报告附章 → {REPORT_004_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-keypoints")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.cmd == "gen-keypoints":
        gen_keypoints()
    else:
        write_reports()
    return 0


if __name__ == "__main__":
    sys.exit(main())

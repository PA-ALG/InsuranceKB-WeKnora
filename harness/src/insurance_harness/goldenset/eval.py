"""Eval runner（spec G4）：金标 vs 抽取结果 → 字段级指标 + markdown 报告。

用法：
    python -m insurance_harness.goldenset.eval \
        --golden dataset/goldenset/gs-v0.1 --pred pred.jsonl --report report.md \
        [--schema-dir docs/insurance-kb/schema-baseline] [--dataset-root dataset/shouxian_product]
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import quote_in_page, values_equal
from .records import GoldenRecord, TriState
from .runner import load_release, read_jsonl

_TRI: tuple[TriState, ...] = ("present", "absent_explicitly", "unknown")


@dataclass
class FieldStats:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class ErrorDetail:
    product_id: str
    field_id: str
    field_name: str
    kind: str  # value_mismatch / false_present / missed / tri_state
    golden_value: str | None
    pred_value: str | None


@dataclass
class EvalResult:
    per_field: dict[str, FieldStats]
    micro: FieldStats
    confusion: dict[tuple[TriState, TriState], int]  # (golden, pred) -> count
    hallucination_rate: float
    evidence_accuracy: float | None  # None = 未启用（缺 --dataset-root 或 pred 无证据）
    errors: list[ErrorDetail] = field(default_factory=list)
    golden_disputed_excluded: int = 0
    pred_only_keys: int = 0
    golden_only_keys: int = 0

    @property
    def macro_f1(self) -> float:
        if not self.per_field:
            return 0.0
        return sum(s.f1 for s in self.per_field.values()) / len(self.per_field)


def evaluate(
    golden: list[GoldenRecord],
    pred: list[GoldenRecord],
    dataset_root: Path | None = None,
) -> EvalResult:
    usable = [g for g in golden if not g.disputed]
    excluded = len(golden) - len(usable)
    g_map = {(g.product_id, g.field_id): g for g in usable}
    p_map = {(p.product_id, p.field_id): p for p in pred}

    per_field: dict[str, FieldStats] = defaultdict(FieldStats)
    micro = FieldStats()
    confusion: Counter[tuple[TriState, TriState]] = Counter()
    errors: list[ErrorDetail] = []
    pred_present = 0
    hallucinated = 0

    for key, g in g_map.items():
        p = p_map.get(key)
        p_tri: TriState = p.tri_state if p is not None else "unknown"
        confusion[(g.tri_state, p_tri)] += 1

        if p is not None and p.tri_state == "present":
            pred_present += 1
            if g.tri_state != "present":
                hallucinated += 1

        stats = per_field[g.field_id]
        if g.tri_state == "present" and p_tri == "present":
            assert p is not None
            if values_equal(g.value, p.value):
                stats.tp += 1
                micro.tp += 1
            else:
                stats.fp += 1
                stats.fn += 1
                micro.fp += 1
                micro.fn += 1
                errors.append(
                    ErrorDetail(
                        key[0], g.field_id, g.field_name, "value_mismatch", g.value, p.value
                    )
                )
        elif g.tri_state == "present":
            stats.fn += 1
            micro.fn += 1
            errors.append(
                ErrorDetail(key[0], g.field_id, g.field_name, "missed", g.value, None)
            )
        elif p_tri == "present":
            assert p is not None
            stats.fp += 1
            micro.fp += 1
            errors.append(
                ErrorDetail(key[0], g.field_id, g.field_name, "false_present", g.value, p.value)
            )
        elif g.tri_state != p_tri:
            errors.append(
                ErrorDetail(key[0], g.field_id, g.field_name, "tri_state", g.tri_state, p_tri)
            )

    # pred 中金标没有的键：多余预测按 false_present 计入 micro FP（覆盖面之外的幻觉）
    pred_only = 0
    for key, p in p_map.items():
        if key in g_map:
            continue
        pred_only += 1
        if p.tri_state == "present":
            pred_present += 1
            micro.fp += 1

    evidence_accuracy = _evidence_accuracy(pred, dataset_root) if dataset_root else None
    return EvalResult(
        per_field=dict(per_field),
        micro=micro,
        confusion=dict(confusion),
        hallucination_rate=(hallucinated / pred_present) if pred_present else 0.0,
        evidence_accuracy=evidence_accuracy,
        errors=errors,
        golden_disputed_excluded=excluded,
        pred_only_keys=pred_only,
        golden_only_keys=len(g_map) - sum(1 for k in g_map if k in p_map),
    )


def _evidence_accuracy(pred: list[GoldenRecord], dataset_root: Path) -> float | None:
    """按回验逻辑对原 PDF 校验 pred 的引文（G4.2）；pred 无证据时返回 None。"""
    from .pdf import extract_pages

    page_cache: dict[Path, dict[int, str]] = {}
    total = 0
    ok = 0
    for r in pred:
        if not r.evidence:
            continue
        pdf_path = dataset_root / r.product_name / r.doc
        if not pdf_path.exists():
            continue
        if pdf_path not in page_cache:
            page_cache[pdf_path] = {p.page_no: p.text for p in extract_pages(pdf_path)}
        pages = page_cache[pdf_path]
        for ev in r.evidence:
            total += 1
            if ev.page in pages and quote_in_page(ev.quote, pages[ev.page]):
                ok += 1
    return (ok / total) if total else None


def render_report(
    result: EvalResult,
    high_risk_field_ids: set[str] | None = None,
    max_errors: int = 200,
) -> str:
    lines: list[str] = ["# 金标评估报告", ""]
    m = result.micro
    lines += [
        "## 总览",
        "",
        f"- micro Precision / Recall / F1：**{m.precision:.4f} / {m.recall:.4f} / {m.f1:.4f}**",
        f"- macro F1（按字段平均）：**{result.macro_f1:.4f}**",
        f"- 幻觉率（pred=present 但金标非 present）：**{result.hallucination_rate:.4f}**",
        "- evidence 准确率："
        + (f"**{result.evidence_accuracy:.4f}**" if result.evidence_accuracy is not None
           else "未启用（缺 --dataset-root 或 pred 无证据）"),
        f"- 金标中排除的 disputed 记录：{result.golden_disputed_excluded}",
        f"- 金标有而预测缺失的键：{result.golden_only_keys}；预测多出的键：{result.pred_only_keys}",
        "",
        "## 三态混淆矩阵（行=金标，列=预测）",
        "",
        "| 金标 \\ 预测 | present | absent_explicitly | unknown |",
        "|---|---|---|---|",
    ]
    for g in _TRI:
        row = " | ".join(str(result.confusion.get((g, p), 0)) for p in _TRI)
        lines.append(f"| {g} | {row} |")

    if high_risk_field_ids:
        lines += ["", "## 高风险字段小结（risk_level=high）", "",
                  "| field_id | P | R | F1 |", "|---|---|---|---|"]
        for fid in sorted(high_risk_field_ids & set(result.per_field)):
            s = result.per_field[fid]
            lines.append(f"| {fid} | {s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} |")

    lines += ["", "## 逐字段指标", "", "| field_id | TP | FP | FN | P | R | F1 |",
              "|---|---|---|---|---|---|---|"]
    for fid, s in sorted(result.per_field.items()):
        lines.append(
            f"| {fid} | {s.tp} | {s.fp} | {s.fn} "
            f"| {s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} |"
        )

    lines += ["", f"## 错误明细（前 {max_errors} 条）", "",
              "| 产品 | 字段 | 类型 | 金标值 | 预测值 |", "|---|---|---|---|---|"]
    for e in result.errors[:max_errors]:
        gv = (e.golden_value or "-")[:60]
        pv = (e.pred_value or "-")[:60]
        lines.append(f"| {e.product_id} | {e.field_name}({e.field_id}) | {e.kind} | {gv} | {pv} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="金标评估 runner（spec G4）")
    parser.add_argument("--golden", required=True, type=Path, help="金标 release 目录")
    parser.add_argument("--pred", required=True, type=Path, help="抽取结果 JSONL")
    parser.add_argument("--report", required=True, type=Path, help="输出 markdown 报告路径")
    parser.add_argument(
        "--schema-dir", type=Path, default=None, help="schema 基线目录（高风险小结）"
    )
    parser.add_argument(
        "--dataset-root", type=Path, default=None, help="原始 PDF 根目录（证据校验）"
    )
    args = parser.parse_args(argv)

    golden = load_release(args.golden)
    pred = read_jsonl(args.pred)
    result = evaluate(golden, pred, dataset_root=args.dataset_root)

    high_risk: set[str] | None = None
    if args.schema_dir is not None:
        from ..schemas import load_schema_registry

        registry = load_schema_registry(args.schema_dir)
        high_risk = {
            f.field_id
            for line in registry.lines.values()
            for f in line.fields
            if f.risk_level == "high"
        }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(result, high_risk), encoding="utf-8")
    print(
        f"micro F1={result.micro.f1:.4f} macro F1={result.macro_f1:.4f} "
        f"幻觉率={result.hallucination_rate:.4f} → {args.report}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

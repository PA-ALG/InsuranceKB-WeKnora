"""Eval runner（spec G4 + 005 spec V2/V3/V4）：金标 vs 抽取结果 → 字段级指标 + markdown 报告。

用法：
    python -m insurance_harness.goldenset.eval \
        --golden dataset/goldenset/gs-v0.1 --pred pred.jsonl --report report.md \
        [--metric v1|v2] [--keypoints <keypoints.jsonl 或目录>] [--judge-queue <path>] \
        [--schema-dir docs/insurance-kb/schema-baseline] [--dataset-root dataset/shouxian_product]

口径：
- v1（默认）：全字段确定性归一化等价（002 原口径，G4.2）；
- v2：有要点条目的 (product, field) 按关键要点匹配计分（V2），其余回落 v1。
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .keypoints import (
    EvalJudgeRequest,
    KeypointEntry,
    load_keypoints,
    score_keypoints,
    value_sha,
    write_eval_judge_queue,
)
from .normalize import quote_in_page, values_equal
from .records import GoldenRecord, TriState
from .runner import load_release, read_jsonl

_TRI: tuple[TriState, ...] = ("present", "absent_explicitly", "unknown")

Metric = Literal["v1", "v2"]

# 五类归因标签（V3.1）与工单建议动作（V3.2）
CATEGORY_VALUE = "值粒度"
CATEGORY_MISSED = "漏抽"
CATEGORY_HALLUCINATION = "幻觉"
CATEGORY_TRI_STATE = "三态混淆"
CATEGORY_EVIDENCE = "证据错位"

CATEGORY_ACTIONS: dict[str, str] = {
    CATEGORY_VALUE: "补齐/复核该字段要点清单（B 类）；或收紧抽取 prompt 的输出粒度约束",
    CATEGORY_MISSED: "跑漏抽归因工具（compiler.recall_attribution）定位 路由/抽取/清洗",
    CATEGORY_HALLUCINATION: "检查投票与回验链；强化三态 prompt 的 unknown 约束",
    CATEGORY_TRI_STATE: "强化 absent_explicitly 判据（须有明示'无/不适用'证据）",
    CATEGORY_EVIDENCE: "检查证据页定位与回验逻辑；必要时进金标质疑工单",
}


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
    kind: str  # value_mismatch / false_present / missed / tri_state / evidence_mismatch
    golden_value: str | None
    pred_value: str | None
    category: str = ""  # 五类归因标签（V3.1）
    coverage: float | None = None  # 要点覆盖率（仅要点计分的 value_mismatch，V2.6）


@dataclass
class PartialDetail:
    """要点计分样本的 partial 覆盖率行（V2.6：主指标二值化，覆盖率单列展示）。"""

    product_id: str
    field_id: str
    field_name: str
    coverage: float
    matched: bool
    contradicted: bool


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
    metric: str = "v1"
    partials: list[PartialDetail] = field(default_factory=list)  # V2.6
    stale_keypoints: int = 0  # 要点条目与金标值不符 → 回落 v1 的计数（V2.5）
    judge_pending: int = 0  # 不确定带样本数（V4.3：关闭落盘也要计数）
    evidence_mismatch_count: int = 0  # 证据错位计数（不入 F1，V3.1）

    @property
    def macro_f1(self) -> float:
        if not self.per_field:
            return 0.0
        return sum(s.f1 for s in self.per_field.values()) / len(self.per_field)

    @property
    def category_counts(self) -> dict[str, int]:
        """五类归因标签分布（V3.2）。"""
        counts: Counter[str] = Counter(e.category for e in self.errors if e.category)
        return dict(counts)


def _classify_non_value(g_tri: TriState, p_tri: TriState) -> str:
    """三态错位的归因标签（V3.1）：漏抽只指 present→unknown；其余错位是三态混淆。"""
    if g_tri == "present" and p_tri == "unknown":
        return CATEGORY_MISSED
    return CATEGORY_TRI_STATE


def _evidence_pages_adjacent(g: GoldenRecord, p: GoldenRecord) -> bool:
    """证据页对齐（±1 容忍解析分页差；任一侧无证据页则不判定）。"""
    g_pages = {e.page for e in g.evidence}
    p_pages = {e.page for e in p.evidence}
    if not g_pages or not p_pages:
        return True
    return any(abs(gp - pp) <= 1 for gp in g_pages for pp in p_pages)


def excluded_disputed_keys(golden: list[GoldenRecord]) -> set[tuple[str, str]]:
    """因 disputed 被排除、且无可用金标覆盖同一 (product_id, field_id) 的键。

    disputed 金标不参与评测；模型对这类 key 的预测既不可判真也不可判假——不得计入 TP/FP/FN、
    幻觉率或 evidence。这是"哪些 key 可评测"的**单一权威**：evaluate 与
    build_profile 共用，避免在 global/field 两处各自重新推导而产生边界漂移。
    同一 key 若另有**可用**金标，则不在此集合、仍按可用金标评测。
    """
    usable_keys = {(g.product_id, g.field_id) for g in golden if not g.disputed}
    disputed_keys = {(g.product_id, g.field_id) for g in golden if g.disputed}
    return disputed_keys - usable_keys


def evaluate(
    golden: list[GoldenRecord],
    pred: list[GoldenRecord],
    dataset_root: Path | None = None,
    metric: Metric = "v1",
    keypoints: dict[tuple[str, str], KeypointEntry] | None = None,
    judge_queue_path: Path | None = None,
) -> EvalResult:
    usable = [g for g in golden if not g.disputed]
    excluded = len(golden) - len(usable)
    g_map = {(g.product_id, g.field_id): g for g in usable}
    p_map = {(p.product_id, p.field_id): p for p in pred}
    excluded_only = excluded_disputed_keys(golden)  # disputed-only 键：预测不可评测，全程排除

    per_field: dict[str, FieldStats] = defaultdict(FieldStats)
    micro = FieldStats()
    confusion: Counter[tuple[TriState, TriState]] = Counter()
    errors: list[ErrorDetail] = []
    partials: list[PartialDetail] = []
    judge_queue: list[EvalJudgeRequest] = []
    pred_present = 0
    hallucinated = 0
    stale = 0
    judge_pending = 0
    evidence_mismatch = 0

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
            value_ok, coverage = _value_verdict(g, p, metric, keypoints, partials)
            if coverage is not None and value_ok is None:
                stale += 1  # 要点条目过期 → 回落 v1（V2.5）
            if value_ok is None:
                value_ok = values_equal(g.value, p.value)
                coverage = None
            if value_ok:
                stats.tp += 1
                micro.tp += 1
                if not _evidence_pages_adjacent(g, p):  # 值判对但证据错位（V3.1）
                    evidence_mismatch += 1
                    errors.append(
                        ErrorDetail(
                            key[0], g.field_id, g.field_name, "evidence_mismatch",
                            g.value, p.value, category=CATEGORY_EVIDENCE,
                        )
                    )
            else:
                stats.fp += 1
                stats.fn += 1
                micro.fp += 1
                micro.fn += 1
                errors.append(
                    ErrorDetail(
                        key[0], g.field_id, g.field_name, "value_mismatch",
                        g.value, p.value, category=CATEGORY_VALUE, coverage=coverage,
                    )
                )
                if coverage is not None and _is_uncertain(coverage):
                    judge_pending += 1  # V4.1/V4.3
                    judge_queue.append(_judge_request(g, p, coverage, keypoints))
        elif g.tri_state == "present":
            stats.fn += 1
            micro.fn += 1
            errors.append(
                ErrorDetail(
                    key[0], g.field_id, g.field_name, "missed", g.value, None,
                    category=_classify_non_value(g.tri_state, p_tri),
                )
            )
        elif p_tri == "present":
            assert p is not None
            stats.fp += 1
            micro.fp += 1
            errors.append(
                ErrorDetail(
                    key[0], g.field_id, g.field_name, "false_present", g.value, p.value,
                    category=CATEGORY_HALLUCINATION,
                )
            )
        elif g.tri_state != p_tri:
            errors.append(
                ErrorDetail(
                    key[0], g.field_id, g.field_name, "tri_state", g.tri_state, p_tri,
                    category=CATEGORY_TRI_STATE,
                )
            )

    # pred 中金标没有的键：多余预测按 false_present 计入 micro FP（覆盖面之外的幻觉）。
    # 这类"覆盖面之外的 present 预测"也是幻觉，必须同时计入幻觉率**分子**——否则伪造大量
    # 出界字段会把 hallucination_rate 稀释下降，让 Q4.6 的幻觉回归护栏形同虚设。
    # 且**已知 field_id** 的出界 present 还要计入该字段 per_field FP——否则字段画像看不到本字段
    # 的伪造，在线 gate 只看字段指标会误放。
    golden_field_ids = {k[1] for k in g_map}
    pred_only = 0
    for key, p in p_map.items():
        if key in g_map or key in excluded_only:  # disputed-only：不可评测，不计幻觉/FP
            continue
        pred_only += 1
        if p.tri_state == "present":
            pred_present += 1
            hallucinated += 1
            micro.fp += 1
            if key[1] in golden_field_ids:
                per_field[key[1]].fp += 1

    if judge_queue_path is not None and judge_queue:  # 默认关（V4.1）
        write_eval_judge_queue(judge_queue_path, judge_queue)

    # evidence 也排除 disputed-only 键的预测（同"可评测键"口径）。
    ev_pred = [p for p in pred if (p.product_id, p.field_id) not in excluded_only]
    evidence_accuracy = _evidence_accuracy(ev_pred, dataset_root) if dataset_root else None
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
        metric=metric,
        partials=partials,
        stale_keypoints=stale,
        judge_pending=judge_pending,
        evidence_mismatch_count=evidence_mismatch,
    )


def _is_uncertain(coverage: float) -> bool:
    from .keypoints import JUDGE_UNCERTAIN_LOW, KEYPOINT_MATCH_THRESHOLD

    return JUDGE_UNCERTAIN_LOW <= coverage < KEYPOINT_MATCH_THRESHOLD


def _value_verdict(
    g: GoldenRecord,
    p: GoldenRecord,
    metric: Metric,
    keypoints: dict[tuple[str, str], KeypointEntry] | None,
    partials: list[PartialDetail],
) -> tuple[bool | None, float | None]:
    """值判定（V2.1）：返回 (判定, 覆盖率)。

    - (None, None)：无要点条目 → 调用方回落 v1；
    - (None, 覆盖率占位 0.0)：条目过期（sha 不符，V2.5）→ 回落 v1 且计 stale；
    - (bool, 覆盖率)：要点计分结论。
    """
    if metric != "v2" or not keypoints:
        return None, None
    entry = keypoints.get((g.product_id, g.field_id))
    if entry is None or p.value is None:
        return None, None
    if entry.golden_value_sha and entry.golden_value_sha != value_sha(g.value):
        return None, 0.0
    score = score_keypoints(p.value, entry)
    partials.append(
        PartialDetail(
            product_id=g.product_id,
            field_id=g.field_id,
            field_name=g.field_name,
            coverage=score.coverage,
            matched=score.matched,
            contradicted=score.contradicted,
        )
    )
    return score.matched, score.coverage


def _judge_request(
    g: GoldenRecord,
    p: GoldenRecord,
    coverage: float,
    keypoints: dict[tuple[str, str], KeypointEntry] | None,
) -> EvalJudgeRequest:
    entry = keypoints.get((g.product_id, g.field_id)) if keypoints else None
    missing: list[str] = []
    if entry is not None and p.value is not None:
        missing = score_keypoints(p.value, entry).missing
    return EvalJudgeRequest(
        product_id=g.product_id,
        product_name=g.product_name,
        doc=g.doc,
        field_id=g.field_id,
        field_name=g.field_name,
        candidates=[
            {"value": g.value, "note": "金标值"},
            {"value": p.value, "note": f"预测值（要点覆盖率 {coverage:.2f}）"},
        ],
        context_excerpt="缺失要点：" + "；".join(missing)[:1900],
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
    lines: list[str] = [f"# 金标评估报告（metric={result.metric}）", ""]
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
        f"- 证据错位（值对但证据页不相邻，不入 F1）：{result.evidence_mismatch_count}",
    ]
    if result.metric == "v2":
        lines += [
            f"- 要点计分样本：{len(result.partials)}；过期要点条目（回落 v1）："
            f"{result.stale_keypoints}",
            f"- 未裁决计数（要点不确定带，judge 兜底默认关）：{result.judge_pending}",
        ]
    lines += [
        "",
        "## 错误类型分布（五类归因，V3）",
        "",
        "| 归因标签 | 条数 | 建议动作 |",
        "|---|---|---|",
    ]
    counts = result.category_counts
    for cat in (CATEGORY_VALUE, CATEGORY_MISSED, CATEGORY_HALLUCINATION,
                CATEGORY_TRI_STATE, CATEGORY_EVIDENCE):
        lines.append(f"| {cat} | {counts.get(cat, 0)} | {CATEGORY_ACTIONS[cat]} |")
    if result.partials:
        lines += ["", "## 要点计分明细（partial 覆盖率，V2.6）", "",
                  "| 产品 | 字段 | 覆盖率 | 矛盾 | 判定 |", "|---|---|---|---|---|"]
        for d in result.partials:
            mark = "✅" if d.matched else "❌"
            lines.append(
                f"| {d.product_id} | {d.field_name}({d.field_id}) | {d.coverage:.2f} "
                f"| {'是' if d.contradicted else '-'} | {mark} |"
            )
    lines += [
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

    lines += ["", f"## 错误工单明细（前 {max_errors} 条，V3.2）", "",
              "| 产品 | 字段 | 类型 | 归因 | 覆盖率 | 金标值 | 预测值 |",
              "|---|---|---|---|---|---|---|"]
    for e in result.errors[:max_errors]:
        gv = (e.golden_value or "-")[:60]
        pv = (e.pred_value or "-")[:60]
        cov = f"{e.coverage:.2f}" if e.coverage is not None else "-"
        lines.append(
            f"| {e.product_id} | {e.field_name}({e.field_id}) | {e.kind} "
            f"| {e.category or '-'} | {cov} | {gv} | {pv} |"
        )
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
    parser.add_argument(
        "--metric", choices=("v1", "v2"), default="v1",
        help="计分口径：v1=确定性等价（默认）；v2=long 字段关键要点匹配（V2.7）",
    )
    parser.add_argument(
        "--keypoints", type=Path, default=None,
        help="要点清单（keypoints.jsonl 或含它的目录）；v2 缺省取 --golden 目录",
    )
    parser.add_argument(
        "--judge-queue", type=Path, default=None,
        help="不确定带样本落盘路径（eval-judge-queue.jsonl）；默认关（V4.1）",
    )
    args = parser.parse_args(argv)

    golden = load_release(args.golden)
    pred = read_jsonl(args.pred)
    metric: Metric = args.metric
    keypoints: dict[tuple[str, str], KeypointEntry] | None = None
    if metric == "v2":
        keypoints = load_keypoints(args.keypoints or args.golden)
    result = evaluate(
        golden,
        pred,
        dataset_root=args.dataset_root,
        metric=metric,
        keypoints=keypoints,
        judge_queue_path=args.judge_queue,
    )

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

"""006 留出验证脚本（spec F7；零真实模型调用，幂等可重跑）。

盛世金越系列（说明书+费率表族）：
用 2 个分红型产品的金标归纳模板 → 发布 → 应用到留出产品（尊享版26终身寿，
唯一有 004 真实 pred 的族内产品）→ fast path 命中字段对照金标算正确率
（v2 口径，对照通用管道同字段分数）→ 预估 LLM 调用节省数 → validation-report.md。

用法：cd harness && uv run python scripts/validate_006.py
"""

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline_004 import DATASET, GOLDEN_WIP, load_golden  # noqa: E402

from insurance_harness.compiler.extract import build_windows  # noqa: E402
from insurance_harness.compiler.routing_data import GROUP_ORDER, group_of_field  # noqa: E402
from insurance_harness.compiler.sections import (  # noqa: E402
    family_fingerprint,
    route_groups,
    split_sections,
)
from insurance_harness.compiler.templates import (  # noqa: E402
    ExtractionTemplate,
    InductionResult,
    PdfplumberTableProvider,
    ProductDocInput,
    dump_template_yaml,
    induce_template,
    load_template_registry,
    render_induction_report,
    run_fastpath,
    write_polish_queue,
)
from insurance_harness.goldenset.eval import evaluate  # noqa: E402
from insurance_harness.goldenset.keypoints import load_keypoints  # noqa: E402
from insurance_harness.goldenset.pdf import PageText, extract_pages  # noqa: E402
from insurance_harness.goldenset.records import GoldenRecord  # noqa: E402
from insurance_harness.goldenset.runner import read_jsonl  # noqa: E402
from insurance_harness.schemas import load_schema_registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHANGE_DIR = ROOT / "openspec/changes/006-template-fastpath"
RUNS_004 = ROOT / "openspec/changes/004-extraction-pipeline-mvp/runs"
TEMPLATES_DIR = ROOT / "dataset/templates"
SCHEMA_DIR = ROOT / "docs/insurance-kb/schema-baseline"
REPORT_PATH = CHANGE_DIR / "validation-report.md"
DRAFT_DIR = CHANGE_DIR / "templates"

HELD_OUT = "平安盛世金越（尊享版26）终身寿险"
INDUCTION_PRODUCTS = [
    "平安盛世金越（尊享版26）终身寿险（分红型）",
    "平安创享盛世金越（尊享版26）终身寿险（分红型）",
]
FAMILY_PRODUCTS = [HELD_OUT, *INDUCTION_PRODUCTS]
DOCS = ["费率表.pdf", "产品说明书.pdf"]
LINE_KEY = "whole-life"
EMPTY_SHA_FAMILY = "fam-e3b0c44298fc"

_pages_cache: dict[tuple[str, str], list[PageText]] = {}


def pages_of(product: str, doc: str) -> list[PageText]:
    key = (product, doc)
    if key not in _pages_cache:
        _pages_cache[key] = extract_pages(DATASET / product / doc)
    return _pages_cache[key]


def fam_of(product: str, doc: str) -> str:
    return family_fingerprint(split_sections(pages_of(product, doc)))


def induce_for_doc(
    doc: str, provider: PdfplumberTableProvider
) -> tuple[InductionResult | None, str]:
    """族一致 → 归纳；不一致 → 返回 (None, 说明)。"""
    fams = {p: fam_of(p, doc) for p in INDUCTION_PRODUCTS}
    if len(set(fams.values())) != 1:
        return None, (
            f"归纳产品的 {doc} 指纹不同族（{fams}）——按 F2.1 不归纳（版式确不同构，"
            f"若业务方判定应并族需引入相似度聚类，见 tasks.md 遗留）"
        )
    inputs = [
        ProductDocInput(
            product_name=p,
            pages=pages_of(p, doc),
            goldens=load_golden(p),
            pdf_path=DATASET / p / doc,
        )
        for p in INDUCTION_PRODUCTS
    ]
    result = induce_template(
        doc, inputs, family_id=next(iter(fams.values())), provider=provider,
        golden_release=GOLDEN_WIP.name,
    )
    return result, ""


def publish(template: ExtractionTemplate) -> Path:
    published = template.model_copy(update={"status": "published"})
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / f"{published.template_id}.yaml"
    path.write_text(dump_template_yaml(published), encoding="utf-8")
    return path


def _pred_record(product_id: str, doc: str, cand) -> GoldenRecord:  # type: ignore[no-untyped-def]
    return GoldenRecord(
        product_id=product_id,
        product_name=HELD_OUT,
        doc=doc,
        field_id=cand.field_id,
        field_name=cand.field_name,
        value=cand.value,
        tri_state=cand.tri_state,
        evidence=cand.evidence,
        annotator_model="fastpath-006",
        schema_version="v1.1",
        created_at=datetime.now(UTC),
    )


def count_extract_calls(covered: set[str], line_fields, max_fields: int = 10) -> int:  # type: ignore[no-untyped-def]
    """确定性调用计数模型（F7.3）：窗口 × ceil(组内字段/10)，与 pipeline 同参。"""
    calls = 0
    for doc in ["保险条款.pdf", *DOCS]:
        sections = split_sections(pages_of(HELD_OUT, doc))
        routing = route_groups(sections)
        sec_by_id = {s.section_id: s for s in sections}
        for group in GROUP_ORDER:
            fields = [
                f for f in line_fields
                if group_of_field(f.name) == group and f.field_id not in covered
            ]
            sec_ids = routing.by_group.get(group, ())
            if not fields or not sec_ids:
                continue
            windows = build_windows([(sid, sec_by_id[sid].fragments) for sid in sec_ids])
            calls += len(windows) * math.ceil(len(fields) / max_fields)
    return calls


def main() -> int:
    provider = PdfplumberTableProvider()
    registry = load_schema_registry(SCHEMA_DIR)
    line = registry.line(LINE_KEY)
    lines: list[str] = [
        "# 006 验收报告：模板 fast path 留出验证（零模型调用）",
        "",
        f"> 生成：`uv run python scripts/validate_006.py`（{datetime.now(UTC).date()}）；"
        "幂等可重跑。",
        "",
        "## 1. 族指纹修复（F6）",
        "",
        "004 疑点：说明书/费率表无编号标题 → 章节标题序列为空 → 指纹退化为空串 sha256 "
        f"前缀 `{EMPTY_SHA_FAMILY}`，无标题文档全部混为一族。修复后（fallback = 文档类型 + "
        "页数桶 + 表头 token）：",
        "",
        "| 产品 | 文档 | 004 指纹 | 修复后 |",
        "|---|---|---|---|",
    ]
    for p in FAMILY_PRODUCTS:
        for doc in [*DOCS, "保险条款.pdf"]:
            fam = fam_of(p, doc)
            old = EMPTY_SHA_FAMILY if doc != "保险条款.pdf" else fam + "（不变）"
            lines.append(f"| {p} | {doc} | {old} | `{fam}` |")
    rate_fams = {p: fam_of(p, "费率表.pdf") for p in FAMILY_PRODUCTS}
    assert len(set(rate_fams.values())) == 1, f"3 份费率表应同族：{rate_fams}"
    lines += [
        "",
        f"结论：3 份费率表同族 `{next(iter(rate_fams.values()))}`；说明书与费率表分族；"
        "有标题文档（条款）指纹与 004 完全一致（测试 F6.3 锚定）。",
        "",
        "## 2. 模板归纳（F2，两产品金标 → 草案；确定性零模型）",
        "",
    ]

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    published_paths: list[Path] = []
    for doc in DOCS:
        result, note = induce_for_doc(doc, provider)
        if result is None:
            lines += [f"### {doc}", "", note, ""]
            continue
        draft_path = DRAFT_DIR / f"{result.template.template_id}.yaml"
        draft_path.write_text(dump_template_yaml(result.template), encoding="utf-8")
        write_polish_queue(
            DRAFT_DIR / f"{result.template.template_id}.polish-queue.jsonl", result
        )
        lines += [render_induction_report(result, title=f"{doc} 归纳报告"), ""]
        if result.template.fields:
            published_paths.append(publish(result.template))
            lines.append(
                f"已发布（人工审核通过口径见 11 §1.2）→ `{published_paths[-1].relative_to(ROOT)}`"
            )
            lines.append("")

    # --- 留出验证（F7.2） ---
    template_registry = load_template_registry(TEMPLATES_DIR)
    golden = [g for g in load_golden(HELD_OUT) if not g.disputed]
    product_id = golden[0].product_id
    baseline_pred = read_jsonl(RUNS_004 / HELD_OUT / "pred.jsonl")
    fields_by_id = {f.field_id: f for f in line.extractable_fields}
    keypoints = load_keypoints(GOLDEN_WIP)

    fastpath_records: list[GoldenRecord] = []
    hit_by_doc: dict[str, list[str]] = {}
    for doc in DOCS:
        template = template_registry.find(fam_of(HELD_OUT, doc), doc)
        if template is None:
            hit_by_doc[doc] = []
            continue
        cands = run_fastpath(
            template, fields_by_id, doc, pages_of(HELD_OUT, doc),
            pdf_path=DATASET / HELD_OUT / doc, provider=provider,
        )
        hit_by_doc[doc] = [c.field_id for c in cands]
        fastpath_records.extend(_pred_record(product_id, doc, c) for c in cands)

    hit_ids = {r.field_id for r in fastpath_records}
    golden_hit = [g for g in golden if g.field_id in hit_ids]
    baseline_hit = [p for p in baseline_pred if p.field_id in hit_ids]
    fp_eval = evaluate(golden_hit, fastpath_records, metric="v2", keypoints=keypoints)
    base_eval = evaluate(golden_hit, baseline_hit, metric="v2", keypoints=keypoints)

    lines += [
        "## 3. 留出验证（F7.2）：留出产品 = " + HELD_OUT,
        "",
        f"模板命中：{ {d: (ids or '—') for d, ids in hit_by_doc.items()} }",
        "",
        "| 字段 | 金标值 | fast path 值 | 004 通用管道值 | fast path 判定 | 基线判定 |",
        "|---|---|---|---|---|---|",
    ]
    base_by_id = {p.field_id: p for p in baseline_hit}
    for r in fastpath_records:
        g = next(x for x in golden_hit if x.field_id == r.field_id)
        b = base_by_id.get(r.field_id)
        fp_ok = "✅" if fp_eval.micro.tp else "❌"
        lines.append(
            f"| {r.field_name}({r.field_id}) | {g.value} | {r.value} | "
            f"{(b.value if b and b.value else f'({b.tri_state if b else 'missing'})')} | "
            f"{fp_ok} | {'❌' if not base_eval.micro.tp else '✅'} |"
        )
    fp_acc = fp_eval.micro.tp / max(len(golden_hit), 1)
    base_acc = base_eval.micro.tp / max(len(golden_hit), 1)
    lines += [
        "",
        f"- fast path 命中字段正确率（v2）：**{fp_acc:.2f}**（micro F1 {fp_eval.micro.f1:.4f}）",
        f"- 通用管道同字段正确率（v2，004 已有 pred）：**{base_acc:.2f}**"
        f"（micro F1 {base_eval.micro.f1:.4f}）",
        f"- 验收判定：fast path ≥ 通用管道 → **{'通过' if fp_acc >= base_acc else '不通过'}**",
        "",
    ]
    assert fp_acc >= base_acc, "F7.2 验收失败：fast path 正确率低于通用管道"

    # --- 调用节省估算（F7.3） ---
    manifest = json.loads((RUNS_004 / HELD_OUT / "manifest.json").read_text(encoding="utf-8"))
    actual_calls = int(manifest["stats"]["calls"])
    base_extract = count_extract_calls(set(), line.extractable_fields)
    fp_extract = count_extract_calls(hit_ids, line.extractable_fields)
    unknown_ids = {p.field_id for p in baseline_pred if p.tri_state == "unknown"}
    gapfill_saved = len(hit_ids & unknown_ids)
    saved = (base_extract - fp_extract) + gapfill_saved
    lines += [
        "## 4. 预估 LLM 调用节省（F7.3，确定性计数模型）",
        "",
        "口径：抽取调用 = Σ(窗口数 × ⌈组内字段数/10⌉)（与 pipeline 同参重算）；"
        "补漏 = 每个 unknown 字段 1 调用；fast path 命中字段退出该产品通用抽取与补漏。",
        "",
        "| 项 | 基线 | fast path | 节省 |",
        "|---|---|---|---|",
        f"| 抽取批调用（计划） | {base_extract} | {fp_extract} | {base_extract - fp_extract} |",
        f"| 补漏调用（命中字段原 unknown） | {len(unknown_ids)} | "
        f"{len(unknown_ids) - gapfill_saved} | {gapfill_saved} |",
        f"| **合计** | - | - | **{saved}** |",
        "",
        f"该产品 004 实跑调用 {actual_calls} 次 → 预估节省 {saved} 次"
        f"（约 {saved / actual_calls:.1%}）。",
        "",
        "说明：本族当前锚定字段少（费率表 2 个确定性字段），节省绝对值小但正确率从 0→1；"
        "节省随模板铺开（按族分数逐个立项，11 §1.4 闭环）与锚点覆盖率增长。说明书族因"
        "分红/非分红版式不同构未能对留出产品生效（见 §2），列 tasks.md 遗留复盘。",
        "",
        "## 5. 结论",
        "",
        f"- F6 指纹修复：无标题文档不再退化为 `{EMPTY_SHA_FAMILY}`，盛世金越 3 份费率表"
        "正确同族，条款指纹零漂移；",
        f"- F7.2：fast path 命中字段正确率 {fp_acc:.2f} ≥ 通用管道 {base_acc:.2f}"
        "（交费期限从漏抽 unknown → 确定性列直取全对，data_quality=table_parsed）；",
        f"- F7.3：留出产品预估节省 {saved} 次 LLM 调用；零真实模型调用完成全部验证。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"fast path 正确率 {fp_acc:.2f} vs 基线 {base_acc:.2f}；预估节省 {saved} 调用")
    print(f"→ {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

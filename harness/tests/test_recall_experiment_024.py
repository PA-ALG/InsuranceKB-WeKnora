"""024 E7/E3 验收（codex PR#13 返工）：审计产物过交付边界 + 触发合同 + 定向检索。

测试名引用条款号。零真实模型调用。证明力=编排/审计/触发合同（E1 边界），
真实召回结论仍由 020 D4 数据说话。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from insurance_harness.compiler.experiment import (
    AssignmentPolicy,
    assign_arm,
    experiment_digest,
)
from insurance_harness.compiler.gapfill import (
    gapfill_eligibility,
    gapfill_field,
    parse_pointer_terms,
    rank_sections,
)
from insurance_harness.compiler.models import FieldCandidate, PredRecord
from insurance_harness.compiler.sections import DocSection
from insurance_harness.compiler.variants import VariantRegistry
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec
from tests.test_compiler_pipeline import ScriptedClient, _run_ok

_DOC = "doc.pdf"


class _SpyClient:
    """计数客户端：E3 负例断言零调用、正例恰 N 调用。"""

    def __init__(self, resp: str) -> None:
        self._resp = resp
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self._resp


# ---------------------------------------------------------------------------
# E7 · 审计穿过交付边界：pred.jsonl 落盘并反序列化后仍可对账
# ---------------------------------------------------------------------------


async def test_e7_pred_jsonl_roundtrip_carries_extraction_audit(
    tmp_path: Path,
) -> None:
    """完整管道 → pred.jsonl → read back：每条 pred 带类型化审计（阻断 1 反例）。"""
    result = await _run_ok(tmp_path, ScriptedClient())
    lines = [
        ln for ln in result.pred_path.read_text(encoding="utf-8").splitlines() if ln
    ]
    assert lines, "pred.jsonl 非空"
    for ln in lines:
        record = PredRecord.model_validate_json(ln)
        audit = record.extraction_audit
        assert audit is not None, "落盘 pred 必须携带 extraction_audit（E7）"
        assert audit.prompt_variant_used, "实际所用模板标识必须非空"
        raw = json.loads(ln)
        assert raw["extraction_audit"]["prompt_variant_used"] == (
            audit.prompt_variant_used
        )
        # 首轮抽取路径如实归因 baseline（vote/judge 可能聚合 gapfill 尝试，
        # 其 stamp 记录的是真实调用过的模板——同样是"实际使用"）
        if audit.winning_origin == "extract":
            assert audit.prompt_variant_used.startswith("baseline@"), (
                f"extract 路径必须归因 baseline，实得 {audit.prompt_variant_used}"
            )
        assert "targeted" not in audit.prompt_variant_used or (
            audit.winning_origin in ("gapfill", "vote", "judge")
        ), "targeted 标识只能出自真实经过定向模板的调用路径"


def test_e7_legacy_pred_without_audit_still_parses() -> None:
    """历史 pred.jsonl（无 extraction_audit 字段）向后兼容 → None。"""
    legacy: dict[str, object] = {
        "product_id": "P", "product_name": "п", "doc": "d", "field_id": "f",
        "field_name": "字段", "value": None, "tri_state": "unknown",
        "evidence": [], "annotator_model": "m", "schema_version": "v",
        "created_at": "2026-07-01T00:00:00+00:00",
    }
    record = PredRecord.model_validate(legacy)
    assert record.extraction_audit is None


# ---------------------------------------------------------------------------
# E7 · 分桶：同一 eligible population 的确定性 control/treatment
# ---------------------------------------------------------------------------


def test_e7_assignment_deterministic_and_partitions_population() -> None:
    policy = AssignmentPolicy(enabled=True, experiment_id="exp-020-d4", seed=42)
    arms = {
        f"zh_f{i:03d}": assign_arm(policy, "P001", f"zh_f{i:03d}") for i in range(64)
    }
    again = {
        f"zh_f{i:03d}": assign_arm(policy, "P001", f"zh_f{i:03d}") for i in range(64)
    }
    assert arms == again, "同 (policy, product, field) 分桶必须确定性"
    assert set(arms.values()) == {"control", "treatment"}, "两臂都必须可达"
    assert assign_arm(AssignmentPolicy(), "P001", "zh_f000") is None, "实验关闭→不分臂"
    other_seed = AssignmentPolicy(enabled=True, experiment_id="exp-020-d4", seed=43)
    assert any(
        assign_arm(other_seed, "P001", f) != arms[f] for f in arms
    ), "seed 变化必须改变分桶（否则不是按策略分桶）"


def test_e7_experiment_digest_tracks_registry_and_policy_content() -> None:
    """注册表/策略任何内容变化 → 摘要变化（run/checkpoint 身份成分，resume 据此拒绝）。"""
    base = experiment_digest(VariantRegistry.default(), AssignmentPolicy())
    assert base == experiment_digest(VariantRegistry.default(), AssignmentPolicy())
    policy_changed = experiment_digest(
        VariantRegistry.default(), AssignmentPolicy(enabled=True, experiment_id="x")
    )
    assert policy_changed != base
    seed_changed = experiment_digest(
        VariantRegistry.default(), AssignmentPolicy(enabled=True, seed=7)
    )
    assert seed_changed not in (base, policy_changed), "seed 亦是内容成分"


async def test_e7_manifest_records_variant_digest(tmp_path: Path) -> None:
    result = await _run_ok(tmp_path, ScriptedClient())
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["variant_digest"] == experiment_digest(
        VariantRegistry.default(), AssignmentPolicy()
    ), "manifest 携带注册表+策略内容摘要（E7；resume 身份成分）"


def test_e7_old_checkpoint_without_digest_fails_closed() -> None:
    """旧 checkpoint state 缺 variant_digest → 身份解析 fail-closed（不静默混用）。"""
    import pytest

    from insurance_harness.compiler.pipeline import _parse_state_run_identity
    from insurance_harness.db.scope import ScopeViolation

    values = {
        "run_id": "r", "run_dir": "d", "checkpoint_path": "c", "product_dir": "p",
        "product_id": "P", "product_name": "п", "line_key": "l", "model_id": "m",
        "schema_version": "s", "prompt_version": "v", "judge_mode": "j",
        # 故意缺 variant_digest（模拟本变更前的 checkpoint）
    }
    with pytest.raises(ScopeViolation):
        _parse_state_run_identity(values)


# ---------------------------------------------------------------------------
# E3 · 触发合同：必填/期望 + 首轮未决 + 预算允许；金标零参与（纯函数签名可证）
# ---------------------------------------------------------------------------


def _unknown_cand(field_id: str) -> FieldCandidate:
    return FieldCandidate(
        field_id=field_id, field_name="字段", group="g", doc=_DOC,
        tri_state="unknown", origin="extract",
    )


def test_e3_eligibility_negatives_and_positive() -> None:
    required = FieldSpec(name="等待期", field_id="zh_wp", requiredness="required")
    optional = FieldSpec(name="备注", field_id="zh_note", requiredness="optional")
    assert not gapfill_eligibility(
        optional, _unknown_cand("zh_note"), budget_remaining=5
    ).eligible, "optional 字段不触发（E3）"
    resolved = _unknown_cand("zh_wp").model_copy(
        update={"tri_state": "present", "value": "90天"}
    )
    assert not gapfill_eligibility(
        required, resolved, budget_remaining=5
    ).eligible, "首轮已决不触发"
    assert not gapfill_eligibility(
        required, _unknown_cand("zh_wp"), budget_remaining=0
    ).eligible, "预算耗尽不触发"
    decision = gapfill_eligibility(
        required, _unknown_cand("zh_wp"), budget_remaining=1
    )
    assert decision.eligible and decision.reason == "required_or_expected_unknown"
    assert gapfill_eligibility(
        required, None, budget_remaining=None
    ).eligible, "预算不限（None）时必填未决触发"


def test_e3_no_candidate_sections_means_zero_llm_calls() -> None:
    field = FieldSpec(name="等待期", field_id="zh_wp")
    spy = _SpyClient("[]")
    page = PageText(page_no=1, text="与该字段完全无关的正文。")
    section = DocSection(section_id="s1", title="无关", headings=(), fragments=(page,))
    cand = asyncio.run(
        gapfill_field(spy, "产品", field, [(_DOC, section)], {_DOC: [page]})
    )
    assert spy.calls == 0, "无候选章节必须零 LLM 调用（E3）"
    assert cand.unknown_reason == "no_candidate_sections"


def test_e3_required_with_candidate_and_budget_calls_once() -> None:
    field = FieldSpec(name="等待期", field_id="zh_wp", requiredness="required")
    spy = _SpyClient(
        '[{"field_id":"zh_wp","value":null,"tri_state":"unknown","evidence":[]}]'
    )
    page = PageText(page_no=1, text="等待期为90天。")
    section = DocSection(section_id="s1", title="责任", headings=(), fragments=(page,))
    asyncio.run(gapfill_field(spy, "产品", field, [(_DOC, section)], {_DOC: [page]}))
    assert spy.calls == 1, "正例：候选章节存在时恰好一次调用（top_n 内首段已答）"


# ---------------------------------------------------------------------------
# E6/E3 · source_pointer 定向检索：被指向正文不含字段名也能命中
# ---------------------------------------------------------------------------


def test_e6_pointer_terms_reach_section_without_field_alias() -> None:
    field = FieldSpec(name="现金价值", field_id="zh_cv")
    pointer_only = DocSection(
        section_id="s-annex",
        title="附表",
        headings=(),
        fragments=(PageText(page_no=9, text="附表二：各年度对应金额如下 1000 元。"),),
    )
    assert rank_sections(field, [(_DOC, pointer_only)]) == [], (
        "前提：仅凭字段关键词命中不了该章节（否则本用例不成立）"
    )
    hits = rank_sections(
        field, [(_DOC, pointer_only)], extra_terms=parse_pointer_terms("详见附表二")
    )
    assert hits, "指针词条必须让被指向章节可命中（E6 定向追抽落地）"

    spy = _SpyClient(
        '[{"field_id":"zh_cv","value":"1000 元","tri_state":"present",'
        '"evidence":[{"page":9,"quote":"附表二：各年度对应金额如下 1000 元。"}]}]'
    )
    cand = asyncio.run(
        gapfill_field(
            spy, "产品", field, [(_DOC, pointer_only)],
            {_DOC: [pointer_only.fragments[0]]},
            source_pointer="详见附表二",
        )
    )
    assert spy.calls == 1 and cand.tri_state == "present"
    assert cand.metadata.get("pointer_terms") == ["附表二"], "指针词条进审计"

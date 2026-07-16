"""024 E5.1 后处理非退化探针：未变更录制集上的回放评分下界。

设计（tasks.md 裁决记录同步）：仓库不含真实模型的已提交录制集（005 基线为实跑），
探针以**冻结响应常量**充当"未变更录制集"，并以三重钉桩保证 E5.1 语义：
1. control 变体钉桩——探针字段不在 targeted 注册表，断言 metadata=default@v1；
2. request_key 钉桩——default 路径 prompt 组装逐字节漂移即 key 断言失败（探针
   显式失效并 fail，不得静默换基线）；
3. manifest 哈希钉桩——录制响应/预期结果任何改动即 manifest 断言失败。
评分下界：每产品 matched/total == 1.0（确定性基线）。真实 3 产品录制集探针
随 020 D4 建立（见 validation-report 交接说明）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Final

import pytest

from insurance_harness.compiler.gapfill import gapfill_field, gapfill_keywords
from insurance_harness.compiler.llm import request_key
from insurance_harness.compiler.models import FieldCandidate
from insurance_harness.compiler.prompts import GAPFILL_SYSTEM, build_gapfill_user
from insurance_harness.compiler.sections import DocSection
from insurance_harness.compiler.variants import DEFAULT_VARIANT_VERSION, VARIANT_METADATA_KEY
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec

# ---------------------------------------------------------------------------
# 冻结录制集（E5.1"未变更录制响应集"）：field_id → 模型响应常量
# ---------------------------------------------------------------------------

_DOC: Final[str] = "探针条款.pdf"


def _resp(fid: str, value: str | None, tri: str, page: int = 1, quote: str = "") -> str:
    ev = [{"page": page, "quote": quote}] if quote else []
    return json.dumps(
        [{"field_id": fid, "value": value, "tri_state": tri, "evidence": ev}],
        ensure_ascii=False,
    )


class _ProbeCase:
    def __init__(
        self,
        product: str,
        fid: str,
        fname: str,
        page_text: str,
        response: str,
        expect_tri: str,
        expect_value: str | None,
        expect_reason: str | None,
    ) -> None:
        self.product = product
        self.field = FieldSpec(name=fname, field_id=fid, source_sheet="024-probe")
        self.page = PageText(page_no=1, text=page_text)
        self.section = DocSection(
            section_id=f"probe-{fid}",
            title=fname,
            headings=(fname,),
            fragments=(PageText(page_no=1, text=page_text),),
        )
        self.response = response
        self.expect_tri = expect_tri
        self.expect_value = expect_value
        self.expect_reason = expect_reason


_P1, _P2, _P3 = "探针产品甲", "探针产品乙", "探针产品丙"

#: 九条录制：verified-present / 占位 / 弱值 / 引用型 / 兼容性 / 回验失败 /
#: absent / 解析双产品对照——覆盖后处理全分支的基线行为。
PROBE_CASES: Final[tuple[_ProbeCase, ...]] = (
    _ProbeCase(
        _P1, "probe_wait", "等待期",
        "等待期：本合同等待期为90天。",
        _resp("probe_wait", "90天", "present", 1, "等待期为90天"),
        "present", "90天", None,
    ),
    _ProbeCase(
        _P1, "probe_hesit", "犹豫期",
        "犹豫期：请仔细阅读本合同犹豫期约定。",
        _resp("probe_hesit", "以合同为准", "present", 1, "犹豫期"),
        "unknown", None, "not_found",  # 弱值（E6）→ 无线索 → not_found
    ),
    _ProbeCase(
        _P1, "probe_fee", "费用说明",
        "费用说明：退保可能产生损失。",
        _resp("probe_fee", "退保时可能遭受一定损失", "present", 1, "退保可能产生损失"),
        "unknown", None, "incompatible_value",  # 兼容性拒入（E6/Q012）→ 可审计原因（F6）
    ),
    _ProbeCase(
        _P2, "probe_ref", "责任免除说明",
        "责任免除说明：内容见相关条款。",
        _resp("probe_ref", "见第5.3条", "present", 1, "责任免除说明"),
        "unknown", None, "not_found",  # 引用型（E6）→ 指针不冒充值 → not_found
    ),
    _ProbeCase(
        _P2, "probe_absent", "满期返还",
        "满期返还：本合同无满期返还责任。",
        _resp("probe_absent", None, "absent_explicitly", 1, "无满期返还责任"),
        "absent_explicitly", None, None,
    ),
    _ProbeCase(
        _P2, "probe_badquote", "宽限期",
        "宽限期：本合同宽限期为60日。",
        _resp("probe_badquote", "60日", "present", 1, "宽限期为六十日"),
        "unknown", None, "not_found",  # 回验失败（E3.2）→ 不出场
    ),
    _ProbeCase(
        _P3, "probe_placeholder", "保单贷款",
        "保单贷款：详见保单贷款相关约定。",
        _resp("probe_placeholder", "未明确", "present", 1, "保单贷款"),
        "unknown", None, "not_found",  # 既有占位清洗（E5.2 原语义）
    ),
    _ProbeCase(
        _P3, "probe_ok2", "保险期间",
        "保险期间：本合同保险期间为终身。",
        _resp("probe_ok2", "终身", "present", 1, "保险期间为终身"),
        "present", "终身", None,
    ),
    _ProbeCase(
        _P3, "probe_unknown", "红利分配",
        "红利分配：本节未涉及相关内容。",
        _resp("probe_unknown", None, "unknown"),
        "unknown", None, "not_found",
    ),
)

# ---------------------------------------------------------------------------
# 钉桩常量：manifest 哈希 + 每条录制的 request_key（首跑后固定；改动即显式失败）
# ---------------------------------------------------------------------------

PINNED_MANIFEST_SHA256: Final[str] = (
    # 有意重钉（F6）：probe_fee 兼容性拒绝原因 not_found→incompatible_value（可审计）
    "1f95a70ac17a158c871cd8f3120f871dabc982d37ea5f4f1608efc0d698a8284"
)

PINNED_REQUEST_KEYS: Final[dict[str, str]] = {
    "probe_wait": "7e6e3121fb617aaf",
    "probe_hesit": "7a3ba60d8629906f",
    "probe_fee": "e4dda4a4a877f3a6",
    "probe_ref": "94188bbb4f827c0a",
    "probe_absent": "d744a16c975b5621",
    "probe_badquote": "f1f776fcb2e04eb3",
    "probe_placeholder": "861f2db880e097fb",
    "probe_ok2": "18869ed1ee3701a2",
    "probe_unknown": "f1ff9d34f91c1397",
}


def _manifest_sha256() -> str:
    payload = {
        "doc": _DOC,
        "cases": [
            {
                "product": c.product,
                "field_id": c.field.field_id,
                "field_name": c.field.name,
                "page_text": c.page.text,
                "response": c.response,
                "expect": [c.expect_tri, c.expect_value, c.expect_reason],
            }
            for c in PROBE_CASES
        ],
        "pinned_keys": dict(sorted(PINNED_REQUEST_KEYS.items())),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _FrozenClient:
    """按字段返回冻结录制。F5：出站 prompt 的 request_key 必须等于钉桩 key，把
    冻结回放**绑定到真实调用路径**——控制变体 prompt 漂移（如默认变体获得定向
    模板）时探针显式 fail，而非静默复用录制（此前 complete 忽略 user，钉桩只校验
    测试内重建的 prompt，漂移可绕过）。"""

    def __init__(self, case: _ProbeCase) -> None:
        self._case = case

    async def complete(self, system: str, user: str) -> str:
        assert system == GAPFILL_SYSTEM
        actual = request_key(system, user)
        assert actual == PINNED_REQUEST_KEYS[self._case.field.field_id], (
            f"{self._case.field.field_id}: 出站 prompt key={actual} 与钉桩不符——"
            "control 路径漂移，冻结录制随之失效，探针按设计显式 fail（E5.1）"
        )
        return self._case.response


def _expected_user_prompt(case: _ProbeCase) -> str:
    return build_gapfill_user(
        case.product, _DOC, case.field,
        list(case.section.fragments), list(gapfill_keywords(case.field)),
    )


def test_e5_1_probe_manifest_hash_pinned() -> None:
    assert _manifest_sha256() == PINNED_MANIFEST_SHA256, (
        f"探针 manifest 变化（实际 {_manifest_sha256()}）——不得静默换基线：",
        "确认改动是有意的再更新钉桩",
    )


@pytest.mark.parametrize("case", PROBE_CASES, ids=lambda c: c.field.field_id)
def test_e5_1_prompt_request_key_pinned(case: _ProbeCase) -> None:
    actual = request_key(GAPFILL_SYSTEM, _expected_user_prompt(case))
    assert actual == PINNED_REQUEST_KEYS[case.field.field_id], (
        f"{case.field.field_id}: default 路径 prompt 组装漂移（实际 key={actual}）——"
        "录制集随之失效，探针按设计显式 fail"
    )


def test_e5_1_frozen_client_rejects_prompt_drift() -> None:
    """F5：出站 prompt 的 request_key 与钉桩不符时 _FrozenClient 显式失败——把
    冻结回放绑定到真实调用路径，控制变体漂移（如默认变体获得定向模板）不可静默
    复用录制（此前 complete 忽略 user，漂移可绕过所有钉桩）。"""
    client = _FrozenClient(PROBE_CASES[0])
    with pytest.raises(AssertionError):
        asyncio.run(client.complete(GAPFILL_SYSTEM, "drifted-control-prompt-not-pinned"))


def test_e5_1_control_prompt_drift_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 端到端回归：默认变体一旦带上定向模板（控制 prompt 漂移，未 bump 版本），
    gapfill 外发 prompt 变化，冻结回放的 request_key 绑定使非退化探针显式 fail——
    不得静默换基线（此前钉桩只校验测试内重建 prompt，此漂移可绕过全部钉桩）。"""
    from insurance_harness.compiler import variants as _variants
    from insurance_harness.compiler.variants import TARGETED_SHORT_ANSWER, PromptVariant

    drifted = PromptVariant(
        variant_id="default", version=DEFAULT_VARIANT_VERSION,
        targeted_template=TARGETED_SHORT_ANSWER, is_default=True,
    )
    monkeypatch.setattr(_variants, "DEFAULT_VARIANT", drifted)
    with pytest.raises(AssertionError):
        test_e5_1_postprocess_nonregression_score_floor()


def test_e5_1_postprocess_nonregression_score_floor() -> None:
    """评分下界：每产品 matched/total == 1.0；control 变体钉桩 default@v1。"""
    per_product: dict[str, list[bool]] = {}
    for case in PROBE_CASES:
        cand: FieldCandidate = asyncio.run(
            gapfill_field(
                _FrozenClient(case), case.product, case.field,
                [(_DOC, case.section)], {_DOC: [case.page]},
            )
        )
        assert cand.metadata.get(VARIANT_METADATA_KEY) == DEFAULT_VARIANT_VERSION, (
            f"{case.field.field_id}: 探针必须钉在 control/default 变体上（E5.1）"
        )
        matched = (
            cand.tri_state == case.expect_tri
            and cand.value == case.expect_value
            and (case.expect_reason is None or cand.unknown_reason == case.expect_reason)
        )
        per_product.setdefault(case.product, []).append(matched)
        assert matched, (
            f"{case.field.field_id}: 后处理退化——期望 "
            f"({case.expect_tri},{case.expect_value},{case.expect_reason})，"
            f"实际 ({cand.tri_state},{cand.value},{cand.unknown_reason})"
        )
    for product, results in per_product.items():
        score = sum(results) / len(results)
        assert score >= 1.0, f"{product}: 回放评分 {score:.2f} 低于基线 1.0（E5.1 下界）"

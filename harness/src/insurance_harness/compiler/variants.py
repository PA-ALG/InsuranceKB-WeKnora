"""E2 prompt 变体机制（024）：单一权威注册表 + 确定性选择 + 版本化审计标识。

设计（tasks.md 裁决记录同步）：
- 注册表为代码内纯数据常量（对齐 ``routing_data`` 风格）——E2.1"单一权威来源"；
- ``select_variant`` 确定性：精确 (group, field_id) → 组级条目 → **默认变体**；
  未注册字段组一律回落默认（E2.3），默认变体不改变任何 prompt 组装（零漂移）；
- 变体 ``version`` 是显式版本化标识（E2.2），进入 pred 元数据键
  ``prompt_variant``，020 D4 真实 A/B 以此对账；
- 变体不改变 pred 输出 schema（E2 条款）；定向模板（T3/E3）与值粒度指引
  （T4/E4）作为变体内容挂载于此机制。
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

#: 元数据键（E2.2）：凡经变体选择的调用路径都以此键记录版本化标识。
VARIANT_METADATA_KEY: Final[str] = "prompt_variant"

#: 默认变体版本（E2.3 回落）：不携带任何模板/指引，prompt 组装零漂移。
DEFAULT_VARIANT_VERSION: Final[str] = "default@v1"


class PromptVariant(BaseModel):
    """一个字段组级 prompt 变体（E2.1 注册表条目）。

    guidance（E4.1 值粒度指引）与 targeted_template（E3 定向模板标识）由
    T3/T4 填充；默认变体两者皆空——组装函数据此保持既有输出逐字不变。
    """

    model_config = ConfigDict(frozen=True)

    variant_id: str
    version: str
    guidance: str | None = None
    targeted_template: str | None = None
    is_default: bool = False


DEFAULT_VARIANT: Final[PromptVariant] = PromptVariant(
    variant_id="default",
    version=DEFAULT_VARIANT_VERSION,
    is_default=True,
)


class VariantRegistry(BaseModel):
    """变体注册表（E2.1 单一权威来源）。

    键为 ``(group, field_id)`` 精确条目与 ``(group, "")`` 组级条目两层；
    查询顺序：精确 → 组级 → 默认。注册数据见 ``DEFAULT_REGISTRY``。
    """

    model_config = ConfigDict(frozen=True)

    entries: tuple[tuple[str, str, PromptVariant], ...] = ()

    @classmethod
    def default(cls) -> VariantRegistry:
        return DEFAULT_REGISTRY

    def lookup(self, group: str, field_id: str) -> PromptVariant | None:
        exact = next(
            (v for g, f, v in self.entries if g == group and f == field_id), None
        )
        if exact is not None:
            return exact
        return next((v for g, f, v in self.entries if g == group and f == ""), None)


#: 定向短答模板标识（E3.1）：gapfill 据此改用 ``build_targeted_gapfill_user``。
TARGETED_SHORT_ANSWER: Final[str] = "short_answer@v1"

#: 值粒度对齐指引（E4.1）：只经变体注入 prompt，不改 pred schema、不动尺子。
GRANULARITY_GUIDANCE: Final[str] = (
    "按条款原文粒度抽取：保留原文限定条件、数值与枚举的完整表述，不概括、不合并多个条款"
)

#: 005 归因工单字段（024 E1 范围）：extract_empty 24 条去重 + 1 条 prompt 域
#: routing_miss（005 结论并入变体迭代）。字段级精确注册，避免组级注册波及
#: 既有字段的 prompt（零漂移边界）。第三列 = 值粒度指引（E4.1，长文本字段）。
_TARGETED_TICKET_FIELDS: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("basic_info", "zh_67ee7025ef", None),  # 主附加险
    ("basic_info", "zh_14b93ce275", None),  # 交费期限
    ("basic_info", "zh_58d313ee26", None),  # 保障人群
    ("basic_info", "zh_0c5a8e59e2", GRANULARITY_GUIDANCE),  # 产品搭配规则
    ("basic_info", "zh_c588207763", None),  # 投保职业
    ("basic_info", "waiting_period_claim_handling", GRANULARITY_GUIDANCE),  # 等待期内出险处理
    ("basic_info", "zh_ad4a95859a", None),  # 产品类别
    ("basic_info", "zh_0b3894ed2a", None),  # 产品类型（prompt 域 routing_miss）
    ("coverage", "zh_69f97f5c40", GRANULARITY_GUIDANCE),  # 意外身故
    ("coverage", "zh_17ba71cda4", GRANULARITY_GUIDANCE),  # 疾病身故
    ("coverage", "zh_a271d96039", GRANULARITY_GUIDANCE),  # 保单权益
    ("cost_rules", "zh_7be37f7605", GRANULARITY_GUIDANCE),  # 保证利率
    ("cost_rules", "illustrated_rate_basis", GRANULARITY_GUIDANCE),  # 演示利率口径
    ("exclusion_uw", "zh_f93c945d66", GRANULARITY_GUIDANCE),  # 免责少
    ("exclusion_uw", "zh_e1bea0527a", GRANULARITY_GUIDANCE),  # 特殊免责
    ("claim_service", "claim_filing_requirements", GRANULARITY_GUIDANCE),  # 理赔申请时效与材料
)

DEFAULT_REGISTRY: Final[VariantRegistry] = VariantRegistry(
    entries=tuple(
        (
            group,
            field_id,
            PromptVariant(
                variant_id=f"targeted-{group}",
                version="targeted@v1",
                guidance=guidance,
                targeted_template=TARGETED_SHORT_ANSWER,
            ),
        )
        for group, field_id, guidance in _TARGETED_TICKET_FIELDS
    )
)


def select_variant(
    registry: VariantRegistry, *, group: str, field_id: str
) -> PromptVariant:
    """确定性变体选择（E2.1）：同输入必同输出，无随机；未注册回落默认（E2.3）。"""
    return registry.lookup(group, field_id) or DEFAULT_VARIANT

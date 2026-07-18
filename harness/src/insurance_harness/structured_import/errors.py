"""010 错误分类（fail-fast/fail-closed 语义的类型化载体）。"""

from __future__ import annotations


class RegistryLoadError(ValueError):
    """来源登记表加载失败（I3：重复 source_system/权威域越界/缺责任人，须定位）。"""


class SourceNotRegisteredError(LookupError):
    """未登记来源不得进入 Claim 通道（I1 fail-closed，任何落库前拒绝）。"""


class ChannelTwoNotAvailableError(RuntimeError):
    """通道二导入排在 018+021 之后（T5+）——已登记来源也显式不可用，不静默成功。"""


class MappingLoadError(ValueError):
    """映射规则加载失败（I2 fail-fast：未知 field_id/未知变换器/重复映射，须定位）。"""


class DraftNotConfirmedError(ValueError):
    """未确认草案不得用于正式导入（I2：mapping-drafts 产物须人工确认）。"""

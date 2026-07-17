"""010 值变换器注册表（I2 映射的 transformer 轴；I4 manifest 的版本轴之一）。

版本纪律（spec I4）：任何会改变输出的行为变更必须 bump 对应版本常量，
禁止只改代码不改版本——effective_mapping_version 以此参与哈希。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

#: 变换器注册表行为版本（I4 manifest 轴）。**唯一权威来源**——mapping_manifest
#: 直接读取本常量，调用方不得自由传字符串（阻断5：杜绝伪造 provenance）；
#: 任何会改变变换器输出的行为变更 SHALL bump 本常量（spec I4 开发者纪律）。
TRANSFORMER_REGISTRY_VERSION: Final[str] = "transformers@v1"

#: 规范化行为版本（跟踪 goldenset.normalize 的行为；其行为变更须同步 bump）。
NORMALIZER_VERSION: Final[str] = "normalize@v1"

Transformer = Callable[[str], str]


def _identity(value: str) -> str:
    return value.strip()


#: 名称 → 变换器（T4 实现填充日期/金额/枚举归一；映射加载 fail-fast 校验名称）。
#: 用 MappingProxyType 封装为**不可变映射**：运行时不可增删改，避免注册表被
#: 就地篡改而 effective_mapping_version 不变（阻断5）。增删变换器须同步 bump
#: TRANSFORMER_REGISTRY_VERSION（pin 测试锁定注册表形状）。
TRANSFORMERS: Final[Mapping[str, Transformer]] = MappingProxyType(
    {
        "identity": _identity,
    }
)

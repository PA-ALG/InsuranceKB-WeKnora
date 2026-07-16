"""010 值变换器注册表（I2 映射的 transformer 轴；I4 manifest 的版本轴之一）。

版本纪律（spec I4）：任何会改变输出的行为变更必须 bump 对应版本常量，
禁止只改代码不改版本——effective_mapping_version 以此参与哈希。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

#: 变换器注册表行为版本（I4 manifest 轴）。
TRANSFORMER_REGISTRY_VERSION: Final[str] = "transformers@v1"

#: 规范化行为版本（跟踪 goldenset.normalize 的行为；其行为变更须同步 bump）。
NORMALIZER_VERSION: Final[str] = "normalize@v1"

Transformer = Callable[[str], str]


def _identity(value: str) -> str:
    return value.strip()


#: 名称 → 变换器（T4 实现填充日期/金额/枚举归一；映射加载 fail-fast 校验名称）。
TRANSFORMERS: Final[dict[str, Transformer]] = {
    "identity": _identity,
}

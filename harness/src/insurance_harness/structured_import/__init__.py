"""OpenSpec 010 结构化直入通道（T1~T4 波次：通道一 bootstrap / 来源登记 / 映射）。

双通道边界（spec I1，Q020 合规）：
- 通道一 bootstrap：`product_meta.json` 类元数据 → 003 产品注册，**零 Claim/Evidence**；
- 通道二（可信业务源 → Claim）：本波次只交付来源登记与映射合同；导入实现
  排在 018+021 之后（T5+），入口显式 fail-closed 不可用。

设计权威：openspec/changes/010-structured-import/（正式 delta，PR #11 五轮定稿）。
"""

from .errors import (
    ChannelTwoNotAvailableError,
    DraftNotConfirmedError,
    MappingLoadError,
    RegistryLoadError,
    SourceNotRegisteredError,
)
from .service import BootstrapReport, bootstrap_from_dir, import_records

__all__ = [
    "BootstrapReport",
    "ChannelTwoNotAvailableError",
    "DraftNotConfirmedError",
    "MappingLoadError",
    "RegistryLoadError",
    "SourceNotRegisteredError",
    "bootstrap_from_dir",
    "import_records",
]

"""010 导入服务（T1/T2 波次）：通道一 bootstrap 薄编排 + 通道二显式门。

- bootstrap：显式 space fail-closed（016 load_scope 语义）→ 003 register_products
  薄编排；dry-run 默认（不落库），``apply=True`` 才提交；**零 Claim/Evidence**
  是通道一的结构性质（I1，测试断言）。
- 通道二：本波次只有门——未登记来源 SourceNotRegisteredError；已登记来源
  ChannelTwoNotAvailableError（T5+ 前置 018+021），任何路径零落库。

骨架（T1/T2 转绿）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from insurance_harness.db.scope import load_scope
from insurance_harness.product.register import RegisterReport, register_products

from .errors import ChannelTwoNotAvailableError
from .registry import SourceRegistry, resolve_source


class BootstrapReport(BaseModel):
    """通道一报告：003 注册结果 + 010 合同字段。"""

    model_config = ConfigDict(frozen=True)

    space_id: str
    applied: bool  # False = dry-run（未落库）
    register: RegisterReport = Field(default_factory=RegisterReport)

    @property
    def summary(self) -> str:
        mode = "apply" if self.applied else "dry-run"
        return f"[{mode}] space={self.space_id} {self.register.summary}"


def bootstrap_from_dir(
    session: Session, root: Path, *, space_id: str, apply: bool = False
) -> BootstrapReport:
    """通道一：meta 目录 → 003 产品注册（I1）。

    显式 space fail-closed（未绑定/不存在 → UnboundKnowledgeSpace，零写入）；
    dry-run 默认：产出与 apply 完全一致的预测报告但不落库（I5 一致性）——
    同一 003 注册逻辑在事务内跑到 flush，dry-run 回滚、apply 提交，预测天然一致。
    """
    scope = load_scope(session, space_id)  # 016 fail-closed：任何写入前拒绝
    report = register_products(session, root, scope=scope, commit=False)
    if apply:
        session.commit()
    else:
        session.rollback()
    return BootstrapReport(space_id=space_id, applied=apply, register=report)


def import_records(
    session: Session,
    registry: SourceRegistry,
    *,
    source_system: str,
    records: list[dict[str, Any]],
    space_id: str,
) -> None:
    """通道二入口（本波次仅门禁）：未登记拒绝；已登记显式不可用（零落库）。"""
    load_scope(session, space_id)  # space 纪律先于一切（I6.1）
    resolve_source(registry, source_system)  # 未登记 → SourceNotRegisteredError
    del records
    raise ChannelTwoNotAvailableError(
        "通道二导入排在 018+021 之后（tasks T5+）——本波次只交付登记与映射合同，"
        "已登记来源也不提供任何落库路径"
    )

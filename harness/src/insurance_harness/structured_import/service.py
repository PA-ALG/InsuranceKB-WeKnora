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
    # 字段名用 registration 而非 register——register 会遮蔽 BaseModel/ABCMeta.register
    # 引发 Pydantic 属性遮蔽 warning（T3）。
    registration: RegisterReport = Field(default_factory=RegisterReport)

    @property
    def summary(self) -> str:
        mode = "apply" if self.applied else "dry-run"
        return f"[{mode}] space={self.space_id} {self.registration.summary}"


def bootstrap_from_dir(
    session: Session, root: Path, *, space_id: str, apply: bool = False
) -> BootstrapReport:
    """通道一：meta 目录 → 003 产品注册（I1）。

    显式 space fail-closed（未绑定/不存在 → UnboundKnowledgeSpace，零写入）。

    **事务归 Session 所有者**：本服务只跑到 flush，**绝不** commit/rollback 它不
    拥有的 Session（阻断1——否则会连带提交/回滚调用方无关的工作单元，破坏原子性）。
    调用方（CLI/任务入口）须在 apply 时 ``commit``、dry-run 时 ``rollback``（见 cli.py）。
    ``apply`` 仅用于登记报告模式；报告在内存生成，与是否提交无关，故 dry-run 预测与
    apply 结果天然一致（I5）。
    """
    scope = load_scope(session, space_id)  # 016 fail-closed：任何写入前拒绝
    report = register_products(session, root, scope=scope, commit=False)
    return BootstrapReport(space_id=space_id, applied=apply, registration=report)


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

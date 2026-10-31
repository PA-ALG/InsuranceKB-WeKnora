"""010 结构化导入合同的共用数据与辅助（测试名引用条款号 I1/I2/I3/I5/I6/I8）。

通道一 bootstrap = 003 注册薄编排（零 Claim/Evidence 为结构性质，I1）；
通道二本波次仅门禁（未登记拒绝 / 已登记显式不可用）。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import bind_space
from insurance_harness.knowledge.tables import Claim, ClaimEvidence
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry


def _bound_space(session: Session, name: str, sfx: str) -> str:
    row = KnowledgeSpace(name=name, binding_status="unbound")
    session.add(row)
    session.flush()
    bind_space(
        session, row.id,
        tenant_id=f"tenant-{sfx}", raw_kb_id=f"raw-{sfx}", wiki_kb_id=f"wiki-{sfx}",
    )
    session.commit()
    return str(row.id)


def _meta_dir(tmp_path: Path, n: int = 2) -> Path:
    root = tmp_path / "meta-root"
    for i in range(n):
        d = root / f"测试产品{i}"
        d.mkdir(parents=True)
        (d / "product_meta.json").write_text(
            json.dumps(
                {
                    "planCode": f"P{i:03d}",
                    "versionNo": "V1",
                    "clauseName": f"测试终身寿险{i}",
                    "planSalesStatus": "在售",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return root


def _claims_footprint(session: Session) -> tuple[int, int]:
    claims = int(session.execute(select(func.count()).select_from(Claim)).scalar_one())
    ev = int(
        session.execute(select(func.count()).select_from(ClaimEvidence)).scalar_one()
    )
    return claims, ev


_MINI_LINE = ProductLineSchema(
    line_key="t",
    sheet_name="测试",
    fields=(
        FieldSpec(name="等待期", field_id="waiting_period", aliases=("waitingPeriod",),
                  source_sheet="t"),
        FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),
    ),
)
_MINI_REGISTRY = SchemaRegistry(version="v1.1+import-test", lines={"t": _MINI_LINE}, glossary=())

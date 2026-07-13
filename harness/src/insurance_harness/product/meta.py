"""product_meta.json/.txt 解析（两种扩展名内容同为 JSON）。"""

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ProductMeta(BaseModel):
    """产品目录随附的主数据快照。字段名对照 db/models.py 模块注释。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    plan_code: str = Field(alias="planCode")
    version_no: str = Field(alias="versionNo")
    clause_name: str = Field(alias="clauseName")
    sales_status: str = Field(alias="planSalesStatus", default="未知")
    plan_type: str | None = Field(alias="planPlanType", default=None)
    sales_channel: str | None = Field(alias="planSalesChannel", default=None)
    region_code: str | None = Field(alias="regionCode", default=None)
    start_date: date | None = Field(alias="startDate", default=None)
    filing_no: str | None = Field(alias="reportPreparedFileCode", default=None)
    registration_no: str | None = Field(alias="sccode", default=None)

    @property
    def channels(self) -> list[str]:
        if not self.sales_channel:
            return []
        return [c for c in self.sales_channel.replace("，", "、").split("、") if c]


class MetaParseError(Exception):
    pass


def load_product_meta(product_dir: Path) -> ProductMeta:
    candidates = sorted(product_dir.glob("product_meta.*"))
    if not candidates:
        raise MetaParseError(f"{product_dir.name}: 缺少 product_meta.json/.txt")
    path = candidates[0]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ProductMeta.model_validate(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise MetaParseError(f"{product_dir.name}: {path.name} 解析失败：{exc}") from exc

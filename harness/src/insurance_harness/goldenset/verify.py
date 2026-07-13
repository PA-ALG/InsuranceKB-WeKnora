"""标注自检：引文回验与 product_meta 比对（spec G2.2 / G2.4）。

原则：任何校验失败都标 ``disputed`` 并留原因，绝不静默通过或静默丢弃。
"""

import json
from pathlib import Path
from typing import Any

from .normalize import quote_in_page, values_equal
from .pdf import PageText
from .records import GoldenRecord

# product_meta.json 键 → 基线字段名（07 §4：meta 是这些字段的 ground truth）
META_KEY_TO_FIELD_NAME: dict[str, str] = {
    "planCode": "险种代码",
    "versionNo": "条款版本标识",
    "reportPreparedFileCode": "条款备案/批复文号",
    "planSalesStatus": "销售状态",
    "startDate": "开始使用时间",
}


def verify_quotes(records: list[GoldenRecord], pages: list[PageText]) -> list[GoldenRecord]:
    """present/absent_explicitly 必须有证据且引文能回到原文（G2.2/G2.3）。原地标注 disputed。"""
    page_map = {p.page_no: p.text for p in pages}
    for rec in records:
        if rec.tri_state == "unknown" or rec.disputed:
            continue
        if not rec.evidence:
            rec.disputed = True
            rec.disputed_reason = "no_evidence"
            continue
        for ev in rec.evidence:
            page_text = page_map.get(ev.page)
            if page_text is None or not quote_in_page(ev.quote, page_text):
                rec.disputed = True
                rec.disputed_reason = "quote_mismatch"
                break
    return records


def load_product_meta(product_dir: Path) -> dict[str, Any]:
    """读 product_meta.json（个别产品为 .txt，内容同为 JSON）。"""
    for name in ("product_meta.json", "product_meta.txt"):
        p = product_dir / name
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            raise ValueError(f"{p}: product_meta 顶层应为 JSON 对象")
    return {}


def compare_with_meta(records: list[GoldenRecord], meta: dict[str, Any]) -> list[GoldenRecord]:
    """与 product_meta.json 可比对字段做 diff：不一致 → disputed=meta_mismatch（G2.4）。"""
    if not meta:
        return records
    name_to_meta_value: dict[str, str] = {}
    for meta_key, field_name in META_KEY_TO_FIELD_NAME.items():
        raw = meta.get(meta_key)
        if raw is not None and str(raw).strip():
            name_to_meta_value[field_name] = str(raw).strip()
    for rec in records:
        if rec.disputed or rec.tri_state != "present" or rec.value is None:
            continue
        expected = name_to_meta_value.get(rec.field_name)
        if expected is not None and not values_equal(rec.value, expected):
            rec.disputed = True
            rec.disputed_reason = "meta_mismatch"
    return records

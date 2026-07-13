"""来源权威序与置信度映射（docs/insurance-kb/03 §6.1；K2.1）。"""

#: doc_role → authority_level（数值越小越权威；1、2 级不可下调）
AUTHORITY_BY_DOC_ROLE: dict[str, int] = {
    "terms": 1,
    "official_desc": 2,
    "approved_faq": 2,
    "internal_ops": 3,
    "training": 4,
    "sales": 5,
    "external": 6,
}

#: 管道离散置信度 → Claim.confidence 浮点（K2.1）
CONFIDENCE_TO_FLOAT: dict[str, float] = {"high": 0.9, "medium": 0.6, "low": 0.3}

_FILENAME_DOC_ROLE: tuple[tuple[str, str], ...] = (
    ("条款", "terms"),
    ("说明书", "official_desc"),
    ("费率", "official_desc"),
    ("FAQ", "approved_faq"),
    ("培训", "training"),
    ("宣传", "sales"),
)


def authority_of(doc_role: str) -> int:
    return AUTHORITY_BY_DOC_ROLE.get(doc_role, 6)


def guess_doc_role(file_name: str) -> str:
    """按文件名猜 doc_role（导入器兜底；调用方可显式覆盖）。"""
    for keyword, role in _FILENAME_DOC_ROLE:
        if keyword in file_name:
            return role
    return "external"

"""证据 quote 回验（004 T1；设计 04 Step 3——本管道最重要的确定性关卡）。

自 002 goldenset/verify.py 的回验逻辑提升为公共模块：
``evidence_quote`` 必须能在所引页原文中做归一化子串匹配，纯字符串操作零模型成本，
确定性杀掉"值是编的 / 引文是编的 / 张冠李戴引错位置"三类幻觉（spec E3.2）。
"""

from collections.abc import Sequence

from ..goldenset.normalize import quote_in_page
from ..goldenset.pdf import PageText
from ..goldenset.records import Evidence


def quote_verified(evidence: Evidence, pages: Sequence[PageText]) -> bool:
    """单条证据回验：页码存在且 quote 归一化后是该页原文子串。"""
    for p in pages:
        if p.page_no == evidence.page:
            return quote_in_page(evidence.quote, p.text)
    return False


def all_quotes_verified(evidence: Sequence[Evidence], pages: Sequence[PageText]) -> bool:
    """present/absent_explicitly 候选值必须全部证据通过回验才允许出场（E3.2）。"""
    if not evidence:
        return False
    return all(quote_verified(ev, pages) for ev in evidence)

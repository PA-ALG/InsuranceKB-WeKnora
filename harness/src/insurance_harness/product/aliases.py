"""产品别名的确定性生成规则（spec P2.3）。

规则全部确定性、可解释；LLM 不参与。生成的别名进 product_aliases，
供路由做 alias 级匹配（同名映射到多个产品时视为歧义，不自动归属）。
"""

import re

_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")
_COMPANY_PREFIX = "平安"
# 从名称尾部逐层剥离的险种/形态后缀（顺序无关，循环剥离直到不再变化）
_TYPE_SUFFIXES = (
    "终身寿险",
    "定期寿险",
    "养老年金保险",
    "年金保险",
    "两全保险",
    "长期医疗保险",
    "医疗保险",
    "意外伤害保险",
    "失能收入损失保险",
    "重大疾病保险",
    "疾病保险",
    "护理保险",
    "保险",
)

_MIN_ALIAS_LEN = 4


def _strip_parens(name: str) -> str:
    prev = None
    while prev != name:
        prev = name
        name = _PAREN_RE.sub("", name)
    return name.strip()


def _strip_type_suffix(name: str) -> str:
    changed = True
    while changed:
        changed = False
        stripped = _strip_parens(name)
        for suffix in _TYPE_SUFFIXES:
            if stripped.endswith(suffix) and name.endswith(suffix):
                name = name[: -len(suffix)].rstrip()
                changed = True
                break
            # 形如 "……终身寿险（分红型）"：先剥尾部括号组再试
            if name.endswith("）") or name.endswith(")"):
                inner = _PAREN_RE.sub("", name).rstrip()
                if inner.endswith(suffix):
                    name = inner[: -len(suffix)].rstrip()
                    changed = True
                    break
        if changed:
            continue
    return name.strip()


def generate_aliases(canonical_name: str) -> list[tuple[str, str]]:
    """返回 [(alias, alias_type)]，去重、剔除过短与等于原名的项。"""
    out: dict[str, str] = {}

    def add(alias: str, alias_type: str) -> None:
        alias = alias.strip()
        if len(alias) >= _MIN_ALIAS_LEN and alias != canonical_name and alias not in out:
            out[alias] = alias_type

    no_paren = _strip_parens(canonical_name)
    add(no_paren, "no_paren")

    if canonical_name.startswith(_COMPANY_PREFIX):
        no_prefix = canonical_name[len(_COMPANY_PREFIX) :]
        add(no_prefix, "no_prefix")
        add(_strip_parens(no_prefix), "no_prefix")

    short = _strip_type_suffix(canonical_name)
    add(short, "short")
    add(_strip_parens(short), "short")
    if short.startswith(_COMPANY_PREFIX):
        add(short[len(_COMPANY_PREFIX) :], "short")
        add(_strip_parens(short[len(_COMPANY_PREFIX) :]), "short")

    return list(out.items())

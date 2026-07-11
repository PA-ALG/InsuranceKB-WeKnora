"""P2.3：别名确定性生成规则。"""

from insurance_harness.product.aliases import generate_aliases


def _aliases(name: str) -> dict[str, str]:
    return dict(generate_aliases(name))


def test_no_paren_and_no_prefix() -> None:
    aliases = _aliases("平安盛世金越养老年金保险（分红型）")
    assert "平安盛世金越养老年金保险" in aliases
    assert "盛世金越养老年金保险（分红型）" in aliases
    assert "盛世金越养老年金保险" in aliases


def test_short_strips_type_suffix() -> None:
    aliases = _aliases("平安盛世金越（尊享版26）终身寿险（分红型）")
    assert "平安盛世金越（尊享版26）" in aliases
    assert "盛世金越（尊享版26）" in aliases


def test_no_self_and_min_length() -> None:
    aliases = _aliases("平安爱满分（2026）两全保险")
    assert "平安爱满分（2026）两全保险" not in aliases
    assert all(len(a) >= 4 for a in aliases)

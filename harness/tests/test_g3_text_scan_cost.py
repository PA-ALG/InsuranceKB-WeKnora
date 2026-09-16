"""Control checks keep exact bytes without Python work per document character."""

import builtins

import pytest

from insurance_harness.knowledge_compiler import batch_canonical_830_g3 as canonical
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as resolution


@pytest.mark.parametrize("check", [canonical._body, canonical._structured,
                                  resolution._validate_body_text,
                                  resolution._validate_structured_text])
def test_large_text_control_check_does_not_scan_in_python(check, monkeypatch):
    calls = 0

    def counted(value):
        nonlocal calls
        calls += 1
        return builtins.ord(value)

    owner = canonical if check.__module__ == canonical.__name__ else resolution
    monkeypatch.setattr(owner, "ord", counted, raising=False)
    check("合同正文与证据。" * 100_000)
    assert calls < 100, "large source text still incurs per-character Python calls"


@pytest.mark.parametrize("code", range(128))
def test_text_control_policy_equivalence(code):
    text = "原文" + chr(code) + "条款"
    body_bad = code == 127 or (code < 32 and code not in (9, 10, 13))
    structured_bad = code < 32 or code == 127
    for check, bad in ((canonical._body, body_bad),
                       (canonical._structured, body_bad),
                       (resolution._validate_body_text, body_bad),
                       (resolution._validate_structured_text, structured_bad)):
        if bad:
            with pytest.raises(ValueError):
                check(text)
        else:
            check(text)
    if structured_bad:
        with pytest.raises(ValueError):
            canonical._structured(text, object_key=True)
    else:
        assert canonical._structured(text, object_key=True) == text

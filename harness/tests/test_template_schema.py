"""spec F1：模板 schema 与注册表（加载 fail-fast、版本、published-only 命中）。"""

from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compiler.templates import (
    TemplateLoadError,
    load_template_registry,
    parse_template,
)

VALID: dict[str, Any] = {
    "template_id": "tpl-abc-费率表",
    "family_id": "fam-0123456789ab",
    "doc": "费率表.pdf",
    "template_version": "v1",
    "status": "published",
    "induced_from": {"products": ["产品A", "产品B"], "golden_release": "wip-gs-v0.1"},
    "fields": [
        {
            "field_id": "zh_14b93ce275",
            "field_name": "交费期限",
            "anchors": {
                "pages": [1],
                "table_columns": {"op": "join_headers", "header_contains": "趸交"},
            },
            "few_shots": [
                {"product": "产品A", "page": 1, "quote": "趸交 3年", "value": "趸交、3年"}
            ],
        },
        {
            "field_id": "zh_67ee7025ef",
            "field_name": "主附加险",
            "anchors": {"regex": r"若本(主\s*险)合同"},
        },
    ],
}


def _write(tmp_path: Path, data: dict[str, Any], name: str = "t.yaml") -> Path:
    import yaml

    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_f1_1_valid_template_loads(tmp_path: Path) -> None:
    _write(tmp_path, VALID)
    registry = load_template_registry(tmp_path)
    assert len(registry.templates) == 1
    t = registry.templates[0]
    assert t.fields[0].anchors.table_columns is not None
    assert t.fields[0].anchors.table_columns.op == "join_headers"
    assert t.fields[1].anchors.regex is not None
    assert t.fields[0].few_shots[0].value == "趸交、3年"


def test_f1_2_fail_fast_with_file_and_field_location(tmp_path: Path) -> None:
    bad = {**VALID, "family_id": "not-a-family"}
    _write(tmp_path, bad, "bad.yaml")
    with pytest.raises(TemplateLoadError, match=r"bad\.yaml.*family_id"):
        load_template_registry(tmp_path)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        # regex 无捕获组
        (lambda d: d["fields"][1]["anchors"].update(regex="主险"), "捕获组"),
        # regex 两个捕获组
        (lambda d: d["fields"][1]["anchors"].update(regex="(主)(险)"), "捕获组"),
        # regex 编译失败
        (lambda d: d["fields"][1]["anchors"].update(regex="(主险"), "编译失败"),
        # status 非法枚举
        (lambda d: d.update(status="live"), "status"),
        # 无可执行锚点
        (lambda d: d["fields"][1].update(anchors={}), "无可执行锚点"),
        # op=cell 缺 row_label/column
        (
            lambda d: d["fields"][0]["anchors"]["table_columns"].update(op="cell"),
            "row_label",
        ),
        # doc 非 PDF
        (lambda d: d.update(doc="费率表.txt"), "PDF"),
    ],
)
def test_f1_2_structural_problems_fail_fast(mutate, match: str) -> None:  # type: ignore[no-untyped-def]
    import copy

    data = copy.deepcopy(VALID)
    mutate(data)
    with pytest.raises(TemplateLoadError, match=match):
        parse_template(data, "case.yaml")


def test_f1_2_duplicate_field_id_rejected() -> None:
    import copy

    data = copy.deepcopy(VALID)
    data["fields"][1]["field_id"] = data["fields"][0]["field_id"]
    with pytest.raises(TemplateLoadError, match="重复"):
        parse_template(data, "dup.yaml")


def test_f1_3_registry_version_content_hash(tmp_path: Path) -> None:
    _write(tmp_path, VALID)
    v1 = load_template_registry(tmp_path).version
    assert v1.startswith("tpl-v1+") and not v1.endswith("empty")
    # 内容变化 → 版本 hash 变化（对齐 schemas G1.3 机制）
    import copy

    data = copy.deepcopy(VALID)
    data["template_version"] = "v2"
    _write(tmp_path, data)
    assert load_template_registry(tmp_path).version != v1


def test_f1_3_find_only_published(tmp_path: Path) -> None:
    import copy

    draft = copy.deepcopy(VALID)
    draft["status"] = "draft"
    _write(tmp_path, draft)
    registry = load_template_registry(tmp_path)
    assert registry.find("fam-0123456789ab", "费率表.pdf") is None  # draft 不命中
    _write(tmp_path, VALID)
    registry = load_template_registry(tmp_path)
    assert registry.find("fam-0123456789ab", "费率表.pdf") is not None
    assert registry.find("fam-0123456789ab", "条款.pdf") is None
    assert registry.find("fam-ffffffffffff", "费率表.pdf") is None


def test_f1_3_empty_or_missing_dir_bypasses(tmp_path: Path) -> None:
    empty = load_template_registry(tmp_path / "not-exist")
    assert empty.version.endswith("+empty") and empty.templates == ()
    (tmp_path / "d").mkdir()
    assert load_template_registry(tmp_path / "d").templates == ()
    assert load_template_registry(None).templates == ()

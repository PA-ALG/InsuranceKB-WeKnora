"""S1 项目脚手架。"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "insurance_harness"
SUBPACKAGES = ["adapters", "compiler", "goldenset", "workbench", "mcp", "schemas"]


def test_s1_3_every_subpackage_has_readme_and_init() -> None:
    for name in SUBPACKAGES:
        pkg = SRC / name
        assert (pkg / "__init__.py").is_file(), f"{name} 缺 __init__.py"
        assert (pkg / "README.md").is_file(), f"{name} 缺 README.md（职责说明，spec S1.3）"


def test_s1_3_readme_mentions_docs_reference() -> None:
    for name in SUBPACKAGES:
        text = (SRC / name / "README.md").read_text(encoding="utf-8")
        assert "docs/insurance-kb" in text, f"{name}/README.md 应引用设计文档"

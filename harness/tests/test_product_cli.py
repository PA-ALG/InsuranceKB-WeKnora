"""T5/P5：CLI register-products / classify 端到端（SQLite 临时库 + 真实样本子集）。"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from insurance_harness.db.models import UnassignedItem
from insurance_harness.product.cli import main

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "dataset" / "shouxian_product"
SAMPLE_PRODUCT = "平安盛世金越（尊享版26）终身寿险"


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/cli.db"


def test_cli_register_synthetic_idempotent_and_skip(
    tmp_path: Path, db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "products"
    good = root / "平安爱满分（2026）两全保险"
    good.mkdir(parents=True)
    good.joinpath("product_meta.json").write_text(
        json.dumps(
            {
                "planCode": "1810",
                "versionNo": "1810-1",
                "clauseName": "平安爱满分（2026）两全保险",
                "planSalesStatus": "在售",
            },
            ensure_ascii=False,
        )
    )
    bad = root / "坏产品"
    bad.mkdir()
    bad.joinpath("product_meta.json").write_text("{broken")

    assert main(["register-products", str(root), "--db-url", db_url]) == 0
    out1 = capsys.readouterr().out
    assert "created=1" in out1 and "skipped=1" in out1

    assert main(["register-products", str(root), "--db-url", db_url]) == 0
    out2 = capsys.readouterr().out
    assert "created=0" in out2 and "unchanged=1" in out2


def test_cli_register_and_classify_real_sample(
    tmp_path: Path, db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """真实样本端到端：注册 13 产品，对单产品目录分类+路由并出报告（P2.1/P4.5）。"""
    assert main(["register-products", str(DATASET_DIR), "--db-url", db_url]) == 0
    assert "created=13" in capsys.readouterr().out

    report = tmp_path / "report.md"
    unassigned = tmp_path / "unassigned.jsonl"
    assert (
        main(
            [
                "classify",
                str(DATASET_DIR / SAMPLE_PRODUCT),
                "--db-url",
                db_url,
                "--report",
                str(report),
                "--unassigned-out",
                str(unassigned),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "LLM调用=0" in out

    text = report.read_text(encoding="utf-8")
    assert "产品 exact 命中（以所在目录为真值）：3/3" in text
    assert "文档类型正确（以文件名关键词为真值）：3/3" in text
    # 全部命中 → 无 unassigned；JSONL 为空、池表为空
    assert unassigned.read_text(encoding="utf-8") == ""
    with Session(create_engine(db_url)) as session:
        assert session.scalar(select(func.count()).select_from(UnassignedItem)) == 0

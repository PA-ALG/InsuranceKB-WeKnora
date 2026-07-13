"""spec F2/F4 CLI 烟测：induce-template（真实金标+PDF，零模型）与 feedability dry-run。"""

from pathlib import Path

import pytest
import yaml

from insurance_harness.compiler import cli as compiler_cli
from insurance_harness.compiler.templates import parse_template

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset/shouxian_product"
GOLDEN_WIP = ROOT / "dataset/goldenset/wip-gs-v0.1"

INDUCTION_PRODUCTS = [
    "平安盛世金越（尊享版26）终身寿险（分红型）",
    "平安创享盛世金越（尊享版26）终身寿险（分红型）",
]


def _need_dataset() -> None:
    if not (DATASET.exists() and GOLDEN_WIP.exists()):
        pytest.skip("样本/金标缺失")


def test_f2_cli_induce_template_writes_draft_report_queue(tmp_path: Path) -> None:
    _need_dataset()
    rc = compiler_cli.main(
        [
            "induce-template",
            "--doc", "费率表.pdf",
            "--products", ",".join(INDUCTION_PRODUCTS),
            "--golden-root", str(GOLDEN_WIP),
            "--dataset-root", str(DATASET),
            "--out-dir", str(tmp_path),
        ]
    )
    assert rc == 0
    yamls = list(tmp_path.glob("tpl-*.yaml"))
    assert len(yamls) == 1
    template = parse_template(
        yaml.safe_load(yamls[0].read_text(encoding="utf-8")), yamls[0].name
    )
    assert template.status == "draft"
    assert {f.field_id for f in template.fields} == {"zh_14b93ce275", "zh_67ee7025ef"}
    assert list(tmp_path.glob("*.report.md")) and list(tmp_path.glob("*.polish-queue.jsonl"))


def test_f2_cli_induce_template_rejects_cross_family(tmp_path: Path) -> None:
    _need_dataset()
    # 说明书：两分红产品版式不同构（指纹不同族）→ fail fast
    with pytest.raises(SystemExit, match="不同族"):
        compiler_cli.main(
            [
                "induce-template",
                "--doc", "产品说明书.pdf",
                "--products", ",".join(INDUCTION_PRODUCTS),
                "--golden-root", str(GOLDEN_WIP),
                "--dataset-root", str(DATASET),
                "--out-dir", str(tmp_path),
            ]
        )


def test_f4_cli_feedability_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _need_dataset()
    product_dir = DATASET / "平安盛世金越（尊享版26）终身寿险"
    quarantine = tmp_path / ".rejections"
    rc = compiler_cli.main(
        [
            "feedability", str(product_dir),
            "--quarantine-dir", str(quarantine),
            "--threshold", "0.75",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "费率表.pdf" in out and "评分" in out
    assert not quarantine.exists(), "默认 dry-run 不得写隔离文件（F4.3）"

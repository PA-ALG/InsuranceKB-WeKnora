"""金标 release 校验器（019 spec Q1.3~Q1.5）。

对一个已发布 release 目录做确定性校验：
- Q1.3 产品齐全、每产品 disputed rate 阈值、每个 extractable 字段有记录（非 extractable 不计）；
- Q1.4 golden self-eval 要求 P/R/F1（+ 有 dataset_root 时 evidence）均为 1.0；发布后目录不可变；
- Q1.5 普通 CI 用最小 fixture 验证成功与各失败分支，无需真实 13 产品或模型凭据。
"""

from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from ..schemas import SchemaRegistry
from .eval import evaluate
from .records import GoldenRecord
from .runner import load_release


class ExpectedProduct(BaseModel):
    """校验时期望存在的产品及其险种。"""

    product_id: str
    line_key: str


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class ValidationResult(BaseModel):
    passed: bool
    checks: list[ValidationCheck]

    def failures(self) -> list[ValidationCheck]:
        return [c for c in self.checks if not c.passed]


def _check_products_complete(
    by_product: dict[str, list[GoldenRecord]],
    expected: list[ExpectedProduct],
) -> ValidationCheck:
    expected_ids = {e.product_id for e in expected}
    present = set(by_product)
    missing = sorted(expected_ids - present)
    extra = sorted(present - expected_ids)
    return ValidationCheck(
        name="products_complete",
        passed=not missing,
        detail=(f"缺失产品={missing}" if missing else "")
        + (f" 额外产品={extra}" if extra else ""),
    )


def _check_disputed_rate(
    by_product: dict[str, list[GoldenRecord]],
    max_disputed_rate: float,
) -> ValidationCheck:
    offenders: list[str] = []
    for product_id, recs in sorted(by_product.items()):
        rate = sum(1 for r in recs if r.disputed) / max(len(recs), 1)
        if rate > max_disputed_rate:
            offenders.append(f"{product_id}={rate:.2f}")
    return ValidationCheck(
        name="disputed_rate",
        passed=not offenders,
        detail=(f"超过阈值 {max_disputed_rate:.2f}：{offenders}" if offenders else ""),
    )


def _check_extractable_coverage(
    by_product: dict[str, list[GoldenRecord]],
    expected: list[ExpectedProduct],
    registry: SchemaRegistry,
) -> ValidationCheck:
    gaps: list[str] = []
    for exp in expected:
        recs = by_product.get(exp.product_id, [])
        covered = {r.field_id for r in recs}
        extractable = {f.field_id for f in registry.line(exp.line_key).extractable_fields}
        missing = sorted(extractable - covered)
        if missing:
            gaps.append(f"{exp.product_id}:{missing}")
    return ValidationCheck(
        name="extractable_coverage",
        passed=not gaps,
        detail=(f"extractable 字段缺记录：{gaps}" if gaps else ""),
    )


def _check_self_eval(
    records: list[GoldenRecord],
    dataset_root: Path | None,
) -> ValidationCheck:
    usable = [r for r in records if not r.disputed]
    result = evaluate(records, usable, dataset_root=dataset_root)
    metrics = {
        "precision": result.micro.precision,
        "recall": result.micro.recall,
        "f1": result.micro.f1,
    }
    failed = {k: round(v, 4) for k, v in metrics.items() if v != 1.0}
    evidence_note = ""
    if dataset_root is not None:
        if result.evidence_accuracy is None or result.evidence_accuracy != 1.0:
            failed["evidence"] = result.evidence_accuracy  # type: ignore[assignment]
        else:
            evidence_note = " evidence=1.0"
    return ValidationCheck(
        name="self_eval",
        passed=not failed,
        detail=(f"self-eval 未达 1.0：{failed}" if failed else "P/R/F1=1.0" + evidence_note),
    )


def _check_immutable(release_dir: Path) -> ValidationCheck:
    manifest_ok = (release_dir / "manifest.json").is_file()
    return ValidationCheck(
        name="release_immutable",
        passed=manifest_ok,
        detail=("manifest.json 缺失，release 未完成" if not manifest_ok else ""),
    )


def validate_release(
    release_dir: Path,
    *,
    registry: SchemaRegistry,
    expected: list[ExpectedProduct],
    dataset_root: Path | None = None,
    max_disputed_rate: float = 0.2,
) -> ValidationResult:
    records = load_release(release_dir)
    by_product: dict[str, list[GoldenRecord]] = defaultdict(list)
    for record in records:
        by_product[record.product_id].append(record)

    checks = [
        _check_immutable(release_dir),
        _check_products_complete(dict(by_product), expected),
        _check_disputed_rate(dict(by_product), max_disputed_rate),
        _check_extractable_coverage(dict(by_product), expected, registry),
        _check_self_eval(records, dataset_root),
    ]
    return ValidationResult(passed=all(c.passed for c in checks), checks=checks)

"""Review-score thresholds calibrated against judge labels, per pack (RV2b Spec §3.2).

usage: python -m insurance_harness.eval.review_calibration --report <semantic report.json>
       --scores <dir> --out <dir> [--precision 0.95] [--min-support 10]

A reviewed claim is a field the compiler stated as present or absent_explicitly, which is what
the review scorer scores; unknown and missing predictions take no part. Its label is the final
result in the `semantic_run score` report (`report.outcomes[]`): correct, incomplete (states
nothing wrong, user ruling 2026-10-14) and correct_non_present are right; wrong_value,
hallucination, contradiction, misfiled and state_mismatch are wrong. Any other result on a
reviewed claim stops the run (LABEL_UNKNOWN) instead of being guessed. Its score is read from
<scores>/<product>/scores.json (RV1's scores file) under `<product>/<field_key>`.

For each pack and for all packs together, every distinct score t gets the number n of claims
scoring at least t, how many of them are right, the precision and its Wilson 95% lower bound
(z = 1.96). The threshold is the lowest t whose precision reaches --precision with n at least
--min-support. Without one the group is insufficient: either it has fewer claims than
--min-support in all, or no t backed by enough claims reaches the precision.

--out receives calibration.json (claims, candidate tables, choices), calibration.md (a summary)
and thresholds.json (chosen pack thresholds in the review policy's shape, with the parameters and
the sha256 of every input). The review policy itself is not changed here (RV3 does that).
Prints one JSON line; exit 2 means stopped, with a code and counts but never paths or material.
"""

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from itertools import groupby
from pathlib import Path
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict, Field, field_validator

from insurance_harness.catalog.review_policy import NonBlank, Score
from insurance_harness.eval.golden import State
from insurance_harness.eval.product_sources import check_product_id

Z = 1.96  # two-sided 95%
OUTPUTS = ("calibration.json", "calibration.md", "thresholds.json")
_RIGHT = frozenset({"correct", "incomplete", "correct_non_present"})
_WRONG = frozenset({"wrong_value", "hallucination", "contradiction", "misfiled", "state_mismatch"})
_REVIEWED = frozenset({"present", "absent_explicitly"})
_ALL = "全体"


class _Stopped(Exception):
    def __init__(self, code: str, **counts: int) -> None:
        super().__init__(code)
        self.code, self.counts = code, counts


class _Parser(argparse.ArgumentParser):
    """Malformed arguments become the INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise _Stopped("INVALID_ARGUMENTS")


class _Outcome(BaseModel):
    """The parts of one semantic report outcome this tool reads; other keys are ignored."""

    model_config = ConfigDict(strict=True, frozen=True)
    pack_id: NonBlank
    product_id: NonBlank
    field_key: NonBlank
    predicted_state: State | None
    result: NonBlank


class _Report(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    outcomes: tuple[_Outcome, ...] = Field(min_length=1)


class _ReportFile(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    report: _Report


class _ScoresFile(BaseModel):
    """RV1's scores file, as `compilers.schema_fields.publish --scores` reads it.

    Mirrored rather than imported: RV1 keeps its model private and this slice does not change
    RV1's files. Keep the two in step until RV1 exposes the format.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    reviewer: NonBlank
    reviewed_at: NonBlank
    scores: dict[NonBlank, Score]

    @field_validator("reviewed_at")
    @classmethod
    def iso_8601_with_offset(cls, value: str) -> str:
        if "T" not in value or datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("reviewed_at must be an ISO 8601 date-time with an offset")
        return value


@dataclass(frozen=True)
class _Claim:
    pack_id: str
    product_id: str
    field_key: str
    state: str
    score: float
    right: bool
    result: str


@dataclass(frozen=True)
class _Candidate:
    threshold: float
    n: int
    right: int

    def as_json(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "n": self.n,
            "correct": self.right,
            "precision": self.right / self.n,
            "wilson_lower": wilson_lower_bound(self.right, self.n),
        }


def wilson_lower_bound(successes: int, trials: int) -> float:
    """Lower end of the Wilson score interval for a binomial proportion, z = 1.96."""
    if trials < 1 or not 0 <= successes <= trials:
        raise ValueError("need 0 <= successes <= trials and trials >= 1")
    p = successes / trials
    z2 = Z * Z
    centre = p + z2 / (2 * trials)
    margin = Z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))
    return max(0.0, (centre - margin) / (1 + z2 / trials))  # rounding can dip below 0


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_report(path: Path) -> tuple[_Report, str]:
    try:
        raw = path.read_bytes()
        report = _ReportFile.model_validate_json(raw).report
        for row in report.outcomes:
            check_product_id(row.product_id)
    except (OSError, ValueError) as error:  # ValidationError is a ValueError
        raise _Stopped("REPORT_UNREADABLE") from error
    keys = [(row.product_id, row.field_key) for row in report.outcomes]
    if len(set(keys)) != len(keys):
        raise _Stopped("REPORT_UNREADABLE")
    return report, _sha(raw)


def _read_scores(root: Path, products: set[str]) -> tuple[dict[str, _ScoresFile], dict[str, str]]:
    if not root.is_dir():
        raise _Stopped("SCORES_UNREADABLE")
    scored = {path.parent.name for path in root.glob("*/scores.json")}
    if scored != products:
        raise _Stopped(
            "PRODUCT_MISMATCH",
            report_only=len(products - scored),
            scores_only=len(scored - products),
        )
    files, digests = {}, {}
    for product in sorted(products):
        try:
            raw = (root / product / "scores.json").read_bytes()
            files[product] = _ScoresFile.model_validate_json(raw)
        except (OSError, ValueError) as error:
            raise _Stopped("SCORES_UNREADABLE") from error
        digests[product] = _sha(raw)
    return files, digests


def _claims(report: _Report, scores: dict[str, _ScoresFile]) -> tuple[list[_Claim], int]:
    """Reviewed claims with label and score, and the number of scores no claim used."""
    reviewed = [row for row in report.outcomes if row.predicted_state in _REVIEWED]
    unlabelled = sum(row.result not in _RIGHT | _WRONG for row in reviewed)
    if unlabelled:
        raise _Stopped("LABEL_UNKNOWN", claims=unlabelled)
    unscored = sum(
        f"{row.product_id}/{row.field_key}" not in scores[row.product_id].scores for row in reviewed
    )
    if unscored:
        raise _Stopped("SCORE_MISSING", claims=unscored)
    claims = [
        _Claim(
            pack_id=row.pack_id,
            product_id=row.product_id,
            field_key=row.field_key,
            state=str(row.predicted_state),
            score=scores[row.product_id].scores[f"{row.product_id}/{row.field_key}"],
            right=row.result in _RIGHT,
            result=row.result,
        )
        for row in reviewed
    ]
    unused = sum(len(document.scores) for document in scores.values()) - len(claims)
    return sorted(claims, key=lambda c: (c.pack_id, c.product_id, c.field_key)), unused


def _group(claims: Sequence[_Claim], precision: Fraction, min_support: int) -> dict[str, Any]:
    """Candidate thresholds from the highest score down, and the lowest one that qualifies."""
    candidates: list[_Candidate] = []
    n = right = 0
    ranked = sorted(claims, key=lambda claim: claim.score, reverse=True)
    for score, tied in groupby(ranked, key=lambda claim: claim.score):
        members = list(tied)
        n += len(members)
        right += sum(claim.right for claim in members)
        candidates.append(_Candidate(score, n, right))
    # Exact arithmetic: 19/20 meets 0.95 although 19 / 20 is a rounded float.
    passing = [c for c in candidates if c.n >= min_support and Fraction(c.right, c.n) >= precision]
    if passing:
        status, reason, selected = "selected", None, passing[-1].as_json()
    else:
        short = len(claims) < min_support
        status, selected = "insufficient", None
        reason = "insufficient_support" if short else "precision_not_reached"
    return {
        "claims": len(claims),
        "correct": sum(claim.right for claim in claims),
        "candidates": [candidate.as_json() for candidate in candidates],
        "status": status,
        "reason": reason,
        "selected": selected,
    }


def _calibrate(
    report: _Report, claims: list[_Claim], precision: Fraction, min_support: int
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    # Every reported pack gets a row, even one whose claims are all unknown.
    packs = sorted({row.pack_id for row in report.outcomes})
    per_pack = {
        pack: _group([c for c in claims if c.pack_id == pack], precision, min_support)
        for pack in packs
    }
    return per_pack, _group(claims, precision, min_support)


def _cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _number(value: float) -> str:
    return f"{value:.4f}"


def _markdown(data: dict[str, Any]) -> str:
    parameters, claims = data["parameters"], data["claims"]
    right = sum(row["label"] == "correct" for row in claims)
    lines = [
        "# 审核门槛校准",
        "",
        f"- 精确率目标 {parameters['precision']}，最少样本 {parameters['min_support']}，"
        f"置信下界 Wilson 95%（z = {parameters['z']}）",
        f"- 被审核的 Claim {len(claims)} 条：对 {right}，错 {len(claims) - right}；"
        f"未用到的分数 {data['unused_scores']} 条",
        f"- 报告 sha256 `{data['sources']['report_sha256']}`",
        *(
            f"- 分数 {_cell(product)} sha256 `{digest}`"
            for product, digest in data["sources"]["scores_sha256"].items()
        ),
        "",
        "## 门槛",
        "",
        "| pack | Claim | 对 | 门槛 | n | 精确率 | Wilson 下界 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    groups = [*data["packs"].items(), (_ALL, data["all"])]
    for name, group in groups:
        chosen = group["selected"]
        if chosen is None:
            why = "样本不足" if group["reason"] == "insufficient_support" else "达不到精确率"
            cells = [f"不足（{why}）", "—", "—", "—"]
        else:
            cells = [
                str(chosen["threshold"]),
                str(chosen["n"]),
                _number(chosen["precision"]),
                _number(chosen["wilson_lower"]),
            ]
        lines.append(
            f"| {_cell(name)} | {group['claims']} | {group['correct']} | "
            + " | ".join(cells)
            + " |"
        )
    lines += ["", "## 结果分布", "", "| pack | 结果 | 标签 | 条数 |", "| --- | --- | --- | --- |"]
    counts = Counter((row["pack_id"], row["result"], row["label"]) for row in claims)
    for (pack, result, label), count in sorted(counts.items()):
        lines.append(f"| {_cell(pack)} | {_cell(result)} | {label} | {count} |")
    for name, group in groups:
        lines += [
            "",
            f"## 候选门槛：{_cell(name)}",
            "",
            "| 门槛 | n | 对 | 精确率 | Wilson 下界 |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| {row['threshold']} | {row['n']} | {row['correct']} | "
            f"{_number(row['precision'])} | {_number(row['wilson_lower'])} |"
            for row in group["candidates"]
        ]
    return "\n".join(lines) + "\n"


def _json_text(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write(out: Path, texts: dict[str, str]) -> None:
    """All outputs or none; existing files are never replaced."""
    if any((out / name).exists() or (out / name).is_symlink() for name in texts):
        raise _Stopped("OUTPUT_EXISTS")
    created: list[Path] = []
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in texts.items():
            with (out / name).open("x", encoding="utf-8") as stream:
                created.append(out / name)
                stream.write(text)
    except OSError as error:
        for path in created:
            path.unlink(missing_ok=True)
        code = "OUTPUT_EXISTS" if isinstance(error, FileExistsError) else "OUTPUT_FAILED"
        raise _Stopped(code) from error


def _options(args: argparse.Namespace) -> tuple[Fraction, int]:
    try:
        precision = Fraction(args.precision)
    except (ValueError, ZeroDivisionError) as error:
        raise _Stopped("INVALID_ARGUMENTS") from error
    if not 0 < precision <= 1 or args.min_support < 1:
        raise _Stopped("INVALID_ARGUMENTS")
    return precision, args.min_support


def _run(args: argparse.Namespace) -> dict[str, Any]:
    precision, min_support = _options(args)
    report, report_sha = _read_report(args.report)
    scores, scores_sha = _read_scores(args.scores, {row.product_id for row in report.outcomes})
    claims, unused = _claims(report, scores)
    per_pack, pooled = _calibrate(report, claims, precision, min_support)
    parameters = {"precision": float(precision), "min_support": min_support, "z": Z}
    sources = {"report_sha256": report_sha, "scores_sha256": scores_sha}
    data = {
        "parameters": parameters,
        "sources": sources,
        "claims": [
            {
                "pack_id": claim.pack_id,
                "product_id": claim.product_id,
                "field_key": claim.field_key,
                "state": claim.state,
                "score": claim.score,
                "label": "correct" if claim.right else "wrong",
                "result": claim.result,
            }
            for claim in claims
        ],
        "unused_scores": unused,
        "packs": per_pack,
        "all": pooled,
    }
    thresholds = {
        pack: {"default": group["selected"]["threshold"]}
        for pack, group in per_pack.items()
        if group["selected"] is not None
    }
    _write(
        args.out,
        {
            "calibration.json": _json_text(data),
            "calibration.md": _markdown(data),
            "thresholds.json": _json_text(
                {"thresholds": thresholds, "parameters": parameters, "sources": sources}
            ),
        },
    )
    return {"claims": len(claims), "thresholds": thresholds}


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--precision", default="0.95")
    parser.add_argument("--min-support", type=int, default=10)
    try:
        summary = _run(parser.parse_args(argv))
    except _Stopped as stop:
        print(json.dumps({"stopped": stop.code, **stop.counts}, sort_keys=True))
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

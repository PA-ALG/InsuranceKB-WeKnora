"""Prepare immutable L2 exchanges and score them with attributed L3 rulings.

Reports are written outside Git without replacement. Exit 0 means files were
generated, regardless of quality gates; exit 2 means invalid inputs or I/O.
"""

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.equivalence import (
    EQUIVALENCE_PROMPT_VERSION,
    EquivalenceQuestion,
    build_equivalence_requests,
    read_equivalence_verdicts,
)
from insurance_harness.eval.evaluator import Report, evaluate, gate
from insurance_harness.eval.golden import GoldenItem, Prediction
from insurance_harness.eval.judge import JudgeRequest
from insurance_harness.eval.judge_files import FileJudgeClient, check_run_directory, write_requests
from insurance_harness.eval.semantic import (
    Ruling,
    SemanticVerdict,
    evaluate_semantic,
    semantic_questions,
)

_BATCH_SIZE = 60
_RULES = '''# 独立语义评分评委

只读本目录及各产品子目录，不打开仓库、PDF、Golden 文件或其他路径，不联网。
必须使用全新的独立会话，不能沿用写过 S2b Golden 的标注会话。
一个会话可依次处理全部产品子目录。
按 requests/ 中 system_lines 的规则，比较 user_lines 中的两种表述。
答案写为严格 JSON，存入同一产品 responses/ 的同名文件；已有答案跳过。
如实判定，不为提高或压低分数调整判断，不用脚本批量生成答案。
不修改 requests/、run.json 与本文件。完成后说明实际模型与推理档位。
'''
_DEFINITION = {
    "metric_id": "golden.semantic_comparison.v1",
    "precision": "TP / (TP + FP)", "recall": "TP / (TP + FN)",
    "scoring": (
        "L1 equality or component match, then independent L2 equivalence, then attributed L3. "
        "Correct present: TP; incomplete/wrong_value: FP + FN; missed present: FN; "
        "hallucination/contradiction/misfiled: FP; golden_defect: excluded from denominators. "
        "Only hallucination counts toward the zero-hallucination gate. "
        "Non-present comparisons and unscored predictions do not enter P/R denominators."
    ),
    "undefined": "A zero denominator is null and fails the quality gate.",
    "limitation": (
        "L2 is one-directional: it checks whether the prediction covers the Golden core facts. "
        "Additional predicted facts absent from Golden are not verified by L2. "
        "Evidence accuracy and production model quality are not certified by this report."
    ),
}


class _Rulings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    entries: list[Ruling]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _load(args: argparse.Namespace) -> tuple[list[GoldenItem], list[Prediction], dict[str, Any]]:
    golden_bytes = [path.read_bytes() for path in args.golden]
    candidate = args.candidate.read_bytes()
    mapping = args.product_map.read_bytes()
    products = _object(mapping)
    if not all(isinstance(value, str) for value in products.values()):
        raise ValueError("product IDs must be strings")
    golden = [GoldenItem.model_validate_json(line)
              for raw in golden_bytes for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not golden:
        raise ValueError("Golden must not be empty")
    predicted = predictions_from_candidate(_object(candidate), products)
    return golden, predicted, {
        "golden_sha256": [_sha(raw) for raw in golden_bytes],
        "candidate_sha256": _sha(candidate), "product_map_sha256": _sha(mapping),
    }


def _requests(
    questions: dict[str, list[EquivalenceQuestion]],
) -> dict[str, list[JudgeRequest]]:
    requests = {}
    for product, rows in sorted(questions.items()):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", product):
            raise ValueError("product ID is not safe for a run directory")
        requests[product] = build_equivalence_requests(
            rows, product_id=product, batch_size=_BATCH_SIZE,
        )
        if len(requests[product]) > 2:
            raise ValueError("product request budget exceeds 2 batches")
    if sum(map(len, requests.values())) > 8:
        raise ValueError("total request budget exceeds 8 batches")
    return requests


def _metadata(
    sources: dict[str, Any], requests: dict[str, list[JudgeRequest]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    common = {**sources, "prompt_version": EQUIVALENCE_PROMPT_VERSION, "batch_size": _BATCH_SIZE}
    products = {
        product: {**common, "product_id": product,
                  "request_sha256": [request.sha256 for request in rows]}
        for product, rows in requests.items()
    }
    return {**common, "products": products}, products


def _write(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def _json_text(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _prepare(
    root: Path, sources: dict[str, Any], requests: dict[str, list[JudgeRequest]],
) -> None:
    check_run_directory(root)
    # Preflight the entire exchange before writing the first product. An existing
    # empty directory is allowed; unrelated files must not enter a blind session.
    if root.exists() and any(root.iterdir()):
        raise ValueError("run directory already contains files")
    root_run, products = _metadata(sources, requests)
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "AGENTS.md", _RULES)
    _write(root / "run.json", _json_text(root_run))
    for product, rows in requests.items():
        directory = root / product
        directory.mkdir()
        write_requests(rows, directory)
        _write(directory / "run.json", _json_text(products[product]))
    print(_json_text({"products": [
        {"product_id": product, "question_count": len(rows),
         "request_sha256": products[product]["request_sha256"]}
        for product, rows in requests.items()
    ]}), end="")


def _verdicts(
    root: Path, sources: dict[str, Any], requests: dict[str, list[JudgeRequest]],
    questions: dict[str, list[EquivalenceQuestion]], model: str,
) -> list[SemanticVerdict]:
    check_run_directory(root)
    if not model.strip():
        raise ValueError("judge model must not be empty")
    root_run, products = _metadata(sources, requests)
    if _object((root / "run.json").read_bytes()) != root_run:
        raise ValueError("inputs changed since prepare")
    if (root / "AGENTS.md").read_text(encoding="utf-8") != _RULES:
        raise ValueError("judge rules changed since prepare")
    actual_products = {p.parent.name for p in root.glob("*/requests")}
    if actual_products != set(products):
        raise ValueError("product exchange directories changed since prepare")
    verdicts: list[SemanticVerdict] = []
    for product in products:
        directory = root / product
        if _object((directory / "run.json").read_bytes()) != products[product]:
            raise ValueError("inputs changed since prepare")
        request_names = {p.name for p in (directory / "requests").glob("*.json")}
        answer_names = {p.name for p in (directory / "responses").glob("*.json")}
        if answer_names != request_names:
            raise ValueError("missing or extra answer files")
        client = FileJudgeClient(directory, model_id=model)
        rows = read_equivalence_verdicts(
            client, questions[product], max_calls=2, batch_size=_BATCH_SIZE,
        )
        if client.unconsumed():
            raise ValueError("unconsumed request files")
        verdicts.extend(SemanticVerdict(product_id=product, **row.model_dump()) for row in rows)
    return verdicts


def _audit(raw: Report, rulings: list[Ruling]) -> list[dict[str, Any]]:
    products = sorted({item.product_id for item in raw.outcomes})
    samples = [item for product in products for item in sorted(
        (row for row in raw.outcomes if row.product_id == product
         and row.basis == "L2" and row.result == "correct"),
        key=lambda row: row.field_key,
    )[:3]]
    identities = {(row.product_id, row.field_key) for row in samples}
    errors = sum((row.product_id, row.field_key) in identities and row.from_result == "correct"
                 for row in rulings)
    if errors >= 2:
        raise ValueError("L2 equivalent audit has at least two errors; final scoring must stop")
    return [row.model_dump() for row in samples]


def _score(
    args: argparse.Namespace, golden: list[GoldenItem], predicted: list[Prediction],
    sources: dict[str, Any], questions: dict[str, list[EquivalenceQuestion]],
    requests: dict[str, list[JudgeRequest]],
) -> dict[str, Any]:
    verdicts = _verdicts(args.run_root, sources, requests, questions, args.judge_model)
    ruling_path = args.run_root / "rulings.json"
    content = ruling_path.read_bytes() if ruling_path.exists() else None
    rulings = _Rulings.model_validate_json(content).entries if content is not None else []
    raw = evaluate_semantic(golden, predicted, verdicts)
    report = evaluate_semantic(golden, predicted, verdicts, rulings)
    samples = _audit(raw, rulings)
    l2_raw = {}
    for product in questions:
        counts = Counter(row.verdict for row in verdicts if row.product_id == product)
        l2_raw[product] = {label: counts[label]
                           for label in ("equivalent", "contradicted", "insufficient")}
    literal = evaluate(golden, predicted)
    return {
        "metric_definition": _DEFINITION, "report": report.model_dump(),
        "gates": {pack: gate(report, pack).model_dump() for pack in sorted(report.per_pack)},
        "l2_raw": l2_raw, "l2_equivalent_audit_samples": samples,
        "review_status": "Claude must confirm source review and the equivalent audit separately.",
        "literal_diagnostic": {pack: {"precision": m.precision, "recall": m.recall}
                               for pack, m in literal.per_pack.items()},
        "rulings": [row.model_dump(by_alias=True) for row in rulings],
        "provenance": {**sources, "judge_model": args.judge_model,
                       "prompt_version": EQUIVALENCE_PROMPT_VERSION,
                       "rulings_sha256": _sha(content) if content is not None else None,
                       "ruling_count": len(rulings)},
    }


def _cell(value: object) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True).replace("\\", "\\\\").replace("|", "\\|").replace(
        "\r\n", "\n",
    ).replace("\r", "\n").replace("\n", "<br>")


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_cell(v) for v in row) + " |" for row in rows)]


def _markdown(data: dict[str, Any]) -> str:
    report = data["report"]
    lines = ["# Semantic Golden evaluation", "", *[
        f"- {name}: {value}" for name, value in _DEFINITION.items()
    ], "", data["review_status"], "", "## Per pack", "",
        "Gate: precision ≥ 0.95, recall ≥ 0.90, hallucinations = 0.", ""]
    rows = []
    for pack, metrics in sorted(report["per_pack"].items()):
        counts = Counter(row["result"] for row in report["outcomes"] if row["pack_id"] == pack)
        verdict = data["gates"][pack]
        rows.append([pack, *[metrics[key] for key in ("tp", "fp", "fn", "precision", "recall")],
                     *[counts[key] for key in ("hallucination", "incomplete", "wrong_value",
                                               "misfiled", "golden_defect")],
                     verdict["passed"], ", ".join(verdict["reasons"])])
    lines += _table(["pack", "TP", "FP", "FN", "P", "R", "幻觉", "缺内容", "说错",
                     "放错字段", "Golden 缺陷", "gate", "reasons"], rows)
    lines += ["", "## Incomplete and wrong-value fields", ""]
    lines += _table(["pack", "product", "field", "result", "basis", "reason"], [
        [row[key] for key in ("pack_id", "product_id", "field_key", "result", "basis", "reason")]
        for row in report["outcomes"] if row["result"] in ("incomplete", "wrong_value")
    ])
    lines += ["", "## L2 raw decisions", ""]
    lines += _table(["product", "equivalent", "contradicted", "insufficient"], [
        [product, counts["equivalent"], counts["contradicted"], counts["insufficient"]]
        for product, counts in sorted(data["l2_raw"].items())
    ])
    lines += ["", "## L3 rulings", ""]
    lines += _table(["product", "field", "from", "to", "reason", "by", "on"], [
        [row[key] for key in ("product_id", "field_key", "from", "to", "reason", "by", "on")]
        for row in data["rulings"]
    ])
    lines += ["", "## Semantic versus literal diagnostic", "",
              "Literal numbers are diagnostic only and never enter semantic gates.", ""]
    lines += _table(["pack", "semantic P", "semantic R", "literal P", "literal R"], [
        [pack, m["precision"], m["recall"], data["literal_diagnostic"][pack]["precision"],
         data["literal_diagnostic"][pack]["recall"]]
        for pack, m in sorted(report["per_pack"].items())
    ])
    lines += ["", "## Provenance", ""]
    lines += [f"- {name}: {_cell(value)}" for name, value in data["provenance"].items()]
    return "\n".join(lines) + "\n"


def _save(args: argparse.Namespace, data: dict[str, Any]) -> None:
    destinations = [Path(f"{args.out}.json"), Path(f"{args.out}.md")]
    inputs = [*args.golden, args.candidate, args.product_map]
    inputs.extend(path for path in args.run_root.rglob("*") if path.is_file())
    for path in destinations:
        check_run_directory(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("output already exists")
        if any(path.resolve() == source.resolve() for source in inputs):
            raise ValueError("output collides with an input")
    created = []
    try:
        for path, text in zip(destinations, (_json_text(data), _markdown(data)), strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                created.append(path)
                stream.write(text)
    except (OSError, ValueError):
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "score"):
        child = commands.add_parser(name)
        child.add_argument("--golden", type=Path, action="append", required=True)
        for option in ("candidate", "product-map", "run-root"):
            child.add_argument(f"--{option}", type=Path, required=True)
        if name == "score":
            child.add_argument("--judge-model", required=True)
            child.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        golden, predicted, sources = _load(args)
        questions = semantic_questions(golden, predicted)
        requests = _requests(questions)
        if args.command == "prepare":
            _prepare(args.run_root, sources, requests)
        else:
            data = _score(args, golden, predicted, sources, questions, requests)
            _save(args, data)
            print("Generated semantic JSON and Markdown reports; review status is recorded.")
    except (ValueError, OSError, UnicodeError) as exc:
        # Validation embeds supplied records and I/O errors contain local paths.
        if isinstance(exc, ValidationError):
            detail = "invalid record shape"
        elif isinstance(exc, OSError):
            detail = f"file operation failed ({type(exc).__name__})"
        else:
            detail = str(exc)
        print(f"Semantic run failed: {detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

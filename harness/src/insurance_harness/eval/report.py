"""Offline reports: --out PREFIX creates PREFIX.json and PREFIX.md outside Git.

Exit 0 means both reports were generated, regardless of gate verdict; exit 2
means invalid input/output or an I/O failure. Existing files are never replaced.
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

from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.evaluator import Metrics, evaluate, gate
from insurance_harness.eval.golden import GoldenItem

_SCOPE = (
    "Offline deterministic comparison of the supplied archived candidate against Golden. "
    "This does not certify production model quality or evidence accuracy; no model is called. "
    "Candidate metadata is supplied, not independently verified."
)
_DEFINITIONS = {
    "metric_id": "golden.value_comparison.v1",
    "precision": "TP / (TP + FP)",
    "recall": "TP / (TP + FN)",
    "undefined": "A zero denominator produces null, never 1.0, and fails the quality gate.",
    "scoring": (
        "Correct present: TP; wrong present: FP + FN; missed present: FN; "
        "present against unknown: hallucination FP; present against absent: contradiction FP. "
        "Non-present matches and disagreements are outside P/R denominators. "
        "Predictions outside Golden are unscored. Components must all match; forbidden terms veto."
    ),
    "missed": "Golden present with missing or non-present prediction.",
    "missing_predictions": "Golden identities with no prediction record, regardless of state.",
    "per_field": "Aggregated by field_key; scored_items retain pack/product/field identity.",
}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _object(content: bytes) -> dict[str, Any]:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _supplied_metadata(candidate: dict[str, Any]) -> dict[str, dict[str, str]]:
    # An allowlist avoids publishing arbitrary execution config, raw output or credentials.
    metadata: dict[str, dict[str, str]] = {}
    for stage in ("compile_result", "model_compile_result"):
        result = candidate.get(stage)
        execution = result.get("execution") if isinstance(result, dict) else None
        if isinstance(execution, dict):
            selected = {
                key: value for key in ("implementation", "model", "model_id", "run_id")
                if isinstance(value := execution.get(key), str) and _TOKEN.fullmatch(value)
            }
            if selected:
                metadata[stage] = selected
    return metadata


def _manifest(path: Path, golden_sha: str, golden_name: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    content = path.read_bytes()
    data = _object(content)
    verified = False
    if "files" in data:
        files = data["files"]
        if not isinstance(files, dict):
            raise ValueError("invalid manifest files")
        if golden_name in files:
            if files[golden_name] != golden_sha:
                raise ValueError("manifest Golden digest does not match")
            verified = True
    version = data.get("dataset_version")
    return {
        "sha256": _digest(content), "golden_digest_verified": verified,
        "supplied_dataset_version": (
            version if isinstance(version, str) and _TOKEN.fullmatch(version) else None
        ),
    }


def _report(inputs: dict[str, Path]) -> dict[str, Any]:
    content = {name: path.read_bytes() for name, path in inputs.items()}
    golden = [
        GoldenItem.model_validate_json(line)
        for line in content["golden"].decode("utf-8").splitlines() if line.strip()
    ]
    if not golden:
        raise ValueError("Golden must not be empty")
    candidate = _object(content["candidate"])
    products = _object(content["product-map"])
    if not all(isinstance(value, str) for value in products.values()):
        raise ValueError("product IDs must be strings")
    predictions = predictions_from_candidate(candidate, products)
    report = evaluate(golden, predictions)
    scored = []
    for outcome in report.outcomes:
        if outcome.result == "unscored":
            continue
        row = outcome.model_dump(mode="json")
        metrics = Metrics(tp=outcome.tp, fp=outcome.fp, fn=outcome.fn)
        row.update(precision=metrics.precision, recall=metrics.recall)
        scored.append(row)
    counts = Counter(outcome.result for outcome in report.outcomes)
    provenance: dict[str, Any] = {
        name: {"sha256": _digest(raw)} for name, raw in content.items()
    }
    provenance["manifest"] = _manifest(
        inputs["golden"].parent / "manifest.json",
        provenance["golden"]["sha256"], inputs["golden"].name,
    )
    provenance["supplied_candidate_metadata"] = _supplied_metadata(candidate)
    provenance["model_identity_status"] = "supplied metadata only; no model identity inferred"
    return {
        "scope": _SCOPE, "metric_definition": _DEFINITIONS, "provenance": provenance,
        "thresholds": {"min_precision": 0.95, "min_recall": 0.90, "max_hallucinations": 0},
        "golden_items": len(golden), "prediction_items": len(predictions),
        "report": report.model_dump(mode="json"), "scored_items": scored,
        "counts": {
            "missed": counts["missed"], "mismatch": counts["mismatch"],
            "state_mismatch": counts["state_mismatch"],
            **{name: getattr(report, name) for name in (
                "hallucinations", "contradictions", "correct_non_present",
                "missing_predictions", "unscored_predictions",
            )},
        },
        "gates": {pack: gate(report, pack).model_dump() for pack in sorted(report.per_pack)},
    }


def _cell(value: object) -> str:
    if value is None:
        return "—"
    text = html.escape(str(value), quote=True).replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows),
    ]


def _markdown(data: dict[str, Any]) -> str:
    lines = ["# Golden evaluation", "", _SCOPE, "", "## Reproducibility", ""]
    for name in ("golden", "candidate", "product-map"):
        lines.append(f"- {name} SHA256: `{data['provenance'][name]['sha256']}`")
    manifest = data["provenance"]["manifest"]
    if manifest is not None:
        lines.extend([
            f"- manifest SHA256: `{manifest['sha256']}`",
            f"- supplied dataset version: {_cell(manifest['supplied_dataset_version'])}",
            f"- Golden digest verified against manifest: {manifest['golden_digest_verified']}",
        ])
    for stage, metadata in data["provenance"]["supplied_candidate_metadata"].items():
        for name, value in metadata.items():
            lines.append(f"- supplied {stage}.{name}: {_cell(value)}")
    lines.extend(["", "## Metric definitions", ""])
    lines.extend(f"- {name}: {value}" for name, value in _DEFINITIONS.items())
    lines.extend(["", "## Counts", ""])
    lines.extend(f"- {name}: {value}" for name, value in data["counts"].items())
    lines.extend([
        "", "## Per pack", "", "Gate: precision ≥ 0.95, recall ≥ 0.90, hallucinations = 0.", "",
    ])
    pack_rows = []
    for pack, metrics in sorted(data["report"]["per_pack"].items()):
        verdict = data["gates"][pack]
        pack_rows.append([
            pack, metrics["tp"], metrics["fp"], metrics["fn"],
            metrics["precision"], metrics["recall"], verdict["passed"],
            ", ".join(verdict["reasons"]) or "—",
        ])
    lines.extend(_table(
        ["pack", "TP", "FP", "FN", "precision", "recall", "gate", "reasons"], pack_rows,
    ))
    lines.extend(["", "## Golden item results", "", "Only Golden identities appear below.", ""])
    keys = [
        "pack_id", "product_id", "field_key", "golden_state", "predicted_state", "result",
        "tp", "fp", "fn", "precision", "recall",
    ]
    lines.extend(_table(keys, [[row[key] for key in keys] for row in data["scored_items"]]))
    return "\n".join(lines) + "\n"


def _check_destinations(paths: list[Path], inputs: list[Path]) -> None:
    for path in paths:
        resolved = path.resolve()
        if path.exists() or path.is_symlink():
            raise ValueError("output already exists")
        if any(resolved == source.resolve() for source in inputs):
            raise ValueError("output collides with input")
        if any((parent / ".git").exists() for parent in resolved.parents):
            raise ValueError("reports must be outside a Git repository")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("golden", "candidate", "product-map", "out"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = {"golden": args.golden, "candidate": args.candidate, "product-map": args.product_map}
    paths = [Path(f"{args.out}.json"), Path(f"{args.out}.md")]
    created: list[Path] = []
    try:
        _check_destinations(paths, [*inputs.values(), args.golden.parent / "manifest.json"])
        data = _report(inputs)
        outputs = [
            json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", _markdown(data),
        ]
        for path, text in zip(paths, outputs, strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also prevents a raced symlink from replacing an input.
            with path.open("x", encoding="utf-8") as stream:
                created.append(path)
                stream.write(text)
    except (ValueError, OSError) as exc:
        for path in created:
            path.unlink(missing_ok=True)
        # Validation exceptions can contain raw model input or private filesystem paths.
        print(
            f"Report failed: invalid input/output or I/O failure ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 2
    print("Generated JSON and Markdown reports; gate verdicts are recorded in the reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

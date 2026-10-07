"""Prepare blind judge files, then ingest answers; no model or network calls.

prepare --product ID --run-root DIR [--pack PACK] [--source-dir DIR]
ingest --product ID --run-root DIR --judge-model MODEL [--calibrate]
Non-calibration products require a passing calibration in the same run root.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.equivalence import (
    EQUIVALENCE_PROMPT_VERSION,
    Adjudication,
    EquivalenceQuestion,
    EquivalenceReport,
    apply_adjudications,
    build_equivalence_requests,
    compare_equivalence,
)
from insurance_harness.eval.golden import GoldenItem
from insurance_harness.eval.judge import PROMPT_VERSION, JudgeAnnotator, JudgeRequest, calibrate
from insurance_harness.eval.judge_files import FileJudgeClient, check_run_directory, write_requests
from insurance_harness.eval.normalize import values_equal
from insurance_harness.eval.pdf_text import PageText, read_pdf

_RULES = '''# 保险条款离线评委

1. 只读当前目录下的文件；不打开当前目录以外的任何路径，不联网，不运行抽取或比对程序。
2. 逐个处理 requests/ 里的题目：system_lines 是规则，user_lines 是题目。
   把答案写成严格 JSON，存为 responses/ 下的同名文件。已有答案的题目跳过。
3. 可以用 grep 等只读命令查找原文和核对引文；不得用脚本批量生成答案。
4. 引文必须从所在页原文逐字复制，核对它确实在你声明的 [page N] 之下；没有依据就答 unknown。
5. 不修改 requests/、run.json 与本文件。
'''
_CATALOG = "internal/handler/schema_pack_catalog_830_g3.generated.json"
_EQUIVALENCE_RULES = '''# 语义等价独立评委

只读本等价题根目录及其各产品子目录，不打开标注目录、PDF 或其他路径，不联网。
本会话可逐个处理各产品子目录，不重新抽取材料，也不兼任标注评委。
按各产品 requests/ 题目中的 system_lines 规则比较 user_lines 中两种表述，
逐字段输出判定与理由到同一产品 responses/ 的同名 JSON 文件。已有答案跳过。
如实报告矛盾与遗漏，不为通过校准放宽判断。
不修改 requests/、run.json 或本文件，不用脚本批量生成答案。
'''


class _Run(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    product_id: str
    pack_id: str
    field_keys: list[str] = Field(min_length=1)
    batch_size: int = Field(ge=1)
    prompt_version: str
    source_directory: str
    source_sha256: dict[str, str]
    request_sha256: list[str] = Field(min_length=1, max_length=3)


class _Adjudications(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    entries: list[Adjudication]


class _PrepareClient:
    @property
    def model_id(self) -> str:
        return "unused"

    def complete(self, request: JudgeRequest) -> str:
        raise RuntimeError("prepare must never call a judge")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _write(path: Path, data: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def _product(product_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", product_id):
        raise ValueError("invalid product identifier")


def _calibration(root: Path, model_id: str | None = None) -> None:
    path = root / "calibration.json"
    if not path.exists():
        raise ValueError("passing calibration required before generation")
    report = _json(path)
    if report.get("passed") is not True or report.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("passing calibration for this prompt version required")
    if model_id is not None and report.get("model_id") != model_id:
        raise ValueError("judge model differs from calibration")


def _sources(repo: Path, product_id: str, directory: Path | None) -> Path:
    if directory is None:
        matches = [
            path.parent for path in (repo / "dataset/shouxian_product").glob("*/product_meta.json")
            if _json(path).get("planCode") == product_id
        ]
        if len(matches) != 1:
            raise ValueError("product source directory ambiguous or missing; supply --source-dir")
        directory = matches[0]
    directory = directory.resolve()
    directory.relative_to((repo / "dataset/shouxian_product").resolve())
    return directory


def _pages(directory: Path) -> list[PageText]:
    paths = sorted(directory.glob("*.pdf"))
    if not paths:
        raise ValueError("no source PDFs")
    pages = [page for path in paths for page in read_pdf(path)]
    if not any(page.text.strip() for page in pages):
        raise ValueError("no source page text")
    return pages


def _pack(repo: Path, product_id: str, pack_id: str | None) -> str:
    if pack_id is not None:
        return pack_id
    manifest = _json(repo / "dataset/golden/v1/manifest.json")
    metadata = manifest if manifest.get("product_id") == product_id else (
        manifest.get("products", {}).get(product_id, {})
    )
    value = metadata.get("pack_id")
    if not isinstance(value, str):
        raise ValueError("pack is not declared; supply --pack")
    return value


def prepare(
    repo: Path, product_id: str, run_root: Path, *, pack_id: str | None = None,
    source_dir: Path | None = None, batch_size: int = 25,
) -> dict[str, Any]:
    """Write one immutable question set outside Git, only after calibration if needed."""
    _product(product_id)
    run_dir = run_root / product_id
    check_run_directory(run_dir)
    if run_dir.exists():
        raise FileExistsError("product run directory already exists")
    # The approved calibration reference is intentionally fixed by the slice protocol.
    if product_id != "596":
        _calibration(run_root)
    catalog = load_catalog(repo / _CATALOG)
    pack_id = _pack(repo, product_id, pack_id)
    fields = list(catalog.source_extractable_fields(pack_id))
    directory = _sources(repo, product_id, source_dir)
    pages = _pages(directory)
    builder = JudgeAnnotator(_PrepareClient(), catalog, max_calls=3, batch_size=batch_size)
    requests = builder.build_requests(product_id, pack_id, fields, pages)
    run = _Run(
        product_id=product_id, pack_id=pack_id, field_keys=fields, batch_size=batch_size,
        prompt_version=PROMPT_VERSION,
        source_directory=directory.relative_to(repo.resolve()).as_posix(),
        source_sha256={page.document: page.document_sha256 for page in pages},
        request_sha256=[request.sha256 for request in requests],
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    write_requests(requests, run_dir)
    with (run_dir / "AGENTS.md").open("x", encoding="utf-8") as stream:
        stream.write(_RULES)
    _write(run_dir / "run.json", run.model_dump())
    return run.model_dump()


def _save_golden(
    repo: Path, product_id: str, items: list[GoldenItem], metadata: dict[str, Any],
) -> None:
    directory = repo / "dataset/golden/v1"
    path = directory / f"{product_id}.jsonl"
    manifest_path = directory / "manifest.json"
    # Serialize manifest updates and never overwrite an existing product's annotations.
    lock = directory / ".manifest.lock"
    with lock.open("x", encoding="utf-8"):
        created = False
        pending = directory / ".manifest.pending"
        try:
            manifest = _json(manifest_path)
            payload = "".join(item.model_dump_json() + "\n" for item in items)
            with path.open("x", encoding="utf-8") as stream:
                created = True
                stream.write(payload)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            manifest.setdefault("files", {})[path.name] = digest
            manifest.setdefault("products", {})[product_id] = metadata
            _write(pending, manifest)
            pending.replace(manifest_path)
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        finally:
            pending.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)


def _equivalence(
    repo: Path, product_id: str, root: Path, *, model_id: str,
    judged: list[GoldenItem], reference: list[GoldenItem],
) -> EquivalenceReport | None:
    """Return None only when new L2 questions await an independent session.

    Bind both inputs before publishing questions. On replay verify this even if
    changed answers would now pass L1, so they cannot bypass the pending review.
    """
    by_identity = {item.identity: item for item in judged}
    questions = []
    literal = 0
    for ref in reference:
        item = by_identity.get(ref.identity)
        if item is None or ref.state != "present" or item.state != "present":
            continue
        if values_equal(ref.value, item.value):
            literal += 1
        else:
            assert ref.value is not None
            questions.append(EquivalenceQuestion(
                field_key=ref.field_key, reference=ref.value, judged=item.value,
                components=item.components,
            ))
    shared_directory = root / "equivalence"
    directory = shared_directory / product_id
    stored = _json(directory / "run.json") if directory.exists() else None
    prompt_version = EQUIVALENCE_PROMPT_VERSION
    if stored is not None:
        version = stored.get("prompt_version")
        if not isinstance(version, str):
            raise ValueError("equivalence prompt version missing or invalid")
        prompt_version = version
    requests = build_equivalence_requests(
        questions, product_id=product_id, batch_size=60, prompt_version=prompt_version,
    )
    metadata = {
        "product_id": product_id, "model_id": model_id, "batch_size": 60,
        "prompt_version": prompt_version,
        "request_sha256": [request.sha256 for request in requests],
        "reference_sha256": hashlib.sha256(
            (repo / f"dataset/golden/v1/{product_id}.jsonl").read_bytes(),
        ).hexdigest(),
        "annotation_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / product_id / "responses").glob("*.json"))
        },
    }
    if stored is not None:
        if stored != metadata:
            raise ValueError("equivalence inputs changed since prepare")
    elif questions:
        check_run_directory(shared_directory)
        shared_directory.mkdir(parents=True, exist_ok=True)
        rules = shared_directory / "AGENTS.md"
        if rules.exists():
            if rules.read_text(encoding="utf-8") != _EQUIVALENCE_RULES:
                raise ValueError("shared equivalence rules changed")
        else:
            with rules.open("x", encoding="utf-8") as stream:
                stream.write(_EQUIVALENCE_RULES)
        write_requests(requests, directory)
        _write(directory / "run.json", metadata)
        return None
    client = FileJudgeClient(directory, model_id=model_id)
    report = compare_equivalence(
        client, questions, max_calls=2, batch_size=60, prompt_version=prompt_version,
    )
    if client.unconsumed():
        raise ValueError("unconsumed equivalence request files")
    adjudication_path = shared_directory / "adjudications.json"
    if adjudication_path.exists():
        adjudications = _Adjudications.model_validate_json(adjudication_path.read_text("utf-8"))
        report = apply_adjudications(report, adjudications.entries)
    report.compared += literal
    report.equivalent += literal
    report.rate = report.equivalent / report.compared if report.compared else None
    return report


def ingest(
    repo: Path, product_id: str, run_root: Path, *, judge_model: str, calibrate_only: bool = False,
) -> dict[str, Any]:
    """Rebuild prompts from original PDF bytes and fail closed before publishing records."""
    _product(product_id)
    if calibrate_only != (product_id == "596"):
        raise ValueError("596 requires --calibrate; --calibrate is only allowed for 596")
    run_dir = run_root / product_id
    check_run_directory(run_dir)
    run = _Run.model_validate_json((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.product_id != product_id or run.prompt_version != PROMPT_VERSION:
        raise ValueError("run identity or prompt version changed")
    if not calibrate_only:
        _calibration(run_root, judge_model)
    catalog = load_catalog(repo / _CATALOG)
    if run.field_keys != list(catalog.source_extractable_fields(run.pack_id)):
        raise ValueError("run fields changed")
    directory = _sources(repo, product_id, repo / run.source_directory)
    pages = _pages(directory)
    if {page.document: page.document_sha256 for page in pages} != run.source_sha256:
        raise ValueError("source PDF bytes changed")
    client = FileJudgeClient(run_dir, model_id=judge_model)
    annotator = JudgeAnnotator(client, catalog, max_calls=3, batch_size=run.batch_size)
    requests = annotator.build_requests(product_id, run.pack_id, run.field_keys, pages)
    if [request.sha256 for request in requests] != run.request_sha256:
        raise ValueError("run request hashes changed")
    result = annotator.annotate(product_id, run.pack_id, run.field_keys, pages)
    if client.unconsumed():
        raise ValueError("unconsumed request files")
    summary = {
        "product_id": product_id, "pack_id": run.pack_id, "model_id": result.model_id,
        "judging_method": "codex-session-file-exchange", "question_count": result.calls,
        "items": len(result.items), "tri_state": dict(Counter(item.state for item in result.items)),
        "evidence_not_verified": len(result.rejected), "rejected": result.rejected,
        "source_sha256": run.source_sha256, "prompt_version": run.prompt_version,
        "request_sha256": run.request_sha256,
    }
    if calibrate_only:
        reference = [
            GoldenItem.model_validate_json(line)
            for line in (repo / "dataset/golden/v1/596.jsonl").read_text().splitlines()
            if line.strip()
        ]
        report = calibrate(result.items, reference)
        state_rate = report.state_agreement / report.compared if report.compared else None
        value_rate = (
            report.present_value_agreement / report.both_present if report.both_present else None
        )
        rejected_rate = len(result.rejected) / len(run.field_keys)
        summary.update(report.model_dump())
        equivalence = _equivalence(
            repo, product_id, run_root, model_id=judge_model,
            judged=result.items, reference=reference,
        )
        summary.update(
            state_agreement_rate=state_rate, present_value_agreement_rate=value_rate,
            literal_agreement_rate=(
                report.literal_agreement / report.both_present if report.both_present else None
            ),
            evidence_not_verified_rate=rejected_rate,
            equivalence=equivalence.model_dump(by_alias=True) if equivalence is not None else None,
            passed=(state_rate is not None and state_rate >= 0.9 and equivalence is not None
                    and equivalence.passes() is True and rejected_rate <= 0.1),
            status="complete" if equivalence is not None else "awaiting_equivalence",
        )
        if equivalence is None:
            summary["equivalence_directory"] = f"equivalence/{product_id}"
            _write(run_root / "calibration.pending.json", summary)
        else:
            _write(run_root / "calibration.json", summary)
    else:
        if not result.items:
            raise ValueError("no verified Golden items")
        _save_golden(repo, product_id, result.items, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "ingest"):
        child = commands.add_parser(command)
        child.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
        child.add_argument("--product", required=True)
        child.add_argument("--run-root", type=Path, required=True)
        if command == "prepare":
            child.add_argument("--pack")
            child.add_argument("--source-dir", type=Path)
            child.add_argument("--batch-size", type=int, default=25)
        else:
            child.add_argument("--judge-model", required=True)
            child.add_argument("--calibrate", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(
                args.repo, args.product, args.run_root, pack_id=args.pack,
                source_dir=args.source_dir, batch_size=args.batch_size,
            )
        else:
            result = ingest(
                args.repo, args.product, args.run_root, judge_model=args.judge_model,
                calibrate_only=args.calibrate,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    except (ValueError, OSError) as exc:
        # Do not echo raw model input, source text or private paths from validation errors.
        print(f"Annotation failed: invalid input/output ({type(exc).__name__}).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

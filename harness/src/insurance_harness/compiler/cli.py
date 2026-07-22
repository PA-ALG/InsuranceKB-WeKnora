"""抽取管道 CLI（004 T8；006 T6/T7 增补）。

用法：
    # 生产抽取：数据库绑定的 WeKnora knowledge IDs（真实网关配置读 harness/.env）
    uv run python -m insurance_harness.compiler.cli extract --source weknora \
        --space-id <space_id> --parser-fingerprint <parser_version> \
        --knowledge-id <knowledge_id> --product-id <product_id> \
        --product-name <product_name> --run-dir out/run1

    # 离线目录/Golden 回放（唯一接受 product_dir 的抽取命令）
    uv run python -m insurance_harness.compiler.cli extract-replay <product_dir> \
        --replay-identity <fixture_identity> --parser-fingerprint <parser_version> \
        --run-dir out/replay1

    # 应用主会话 Claude 批处理后的裁决结果（judge_mode=claude-session）
    uv run python -m insurance_harness.compiler.cli apply-judgements <run_dir> <judgements.jsonl>

    # 模板归纳（零模型调用；006 F2）：族内 ≥2 产品金标 → 模板草案 + 归纳报告
    uv run python -m insurance_harness.compiler.cli induce-template --doc 费率表.pdf \
        --products "产品A,产品B" --golden-root dataset/goldenset/wip-gs-v0.1 \
        --dataset-root dataset/shouxian_product --out-dir out/templates

    # 可喂性评分（006 F4；默认 dry-run，--apply 才写隔离文件）
    uv run python -m insurance_harness.compiler.cli feedability <product_dir> \
        [--quarantine-dir out/.rejections --apply]
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Literal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..adapters.weknora import WeKnoraClient
from ..config import HarnessSettings
from ..db import make_engine
from ..db.scope import load_scope
from ..goldenset.pdf import extract_pages
from ..model_policy import ModelIdentity, StrictAdmissionRequestBinding
from ..model_policy.composition import (
    _bind_verified_production_model_composition,
    _build_production_model_composition,
)
from ..schemas import load_schema_registry
from ..sources import (
    DirectoryDocumentSource,
    DirectorySourceRequest,
    WeKnoraDocumentSource,
    WeKnoraSourceRequest,
)
from .experiment import AssignmentPolicy
from .feedability import render_feedability, score_feedability, write_quarantine
from .judge import JudgeDispatcher, read_judgements
from .llm import (
    ModelClient,
    OpenAICompatClient,
    ProductionEntrypointDenied,
    ReplayClient,
)
from .models import PredRecord
from .pipeline import ExtractionPipeline, PipelineConfig, _compiler_schema_hash
from .sections import family_fingerprint, split_sections
from .templates import (
    ProductDocInput,
    dump_template_yaml,
    induce_template,
    load_template_registry,
    render_induction_report,
    select_table_provider,
    write_polish_queue,
)
from .templates.induce import load_wip_goldens

_DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "docs/insurance-kb/schema-baseline"


async def _aclose_if_supported(resource: object) -> None:
    aclose = getattr(resource, "aclose", None)
    if callable(aclose):
        await aclose()


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _nonnegative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return value


def _pipeline_config_from_args(
    args: argparse.Namespace,
    *,
    judge_mode: str,
    model_profile: Literal["disabled", "production", "offline-eval", "replay"] = (
        "disabled"
    ),
) -> PipelineConfig:
    experiment_id = getattr(args, "experiment_id", None)
    experiment_seed = getattr(args, "experiment_seed", 0)
    gapfill_max_calls = getattr(args, "gapfill_max_calls", None)
    if experiment_id is not None and not experiment_id.strip():
        raise SystemExit("--experiment-id must not be blank")
    if experiment_id is None and experiment_seed != 0:
        raise SystemExit("--experiment-seed requires --experiment-id")
    assignment = AssignmentPolicy(
        enabled=experiment_id is not None,
        experiment_id=experiment_id or "",
        seed=experiment_seed,
    )
    return PipelineConfig(
        judge_mode=judge_mode,
        concurrency=args.concurrency,
        gapfill_max_calls=gapfill_max_calls,
        assignment=assignment,
        model_profile=model_profile,
    )


def _add_recall_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--concurrency", type=_positive_int, default=6)
    parser.add_argument(
        "--gapfill-max-calls",
        type=_nonnegative_int,
        default=None,
        help="run 级补漏真实出站调用硬上限（0=禁止，缺省=不限）",
    )
    parser.add_argument(
        "--experiment-id",
        default=None,
        help="启用 020 D4 A/B 分桶并指定稳定实验身份",
    )
    parser.add_argument(
        "--experiment-seed",
        type=_nonnegative_int,
        default=0,
        help="实验确定性分桶 seed（非零时必须同时给 --experiment-id）",
    )


def load_settings(*, require_weknora: bool = False) -> HarnessSettings:
    """加载配置；仅离线子命令可在缺 WeKnora 配置时使用占位值。"""
    if require_weknora:
        return HarnessSettings()  # type: ignore[call-arg]  # required env configuration
    try:
        return HarnessSettings()  # type: ignore[call-arg]  # weknora_* 经环境变量注入
    except ValidationError:
        return HarnessSettings(weknora_base_url="http://unused.local", weknora_api_key="unused")


def build_client(
    settings: HarnessSettings, replay_dir: Path | None, model_override: str | None = None
) -> tuple[ModelClient, str]:
    if replay_dir is not None:
        return ReplayClient(replay_dir), "replay"
    model = model_override or settings.llm_model_weak
    if not (settings.llm_base_url and settings.llm_api_key and model):
        raise SystemExit(
            "缺少弱模型网关配置（HARNESS_LLM_BASE_URL/API_KEY/MODEL_WEAK，见 harness/.env）；"
            "或改用 --replay-dir 录制回放"
        )
    client = OpenAICompatClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=model,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
    )
    return client, model


def _strict_production_request(
    settings: HarnessSettings,
) -> StrictAdmissionRequestBinding:
    """Build the independent expected request; never copy verifier-returned actuals."""

    payload = {
        field: getattr(settings, f"production_{field}")
        for field in StrictAdmissionRequestBinding.model_fields
    }
    return StrictAdmissionRequestBinding.model_validate(payload)


def _production_identity(
    settings: HarnessSettings,
    *,
    role: Literal["extract", "gap", "verify", "consensus"],
) -> ModelIdentity:
    """Bind every compiler role to the single frozen weak deployment."""

    return ModelIdentity.model_validate(
        {
            "provider": settings.production_model_provider,
            "deployment_id": settings.production_model_deployment_id,
            "family": settings.production_model_family,
            "role": role,
            "policy_version": settings.production_model_policy_version,
        }
    )


def _build_production_compiler_client(
    settings: HarnessSettings,
    *,
    schema_hash: str | None,
    space_id: str | None,
) -> ModelClient:
    """Verify canonical admission before any provider adapter can be constructed.

    OpenSpec 028 owns the reviewed provider adapter. Until that adapter is present,
    a successfully verified admission still fails closed instead of using the raw
    OpenAI-compatible transport primitive.
    """

    if settings.model_profile != "production":
        raise ProductionEntrypointDenied("invalid_model_profile")
    request = _strict_production_request(settings)
    if (
        schema_hash is None
        or schema_hash != request.expected_schema_hash
        or space_id is None
        or space_id != request.expected_space_id
    ):
        raise ProductionEntrypointDenied("invalid_production_client")
    identities = tuple(
        _production_identity(settings, role=role)
        for role in ("extract", "gap", "verify", "consensus")
    )
    verification_composition = _build_production_model_composition()
    verified = verification_composition.verify(request)
    _bind_verified_production_model_composition(
        verified,
        expected_identities=identities,
        expected_model_plan_hash=request.expected_model_plan_hash,
    )
    raise ProductionEntrypointDenied("canonical_adapter_unavailable")


async def _cmd_extract(args: argparse.Namespace) -> int:
    async with AsyncExitStack() as resources:
        settings = load_settings(require_weknora=True)
        if settings.model_profile != "production":
            raise ProductionEntrypointDenied("invalid_model_profile")
        if args.space_id != settings.production_expected_space_id:
            raise ProductionEntrypointDenied("invalid_production_client")
        registry = load_schema_registry(args.schema_dir)
        client = _build_production_compiler_client(
            settings,
            schema_hash=_compiler_schema_hash(registry),
            space_id=args.space_id,
        )
        resources.push_async_callback(_aclose_if_supported, client)
        model_id = settings.production_model_deployment_id
        if model_id is None:
            raise ProductionEntrypointDenied("invalid_production_client")
        # 006 F3：--templates-dir 提供且非空时启用 fast path；否则 004 行为不变
        template_registry = load_template_registry(args.templates_dir)
        db_url = args.db_url or settings.db_url
        if not db_url:
            raise SystemExit("生产抽取需要 --db-url 或 HARNESS_DB_URL")
        engine = make_engine(db_url)
        resources.callback(engine.dispose)
        source_client = WeKnoraClient(settings)
        resources.push_async_callback(_aclose_if_supported, source_client)
        with Session(engine) as session:
            scope = load_scope(session, args.space_id)
        source = WeKnoraDocumentSource(
            client=source_client,
            scope=scope,
            parser_fingerprint=args.parser_fingerprint,
            source_max_documents_per_batch=settings.source_max_documents_per_batch,
            source_max_batch_bytes=settings.source_max_batch_bytes,
            source_max_batch_pages=settings.source_max_batch_pages,
            source_max_batch_chunks=settings.source_max_batch_chunks,
        )
        pipeline = ExtractionPipeline(
            client=client,
            registry=registry,
            model_id=model_id,
            source=source,
            config=_pipeline_config_from_args(
                args,
                judge_mode="guarded",
                model_profile="production",
            ),
            template_registry=template_registry if template_registry.templates else None,
            table_provider=select_table_provider(settings.table_provider),
            scope=scope,
        )
        result = await pipeline.run(
            product_dir=None,
            product_id=args.product_id,
            product_name=args.product_name,
            run_dir=args.run_dir,
            source_request=WeKnoraSourceRequest(
                knowledge_ids=tuple(args.knowledge_ids)
            ),
            line_key=args.line_key,
            resume=args.resume,
            thread_id=settings.production_expected_run_id,
        )
    m = result.manifest
    print(
        f"run={m.run_id} model={m.model_id} 字段={len(result.records)} "
        f"调用={m.stats.calls} est_tokens={m.stats.est_tokens} "
        f"死信={len(m.dead_letters)} pending_judge={m.pending_judge_count} "
        f"→ {result.pred_path}"
    )
    return 0


async def _cmd_extract_replay(args: argparse.Namespace) -> int:
    async with AsyncExitStack() as resources:
        settings = load_settings()
        profile = settings.model_profile
        if profile not in {"offline-eval", "replay"}:
            raise ProductionEntrypointDenied("invalid_model_profile")
        if profile == "replay" and args.replay_dir is None:
            raise ProductionEntrypointDenied("replay_fixture_required")
        if profile == "offline-eval" and args.replay_dir is not None:
            raise ProductionEntrypointDenied("invalid_model_profile")
        client, model_id = build_client(settings, args.replay_dir, args.model)
        resources.push_async_callback(_aclose_if_supported, client)
        registry = load_schema_registry(args.schema_dir)
        if profile == "offline-eval" and settings.judge_mode == "gateway":
            fallback = settings.llm_model_judge_fallback
            if not (settings.llm_base_url and settings.llm_api_key and fallback):
                raise SystemExit(
                    "judge_mode=gateway 需要 HARNESS_LLM_MODEL_JUDGE_FALLBACK 配置"
                )
            judge_client = OpenAICompatClient(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=fallback,
                max_tokens=settings.llm_max_tokens,
                timeout_s=settings.llm_timeout_s,
            )
            resources.push_async_callback(_aclose_if_supported, judge_client)
            judge = JudgeDispatcher(mode="gateway", client=judge_client)
        else:
            judge = JudgeDispatcher(mode="claude-session")
        template_registry = load_template_registry(args.templates_dir)
        source = DirectoryDocumentSource(
            replay_identity=args.replay_identity,
            parser_fingerprint=args.parser_fingerprint,
        )
        pipeline = ExtractionPipeline(
            client=client,
            registry=registry,
            model_id=model_id,
            source=source,
            config=_pipeline_config_from_args(
                args,
                judge_mode=judge.mode,
                model_profile=profile,
            ),
            judge=judge,
            template_registry=template_registry if template_registry.templates else None,
            table_provider=select_table_provider(settings.table_provider),
        )
        result = await pipeline.run(
            product_dir=args.product_dir,
            run_dir=args.run_dir,
            source_request=DirectorySourceRequest(product_dir=args.product_dir),
            line_key=args.line_key,
            resume=args.resume,
        )
    m = result.manifest
    print(
        f"run={m.run_id} model={m.model_id} 字段={len(result.records)} "
        f"调用={m.stats.calls} est_tokens={m.stats.est_tokens} "
        f"死信={len(m.dead_letters)} pending_judge={m.pending_judge_count} "
        f"→ {result.pred_path}"
    )
    return 0


def _cmd_apply_judgements(args: argparse.Namespace) -> int:
    settings = load_settings()
    if settings.model_profile not in {"manual", "offline-eval"}:
        raise ProductionEntrypointDenied("invalid_model_profile")
    pred_path = args.run_dir / "pred.jsonl"
    records = [
        PredRecord.model_validate_json(line)
        for line in pred_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    judgements = {(j.product_id, j.field_id): j for j in read_judgements(args.judgements)}
    applied = 0
    for i, rec in enumerate(records):
        j = judgements.get((rec.product_id, rec.field_id))
        if j is None:
            continue
        records[i] = rec.model_copy(
            update={
                "value": j.value,
                "tri_state": j.tri_state,
                "evidence": j.evidence,
                "confidence": j.confidence,
                "pending_judge": False,
                "reasoning": j.reasoning,
            }
        )
        applied += 1
    pred_path.write_text(
        "".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8"
    )
    print(f"已应用裁决 {applied}/{len(judgements)} 条 → {pred_path}")
    return 0


def _cmd_induce_template(args: argparse.Namespace) -> int:
    """模板归纳 CLI（006 F2；确定性零模型）：产出草案 YAML + 归纳报告 + 润色队列。"""
    products = [p.strip() for p in args.products.split(",") if p.strip()]
    provider = select_table_provider(load_settings().table_provider)
    inputs: list[ProductDocInput] = []
    family_ids: set[str] = set()
    for product in products:
        pdf_path = args.dataset_root / product / args.doc
        if not pdf_path.exists():
            raise SystemExit(f"缺原文档：{pdf_path}")
        pages = extract_pages(pdf_path)
        family_ids.add(family_fingerprint(split_sections(pages)))
        golden_path = args.golden_root / product / "golden.jsonl"
        if not golden_path.exists():
            raise SystemExit(f"缺金标：{golden_path}")
        inputs.append(
            ProductDocInput(
                product_name=product,
                pages=pages,
                goldens=load_wip_goldens(golden_path, product),
                pdf_path=pdf_path,
            )
        )
    if len(family_ids) != 1:
        raise SystemExit(
            f"归纳产品的 {args.doc} 不同族（{sorted(family_ids)}）——模板必须按族归纳（F2.1）"
        )
    result = induce_template(
        args.doc,
        inputs,
        family_id=family_ids.pop(),
        provider=provider,
        golden_release=args.golden_root.name,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = args.out_dir / f"{result.template.template_id}.yaml"
    yaml_path.write_text(dump_template_yaml(result.template), encoding="utf-8")
    report_path = args.out_dir / f"{result.template.template_id}.report.md"
    report_path.write_text(render_induction_report(result), encoding="utf-8")
    queue_path = write_polish_queue(
        args.out_dir / f"{result.template.template_id}.polish-queue.jsonl", result
    )
    published = [r for r in result.report if r.published]
    print(
        f"模板草案 {result.template.template_id}：发布字段 {len(published)}/"
        f"{len(result.report)} → {yaml_path}（报告 {report_path.name}，"
        f"润色队列 {queue_path.name}）"
    )
    return 0


def _cmd_feedability(args: argparse.Namespace) -> int:
    """可喂性评分 CLI（006 F4）：默认 dry-run 打印评分，--apply 写隔离文件。"""
    reports = []
    for pdf_path in sorted(args.product_dir.glob("*.pdf")):
        pages = extract_pages(pdf_path)
        reports.append(score_feedability(pdf_path.name, pages, threshold=args.threshold))
    print(render_feedability(reports))
    to_quarantine = [r for r in reports if r.quarantine_suggested]
    if not to_quarantine:
        return 0
    if not args.apply:
        print(f"dry-run：{len(to_quarantine)} 份文档建议隔离（--apply 才写入隔离区）")
        return 0
    for report in to_quarantine:
        path = write_quarantine(
            args.quarantine_dir, args.product_dir.name, report.doc, report
        )
        print(f"已隔离：{path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="弱模型抽取管道（004；006 模板 fast path）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ext = sub.add_parser("extract", help="从 WeKnora 生产来源运行全管道")
    p_ext.add_argument("--source", choices=("weknora",), required=True)
    p_ext.add_argument("--space-id", required=True)
    p_ext.add_argument("--parser-fingerprint", required=True)
    p_ext.add_argument(
        "--knowledge-id", dest="knowledge_ids", action="append", required=True
    )
    p_ext.add_argument("--product-id", required=True)
    p_ext.add_argument("--product-name", required=True)
    p_ext.add_argument("--db-url", default=None)
    p_ext.add_argument("--run-dir", type=Path, required=True)
    p_ext.add_argument("--line-key", default=None)
    p_ext.add_argument("--schema-dir", type=Path, default=_DEFAULT_SCHEMA_DIR)
    _add_recall_config_arguments(p_ext)
    p_ext.add_argument("--resume", action="store_true", help="从 checkpoint 续跑")
    p_ext.add_argument(
        "--templates-dir", type=Path, default=None,
        help="模板注册表目录（如 dataset/templates）；缺省不启用 fast path",
    )

    p_replay = sub.add_parser("extract-replay", help="从显式本地目录回放全管道")
    p_replay.add_argument("product_dir", type=Path)
    p_replay.add_argument("--replay-identity", required=True)
    p_replay.add_argument("--parser-fingerprint", required=True)
    p_replay.add_argument("--run-dir", type=Path, required=True)
    p_replay.add_argument("--line-key", default=None)
    p_replay.add_argument("--schema-dir", type=Path, default=_DEFAULT_SCHEMA_DIR)
    p_replay.add_argument("--replay-dir", type=Path, default=None, help="录制回放夹具目录")
    p_replay.add_argument("--model", default=None, help="覆盖 HARNESS_LLM_MODEL_WEAK")
    _add_recall_config_arguments(p_replay)
    p_replay.add_argument("--resume", action="store_true", help="从 checkpoint 续跑")
    p_replay.add_argument(
        "--templates-dir", type=Path, default=None,
        help="模板注册表目录（如 dataset/templates）；缺省不启用 fast path",
    )

    p_apply = sub.add_parser("apply-judgements", help="应用 Claude 会话裁决结果")
    p_apply.add_argument("run_dir", type=Path)
    p_apply.add_argument("judgements", type=Path)

    p_ind = sub.add_parser("induce-template", help="族内金标 → 模板草案（零模型，006 F2）")
    p_ind.add_argument("--doc", required=True, help="文档文件名（如 费率表.pdf）")
    p_ind.add_argument("--products", required=True, help="逗号分隔的 ≥2 个产品目录名")
    p_ind.add_argument("--golden-root", type=Path, required=True)
    p_ind.add_argument("--dataset-root", type=Path, required=True)
    p_ind.add_argument("--out-dir", type=Path, required=True)

    p_feed = sub.add_parser("feedability", help="文档可喂性评分（006 F4；默认 dry-run）")
    p_feed.add_argument("product_dir", type=Path)
    p_feed.add_argument("--threshold", type=float, default=0.75)
    p_feed.add_argument("--quarantine-dir", type=Path, default=Path("out/.rejections"))
    p_feed.add_argument("--apply", action="store_true", help="写入隔离区（默认 dry-run）")

    args = parser.parse_args(argv)
    if args.cmd == "extract":
        return asyncio.run(_cmd_extract(args))
    if args.cmd == "extract-replay":
        return asyncio.run(_cmd_extract_replay(args))
    if args.cmd == "induce-template":
        return _cmd_induce_template(args)
    if args.cmd == "feedability":
        return _cmd_feedability(args)
    return _cmd_apply_judgements(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

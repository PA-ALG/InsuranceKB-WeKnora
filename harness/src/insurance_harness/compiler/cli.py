"""抽取管道 CLI（004 T8）。

用法：
    # 单产品抽取（真实网关配置读 harness/.env；或 --replay-dir 用录制回放）
    uv run python -m insurance_harness.compiler.cli extract <product_dir> --run-dir out/run1

    # 应用主会话 Claude 批处理后的裁决结果（judge_mode=claude-session）
    uv run python -m insurance_harness.compiler.cli apply-judgements <run_dir> <judgements.jsonl>
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import ValidationError

from ..config import HarnessSettings
from ..schemas import load_schema_registry
from .judge import JudgeDispatcher, read_judgements
from .llm import ModelClient, OpenAICompatClient, ReplayClient
from .models import PredRecord
from .pipeline import ExtractionPipeline, PipelineConfig

_DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "docs/insurance-kb/schema-baseline"


def load_settings() -> HarnessSettings:
    """加载配置；compiler CLI 不依赖 WeKnora，缺 WeKnora 配置时以占位值降级。"""
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


async def _cmd_extract(args: argparse.Namespace) -> int:
    settings = load_settings()
    client, model_id = build_client(settings, args.replay_dir, args.model)
    registry = load_schema_registry(args.schema_dir)
    judge: JudgeDispatcher
    if settings.judge_mode == "gateway":
        fallback = settings.llm_model_judge_fallback
        if not (settings.llm_base_url and settings.llm_api_key and fallback):
            raise SystemExit("judge_mode=gateway 需要 HARNESS_LLM_MODEL_JUDGE_FALLBACK 配置")
        judge_client = OpenAICompatClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=fallback,
            max_tokens=settings.llm_max_tokens,
            timeout_s=settings.llm_timeout_s,
        )
        judge = JudgeDispatcher(mode="gateway", client=judge_client)
    else:
        judge = JudgeDispatcher(mode="claude-session")
    pipeline = ExtractionPipeline(
        client=client,
        registry=registry,
        model_id=model_id,
        config=PipelineConfig(judge_mode=judge.mode, concurrency=args.concurrency),
        judge=judge,
    )
    result = await pipeline.run(
        product_dir=args.product_dir,
        run_dir=args.run_dir,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="弱模型抽取管道（004）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ext = sub.add_parser("extract", help="对一个产品目录跑全管道")
    p_ext.add_argument("product_dir", type=Path)
    p_ext.add_argument("--run-dir", type=Path, required=True)
    p_ext.add_argument("--line-key", default=None)
    p_ext.add_argument("--schema-dir", type=Path, default=_DEFAULT_SCHEMA_DIR)
    p_ext.add_argument("--replay-dir", type=Path, default=None, help="录制回放夹具目录")
    p_ext.add_argument("--model", default=None, help="覆盖 HARNESS_LLM_MODEL_WEAK")
    p_ext.add_argument("--concurrency", type=int, default=6)
    p_ext.add_argument("--resume", action="store_true", help="从 checkpoint 续跑")

    p_apply = sub.add_parser("apply-judgements", help="应用 Claude 会话裁决结果")
    p_apply.add_argument("run_dir", type=Path)
    p_apply.add_argument("judgements", type=Path)

    args = parser.parse_args(argv)
    if args.cmd == "extract":
        return asyncio.run(_cmd_extract(args))
    return _cmd_apply_judgements(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

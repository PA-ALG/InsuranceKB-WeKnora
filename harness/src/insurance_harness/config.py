"""统一配置：全部经环境变量注入（前缀 ``HARNESS_``），零硬编码。

必填项缺失时在实例化（即进程启动）时立即抛 ``ValidationError``，
而不是等到运行时才失败（spec S2.1）。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class HarnessSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HARNESS_", extra="ignore", env_file=".env", env_file_encoding="utf-8"
    )

    # --- WeKnora（必填） ---
    weknora_base_url: str
    weknora_api_key: str

    # --- Langfuse（可选；未配置时 tracing 静默降级为 no-op） ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    # --- 轮询与重试 ---
    poll_interval_s: float = 2.0
    poll_timeout_s: float = 600.0
    retry_max_attempts: int = 3

    # --- HTTP ---
    http_timeout_s: float = 30.0

    # --- Harness 自有数据库（change 003；生产 Postgres，SQLite 仅测试） ---
    db_url: str | None = None

    # --- 金标注（change 002；均可选，仅 LiteLLMClient 需要） ---
    goldenset_model: str | None = None
    goldenset_api_base: str | None = None
    goldenset_api_key: str | None = None
    # 单次标注调用送入的文档文本上限（字符）；超限按页窗口过滤（spec G2.6）
    goldenset_doc_char_budget: int = 30_000

    # --- 弱模型网关（change 004；百炼 OpenAI 兼容端点，凭据在 harness/.env，勿入库） ---
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_weak: str | None = None  # 主力弱模型（deepseek-v4-flash；MiniMax-M2.5 为备选）
    llm_model_judge: str | None = None  # （历史字段）网关裁决模型；judge_mode=gateway 时的旧配置
    # 裁决可插拔（08 选型更新 2026-07-12）：claude-session=裁决请求落 judge-queue.jsonl
    # 由主会话 Claude 批处理回写；gateway=直接调 llm_model_judge_fallback
    judge_mode: str = "claude-session"
    llm_model_judge_fallback: str | None = None
    # 推理型模型（reasoning_content）会大量消耗输出 token，max_tokens 必须给足
    llm_max_tokens: int = 4096
    llm_timeout_s: float = 180.0

    # --- 增量合并审核门禁（change 007，spec K4.4）---
    # 默认关闭自动通过=全部走审核（保守）；开启后仅 risk=low 且 confidence≥阈值 的 enrich 自动应用
    merge_auto_apply_enrich: bool = False
    merge_enrich_auto_min_confidence: float = 0.8

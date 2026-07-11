"""统一配置：全部经环境变量注入（前缀 ``HARNESS_``），零硬编码。

必填项缺失时在实例化（即进程启动）时立即抛 ``ValidationError``，
而不是等到运行时才失败（spec S2.1）。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class HarnessSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HARNESS_", extra="ignore")

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

    # --- 金标注（change 002；均可选，仅 LiteLLMClient 需要） ---
    goldenset_model: str | None = None
    goldenset_api_base: str | None = None
    goldenset_api_key: str | None = None
    # 单次标注调用送入的文档文本上限（字符）；超限按页窗口过滤（spec G2.6）
    goldenset_doc_char_budget: int = 30_000

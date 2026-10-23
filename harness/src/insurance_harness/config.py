"""统一配置：全部经环境变量注入（前缀 ``HARNESS_``），零硬编码。

必填项缺失时在实例化（即进程启动）时立即抛 ``ValidationError``，
而不是等到运行时才失败（spec S2.1）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .jobs.models import JobRuntimeConfig, JobTypePolicy


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

    # --- WeKnora 原件下载（change 017） ---
    source_max_file_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    source_download_chunk_bytes: int = Field(default=64 * 1024, gt=0)
    source_max_chunk_pages: int = Field(default=1_000, gt=0)
    source_max_chunks_per_knowledge: int = Field(default=100_000, gt=0)
    source_max_documents_per_batch: int = Field(default=8, gt=0)
    source_max_batch_bytes: int = Field(default=256 * 1024 * 1024, gt=0)
    source_max_batch_pages: int = Field(default=20_000, gt=0)
    source_max_batch_chunks: int = Field(default=200_000, gt=0)
    # None 使用系统安全临时目录；测试/受控部署可显式覆盖。
    source_temp_dir: Path | None = None

    # --- Harness 自有数据库（change 003；生产 Postgres，SQLite 仅测试） ---
    db_url: str | None = None

    # --- P1 任务运行时（change 035）；数值只是环境默认值而非产品上限 ---
    # P1.3（D-2026-07-27-16）：lease 必须严格为正；`0` 会使每个 lease 出生即
    # 过期，静默作废并发限额与 heartbeat。与 heartbeat 的大小关系由
    # `JobRuntimeConfig` 在装配时校验。
    job_lease_seconds: float = Field(default=60.0, gt=0)
    job_heartbeat_interval_seconds: float = Field(default=20.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1)
    job_backoff_seconds: tuple[float, ...] = (5.0, 30.0, 120.0)
    job_type_policies: dict[str, JobTypePolicy] = Field(default_factory=dict)
    job_per_space_concurrency_limit: int = Field(default=2, ge=1)
    job_global_concurrency_limit: int = Field(default=8, ge=1)
    job_maintenance_batch_size: int = Field(default=128, ge=1)
    # outbox 投递失败的持久退避档位（P1.6，D-2026-07-27-16）。默认值只是环境
    # 默认而非产品上限；不得默认为全 0，否则"让位"在真实部署里是空操作。
    job_dispatch_backoff_seconds: tuple[float, ...] = (1.0, 5.0, 30.0, 120.0)

    def job_runtime_config(self) -> JobRuntimeConfig:
        """把 HARNESS_JOB_* 环境配置接线为 P1 JobStore 的运行时配置。"""
        return JobRuntimeConfig(
            lease_seconds=self.job_lease_seconds,
            heartbeat_interval_seconds=self.job_heartbeat_interval_seconds,
            max_attempts=self.job_max_attempts,
            backoff_seconds=self.job_backoff_seconds,
            job_type_policies=self.job_type_policies,
            per_space_concurrency_limit=self.job_per_space_concurrency_limit,
            global_concurrency_limit=self.job_global_concurrency_limit,
            maintenance_batch_size=self.job_maintenance_batch_size,
            dispatch_backoff_seconds=self.job_dispatch_backoff_seconds,
        )

    # --- 金标注（change 002；均可选，仅 LiteLLMClient 需要） ---
    goldenset_model: str | None = None
    goldenset_api_base: str | None = None
    goldenset_api_key: str | None = None
    # Schema67 Golden quality evaluation uses two deployment-owned human
    # approval public keys and a separate evaluator signing identity.  Only
    # public material belongs in settings; the evaluator private key remains
    # behind the task-local credential-source interface.
    schema67_golden_approver_public_keys: tuple[tuple[str, str], ...] = ()
    schema67_golden_evaluator_signer_key_id: str | None = None
    schema67_golden_evaluator_public_key_base64: str | None = None
    # Existing HumanBatchDecisionReceiptV1 verification ring reused by the
    # Golden dossier review subject. Public keys only; callers cannot inject a
    # per-call ring and private signing material never enters Harness settings.
    schema_wiki_human_decision_public_keys: tuple[tuple[str, str], ...] = ()
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

    # --- 生产弱模型边界（change 027） ---
    # disabled 是安全默认；历史 replay/goldenset/manual 路径必须显式选择非生产 profile。
    model_profile: Literal[
        "disabled", "production", "offline-eval", "replay", "goldenset", "manual"
    ] = "disabled"
    production_model_provider: str | None = None
    production_model_deployment_id: str | None = None
    production_model_family: Literal["deepseek", "minimax", "qwen", "qwen-vl"] | None = None
    production_model_policy_version: str | None = None

    # 独立 expected request；不得从 verifier 返回的 actual admission 回填。
    production_expected_purpose: str | None = None
    production_expected_run_schema_version: str | None = None
    production_expected_run_id: str | None = None
    production_expected_run_revision: str | None = None
    production_expected_space_id: str | None = None
    production_expected_admission_artifact_ref: str | None = None
    production_expected_admission_artifact_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_manifest_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_eligibility_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_golden_slice_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_routing_policy_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_schema_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_template_lock_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_structured_dispatch_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_model_plan_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_deployment_roles_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_resource_caps_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_rights_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_provenance_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    production_expected_clean_integration_sha: str | None = Field(
        default=None, pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
    )

    # --- 表格结构识别 provider（change 006，spec F5.3 配置位） ---
    # pdfplumber（默认，零新增依赖）；pp-structure-v3 为预留位（重依赖部署见 HANDOFF ⓪-B）
    table_provider: str = "pdfplumber"

    # --- 增量合并审核门禁（change 007，spec K4.4）---
    # 默认关闭自动通过=全部走审核（保守）；开启后仅 risk=low 且 confidence≥阈值 的 enrich 自动应用
    merge_auto_apply_enrich: bool = False
    merge_enrich_auto_min_confidence: float = 0.8

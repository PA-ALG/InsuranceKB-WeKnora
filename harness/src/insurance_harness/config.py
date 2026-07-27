"""统一配置：全部经环境变量注入（前缀 ``HARNESS_``），零硬编码。

必填项缺失时在实例化（即进程启动）时立即抛 ``ValidationError``，
而不是等到运行时才失败（spec S2.1）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .jobs.models import JobRuntimeConfig, JobTypePolicy
from .model_policy import ModelIdentity, ModelPolicyDenied
from .model_policy.policy import _validate_production_identity_declaration


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
    production_model_family: Literal["minimax", "qwen", "qwen-vl"] | None = None
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

    # --- 审核工作台鉴权（change 008，spec W6：token→principal+Space 集合绑定） ---
    # JSON：{"<token>": {"principal": "审核人标识", "space_ids": ["<space-id>", ...]}}
    # 未配置 = 拒绝一切请求（fail-closed 默认）；operator 一律取 token 绑定 principal
    workbench_tokens_json: str | None = None
    # 浏览器会话 cookie 签名密钥（HMAC-SHA256）。未配置=进程内随机（单进程可用，
    # 重启即全员重登）；多 worker/重启保活需显式配置随机长串（勿入库）。
    workbench_session_secret: str | None = None
    # 会话有效期（秒）；到期须重新以 token 登录
    workbench_session_ttl_s: int = 8 * 3600
    # 完整度矩阵 schema 基线目录（W3 产品×schema 全字段底图）；生产工厂必需——
    # 未配置且默认路径不存在时启动即失败（fail-closed，不空底图冒充全量）
    workbench_schema_baseline_dir: Path | None = None

    # --- 表格结构识别 provider（change 006，spec F5.3 配置位） ---
    # pdfplumber（默认，零新增依赖）；pp-structure-v3 为预留位（重依赖部署见 HANDOFF ⓪-B）
    table_provider: str = "pdfplumber"

    # --- 增量合并审核门禁（change 007，spec K4.4）---
    # 默认关闭自动通过=全部走审核（保守）；开启后仅 risk=low 且 confidence≥阈值 的 enrich 自动应用
    merge_auto_apply_enrich: bool = False
    merge_enrich_auto_min_confidence: float = 0.8

    @model_validator(mode="after")
    def require_frozen_production_model_policy(self) -> HarnessSettings:
        if self.model_profile != "production":
            return self
        required = (
            "production_model_provider",
            "production_model_deployment_id",
            "production_model_family",
            "production_model_policy_version",
            "production_expected_purpose",
            "production_expected_run_schema_version",
            "production_expected_run_id",
            "production_expected_run_revision",
            "production_expected_space_id",
            "production_expected_admission_artifact_ref",
            "production_expected_admission_artifact_digest",
            "production_expected_manifest_hash",
            "production_expected_eligibility_hash",
            "production_expected_golden_slice_hash",
            "production_expected_routing_policy_hash",
            "production_expected_schema_hash",
            "production_expected_template_lock_hash",
            "production_expected_structured_dispatch_hash",
            "production_expected_model_plan_hash",
            "production_expected_deployment_roles_hash",
            "production_expected_resource_caps_hash",
            "production_expected_rights_hash",
            "production_expected_provenance_hash",
            "production_expected_clean_integration_sha",
            "llm_base_url",
            "llm_api_key",
        )
        missing = [name for name in required if not _nonblank(getattr(self, name))]
        if missing:
            raise ValueError("production model policy configuration is incomplete")
        if self.judge_mode != "guarded" or self.llm_model_judge_fallback is not None:
            raise ValueError("legacy model judge routes are forbidden in production")

        assert self.production_model_provider is not None
        assert self.production_model_deployment_id is not None
        assert self.production_model_family is not None
        assert self.production_model_policy_version is not None
        if (
            self.production_model_provider.casefold() == "unknown"
            or self.production_model_deployment_id.casefold() == "unknown"
        ):
            raise ValueError("production model identity must be immutable and known")
        identity = ModelIdentity(
            provider=self.production_model_provider,
            deployment_id=self.production_model_deployment_id,
            family=self.production_model_family,
            role="extract",
            policy_version=self.production_model_policy_version,
        )
        try:
            _validate_production_identity_declaration(identity)
        except ModelPolicyDenied:
            raise ValueError("production model identity is not approved") from None
        return self


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())

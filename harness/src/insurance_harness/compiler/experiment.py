"""024 E7：变体实验归属（assignment）与注册表内容摘要。

三个概念分离（codex PR#13 阻断 2 裁决）：

- **variant_assignment**：运行前基于 ``(experiment_id, seed, product_id, field_id)``
  对**同一 eligible population** 确定性分桶（control/treatment）；实验关闭时为 None。
  分桶只决定 gapfill 定向模板是否启用——首轮 baseline 抽取对两臂完全一致，
  差异仅在补漏模板，因此臂间可比。
- **prompt_variant_used**：每条 pred 实际经过的模板标识（在产生处记录，见
  gapfill/_to_pred）；注册表 membership 不得冒充实际使用。
- **experiment_digest**：canonical 注册表 + assignment policy 的内容摘要，进入
  RunManifest 与 checkpoint 身份——注册表内容变化而标签未 bump 时，resume
  fail-closed，杜绝同一 run 混用两套 prompt。
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .variants import VariantRegistry

Arm = Literal["control", "treatment"]


class AssignmentPolicy(BaseModel):
    """实验分桶策略（配置注入，管道节点不得各自取全局默认）。

    ``enabled=False``（默认）= 不开实验：不分臂（assignment=None），gapfill 对
    注册字段使用注册表变体（现状语义，实际使用会如实记录）。
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    experiment_id: str = ""
    seed: int = Field(default=0, ge=0)


def assign_arm(
    policy: AssignmentPolicy, product_id: str, field_id: str
) -> Arm | None:
    """确定性分桶：同 (policy, product, field) 永远同臂；实验关闭 → None。"""
    if not policy.enabled:
        return None
    payload = f"{policy.experiment_id}::{policy.seed}::{product_id}::{field_id}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return "treatment" if digest[-1] % 2 == 0 else "control"


def experiment_digest(registry: VariantRegistry, policy: AssignmentPolicy) -> str:
    """canonical 内容摘要：注册表或策略任何变化 → 新摘要（run/checkpoint 身份成分）。"""
    payload = (
        registry.model_dump_json()
        + "|"
        + policy.model_dump_json()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

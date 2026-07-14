"""Baseline artifact 与不可变批准记录（019 spec Q2）。

- Q2.1 artifact 记录每产品 run manifest/pred/dead-letter/judge-queue/judgements/keypoints/eval，
  未解决数量（dead-letter/judge-queue/judgements 缺口）显式保留，不省略；
- Q2.2 artifact 绑定运行指纹（git SHA/schema/model/prompt/template+source/golden hash），
  指纹缺项或仍有未解决项时不能批准；
- Q2.3 批准记录独立、不可改写，只能追加新版本。

真实 13 产品 artifacts 由 020 用同一 schema 产出；本模块只做确定性结构与判定。
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from .records import GoldenRecord

if TYPE_CHECKING:
    from .profile import FieldVerdict

_FINGERPRINT_FIELDS = (
    "git_sha",
    "schema_version",
    "model_id",
    "prompt_version",
    "template_profile",
    "source_profile",
    "golden_release_hash",
)

# Q2.1：可批准的 baseline 要求关键点标注完成、eval 报告存在、且至少有预测产物。
_APPROVABLE_KEYPOINTS = frozenset({"ready", "done"})


class RunFingerprint(BaseModel):
    """一次运行的不可变指纹；任一项变化都要求重跑或重新批准（Q2.2/Q3.2）。"""

    model_config = ConfigDict(frozen=True)

    git_sha: str
    schema_version: str
    model_id: str
    prompt_version: str
    template_profile: str
    source_profile: str
    golden_release_hash: str

    def missing_fields(self) -> list[str]:
        return [f for f in _FINGERPRINT_FIELDS if not str(getattr(self, f)).strip()]


class ProductRunStatus(BaseModel):
    """单产品运行状态；未解决数量（dead-letter/judge-queue）显式保留（Q2.1）。"""

    model_config = ConfigDict(frozen=True)

    product_id: str
    pred_count: int
    dead_letter_count: int = 0
    judge_queue_count: int = 0
    judgements_count: int = 0
    keypoints_status: str = "pending"
    eval_report_path: str | None = None

    @property
    def unresolved(self) -> int:
        """dead-letter + 尚未回写的 judge 请求（judge_queue 超出 judgements 的部分）。"""
        pending_judge = max(self.judge_queue_count - self.judgements_count, 0)
        return self.dead_letter_count + pending_judge

    def completeness_blockers(self) -> list[str]:
        """Q2.1：产物齐全性检查——缺预测/关键点未完成/无 eval 报告都阻断批准。"""
        blockers: list[str] = []
        if self.pred_count <= 0:
            blockers.append(f"{self.product_id} 无预测产物（pred_count=0）")
        if self.keypoints_status not in _APPROVABLE_KEYPOINTS:
            blockers.append(
                f"{self.product_id} 关键点未完成（keypoints={self.keypoints_status}）"
            )
        if not (self.eval_report_path or "").strip():
            blockers.append(f"{self.product_id} 缺 eval 报告（eval_report_path 为空）")
        return blockers


class BaselineArtifact(BaseModel):
    """一次 baseline 运行的不可变 artifact（Q2.1/Q2.2）。"""

    model_config = ConfigDict(frozen=True)

    baseline_id: str
    fingerprint: RunFingerprint
    products: tuple[ProductRunStatus, ...]

    def unresolved_total(self) -> int:
        return sum(p.unresolved for p in self.products)

    def approval_blockers(self) -> list[str]:
        """批准阻断项：指纹缺项（Q2.2）+ 未解决项 + 每产品产物齐全性（Q2.1）。"""
        blockers = [f"fingerprint.{f} 缺失" for f in self.fingerprint.missing_fields()]
        if not self.products:
            blockers.append("无任何产品运行状态")
        unresolved = self.unresolved_total()
        if unresolved:
            blockers.append(f"仍有 {unresolved} 项未解决（dead-letter/待裁决）")
        for product in self.products:
            blockers.extend(product.completeness_blockers())
        return blockers


class ApprovalRecord(BaseModel):
    """独立、不可改写的批准记录（Q2.3）；只能追加新版本。

    `profile_hash` 把批准动作**绑定到被批准画像的内容**（Q4.3）：闸门只有在
    候选画像内容哈希与该记录一致时才认可"已批准"，杜绝拿任意临时画像冒充已批准。
    """

    model_config = ConfigDict(frozen=True)

    baseline_id: str
    version: int
    approved_by: str
    approved_at: datetime
    fingerprint: RunFingerprint
    profile_hash: str


class BaselineNotApprovableError(Exception):
    """artifact 有批准阻断项（指纹缺项 / 未解决项 / 产物不齐 / 回归失败）时拒绝批准。"""


def _record_hash_payload(record: GoldenRecord) -> str:
    """一条金标记录的全语义序列化：改动任一语义字段都会改变 release hash（Q3.2）。"""
    evidence = ";".join(
        f"{ev.page}|{ev.quote}"
        for ev in sorted(record.evidence, key=lambda e: (e.page, e.quote))
    )
    return "\t".join(
        [
            record.product_id,
            record.field_id,
            record.tri_state,
            record.value or "",
            evidence,
            record.schema_version,
            record.annotator_model,
            "1" if record.disputed else "0",
        ]
    )


def release_hash(records: Sequence[GoldenRecord]) -> str:
    """内容寻址的 golden release 指纹：覆盖值/证据/schema/标注者/disputed 等全部语义字段。"""
    payload = "\n".join(sorted(_record_hash_payload(r) for r in records))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approve_baseline(
    artifact: BaselineArtifact,
    *,
    approved_by: str,
    profile_hash: str,
    prior: Sequence[ApprovalRecord] = (),
    regression: "FieldVerdict | None" = None,
    approved_at: datetime | None = None,
) -> ApprovalRecord:
    """产出一条新版本批准记录并绑定画像内容哈希；有阻断项/回归失败则拒绝。

    `profile_hash` 由调用方对被批准画像取 `QualityProfile.content_hash()`；
    `regression` 为候选相对上一个已批准画像的回归判定（Q4.6），失败即阻断批准。
    绝不改写既有记录（Q2.3）。
    """
    blockers = artifact.approval_blockers()
    if regression is not None and not regression.eligible:
        blockers.append("回归 gate 失败：" + "；".join(regression.failures))
    if blockers:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 不可批准：{blockers}"
        )
    same_baseline = [r for r in prior if r.baseline_id == artifact.baseline_id]
    next_version = max((r.version for r in same_baseline), default=0) + 1
    return ApprovalRecord(
        baseline_id=artifact.baseline_id,
        version=next_version,
        approved_by=approved_by,
        approved_at=approved_at or datetime.now(UTC),
        fingerprint=artifact.fingerprint,
        profile_hash=profile_hash,
    )

"""Baseline artifact 与不可变批准记录（019 spec Q2）。

- Q2.1 artifact 记录每产品 run manifest/pred/dead-letter/judge-queue/judgements/keypoints/eval，
  未解决数量（dead-letter/judge-queue/judgements 缺口）显式保留，不省略；
- Q2.2 artifact 绑定运行指纹（git SHA/schema/model/prompt/template+source/golden hash），
  指纹缺项或仍有未解决项时不能批准；
- Q2.3 批准记录独立、不可改写，只能追加新版本。

真实 13 产品 artifacts 由 020 用同一 schema 产出；本模块只做确定性结构与判定。
"""

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from .records import GoldenRecord

if TYPE_CHECKING:
    from .profile import QualityProfile, RegressionThresholds

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

# release_hash 不纳入的易变字段：created_at 是标注时间戳、非内容语义（同内容重标不应改变身份）。
_VOLATILE_RECORD_FIELDS = frozenset({"created_at"})

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


class ArtifactRef(BaseModel):
    """产物的内容寻址引用（Q2.1）：path + sha256 (+ count)，据此证明产物真实存在且可重放。

    只有 path 非空且 sha256 为合法 64 位十六进制才算"存在"——防止用任意路径字符串冒充产物。
    """

    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    count: int = 0

    def is_present(self) -> bool:
        return bool(self.path.strip()) and _SHA256_HEX.fullmatch(self.sha256) is not None


# Q2.1：批准前必须齐备的内容寻址产物（020 产出真实 path+hash；本层做结构性合同校验）。
_REQUIRED_ARTIFACTS = ("run_manifest_ref", "pred_ref", "eval_ref")


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
    # 内容寻址产物引用（Q2.1）：020 产出真实 path+sha256；缺失/空 hash 不能批准。
    run_manifest_ref: ArtifactRef | None = None
    pred_ref: ArtifactRef | None = None
    eval_ref: ArtifactRef | None = None

    @property
    def unresolved(self) -> int:
        """dead-letter + 尚未回写的 judge 请求（judge_queue 超出 judgements 的部分）。"""
        pending_judge = max(self.judge_queue_count - self.judgements_count, 0)
        return self.dead_letter_count + pending_judge

    def completeness_blockers(self) -> list[str]:
        """Q2.1：产物齐全性——缺预测/关键点未完成/产物引用缺失或不一致都阻断批准。"""
        blockers: list[str] = []
        if self.pred_count <= 0:
            blockers.append(f"{self.product_id} 无预测产物（pred_count=0）")
        if self.keypoints_status not in _APPROVABLE_KEYPOINTS:
            blockers.append(
                f"{self.product_id} 关键点未完成（keypoints={self.keypoints_status}）"
            )
        for name in _REQUIRED_ARTIFACTS:
            ref = getattr(self, name)
            if ref is None or not ref.is_present():
                blockers.append(
                    f"{self.product_id} 缺产物引用 {name}（需非空 path + 64 位 sha256）"
                )
        # pred 产物条数须与 pred_count 一致——防止计数与实际产物脱节。
        if self.pred_ref is not None and self.pred_ref.count != self.pred_count:
            blockers.append(
                f"{self.product_id} pred_ref.count={self.pred_ref.count} 与 "
                f"pred_count={self.pred_count} 不一致"
            )
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


def _canonical_record(record: GoldenRecord) -> str:
    """一条金标记录的 canonical 全量序列化：对完整模型（含嵌套 evidence lineage）做
    去易变字段的 canonical JSON——任一影响评测/回验/来源审计的字段变化都会改变结果。"""
    data = record.model_dump(mode="json")
    for field in _VOLATILE_RECORD_FIELDS:
        data.pop(field, None)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def release_hash(records: Sequence[GoldenRecord]) -> str:
    """内容寻址的 golden release 指纹：对每条记录做 canonical 全量序列化后排序 sha256。

    覆盖 GoldenRecord/Evidence 的**全部内容字段**（product/doc/field/value/tri_state/
    disputed(+reason)/reasoning/schema/annotator + evidence 的 page/quote/来源审计 lineage），
    仅排除 created_at（标注时间戳，非内容语义）。新增字段自动纳入，无需手工补。
    """
    payload = "\n".join(sorted(_canonical_record(r) for r in records))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approve_baseline(
    artifact: BaselineArtifact,
    profile: "QualityProfile",
    *,
    approved_by: str,
    prior: Sequence[ApprovalRecord] = (),
    prior_profile: "QualityProfile | None" = None,
    regression_thresholds: "RegressionThresholds | None" = None,
    approved_at: datetime | None = None,
) -> ApprovalRecord:
    """对 (artifact, profile) 产出一条不可改写的新版本批准记录（Q2.3/Q4.3/Q4.6）。

    让非法状态无法构造，而非信任调用方：
    - **身份绑定**：`profile.fingerprint` 必须等于 `artifact.fingerprint`，画像哈希由本函数
      内部计算（调用方无法传入错绑的 hash）；
    - **回归强制**：该 baseline 已有批准版本时，必须提供 `prior_profile`，由本函数内部跑
      `check_regression`，退化即拒（调用方无法靠省略参数跳过 Q4.6）；
    - 指纹缺项 / 未解决项 / 产物不齐（Q2.1）任一都阻断批准。
    """
    if profile.fingerprint != artifact.fingerprint:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 不可批准：画像指纹与 artifact 指纹不一致"
            "（画像不属于该次运行）"
        )
    same_baseline = [r for r in prior if r.baseline_id == artifact.baseline_id]
    blockers = artifact.approval_blockers()
    if same_baseline and prior_profile is None:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 已有批准版本，必须提供 prior_profile "
            "做回归检查（Q4.6 不可省略）"
        )
    if prior_profile is not None:
        from .profile import check_regression  # 延迟导入避免 baseline↔profile 循环

        verdict = check_regression(prior_profile, profile, regression_thresholds)
        if not verdict.eligible:
            blockers.append("回归 gate 失败：" + "；".join(verdict.failures))
    if blockers:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 不可批准：{blockers}"
        )
    next_version = max((r.version for r in same_baseline), default=0) + 1
    return ApprovalRecord(
        baseline_id=artifact.baseline_id,
        version=next_version,
        approved_by=approved_by,
        approved_at=approved_at or datetime.now(UTC),
        fingerprint=artifact.fingerprint,
        profile_hash=profile.content_hash(),
    )

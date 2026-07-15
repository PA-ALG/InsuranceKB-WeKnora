"""不可变 baseline artifact、内容寻址批准记录与批准闸门（019 spec Q2 + 实施计划 Task3）。

- Q2.1 每产品记录 run manifest/pred/dead-letter/judge-queue/judgements/keypoints/eval 的
  **内容哈希(sha256)**与计数，未解决数量显式保留、可一致性校验，不省略；
- Q2.2 artifact 绑定运行指纹；指纹缺项/未解决/产物不齐/计数不一致时不能批准；
- Q2.3 批准记录独立不可改写，只能追加新版本；批准**绑定 artifact 内容哈希**
  （`approve(...).artifact_sha256 == artifact.sha256()`），且画像必须派生自该 artifact。

真实 13 产品 artifacts 由 020 用同一 schema 产出并回验真实文件；本模块做确定性结构与判定。
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

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

# release_hash 不纳入的易变字段：created_at 是标注时间戳、非内容语义（同内容重标不应改变身份）。
_VOLATILE_RECORD_FIELDS = frozenset({"created_at"})

_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")

# 每产品批准前必须齐备且哈希合法的内容寻址产物。
_REQUIRED_PRODUCT_SHA = (
    "run_manifest_sha256",
    "pred_sha256",
    "dead_letter_sha256",
    "judge_queue_sha256",
    "judgements_sha256",
    "eval_report_sha256",
)


def _is_sha256(value: str | None) -> bool:
    return value is not None and _SHA256_HEX.fullmatch(value) is not None


def canonical_sha256(data: object) -> str:
    """对任意 JSON 可序列化对象做 canonical JSON（sorted keys + 紧凑分隔符）后 sha256。"""
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


class BaselineProductArtifacts(BaseModel):
    """单产品运行现场（实施计划 Task3）：每类产物的内容哈希 + 计数，可自证齐全与一致。

    与 020 的 D3/D4 合同对齐——run/pred/dead-letter/judge/judgement/keypoints/eval 都以 sha256
    引用；本确定性层校验引用齐备且计数自洽，真实文件字节哈希由 020 运行时回验。
    """

    model_config = ConfigDict(frozen=True)

    product_id: str
    run_manifest_sha256: str
    pred_sha256: str
    pred_count: int
    dead_letter_sha256: str
    dead_letter_count: int
    judge_queue_sha256: str
    judge_queue_count: int
    judgements_sha256: str
    resolved_judgement_count: int
    keypoints_status: Literal["complete", "pending"]
    keypoints_sha256: str | None
    keypoints_pending_count: int
    eval_report_sha256: str
    unresolved_judge_count: int
    unresolved_dead_letter_count: int

    @property
    def unresolved(self) -> int:
        return self.unresolved_judge_count + self.unresolved_dead_letter_count

    def consistency_errors(self) -> list[str]:
        """内部一致性：产物哈希齐备合法、计数自洽、keypoints 现场自洽（不含"是否可批准"）。"""
        errors: list[str] = []
        for name in _REQUIRED_PRODUCT_SHA:
            if not _is_sha256(getattr(self, name)):
                errors.append(f"{self.product_id} 产物哈希 {name} 缺失或非法（需 64 位 sha256）")
        if self.pred_count <= 0:
            errors.append(f"{self.product_id} 无预测产物（pred_count=0）")
        if not (0 <= self.resolved_judgement_count <= self.judge_queue_count):
            errors.append(
                f"{self.product_id} resolved_judgement_count={self.resolved_judgement_count} "
                f"超出 judge_queue_count={self.judge_queue_count}"
            )
        expected_unresolved_judge = self.judge_queue_count - self.resolved_judgement_count
        if self.unresolved_judge_count != expected_unresolved_judge:
            errors.append(
                f"{self.product_id} unresolved_judge_count={self.unresolved_judge_count} 与 "
                f"queue-resolved={expected_unresolved_judge} 不一致"
            )
        if self.unresolved_dead_letter_count != self.dead_letter_count:
            errors.append(
                f"{self.product_id} unresolved_dead_letter_count="
                f"{self.unresolved_dead_letter_count} 与 dead_letter_count="
                f"{self.dead_letter_count} 不一致"
            )
        if self.keypoints_status == "complete":
            if not _is_sha256(self.keypoints_sha256):
                errors.append(f"{self.product_id} keypoints 声明 complete 但缺 keypoints_sha256")
            if self.keypoints_pending_count != 0:
                errors.append(
                    f"{self.product_id} keypoints complete 但 pending_count="
                    f"{self.keypoints_pending_count}≠0"
                )
        else:  # pending
            if self.keypoints_pending_count <= 0:
                errors.append(f"{self.product_id} keypoints pending 但 pending_count≤0")
        return errors

    def approval_blockers(self) -> list[str]:
        """可批准要求：内部一致 + keypoints 已完成 + 无未解决项。"""
        blockers = self.consistency_errors()
        if self.keypoints_status != "complete":
            blockers.append(f"{self.product_id} 关键点未完成（keypoints=pending）")
        if self.unresolved:
            blockers.append(
                f"{self.product_id} 仍有 {self.unresolved} 项未解决"
                "（dead-letter/待裁决）"
            )
        return blockers


class BaselineArtifact(BaseModel):
    """一次 baseline 运行的不可变 artifact（Q2.1/Q2.2）；有 canonical 内容哈希用于批准绑定。"""

    model_config = ConfigDict(frozen=True)

    baseline_id: str
    fingerprint: RunFingerprint
    products: tuple[BaselineProductArtifacts, ...]

    def sha256(self) -> str:
        """artifact 的 canonical 内容哈希：同配置不同产物输出会得到不同哈希（身份 = 输出内容）。"""
        return canonical_sha256(self.model_dump(mode="json"))

    def unresolved_total(self) -> int:
        return sum(p.unresolved for p in self.products)

    def approval_blockers(self) -> list[str]:
        """指纹缺项（Q2.2）+ 空产品 + 每产品产物齐全/一致/无未解决（Q2.1）。"""
        blockers = [f"fingerprint.{f} 缺失" for f in self.fingerprint.missing_fields()]
        if not self.products:
            blockers.append("无任何产品运行状态")
        for product in self.products:
            blockers.extend(product.approval_blockers())
        return blockers


class ApprovalRecord(BaseModel):
    """独立、不可改写的批准记录（Q2.3）；**绑定被批准 artifact 的内容哈希**（实施计划 Task3）。"""

    model_config = ConfigDict(frozen=True)

    baseline_id: str
    version: int
    approved_by: str
    approved_at: datetime
    fingerprint: RunFingerprint
    artifact_sha256: str

    def sha256(self) -> str:
        """批准记录自身的 canonical 内容哈希；QualityProfile 以此回链其批准基线。"""
        return canonical_sha256(self.model_dump(mode="json"))


class BaselineNotApprovableError(Exception):
    """artifact 有阻断项（指纹缺项/未解决/产物不齐或不一致/画像错绑/回归失败）时拒绝批准。"""


def _canonical_record(record: GoldenRecord) -> str:
    """一条金标记录的 canonical 全量序列化：对完整模型（含嵌套 evidence lineage）做去易变字段的
    canonical JSON——任一影响评测/回验/来源审计的字段变化都会改变结果。"""
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
    thresholds: "RegressionThresholds | None" = None,
    approved_at: datetime | None = None,
) -> ApprovalRecord:
    """对 (artifact, 派生画像) 产出一条不可改写、绑定 artifact 内容哈希的批准记录。

    让非法状态无法构造，而非信任调用方：
    - **画像必须派生自该 artifact**：`profile.artifact_sha256 == artifact.sha256()` 且指纹一致；
    - **回归不可绕过且不可伪造**：该 baseline 已有批准版本时必须提供 `prior_profile`，且它必须
      正是最近批准所绑定的画像（`prior_profile.baseline_approval_sha256 == latest.sha256()`），
      回归由本函数内部跑 `compare_baselines`，退化即拒（Q4.6）；
    - 指纹缺项 / 未解决 / 产物不齐或不一致（Q2.1）任一都阻断批准。
    """
    art_hash = artifact.sha256()
    if profile.artifact_sha256 != art_hash:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 不可批准：画像未派生自该 artifact"
            "（artifact_sha256 不符）"
        )
    if profile.fingerprint != artifact.fingerprint:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 不可批准：画像指纹与 artifact 指纹不一致"
        )
    blockers = artifact.approval_blockers()
    same_baseline = [r for r in prior if r.baseline_id == artifact.baseline_id]
    if same_baseline:
        latest = max(same_baseline, key=lambda r: r.version)
        if prior_profile is None:
            raise BaselineNotApprovableError(
                f"baseline {artifact.baseline_id} 已有批准版本，必须提供 prior_profile "
                "做回归检查（Q4.6 不可省略）"
            )
        if prior_profile.baseline_approval_sha256 != latest.sha256():
            raise BaselineNotApprovableError(
                f"baseline {artifact.baseline_id} 不可批准：prior_profile 不是最近批准所绑定的"
                "画像（回归基线被伪造/替换）"
            )
        from .profile import compare_baselines  # 延迟导入避免 baseline↔profile 循环

        result = compare_baselines(prior_profile, profile, thresholds)
        if result.failures:
            blockers.append("回归失败：" + result.summary())
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
        artifact_sha256=art_hash,
    )


def build_product_artifacts(
    product_id: str,
    *,
    shas: Mapping[str, str],
    pred_count: int,
    dead_letter_count: int = 0,
    judge_queue_count: int = 0,
    resolved_judgement_count: int = 0,
    keypoints_pending_count: int = 0,
) -> BaselineProductArtifacts:
    """便捷构造：给定各产物 sha256 与计数，自动推导未解决数与 keypoints 状态（供 020/测试）。"""
    keypoints_status: Literal["complete", "pending"] = (
        "complete" if keypoints_pending_count == 0 else "pending"
    )
    return BaselineProductArtifacts(
        product_id=product_id,
        run_manifest_sha256=shas["run_manifest"],
        pred_sha256=shas["pred"],
        pred_count=pred_count,
        dead_letter_sha256=shas["dead_letter"],
        dead_letter_count=dead_letter_count,
        judge_queue_sha256=shas["judge_queue"],
        judge_queue_count=judge_queue_count,
        judgements_sha256=shas["judgements"],
        resolved_judgement_count=resolved_judgement_count,
        keypoints_status=keypoints_status,
        keypoints_sha256=shas.get("keypoints") if keypoints_status == "complete" else None,
        keypoints_pending_count=keypoints_pending_count,
        eval_report_sha256=shas["eval_report"],
        unresolved_judge_count=max(judge_queue_count - resolved_judgement_count, 0),
        unresolved_dead_letter_count=dead_letter_count,
    )

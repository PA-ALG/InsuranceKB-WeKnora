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
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .records import GoldenRecord

if TYPE_CHECKING:
    from .profile import QualityProfile, RegressionThresholds

# 领域数值合法域（让"越界即非法"在构造期不可构造，不只是拒 NaN/Inf）：
# - Rate：比率/精度类指标与阈值恒在 [0,1] 且有限；
# - NonNegativeInt：计数不得为负（否则正负相消会掩盖真实未解决项，违反 Q2.2 fail-closed）。
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Rate = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(ge=0)]


def _validate_identifier(v: str) -> str:
    if not v.strip():
        raise ValueError("标识符不得为空/纯空白")
    if v != v.strip():
        raise ValueError(
            "标识符不得带首尾空白（避免审计歧义，并防止 'x ' 之类空白变体绕过新 lineage 精确匹配）"
        )
    return v


# baseline_id 等标识符：构造期即拒空/纯空白/带首尾空白（红队 R6/弱点2）。
Identifier = Annotated[str, AfterValidator(_validate_identifier)]

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


def _canon_hash(v: str) -> str:
    """SHA 文本身份的规范形（去首尾空白 + 小写）——身份比较的**单一权威**。

    构造期由 Sha256Hex 严格校验并规范化；此函数供**比较点**二次规范化，使身份比较不依赖
    单一构造期不变量——防止绕过构造校验（model_copy/model_construct，无 revalidate_instances）
    塞入的未规范化值制造"同 digest 两身份"、重开 reset 洗白（红队 F）。
    """
    return v.strip().lower()


def _validate_sha256_hex(v: str) -> str:
    if not _SHA256_HEX.fullmatch(v):
        raise ValueError("必须是规范 SHA-256：64 位十六进制、无首尾空白")
    return _canon_hash(v)  # 规范化为小写，使同一 digest 只有唯一文本身份


# 内容身份哈希：构造期强制 64 位 hex 并规范化为小写（codex 六轮 #2）。
# 同一 SHA 的大小写/空白变体不得成为两个"身份"——否则 reset 的"同 golden 集必回归"可被绕过。
Sha256Hex = Annotated[str, AfterValidator(_validate_sha256_hex)]


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
    golden_release_hash: Sha256Hex  # 内容身份：64hex + 规范小写（六轮 #2；reset 比较依赖其唯一性）

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
    pred_count: NonNegativeInt
    dead_letter_sha256: str
    dead_letter_count: NonNegativeInt
    judge_queue_sha256: str
    judge_queue_count: NonNegativeInt
    judgements_sha256: str
    resolved_judgement_count: NonNegativeInt
    keypoints_status: Literal["complete", "pending"]
    keypoints_sha256: str | None
    keypoints_pending_count: NonNegativeInt
    eval_report_sha256: str
    unresolved_judge_count: NonNegativeInt
    unresolved_dead_letter_count: NonNegativeInt

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
        """可批准要求：内部一致 + keypoints 已完成 + 无未解决项。

        **逐项检查 judge/dead-letter 未解决数，不用合计 truthiness**——否则任一为负时正负相消
        会掩盖真实未解决项（配合 NonNegativeInt 双保险，Q2.2 fail-closed）。
        """
        blockers = self.consistency_errors()
        if self.keypoints_status != "complete":
            blockers.append(f"{self.product_id} 关键点未完成（keypoints=pending）")
        if self.unresolved_judge_count:
            blockers.append(
                f"{self.product_id} 仍有 {self.unresolved_judge_count} 条待裁决未解决"
            )
        if self.unresolved_dead_letter_count:
            blockers.append(
                f"{self.product_id} 仍有 {self.unresolved_dead_letter_count} 条 dead-letter 未解决"
            )
        return blockers


class BaselineArtifact(BaseModel):
    """一次 baseline 运行的不可变 artifact（Q2.1/Q2.2）；有 canonical 内容哈希用于批准绑定。"""

    model_config = ConfigDict(frozen=True)

    baseline_id: Identifier
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
    """独立、不可改写的批准记录（Q2.3）；**同时提交被批准 artifact 与画像的内容哈希**。

    - `artifact_sha256`：绑定被批准的 baseline 产物输出内容（实施计划 Task3）；
    - `profile_content_sha256`：**提交被批准画像的内容哈希**（四轮 #1/#2）——批准即"提交这份
      画像内容"，任何替换指标/指纹的画像 content_hash 必不同，无法用可复制的公开 approval
      哈希冒充"已批准画像"。两者都进入 `sha256()`，批准身份对 (artifact, 画像) 唯一。
    """

    model_config = ConfigDict(frozen=True)

    baseline_id: Identifier
    version: int
    approved_by: str
    approved_at: datetime
    fingerprint: RunFingerprint
    artifact_sha256: str
    profile_content_sha256: str
    # 该批准是否为显式 lineage 重置（跳过了与上一生产基线的回归）——记录在案以便审计，
    # 使"跳过回归"永不静默（reset 必须显式、开新 lineage、带理由）。
    lineage_reset: bool = False
    lineage_reset_reason: str | None = None

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
    allow_lineage_reset: bool = False,
    lineage_reset_reason: str | None = None,
    approved_at: datetime | None = None,
) -> ApprovalRecord:
    """对 (artifact, 派生画像) 产出一条不可改写、提交 artifact 与画像内容哈希的批准记录。

    让非法状态无法构造，而非信任调用方：
    - **画像必须派生自该 artifact**：`profile.artifact_sha256 == artifact.sha256()` 且指纹一致；
    - **回归不可绕过、不可伪造、不可靠换 id 跳过**：只要系统已有生产批准（`prior` 非空），候选
      就必须与**当前生产基线**（`prior` 中最近一条，跨 baseline_id）比较——必须提供 `prior_profile`
      且其内容哈希正是该生产批准提交的画像（`content_hash() == latest.profile_content_sha256`，
      四轮 #1/#3），回归由本函数内部跑 `compare_baselines`，退化即拒（Q4.6）；
    - **lineage 重置只对真正的新评测基准开放**：`allow_lineage_reset=True` 才跳过回归，且必须
      (a) `prior` 非空（无生产基线无从 reset，首批准本就免回归——红队 R6/弱点3）、
      (b) `artifact.baseline_id` 不在任何 prior 中（不能给同 id 降级）、
      (c) **`golden_release_hash` 与所有 prior 不同**——golden 集才是评测基准；同一 golden 集换个
      新 id 仍必须走零容差回归，不得借 reset（换 id/换模型）洗白降级（红队 R6/弱点1）、
      (d) 提供非空 `lineage_reset_reason`（记入 ApprovalRecord，可审计）。本 bool 只是 019 层的
      **结构约束 + 审计信号**；真正的人工授权真实性由 020 提供不可伪造的授权输入（见文档边界）；
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
    if allow_lineage_reset:
        if not prior:
            raise BaselineNotApprovableError(
                "lineage_reset 无意义：无 prior 生产批准可重置（首批准本就免回归，属调用方误用）"
            )
        if artifact.baseline_id in {r.baseline_id for r in prior}:
            raise BaselineNotApprovableError(
                f"lineage_reset 必须开新 lineage：baseline_id {artifact.baseline_id} 已存在于"
                "生产批准中，不能用 reset 给同一 lineage 降级/跳过回归"
            )
        if _canon_hash(artifact.fingerprint.golden_release_hash) in {
            _canon_hash(r.fingerprint.golden_release_hash) for r in prior
        }:
            raise BaselineNotApprovableError(
                f"lineage_reset 必须是真正的新评测基准：golden 集 "
                f"{artifact.fingerprint.golden_release_hash} 与现有生产基线相同——"
                "同一 golden 集必须走零容差回归，不得借 reset（换 id/换模型/大小写变体）洗白降级"
            )
        if not (lineage_reset_reason and lineage_reset_reason.strip()):
            raise BaselineNotApprovableError(
                "lineage_reset 必须提供非空 reason（记入批准记录以便审计）"
            )
    blockers = artifact.approval_blockers()
    # 当前生产基线 = 全部 prior 中最近一条（跨 baseline_id；换 id 不能另起免检 lineage）。
    if prior and not allow_lineage_reset:
        latest = max(prior, key=lambda r: (r.approved_at, r.version, r.baseline_id))
        if prior_profile is None:
            raise BaselineNotApprovableError(
                f"baseline {artifact.baseline_id} 已有生产基线，必须提供 prior_profile "
                "做回归检查（Q4.6 不可省略；换 baseline_id 也不例外）"
            )
        if prior_profile.content_hash() != latest.profile_content_sha256:
            raise BaselineNotApprovableError(
                f"baseline {artifact.baseline_id} 不可批准：prior_profile 不是当前生产基线所"
                "批准的画像（内容哈希不符——回归基线被伪造/替换/靠换 id 绕过）"
            )
        # 零容差回归必须在**同一 golden 集**（评测基准一致）上比较——否则候选可借 disputed 削弱
        # 自身评测面（≤5% 过 validator）藏退化，把非对称评测集偷渡过回归（红队 E/3b）。reset 路径
        # 强制 golden 集必须**不同**且留审计；非 reset 路径对称地要求 golden 集必须**相同**。
        if _canon_hash(artifact.fingerprint.golden_release_hash) != _canon_hash(
            latest.fingerprint.golden_release_hash
        ):
            raise BaselineNotApprovableError(
                f"baseline {artifact.baseline_id} 不可批准：候选与生产基线的 golden 集不同，"
                "零容差回归无从在同一评测基准上比较——真正的新评测基准须走 allow_lineage_reset"
                "（另起 lineage、留审计），不得靠换/削弱评测集静默通过回归"
            )
        from .profile import compare_baselines  # 延迟导入避免 baseline↔profile 循环

        result = compare_baselines(prior_profile, profile, thresholds)
        if result.failures:
            blockers.append("回归失败：" + result.summary())
    if blockers:
        raise BaselineNotApprovableError(
            f"baseline {artifact.baseline_id} 不可批准：{blockers}"
        )
    same_baseline = [r for r in prior if r.baseline_id == artifact.baseline_id]
    next_version = max((r.version for r in same_baseline), default=0) + 1
    is_reset = bool(prior) and allow_lineage_reset
    return ApprovalRecord(
        baseline_id=artifact.baseline_id,
        version=next_version,
        approved_by=approved_by,
        approved_at=approved_at or datetime.now(UTC),
        fingerprint=artifact.fingerprint,
        artifact_sha256=art_hash,
        profile_content_sha256=profile.content_hash(),
        lineage_reset=is_reset,
        lineage_reset_reason=lineage_reset_reason if is_reset else None,
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

"""红队：gate 纯逻辑攻击（方向 3 版本校验时序、方向 4 pending 与 eligible 顺序）。

运行：cd harness && export PATH=... && uv run python <this>
"""

from datetime import UTC, datetime

from insurance_harness.goldenset.baseline import (
    RunFingerprint,
    approve_baseline,
    build_product_artifacts,
)
from insurance_harness.goldenset.baseline import BaselineArtifact
from insurance_harness.goldenset.profile import (
    FieldMetrics,
    GlobalMetrics,
    QualityProfile,
)
from insurance_harness.knowledge.quality_gate import (
    SUPPORTED_PROFILE_VERSION,
    QualityGate,
)

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_FIELD = "waiting_period"
_HEX = "a" * 64


def _fp(**ov: str) -> RunFingerprint:
    base = dict(
        git_sha="abc", schema_version="v1.1+x", model_id="m1", prompt_version="p1",
        template_profile="t1", source_profile="s1", golden_release_hash="rh1",
    )
    base.update(ov)
    return RunFingerprint(**base)


def _metrics(**ov: object) -> FieldMetrics:
    base: dict[str, object] = dict(
        field_id=_FIELD, support=10, value_accuracy=1.0, hallucination_rate=0.0,
        evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
    )
    base.update(ov)
    return FieldMetrics(**base)  # type: ignore[arg-type]


def _artifact(fp: RunFingerprint) -> BaselineArtifact:
    shas = {k: _HEX for k in (
        "run_manifest", "pred", "dead_letter", "judge_queue", "judgements",
        "keypoints", "eval_report",
    )}
    product = build_product_artifacts("P1", shas=shas, pred_count=12)
    return BaselineArtifact(baseline_id="b1", fingerprint=fp, products=(product,))


def _approved_profile(version: object, fp: RunFingerprint) -> tuple[QualityProfile, object]:
    """完整可批准链，profile_version 可注入任意值。返回 (已批准画像, approval)。"""
    artifact = _artifact(fp)
    candidate = QualityProfile(
        profile_version=version,  # type: ignore[arg-type]
        artifact_sha256=artifact.sha256(), baseline_approval_sha256="",
        fingerprint=fp, fields={_FIELD: _metrics()},
        global_metrics=GlobalMetrics(micro_f1=1.0, macro_f1=1.0,
                                     hallucination_rate=0.0, evidence_accuracy=1.0),
    )
    approval = approve_baseline(artifact, candidate, approved_by="claude", approved_at=_AT)
    return candidate.with_approval(approval), approval


def sec(t: str) -> None:
    print(f"\n{'='*70}\n{t}\n{'='*70}")


findings: list[str] = []

# ---------------------------------------------------------------- 方向 3
sec("方向 3：版本校验能否让 profile_version != '1' 走到 eligible")
print(f"SUPPORTED_PROFILE_VERSION = {SUPPORTED_PROFILE_VERSION!r}")

# 3a: v999 走完整批准链 —— 期望被拒（版本）
fp = _fp()
approved999, appr999 = _approved_profile("999", fp)
d = QualityGate(approved999, approval=appr999).decide(_FIELD, "low", "add", fp)
print(f"3a v999 完整批准链: eligible={d.eligible} reason={d.reason!r}")
assert not d.eligible, "v999 竟然 eligible！"
assert "版本" in d.reason
if d.eligible:
    findings.append("方向3: v999 绕过版本校验")

# 3b: 各种非 '1' 字符串是否都被拒
for v in ["1 ", " 1", "01", "1.0", "1\n", "v1", "", "11", "10"]:
    ap, apr = _approved_profile(v, _fp())
    dd = QualityGate(ap, approval=apr).decide(_FIELD, "low", "add", _fp())
    ok = (not dd.eligible) and ("版本" in dd.reason)
    print(f"3b version={v!r:8} -> eligible={dd.eligible} deny_by_version={ok}")
    if dd.eligible:
        findings.append(f"方向3: version={v!r} 绕过")

# 3c: pydantic 对非 str 输入（int/bool/float）的强制转换行为
print("\n3c pydantic 对非字符串 profile_version 的处理：")
for raw in [1, True, 1.0, "1"]:
    try:
        ap, apr = _approved_profile(raw, _fp())
        stored = ap.profile_version
        dd = QualityGate(ap, approval=apr).decide(_FIELD, "low", "add", _fp())
        print(f"   输入 {raw!r:6}({type(raw).__name__:5}) -> 存为 {stored!r:6}"
              f"({type(stored).__name__}) eligible={dd.eligible}")
        # 若非 '1' 输入被强制成 '1' 且 eligible，才算问题；'1'/1 -> '1' 是合法 v1
        if dd.eligible and str(raw) not in ("1", "True", "1.0"):
            findings.append(f"方向3: 非法输入 {raw!r} 被强制成 '1' 且 eligible")
        if dd.eligible and stored != "1":
            findings.append(f"方向3: 存储值 {stored!r}!='1' 却 eligible（矛盾）")
    except Exception as e:  # noqa: BLE001
        print(f"   输入 {raw!r:6}({type(raw).__name__:5}) -> 构造被拒: {type(e).__name__}")

# ---------------------------------------------------------------- 方向 4
sec("方向 4：pending 的 deny 是否被任何 eligible 分支抢先绕过")
# 4a: 一份本来完美达标（会 eligible）的画像 + pending=True -> 必须 deny 且原因是 pending
fp = _fp()
approved1, appr1 = _approved_profile("1", fp)
gate = QualityGate(approved1, approval=appr1)
base = gate.decide(_FIELD, "low", "add", fp)
print(f"4a 基线（pending=False）: eligible={base.eligible} reason={base.reason!r}")
assert base.eligible, "基线画像未 eligible，测试前提失效"
pend = gate.decide(_FIELD, "low", "add", fp, pending_judge=True)
print(f"4a 同画像 pending=True:  eligible={pend.eligible} reason={pend.reason!r}")
assert not pend.eligible and "pending_judge" in pend.reason
if pend.eligible:
    findings.append("方向4: pending=True 仍 eligible")

# 4b: 穷举 (action, risk) 组合，pending=True 时是否有任一 eligible 泄漏
print("\n4b 穷举 pending=True：")
leak = False
for action in ["add", "enrich", "supersede", "conflict", "retract", ""]:
    for risk in ["low", "medium", "high"]:
        r = gate.decide(_FIELD, risk, action, fp, pending_judge=True)
        if r.eligible:
            leak = True
            print(f"   泄漏! action={action!r} risk={risk!r} eligible=True")
print(f"   任一 pending=True 组合 eligible? {leak}")
if leak:
    findings.append("方向4: 存在 pending=True 仍 eligible 的组合")

# 4c: pending 是否在 profile/approval 缺失前就 deny（顺序证据）——不算漏洞，仅记录顺序
none_gate = QualityGate(None, approval=None)
r = none_gate.decide(_FIELD, "low", "add", fp, pending_judge=True)
print(f"\n4c profile=None + pending=True -> reason={r.reason!r} "
      f"(pending 早于 profile-None 检查 => {'pending' if 'pending' in r.reason else 'profile'})")

# ---------------------------------------------------------------- 结论
sec("gate 逻辑攻击结论")
if findings:
    print("发现可复现问题：")
    for f in findings:
        print("  -", f)
else:
    print("方向 3、4：未发现绕过。版本校验为严格字符串 !=，pending 的 deny 早于唯一的 eligible 返回。")

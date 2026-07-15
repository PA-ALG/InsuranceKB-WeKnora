"""方向2+6：reset 是否真的'只对真正的新 lineage 开放'？
攻击：系统已有强生产基线 A（value=1.0，同一 golden 集）。攻击者用【完全相同的 fingerprint/
golden_release_hash】（即同一 golden 集 = 同一 lineage）+ 一个新 baseline_id 字符串 +
退化到 gate 绝对下限的指标，走 allow_lineage_reset=True。
若被接受，则'真正的新 lineage'的说法未被 fingerprint 强制，reset 沦为'同 lineage 降级'。
再把结果接到 QualityGate.decide 看是否 eligible（端到端洗白）。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from insurance_harness.goldenset import BaselineNotApprovableError, approve_baseline
from insurance_harness.knowledge.quality_gate import QualityGate
from fixtures import AT, B, artifact, candidate, fp, raw_product

SHARED_FP = fp(golden_release_hash="rh1", source_profile="src1", model_id="m1")

print("=== 生产基线 A：强画像 value=1.0，golden_release_hash=rh1 ===")
a = artifact(baseline_id="prod-A", fingerprint=SHARED_FP)
prod = approve_baseline(a, candidate(a, value_accuracy=1.0), approved_by="claude", approved_at=AT)
prod_profile = candidate(a, value_accuracy=1.0).with_approval(prod)
print(f"  prod approved: baseline_id={prod.baseline_id} v{prod.version} "
      f"lineage_reset={prod.lineage_reset}")

print("\n=== 对照：常规路径提交同一 golden 集的退化候选（value 1.0->0.98）应被回归拦截 ===")
try:
    approve_baseline(a, candidate(a, value_accuracy=0.98), approved_by="attacker",
                     prior=[prod], prior_profile=prod_profile, approved_at=AT)
    print("  常规路径 -> ACCEPTED (意外)")
except BaselineNotApprovableError as e:
    print(f"  常规路径 -> REJECTED (回归拦截): {str(e)[:70]}")

print("\n=== 攻击 A：同一 fingerprint（同 golden 集）+ 新 baseline_id 'gs-v2-rebrand' + reset ===")
# 注意 fingerprint 与生产基线【完全相同】：golden_release_hash 都是 rh1 -> 同一 ground truth
evil = artifact(baseline_id="gs-v2-rebrand", fingerprint=SHARED_FP,
                products=(raw_product(pred_sha256=B),))
evil_prof = candidate(evil, value_accuracy=0.98, hallucination_rate=0.01)  # 退化到绝对下限
print(f"  evil.fingerprint == prod.fingerprint ? {evil.fingerprint == prod.fingerprint}")
print(f"  evil.golden_release_hash = {evil.fingerprint.golden_release_hash} (与生产同一 golden 集)")
try:
    rec = approve_baseline(evil, evil_prof, approved_by="attacker", prior=[prod],
                           allow_lineage_reset=True,
                           lineage_reset_reason="启用 gs-v2", approved_at=AT)
    print(f"  reset -> ACCEPTED !!! baseline_id={rec.baseline_id} v{rec.version} "
          f"lineage_reset={rec.lineage_reset} (回归被完全跳过，尽管是同一 golden 集)")
    approved_evil = evil_prof.with_approval(rec)
    # 端到端：接到 gate
    gate = QualityGate(approved_evil, approval=rec)
    d = gate.decide("f1", "low", "add", SHARED_FP)
    print(f"  QualityGate.decide -> eligible={d.eligible}  reason={d.reason!r}")
    if d.eligible:
        print("  >>> 端到端洗白成功：同 golden 集的退化画像（value=0.98<生产1.0）拿到自动发布资格")
except BaselineNotApprovableError as e:
    print(f"  reset -> REJECTED: {str(e)[:70]}")

print("\n=== 攻击 B：'同一 lineage'的 baseline_id 只需空白/大小写变体即可绕过 'new lineage' 检查 ===")
for variant in ["prod-A ", " prod-A", "prod-A\n", "PROD-A", "prod-A\t"]:
    v_art = artifact(baseline_id=variant, fingerprint=SHARED_FP,
                     products=(raw_product(pred_sha256=B),))
    v_prof = candidate(v_art, value_accuracy=0.98)
    try:
        rec = approve_baseline(v_art, v_prof, approved_by="attacker", prior=[prod],
                               allow_lineage_reset=True,
                               lineage_reset_reason="reset", approved_at=AT)
        print(f"  baseline_id={variant!r:>12} (肉眼=生产'prod-A') -> ACCEPTED as new lineage "
              f"(v{rec.version}, reset={rec.lineage_reset})")
    except BaselineNotApprovableError as e:
        print(f"  baseline_id={variant!r:>12} -> REJECTED: {str(e)[:40]}")

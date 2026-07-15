"""方向4：latest=max(prior, key=(approved_at, version, baseline_id))。
approved_at 由调用方可控；构造相等 approved_at + 相等 version，让 baseline_id 字典序决出 latest。
目标：让一个【较弱】的批准被选成'当前生产基线'，使退化候选通过回归。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import UTC, datetime

from insurance_harness.goldenset import BaselineNotApprovableError, approve_baseline
from fixtures import AT, B, artifact, candidate, fp, raw_product

FP = fp()
T = datetime(2026, 7, 14, tzinfo=UTC)

print("=== 建立生产历史：强 lineage 'aaa'(value=1.0) ===")
a_strong = artifact(baseline_id="aaa-strong", fingerprint=FP)
rec_strong = approve_baseline(a_strong, candidate(a_strong, value_accuracy=1.0), approved_by="c", approved_at=T)
p_strong = candidate(a_strong, value_accuracy=1.0).with_approval(rec_strong)

print("=== 攻击者用 reset 引入弱 lineage（value=0.98），并把 approved_at 设成与强基线【相等】、")
print("    baseline_id 选成字典序【更大】'zzz'，从而在 tie-break 中胜出成为 latest ===")
a_weak = artifact(baseline_id="zzz-weak", fingerprint=FP, products=(raw_product(pred_sha256=B),))
rec_weak = approve_baseline(a_weak, candidate(a_weak, value_accuracy=0.98), approved_by="attacker",
                            prior=[rec_strong], allow_lineage_reset=True,
                            lineage_reset_reason="reset", approved_at=T)  # 同一 approved_at=T
p_weak = candidate(a_weak, value_accuracy=0.98).with_approval(rec_weak)

prior = [rec_strong, rec_weak]
latest = max(prior, key=lambda r: (r.approved_at, r.version, r.baseline_id))
print(f"  approved_at 相等? {rec_strong.approved_at == rec_weak.approved_at}; "
      f"version 相等? {rec_strong.version == rec_weak.version}")
print(f"  max-key 选出的 latest = {latest.baseline_id} "
      f"(value={'0.98 弱' if latest is rec_weak else '1.0 强'})  <- 由 baseline_id 字典序决定")

print("\n=== 后果：后续 0.98 退化候选，对'当前生产基线'跑回归 ===")
print("  (a) 若正确地对【强基线 1.0】回归：")
try:
    approve_baseline(a_strong, candidate(a_strong, value_accuracy=0.98), approved_by="x", prior=[rec_strong],
                     prior_profile=p_strong, approved_at=T)
    print("      -> ACCEPTED (意外)")
except BaselineNotApprovableError as e:
    print(f"      -> REJECTED（应当）：{str(e)[:45]}")

print("  (b) 攻击者对被操纵成 latest 的【弱基线 0.98】回归（提供 p_weak）：")
try:
    c2 = artifact(baseline_id="zzz-weak", fingerprint=FP, products=(raw_product(pred_sha256=B),))
    # 同 lineage v2：baseline_id 与弱基线相同，走常规回归路径，latest 必须是弱基线
    rec2 = approve_baseline(c2, candidate(c2, value_accuracy=0.98), approved_by="attacker",
                            prior=prior, prior_profile=p_weak, approved_at=T)
    print(f"      -> ACCEPTED：退化 0.98 候选借'弱 latest'通过回归 (v{rec2.version})")
    print("      >>> tie-break 放大：把生产基线选成弱基线后，退化候选可持续过关")
except BaselineNotApprovableError as e:
    print(f"      -> REJECTED：{str(e)[:60]}")

print("\n=== 补充：approved_at 直接可控（无需 tie-break，把 reset 设成更晚即成 latest）===")
later = datetime(2027, 1, 1, tzinfo=UTC)
rec_weak_later = approve_baseline(
    artifact(baseline_id="bbb-weak", fingerprint=FP, products=(raw_product(pred_sha256=B),)),
    candidate(artifact(baseline_id="bbb-weak", fingerprint=FP, products=(raw_product(pred_sha256=B),)), value_accuracy=0.98),
    approved_by="attacker", prior=[rec_strong], allow_lineage_reset=True,
    lineage_reset_reason="reset", approved_at=later)
latest2 = max([rec_strong, rec_weak_later], key=lambda r: (r.approved_at, r.version, r.baseline_id))
print(f"  设 approved_at=2027 的弱 reset -> latest={latest2.baseline_id} "
      f"({'弱基线成为当前生产基线' if latest2 is rec_weak_later else '强'})")

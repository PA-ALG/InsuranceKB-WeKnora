"""方向1（空白 reason）+ 方向5（伪造 prior_profile）：验证是否已被防住。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from insurance_harness.goldenset import BaselineNotApprovableError, approve_baseline
from fixtures import AT, B, artifact, candidate, fp, raw_product


def try_reset(reason, label):
    b1 = artifact(baseline_id="b1", fingerprint=fp())
    prod = approve_baseline(b1, candidate(b1, value_accuracy=1.0), approved_by="claude", approved_at=AT)
    b2 = artifact(baseline_id="b2", fingerprint=fp(), products=(raw_product(pred_sha256=B),))
    try:
        rec = approve_baseline(b2, candidate(b2, value_accuracy=1.0), approved_by="human",
                               prior=[prod], allow_lineage_reset=True,
                               lineage_reset_reason=reason, approved_at=AT)
        print(f"  [{label}] reason={reason!r:>8} -> ACCEPTED  lineage_reset={rec.lineage_reset} "
              f"stored_reason={rec.lineage_reset_reason!r}")
        return True
    except BaselineNotApprovableError as e:
        print(f"  [{label}] reason={reason!r:>8} -> REJECTED  ({str(e)[:40]}...)")
        return False


print("=== 方向1：空白/无意义 reason 能否通过 reset 的'非空 reason'检查 ===")
for reason, label in [("   ", "3空格"), ("\n", "换行"), ("\t ", "tab+空格"),
                      ("", "空串"), (".", "单点"), ("x", "单字符")]:
    try_reset(reason, label)

print("\n=== 方向5：伪造低标准 prior_profile（内容哈希是否含指标）===")
a = artifact()
first = approve_baseline(a, candidate(a, value_accuracy=1.0), approved_by="claude", approved_at=AT)
forged = candidate(a, value_accuracy=0.1)  # 未被批准的假基线，指标很低
cand = candidate(a, value_accuracy=0.99)
try:
    approve_baseline(a, cand, approved_by="claude", prior=[first],
                     prior_profile=forged, approved_at=AT)
    print("  伪造 prior_profile -> ACCEPTED  (!!! 绕过：content_hash 未含指标)")
except BaselineNotApprovableError as e:
    print(f"  伪造 prior_profile -> REJECTED  ({str(e)[:50]}...)")
# 证明 content_hash 确实随指标变化
print(f"  content_hash(v=1.0) == content_hash(v=0.1) ? "
      f"{candidate(a, value_accuracy=1.0).content_hash() == forged.content_hash()}")

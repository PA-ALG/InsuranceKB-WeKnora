"""方向3：首批准/空 prior 边界。allow_lineage_reset=True 但 prior=[] 时：
- 'new lineage'+'非空 reason' 校验块是否被跳过？
- 返回记录的 lineage_reset / reason 是什么？有无审计信息静默丢失 / 状态不自洽？
- 能否构造 lineage_reset=True 但 reason=None（自相矛盾）？"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from insurance_harness.goldenset import BaselineNotApprovableError, approve_baseline
from fixtures import AT, artifact, candidate, fp

a = artifact()

print("=== 首批准 prior=[]，allow_lineage_reset=True，但【不提供 reason】===")
rec = approve_baseline(a, candidate(a, value_accuracy=1.0), approved_by="human",
                       prior=[], allow_lineage_reset=True,
                       lineage_reset_reason=None, approved_at=AT)
print(f"  无报错。record.lineage_reset={rec.lineage_reset}  reason={rec.lineage_reset_reason!r}")
print("  -> 'reset 必须非空 reason' 校验被跳过（prior 为空使 'if allow_lineage_reset and prior' 为假）")

print("\n=== 首批准 prior=[]，allow_lineage_reset=True，【提供】reason='紧急初始化' ===")
rec2 = approve_baseline(a, candidate(a, value_accuracy=1.0), approved_by="human",
                        prior=[], allow_lineage_reset=True,
                        lineage_reset_reason="紧急初始化：跳过回归", approved_at=AT)
print(f"  record.lineage_reset={rec2.lineage_reset}  reason={rec2.lineage_reset_reason!r}")
print("  -> 调用方明确声明的 reset 意图 + reason 被【静默吞掉】（记录里 reset=False, reason=None）")

print("\n=== 试图构造 lineage_reset=True 但 reason=None（状态自洽性）===")
# 唯一能让 is_reset=True 的路径需要 prior 非空 -> 触发 reason 非空校验；故理论上无法。实测确认：
try:
    b1 = artifact(baseline_id="b1", fingerprint=fp())
    prod = approve_baseline(b1, candidate(b1), approved_by="c", approved_at=AT)
    b2 = artifact(baseline_id="b2", fingerprint=fp())
    bad = approve_baseline(b2, candidate(b2), approved_by="h", prior=[prod],
                           allow_lineage_reset=True, lineage_reset_reason=None, approved_at=AT)
    print(f"  reset=True/reason=None 构造成功? lineage_reset={bad.lineage_reset} reason={bad.lineage_reset_reason!r}")
except BaselineNotApprovableError as e:
    print(f"  非空 prior + reset + reason=None -> REJECTED（无法构造不自洽记录）: {str(e)[:40]}")
print("  结论：lineage_reset=True 必然 reason 非空（状态自洽）；风险在【首批准静默吞掉 reset 意图】。")

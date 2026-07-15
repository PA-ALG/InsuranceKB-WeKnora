"""红队方向1 补漏：merge 中两条 decision='auto_applied' 但**不经过 _gate_ok** 的路径
（unknown 占位 / 裁决 existing 胜）是否会发布任何东西？——即便 pending=True。"""

import sys
from pathlib import Path

# 便携化：从本脚本位置解析出仓库内 harness 目录（原为绝对本机路径）。
sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "harness"))

from sqlalchemy import select

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.db import models as _dbm  # noqa: F401
from insurance_harness.knowledge import tables as _kbt  # noqa: F401
from insurance_harness.knowledge import MergeEngine, MergePolicy
from insurance_harness.knowledge.merge import claim_value_text
from insurance_harness.knowledge.models import ProposedClaim, ProposedEvidence
from insurance_harness.knowledge.tables import Claim
from tests.kbhelpers import allow_all_gate, seed_bound_scope, seed_product

_N = 0


def fresh():
    global _N
    _N += 1
    e = make_engine(f"sqlite:///file:u{_N}?mode=memory&cache=shared&uri=true")
    Base.metadata.create_all(e)
    return make_session_factory(e)()


def prop(scope, ver, pred, *, value, state="present", authority=2, pending=False):
    ev = [] if state == "unknown" else [ProposedEvidence(
        knowledge_id="k1", doc_title="k1", quote="q", page=1,
        doc_role="official_desc", authority_level=authority)]
    return ProposedClaim(
        space_id=scope.space_id, product_version_id=ver.id, predicate=pred,
        field_name=pred, value_state=state, value=value, confidence=0.9,
        pending_judge=pending, evidence=ev)


def statuses(s, scope, pred):
    return sorted((claim_value_text(c), c.status) for c in s.execute(
        select(Claim).where(Claim.space_id == scope.space_id,
                            Claim.predicate == pred)).scalars())


bad = []
gate, fp = allow_all_gate()

print("== 路径A：unknown 占位（value_state=unknown，无 gate 调用），pending=True ==")
s = fresh()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="r", wiki_kb_id="w")
_, ver = seed_product(s, scope=scope)
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True),
                  quality_gate=gate, run_fingerprint=fp)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [prop(scope, ver, "wp", value=None, state="unknown", pending=True)])
st = statuses(s, scope, "wp")
print(f"   claims={st}  (期望 draft，禁止发布)")
if any(status == "published" for _v, status in st):
    bad.append("路径A unknown 占位竟发布")

print("\n== 路径B：裁决 existing 胜（低权威新值），existing 已发布，pending=True ==")
s = fresh()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="r", wiki_kb_id="w")
_, ver = seed_product(s, scope=scope)
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True),
                  quality_gate=gate, run_fingerprint=fp)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [prop(scope, ver, "cov", value="HIGH", authority=1)])  # 先发布高权威
print(f"   前置：{statuses(s, scope, 'cov')}")
cs2, _ = eng.open_change_set(source_kind="document")
# 低权威(authority=3)异值 -> new_auth(3) > old_auth(1) -> winner=existing -> auto_applied,无新发布
eng.apply_batch(cs2, [prop(scope, ver, "cov", value="LOW", authority=3, pending=True)])
st = statuses(s, scope, "cov")
print(f"   claims={st}")
pub_vals = {v for v, status in st if status == "published"}
print(f"   已发布的值={pub_vals}  (期望仅 {{'HIGH'}}，低权威新值 LOW 不得发布)")
if "LOW" in pub_vals:
    bad.append("路径B 低权威新值 LOW 竟发布")

print("\n== 结论 ==")
if bad:
    print("发现：", bad)
else:
    print("两条不经过 _gate_ok 的 auto_applied 路径均**不发布**任何事实"
          "（unknown→draft；existing 胜→无新发布）——方向1 无绕过。")

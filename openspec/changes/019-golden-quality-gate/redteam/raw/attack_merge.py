"""红队：merge 自动路径端到端攻击（方向 1 删预检查、方向 2 旧签名 gate、方向 5 端到端）。

运行：cd harness && export PATH=... && uv run python <this>

关键攻击对象：merge.py 删除 add/enrich/supersede 三处 `and not prop.pending_judge`
预检查后，pending 的安全**完全依赖注入 gate 的 decide 是否 honor pending_judge**。
"""

import sys
from pathlib import Path

# 便携化：从本脚本位置解析出仓库内 harness 目录（原为绝对本机路径）。
HARNESS = Path(__file__).resolve().parents[5] / "harness"
sys.path.insert(0, str(HARNESS))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from insurance_harness.db.base import Base, make_engine, make_session_factory  # noqa: E402
from insurance_harness.db import models as _dbm  # noqa: E402,F401
from insurance_harness.knowledge import tables as _kbt  # noqa: E402,F401
from insurance_harness.knowledge import MergeEngine, MergePolicy  # noqa: E402
from insurance_harness.knowledge.merge import claim_value_text  # noqa: E402
from insurance_harness.knowledge.models import ProposedClaim, ProposedEvidence  # noqa: E402
from insurance_harness.knowledge.quality_gate import (  # noqa: E402
    GateDecision,
    QualityGate,
    _AUTOMATABLE_ACTIONS,
)
from insurance_harness.knowledge.tables import Claim, ReviewItem  # noqa: E402
from tests.kbhelpers import allow_all_gate, green_gate, seed_bound_scope, seed_product  # noqa: E402

_COUNTER = 0


def fresh_session() -> Session:
    global _COUNTER
    _COUNTER += 1
    engine = make_engine(f"sqlite:///file:mem{_COUNTER}?mode=memory&cache=shared&uri=true")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def add_prop(scope, version_id, predicate, *, value="X", authority=2,
             quote="X 的证据", pending=False, confidence=0.9) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id, product_version_id=version_id, predicate=predicate,
        field_name=predicate, value_state="present", value=value, confidence=confidence,
        pending_judge=pending,
        evidence=[ProposedEvidence(
            knowledge_id="k1", doc_title="k1", quote=quote, page=1,
            doc_role="official_desc", authority_level=authority,
        )],
    )


def claims_by_pred(session, scope) -> dict:
    return {c.predicate: c for c in session.execute(
        select(Claim).where(Claim.space_id == scope.space_id)).scalars()}


def reviews(session, scope) -> list:
    return list(session.execute(
        select(ReviewItem).where(ReviewItem.space_id == scope.space_id)).scalars())


def sec(t: str) -> None:
    print(f"\n{'='*72}\n{t}\n{'='*72}")


findings: list[str] = []


# ================================================================= 方向1：记录 gate
class RecordingGate(QualityGate):
    """honor pending（与真实 gate 一致），但记录每次 decide 调用——用于证明
    add/enrich/supersede 三路径是否**都**经过 _gate_ok。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def decide(self, field_id, risk, action, run_fingerprint, *, pending_judge=False):
        self.calls.append((field_id, risk, action, pending_judge))
        if action not in _AUTOMATABLE_ACTIONS:
            return GateDecision(eligible=False, reason="不可自动化", field_id=field_id, action=action)
        if risk != "low":
            return GateDecision(eligible=False, reason="非low", field_id=field_id, action=action)
        if pending_judge:
            return GateDecision(eligible=False, reason="pending_judge", field_id=field_id, action=action)
        return GateDecision(eligible=True, reason="放行", field_id=field_id, action=action)


sec("方向1：三条自动路径（add / enrich / supersede）是否都经过 _gate_ok？"
    "\n（用 RecordingGate 记录 decide 调用；pending=True 应被 gate 挡下进审核）")

# --- add 路径 ---
s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
g = RecordingGate()
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True), quality_gate=g)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [add_prop(scope, ver.id, "waiting_period", pending=True)])
c = claims_by_pred(s, scope)["waiting_period"]
add_gated = any(call[2] == "add" and call[3] is True for call in g.calls)
print(f"[add]       gate 调用={g.calls}")
print(f"[add]       claim.status={c.status}  期望=candidate  gate收到add+pending={add_gated}")
assert add_gated, "add 路径未把 pending=True 交给 gate！"
assert c.status == "candidate", f"add pending 竟自动发布：{c.status}"
if c.status == "published":
    findings.append("方向1: add 路径 pending 自动发布")

# --- enrich 路径：先发布同值，再同值追加新证据触发 _do_enrich_append ---
s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
g = RecordingGate()
eng = MergeEngine(s, scope=scope,
                  policy=MergePolicy(auto_apply_add=True, auto_apply_enrich=True),
                  quality_gate=g)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [add_prop(scope, ver.id, "grace_period", value="V",
                              quote="首证", pending=False)])  # 先发布
pub = claims_by_pred(s, scope)["grace_period"]
print(f"\n[enrich]    前置发布 status={pub.status}（应 published）")
g.calls.clear()
revs_before = len(reviews(s, scope))
cs2, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs2, [add_prop(scope, ver.id, "grace_period", value="V",
                               quote="第二条不同证据", pending=True)])  # 同值+新证据+pending
enrich_gated = any(call[2] == "enrich" and call[3] is True for call in g.calls)
went_review = len(reviews(s, scope)) > revs_before
print(f"[enrich]    gate 调用={g.calls}")
print(f"[enrich]    gate收到enrich+pending={enrich_gated}  新增ReviewItem={went_review}"
      f"（pending 追加证据被挡下进审核，未自动 append）")
assert enrich_gated, "enrich 路径未把 pending=True 交给 gate！"
assert went_review, "enrich pending 未进审核（可能被自动 append）"
if not enrich_gated:
    findings.append("方向1: enrich 路径未经过 _gate_ok")

# --- supersede 路径：先发布低权威，再高权威异值 pending ---
s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
g = RecordingGate()
eng = MergeEngine(
    s, scope=scope,
    policy=MergePolicy(auto_apply_add=True, auto_apply_supersede_low_risk=True),
    quality_gate=g,
)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [add_prop(scope, ver.id, "coverage", value="OLD",
                              authority=2, quote="低权威", pending=False)])
old = claims_by_pred(s, scope)["coverage"]
print(f"\n[supersede] 前置发布 status={old.status}（应 published）value=OLD authority=2")
g.calls.clear()
cs2, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs2, [add_prop(scope, ver.id, "coverage", value="NEW",
                               authority=1, quote="高权威", pending=True)])  # 高权威胜->supersede
sup_gated = any(call[2] == "supersede" and call[3] is True for call in g.calls)
after_claims = list(s.execute(select(Claim).where(
    Claim.space_id == scope.space_id, Claim.predicate == "coverage")).scalars())
statuses = sorted((claim_value_text(c), c.status) for c in after_claims)
print(f"[supersede] gate 调用={g.calls}")
print(f"[supersede] gate收到supersede+pending={sup_gated}  (value,status)={statuses}")
assert sup_gated, "supersede 路径未把 pending=True 交给 gate！"
new_claim = [c for c in after_claims if claim_value_text(c) == "NEW"][0]
old_claim = [c for c in after_claims if claim_value_text(c) == "OLD"][0]
assert new_claim.status != "published", f"supersede pending 竟发布新值：{new_claim.status}"
assert old_claim.status == "published", f"旧值不应被撤：{old_claim.status}"
if new_claim.status == "published":
    findings.append("方向1: supersede 路径 pending 自动发布新值")
print("\n方向1 结论：add/enrich/supersede 三路径均把 (action, pending=True) 交给 gate，"
      "\n           gate 挡下后候选停 candidate 进审核——未发现绕过 _gate_ok 的路径。")


# ================================================================= 方向2a：旧签名 gate
sec("方向2a：注入**旧签名** gate（decide 不接受 pending_judge）会怎样？")


class OldSigGate:
    """四轮时代签名：decide(field_id, risk, action, run_fingerprint) —— 无 pending_judge。"""

    def decide(self, field_id, risk, action, run_fingerprint):  # noqa: ANN001
        if action in _AUTOMATABLE_ACTIONS and risk == "low":
            return GateDecision(eligible=True, reason="旧gate放行", field_id=field_id, action=action)
        return GateDecision(eligible=False, reason="旧gate拒", field_id=field_id, action=action)


s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True),
                  quality_gate=OldSigGate())  # type: ignore[arg-type]
cs, _ = eng.open_change_set(source_kind="document")
# 注意：连 pending=False 的普通候选都会触发（_gate_ok 无条件传 pending_judge=）
try:
    eng.apply_batch(cs, [add_prop(scope, ver.id, "waiting_period", pending=False)])
    c = claims_by_pred(s, scope)["waiting_period"]
    print(f"未抛异常，claim.status={c.status}")
    print(">>> 旧签名 gate 未导致异常（被吞成 fail-closed？静默漏检？需检查）")
    findings.append("方向2a: 旧签名 gate 未抛异常（意外）")
except TypeError as e:
    print(f">>> 抛 TypeError（fail-loud，破坏整批）：{e}")
    print(">>> 结论：_gate_ok 无 try/except，旧签名 gate 令**每条**自动候选（含非 pending）"
          "崩溃；\n    非静默绕过（无发布），但是健壮性/兼容性缺口——见修复建议。")
    findings.append("方向2a[健壮性]: 旧签名 gate -> 未捕获 TypeError -> 整批 merge 崩溃")
except Exception as e:  # noqa: BLE001
    print(f">>> 抛 {type(e).__name__}: {e}")


# ================================================================= 方向2b：忽略pending的新gate
sec("方向2b：注入接受 **kwargs 但**忽略** pending 的 gate（模拟 020 写错的新 gate）"
    "\n—— 证明删预检查后 merge 层对 pending **零独立防御**")


class PendingIgnoringGate:
    """新签名但漏 honor：**kwargs 吞掉 pending_judge，从不据此 deny。"""

    def decide(self, field_id, risk, action, run_fingerprint, **kwargs):  # noqa: ANN001
        # kwargs 里有 pending_judge=True，但这里**不看**它
        if action in _AUTOMATABLE_ACTIONS and risk == "low":
            return GateDecision(eligible=True, reason="放行(漏看pending)", field_id=field_id, action=action)
        return GateDecision(eligible=False, reason="拒", field_id=field_id, action=action)


s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True),
                  quality_gate=PendingIgnoringGate())  # type: ignore[arg-type]
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [add_prop(scope, ver.id, "waiting_period", pending=True)])
c = claims_by_pred(s, scope)["waiting_period"]
print(f"pending=True 候选（gate 漏看 pending）-> claim.status={c.status}")
if c.status == "published":
    print(">>> **BYPASS**：未裁决(pending)候选被自动发布。删掉 merge 的 `not prop.pending_judge`"
          "\n    预检查后，唯一防线是 gate；gate 一旦漏 honor pending，无兜底。")
    findings.append("方向2b[后果]: 删预检查后，gate 漏honor pending -> pending 候选自动发布（无兜底）")
else:
    print(f">>> 仍未发布（status={c.status}）——merge 层另有兜底？")


# ================================================================= 方向5：端到端 real gate
sec("方向5：端到端——真实 QualityGate(green_gate) + pending=True 走 add 自动路径")
s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
gate, fp = green_gate(["waiting_period"])
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True),
                  quality_gate=gate, run_fingerprint=fp)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [add_prop(scope, ver.id, "waiting_period", pending=True)])
c = claims_by_pred(s, scope)["waiting_period"]
revs = reviews(s, scope)
in_review = any(c.id in str(r.subject) for r in revs)
print(f"真实 gate + pending=True -> status={c.status}  进审核={in_review}")
assert c.status == "candidate" and in_review, "真实 gate 未挡下 pending！"
print(">>> 真实 gate 正确挡下：候选停 candidate + 进 ReviewItem，未丢弃、未发布。")

# 对照：同 gate pending=False -> 应发布
s = fresh_session()
scope = seed_bound_scope(s, tenant_id="t", raw_kb_id="raw", wiki_kb_id="wiki")
_, ver = seed_product(s, scope=scope)
gate, fp = green_gate(["waiting_period"])
eng = MergeEngine(s, scope=scope, policy=MergePolicy(auto_apply_add=True),
                  quality_gate=gate, run_fingerprint=fp)
cs, _ = eng.open_change_set(source_kind="document")
eng.apply_batch(cs, [add_prop(scope, ver.id, "waiting_period", pending=False)])
c = claims_by_pred(s, scope)["waiting_period"]
print(f"对照 pending=False -> status={c.status}（应 published，证明 gate 本可放行，"
      f"差别仅在 pending）")
assert c.status == "published"


# ================================================================= 汇总
sec("merge 端到端攻击汇总")
real_bypass = [f for f in findings if "方向1:" in f
               or "方向2b[后果]" in f or "方向2a: 旧签名 gate 未抛异常" in f]
robustness = [f for f in findings if "[健壮性]" in f]
consequence = [f for f in findings if "[后果]" in f]
print("发现清单：")
for f in findings:
    print("  -", f)
print(f"\n真实可复现『静默绕过当前代码』：{'无' if not real_bypass else real_bypass}")
print(f"健壮性/兼容缺口（fail-loud 崩溃）：{robustness or '无'}")
print(f"删预检查的后果（需注入不合规 gate 才触发）：{consequence or '无'}")

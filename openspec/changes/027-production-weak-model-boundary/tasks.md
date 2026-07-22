# 027 任务（风险 A；小 PR）

- [x] T1 枚举 production 模型与候选推进入口，写入 `entrypoint-inventory.md`；标注 owner、角色、当前模型来源和预期 guard
- [x] T2 写 `PWB1/PWB4` RED：冻结 027-owned strict request/rich binding/opaque capability/verifier Protocol；不可变身份、allowlist、独立 expected purpose/schema/Space/run；binding 保留 artifact+expiry、manifest/eligibility/Golden/routing/schema/template/structured-dispatch/model/deployment/caps/rights/provenance/integration SHA 并覆盖 strict-request 产生 full digest；手工 READY/自定义 verifier 拒绝；opaque permit 绑定 purpose/schema/Space/admission/request/full-binding/template/model/call-scope/expiry，cross-Space/profile/domain/manifest/structured-dispatch/template-lock/integration/request/binding replay零网络；027 不复制 030 验签
- [x] T3 实现冻结的 policy/permit/receipt 领域模型和单一 evaluator
- [x] T4 写 `PWB2` RED：CLI/API/package exports 的旁路枚举；在 compiler 入口最小接线；030/028 缺失时 typed fail closed
- [x] T5 写 `PWB3` RED：弱模型失败、模板失配、unknown identity 不得强模型 fallback 或推进候选；失败仅形成 compiler dead-letter/unknown，且 027 不越权声称通用 downstream artifact promotion gate
- [x] T6 关闭/隔离历史强 judge/fallback production 路由；offline-eval/replay/manual 必须显式 profile
- [ ] T7 focused → 相关 compiler/config suites → PR ready 时一次 full deterministic；validation report 真实 provider=`NOT RUN`
- [ ] T8 独立规格/质量复核；更新 HANDOFF MVP-0 一行与七段时间

完成前不得启动 028 的真实 provider wiring 或 030 live run。

## 裁决记录

- PWB1 corrective：`family` 纳入 `IdentityKey`；production config 仅作独立期望声明与 code-owned provider 能力域预检，不得再以自身 identity 构造 allowlist。具体 deployment/role/policy 批准只取 canonical `VerifiedAdmission` 的完整 identity 集合，并与 production profile、独立 model-plan hash 精确绑定。依据：PR #27 安全复核可稳定复现 family 标签伪装与 config 自批准。
- PWB1 final corrective：code-owned deny-only catalog 不再通过 prefix/marker 推断 family；当前 MVP 只接受原文 canonical ASCII lowercase `bailian`，并以互斥锚定根、受控 capability/size token 与严格 immutable anchor 解析 deployment。`qwen-gpt-04`/分隔变体/`qwen-minimax`/跨 family 根/Unicode 或大小写变体/短 digest 一律拒绝；强模型 marker 仅作纵深防御。exact deployment 批准仍只来自 opaque `VerifiedAdmission`，每次 guarded call 从当前 authority snapshot 重算完整角色 identity set。

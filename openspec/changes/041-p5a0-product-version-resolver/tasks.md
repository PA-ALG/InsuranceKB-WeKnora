# 041 · Tasks

## Contract Card

1. **单一职责**：把文档或章节确定性归属到 exact persisted
   `ProductVersion`，并为 fragment 提供纯继承绑定。
2. **Authority**：attested `KnowledgeScope` + 现有
   `InsuranceProduct/ProductVersion/ProductAlias`；解析器只读，不 mint
   product/version，不持久化 receipt。
3. **优先级**：version `terms_revision` 中的备案/注册编号 → exact product
   code/canonical name → `alias_type=manual AND source=manual` 的
   code-owned approved alias allowlist。任何 `source=auto` alias 都不定案。
4. **幂等与内容身份**：policy/result 统一使用 C0 `canonical_hash`；相同输入与
   主数据快照得到相同结果。
5. **失败边界**：冲突、歧义、无版本、跨 Space、主数据否决均 typed
   quarantine；零猜测、零部分 identity。
6. **路径预算**：OpenSpec 041、一个 plan、一个 resolver module、一个小型
   registration fill、一个 package export、resolver 与 registration 两个
   focused test、一个 fixture。
7. **禁止路径**：`HANDOFF.md`、`docs/insurance-kb/23-mvp-control-board.md`、
   `openspec/changes/README.md`、`harness/src/insurance_harness/config.py`、
   `harness/src/insurance_harness/jobs/**`、`harness/migrations/**`、CI。

## 执行清单

- [x] T1 fresh main / 独立 worktree / 041 空闲 / 现有 schema 可承载确认
- [x] T2 冻结 proposal、Contract Card 与验收规格
- [x] T3 RED：1072-1/1072-4、冲突/歧义/跨 Space/无版本
- [x] T4 RED：approved alias、auto registration alias、Product.filing_no
      非版本 fallback、candidate-only signals、master-data veto；新版本
      filing 优先、缺 filing 才用 registration、不同编号重放不改已有值、
      历史空值不回填
- [x] T5 RED：fragment inheritance、canonical hash 稳定性与 ORM
      identity-map 未落库篡改不构成 authority
- [x] T6 GREEN：最小 resolver kernel；新版本 registration fill 仅从同一
      ProductMeta 写入 terms_revision，已有版本永不改写
- [x] T7 focused + Ruff + mypy + strict OpenSpec + diff/scope/secret
- [x] T8 独立 Spec / Quality / Security 双审，唯一 I 按 TDD 关闭后
      `0C/0I/0M` 批准
- [ ] T9 commit、push、Draft PR；不 Ready、不 merge

## 验证状态

基线：`65 passed`（product routing + scoped product + C0 envelope）。
新增 focused：`27 passed`。受影响产品/C0 回归：`116 passed`。全 Harness
Ruff 通过；strict mypy `341 source files` 通过；OpenSpec strict 通过。

# 040 · Tasks

## Contract Card

1. **单一职责**：金标记录的 provenance 分级、权威来源 lift 装载、确定性验证
   内核与内容寻址体检报告。
   **非目标**：任何模型调用、重新标注、修改既有 golden 值、holdout custody、
   dev/acceptance 切分、evaluator 计分、正式冻结、补 `absent_explicitly`
   分母、`admission_*`/`run_020` 冻结件、Alembic 迁移。

2. **读写权威 / 事务边界 / 幂等键**
   - 纯读 + 旁路写：只读 `dataset/goldenset/wip-gs-v0.1/**` 与
     `dataset/shouxian_product/**`，产出独立 artifact；**不写回、不改任何
     既有 golden 文件**（033 §14.1 硬红线）。
   - 无 DB、无网络、无迁移。
   - 幂等性即确定性：同一输入字节 → 同一报告 canonical digest。
   - 权威来源唯一：`product_id`/`product_name` ← `product_meta.json`；
     `schema_version` ← `manifest.json`。其余不得推断。

3. **状态机**
   - `GoldenProvenanceClass`：`attributed | legacy_unattributed`，由内容自算，
     **无转换边**——升级只能由重新标注产生新记录，不存在原地改标记的路径。
   - 引文回验结果：`hit_on_page | hit_wrong_page | ambiguous_locator |
     not_found | empty_quote | document_missing`，封闭枚举，无 None/bool。

4. **威胁矩阵**
   - **伪造 receipt 洗白 legacy** → 分级内容自算，不接受自报；禁止 mtime/
     当前时间/占位串合成 `annotator_model`/`created_at`；无"信任"参数存在。
   - **legacy 静默混入 baseline** → 验收入口收到任一 legacy 即 typed 拒绝，
     不过滤后继续、不降级、不只告警；零部分 artifact。
   - **护栏净伤召回**（024 教训）→ 唯一性护栏必须与接受侧全集扫描成对；
     722 条既有命中全部仍通过，或被逐条解释；净下降即阻断。
   - **绑定钉在可变标签**（019 教训）→ 源文档以 SHA-256 标识，不以路径/文件名。
   - **第三套哈希规则** → 报告 digest 强制走 C0 `canonical_hash`。
   - **零分母给满分** → 零观测显式 `INSUFFICIENT_DATA`，denominator 必报。
   - **选择性标注消失** → 缺失字段逐个列出并留在分母。
   - **规范化掩盖差异** → 规范化规则显式声明且为纯函数；`hit_wrong_page` 与
     `not_found` 分开计数，均不计通过。

5. **exact 验收测试清单**
   - `test_provenance_class_*`：缺 receipt → legacy；无自报升级路径；
     验收入口含 legacy 即拒绝且零部分产出；种子入口成功且暴露分级计数。
   - `test_lift_authoritative_*`：三字段回填正确；缺 `product_meta`/空
     `planCode` → typed 拒绝；不以目录名代替；不合成 receipt。
   - `test_quote_verification_*`：`hit_on_page`/`hit_wrong_page`/`not_found`/
     `empty_quote`/`document_missing` 五态各一；规范化确定性。
   - `test_ambiguous_locator_*`：同页两处命中 → `ambiguous_locator`。
   - **`test_accept_side_full_scan_040`**（阻断项）：全库扫描，722 条既有
     `hit_on_page` 无未解释的净回归。
   - `test_structural_invariants_*`：present 无证据 / unknown 有值 / unknown
     有证据各产生 finding。
   - `test_field_closure_*`：缺字段逐个列出且留在分母。
   - `test_source_digest_*`：改名同 digest；改字节 digest 变。
   - `test_report_digest_*`：同输入同 digest；零观测 `INSUFFICIENT_DATA`。

6. **路径与规模预算**
   - 允许写入：`harness/src/insurance_harness/goldenset/`（新模块）、
     `harness/tests/`、`openspec/changes/040-*/`、
     `openspec/changes/README.md`（仅 040 占号一行）。
   - **禁止写入**：`harness/src/insurance_harness/`（`goldenset/` 以外，
     特别是 P1 的 job/outbox 域）、任何 migration、`dataset/**`、
     `pyproject.toml`/lockfile。
   - 生产代码目标 300–500 行；逻辑文件 ≤ 12；单一 migration = 无。

## 执行清单

- [ ] T1 占号 040 并推送分支（使编号在 origin 可见）
- [ ] T2 RED：provenance 分级与验收入口拒绝（G040.1）
- [ ] T3 RED：lift 装载器权威来源与禁伪造（G040.2）
- [ ] T4 RED：引文回验五态 + 唯一性护栏（G040.3 / G040.4 拒绝侧）
- [ ] T5 RED：接受侧全集扫描（G040.4 接受侧，阻断项）
- [ ] T6 RED：结构不变量与字段闭合（G040.5）
- [ ] T7 RED：源文档 digest 与报告 canonical digest（G040.6 / G040.7）
- [ ] T8 GREEN：实现内核，全部 RED 转绿
- [ ] T9 对 `wip-gs-v0.1` 全库生成体检报告 artifact 并记录结论
- [ ] T10 门禁：focused、Ruff、mypy、`openspec validate --strict`、
      deterministic lane；准确报告 NOT RUN 项
- [ ] T11 更新 23 号认领表本行、HANDOFF 当前状态、validation-report

## 验证状态

未开始。本文件在实施过程中持续更新，完成项须附证据（测试名与实际计数），
不得以"已实现"代替"已验证"。

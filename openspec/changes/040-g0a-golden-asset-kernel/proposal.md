# 040 · G0a 金标资产化内核

> 状态：实施中（总控窗口，2026-07-27）。授权：业务方 2026-07-27 口头指示
> （"要不你去做 golden set，把这块的质量大幅度提升下，建立一个 PR，新开一个
> worktree"）+ 23 号控制板 §8 D-2026-07-26-4（金标标注草稿即刻并行启动）。
> 权威设计源：033 §14.1（G0 门禁与防刷规则）+
> `docs/superpowers/specs/2026-07-27-enterprise-llm-wiki-knowledge-compilation-amendment.md`
> §2 `G0a+` 行。存量处置依据：24 号 §2 `goldenset` 行（拆分：019 的
> `eval/profile/baseline/assemble/validate/keypoints` 作为 **G0a 种子移植**）。

## 为什么做

本 change 开工前对 `dataset/goldenset/wip-gs-v0.1` 做了只读体检（11 产品 /
660 条记录 / 724 条 evidence），结论有一好一坏：

**内容质量远好于预期**——引文回验 **722/724 = 99.72%** 精确命中（按页号定位、
NFKC 规范化后精确子串匹配）；三态结构不变量**零违规**；**11/11 产品全字段闭合
标注**（60/60、61/61、59/59…），没有一个产品跳过字段。033 §14.1 最容易被规避的
"禁止只选择模型擅长的字段"这一条，这批数据做到了。

**但资产化为零，且既有验证从未真正运行过**：

1. **660 条记录中，能装入 019 定义的 `GoldenRecord` 模型的是 0 条。**
   数据只有 `doc/field_id/field_name/value/tri_state/evidence/reasoning` 七个
   字段，缺全部五个必填项：`product_id`、`product_name`、`schema_version`、
   `annotator_model`、`created_at`。019 的 `records.py`/`verify.py`/
   `validate.py` 经七轮复审建成，却**从未对真实金标数据跑过一次**——模型与
   数据是两条平行线。
2. **provenance 不可考**：`annotator_model` 与 `created_at` 在 manifest、
   fields.json、product_meta 中均无记录；`build_golden.py` 是硬编码绝对路径
   指向已不存在的 scratchpad 目录的一次性脚本，不可复现。这与工作约定第 5 条
   （"金标构建要做成独立的、可持续升级维护的标注 Agent 子系统，不是一次性
   脚本"）直接冲突。
3. **短引文无唯一性保证**：724 条 quote 中位长度 24 字符，**17 条 < 10 字符**
   （最短 5）。现有 locator 只到页级，短 quote 在同一页可多处命中，回验会产生
   假阳性。
4. **无文档字节绑定**：金标不 pin 源文档的 SHA-256。033 §14.1 防刷规则第 1 条
   要求"Golden release、Source、Schema、comparator 任一 hash 变化都必须升版
   并重跑"——无字节绑定则该规则形同虚设。

因此当前 `wip-gs-v0.1` 符合 033 §14.1 对它的定性（"只作为种子资产；它们不是
已批准的 G0 baseline"），但仓库里**没有任何机制阻止它被误用为 baseline**。
本 change 建立该机制。

## 本 Change 做什么

单一领域不变量：

> **金标记录必须能被其领域模型装载、通过全部确定性验证、并绑定不可伪造的
> provenance 分级；不满足的记录可以作为种子存在，但必须被显式标记为不可用于
> 验收，绝不能静默混入 baseline。**

- **Provenance 分级（fail-closed 内核）**：`attributed`（有完整 annotator
  receipt，可进入候选 baseline）与 `legacy_unattributed`（无 receipt，**永久
  不可用于 G0b/G0v 验收**）。分级由**内容自算**（依据 receipt 字段是否齐全），
  不接受调用方自报；升级只能通过重新标注产生新记录，不能原地改标记。
- **Lift 装载器**：把 `wip-gs-v0.1` 提升为 `GoldenRecord` 合规形态，五个缺失
  字段只从**权威来源**取值——`product_id` ← `product_meta.planCode`、
  `product_name` ← `product_meta.clauseName`、`schema_version` ←
  `manifest.schema_version`；`annotator_model`/`created_at` 不可考，一律落
  `legacy_unattributed`，**禁止用文件 mtime 或占位串伪造 receipt**。
- **确定性验证内核**（零模型、可复用于 G0-probe 与 G0a+）：引文回验（复用并
  收窄既有 `verify.verify_quotes`/`normalize.quote_in_page`）、三态结构不变量、
  全字段闭合覆盖（对账 `fields.json` 声明集）、**短引文唯一性**（新增：quote
  在其绑定页内必须唯一命中，多处命中即 typed 失败）、源文档 SHA-256 绑定。
- **内容寻址体检报告**：报告 digest 使用 **C0 的 `canonical.canonical_hash`**
  （本 change 是 C0 的第一个真实消费者），含 numerator/denominator 与逐类
  typed findings；失败项不得从分母消失。

## 不做什么（非目标）

- **不调用任何模型**：强模型标注器、≥2 模型交叉一致、分歧队列按 Amendment
  归 `G0a+`（依赖 P4c + P5a2），本 change 只建它们要消费的验证内核；
- **不重新标注、不修改任何既有 golden 值**：033 §14.1"实现 PR 不得同时修改
  Golden expected value"是硬红线；本 change 只读 `wip-gs-v0.1`，产出旁路
  artifact；
- **不做 holdout custody、dev/acceptance 切分、evaluator 计分、正式冻结**：
  归 `G0a+`；
- **不补 `absent_explicitly` 分母**（体检发现仅 15/660 = 2.3%，该维分母不足）：
  需要重新标注，单独 change；本 change 只把它作为 typed finding 报出；
- **不动 `admission_*`/`run_020`/`execution_artifacts_020`**：24 号定为冻结
  审计；
- 无 Alembic 迁移（P1 独占当前 migration lane，用 0015）。

## 影响面

- 新增：`goldenset/` 下的 lift/provenance/verification 模块 + 报告 artifact
  + 本 change + README 台账 040 占号；
- 修改：`verify.py`/`normalize.py` 仅做**收窄**（新增唯一性判定），既有
  722 条命中记录必须全部仍然通过——接受侧全集扫描是本 change 的阻断验收项
  （024 教训：护栏必须成对，只有拒绝侧的护栏会净伤召回）；
- 不动 `records.py` 的既有字段语义（只新增 provenance 分级为独立类型）；
- 无迁移、无 DB、无网络；deterministic lane 新增测试文件；
- 后续消费者：`G0-probe`（用同一内核量弱模型）、`G0a+`（标注子系统消费同一
  验证内核与 provenance 分级）。

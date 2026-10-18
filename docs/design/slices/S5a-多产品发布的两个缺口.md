# S5a · 多产品发布的两个缺口：整款替换与产品 pack 声明

> 状态：用户已确认（2026-10-18："不止跑 1828，跑多几份，额度批准"；"养老年金 那肯定是年金啊"） ｜ 作者：Claude Code
> 依据：蓝图 §6.2（Candidate 是相对 base Release 的 delta）、§7.1；Issue #207 的准备结论
> 分支：`slice/s5a` ｜ 工作目录：`.worktrees/s5a` ｜ 实现方：Claude ｜ 审核方：Codex（发布语义、跨组件合同字段的使用）
> 实现时机：与 S4j（#206）都要改 `claims.py`、`publish.py`、`product_sources.py`，等 S4j 合并后再 merge main 实现；Spec 与函数级 RED 先行。

## 1. 问题

1. **整款替换**：
   - 平台激活时把候选包合并进当前 Head，只删除 `removals` 中列出的成员（`internal/enterprise/release/publish.go` 的 `materialize`）；
   - Harness 从来不发 `removals`；
   - 一款产品重新编译后，如果某个字段不再出现（例如被丢弃，或字段下线），上一版的旧 Claim 会一直留在 Release 里，页面继续显示过时内容；
   - 1828 重新发布前必须补上。
2. **产品 pack 声明**：
   - `declared_pack` 只读 Golden v2/v1 manifest；
   - 不在 Golden 中的产品（1818、1837、5003、1830、1847H、2650、594）编译时找不到 pack，`compile_run` 停止。

## 2. 设计

### 2.1 整款替换（`bundle/assemble.py`、`compilers/schema_fields/claims.py`、`publish.py`）

```python
def retired_claims(active: Release | None, entity_id: str, keep: Collection[str]) -> list[str]
def assemble(..., removals: Sequence[str] = ()) -> CandidateBundle
def candidate_bundle(..., removals: Sequence[str] = ()) -> CandidateBundle
```

- `retired_claims`：Active Release 中 `kind == "claim"` 且 payload 为对象、`subject_ref == entity_id` 的成员，去掉 `keep` 中的 logical slug 后，按 slug 排序。
  - 其他产品的 Claim、entity 与 presentation_profile 成员一律不动；没有 Active Release 返回 `[]`。
- `assemble`：把 `removals` 原样放进 `CandidateBundle.removals`。
  - 与成员 slug 重叠、重复或为空白时抛 `BundleError("REMOVAL_OVERLAP")`，与平台校验一致，避免提交后才被拒。
- `publish.py`：
  - 读到 Active 后，以本次全部 Claim 的 logical key 为 `keep` 计算 `retired_claims`，传给 `candidate_bundle`；
  - 有撤下的 Claim 时，成功输出增加 `"retired": <条数>`；没有撤下时不输出该键（同 `reasons` 的做法，既有输出形状不变，S4g/RV1 的发布验收无需改动）。

### 2.2 产品 pack 声明（`dataset/product_packs.json`、`eval/product_sources.py`）

```json
{"version": "2026-10-18.1",
 "basis": "...",
 "packs": {"1818": "schemapack_endowment_insurance", "1837": "schemapack_whole_life_insurance",
           "5003": "schemapack_whole_life_insurance", "1830": "schemapack_annuity_insurance",
           "1847H": "schemapack_annuity_insurance", "2650": "schemapack_medical_insurance",
           "594": "schemapack_medical_insurance"}}
```

- **归属依据**：备案名称中的险种（两全、终身寿险、年金、医疗）。养老年金归年金险（用户 2026-10-18）。
- **`declared_pack` 查找顺序**：显式参数 → Golden v2 → Golden v1 → `product_packs.json`。
  - 同一产品在 manifest 与本文件中声明了不同的 pack → `ValueError`，不静默取其一；
  - 文件不存在等同于没有声明；
  - 文件结构不对（缺 `version`、`packs` 不是"字符串 → 字符串"）→ `ValueError`。
- 本文件声明的每个 pack 必须存在于 schema pack 目录中（由验收核对）。

## 3. 验收

受保护验收（Claude 写，RED 单独提交）：

- `harness/tests/compilers/schema_fields/test_retired_claims.py`：
  - `retired_claims` 只列本产品不再出现的 Claim，不动其他产品与非 Claim 成员，排序可复现，没有 Active 时为空；
  - `assemble`/`candidate_bundle` 带上 `removals`，重叠、重复、空白都报 `REMOVAL_OVERLAP`。
- `harness/tests/eval/test_product_packs.py`：
  - 数据集中每个带 planCode 的产品都能解析出 pack；
  - 新增 7 款的归属如 §2.2 所列；
  - 声明的 pack 都在目录中；
  - 与 manifest 冲突、文件结构不对都报 `ValueError`；
  - 文件缺失时行为与现在相同。
- `harness/tests/compilers/schema_fields/test_publish_retires.py`（S4j 合并后单独 RED 提交）：Active 中有本产品的旧 Claim 而本次没有时，候选包 `removals` 恰好列出它、不动其他产品，输出 `retired` 计数正确；首次发布 `removals` 为空且输出没有 `retired` 键。
- 门禁：Harness `pytest`、`ruff`、`mypy src tests`；架构守卫；CI 全绿。

## 4. 改动范围

- **允许**：
  - `bundle/assemble.py`、`compilers/schema_fields/claims.py`、`compilers/schema_fields/publish.py`、`eval/product_sources.py`；
  - 新增 `dataset/product_packs.json`；
  - 上述测试。
- **不改**：Go、前端、`contracts/`（`removals` 已在合同中）、编译行为、Golden。
- **受保护**：本片验收文件、`docs/design/`、蓝图。

## 5. 预算

无真实调用。之后的编译与发布按 #207 的批次执行（deepseek-flash 上限 60 次，用户已批准）。

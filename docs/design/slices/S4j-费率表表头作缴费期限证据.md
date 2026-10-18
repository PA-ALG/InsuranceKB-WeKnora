# S4j · 费率表表头作缴费期限的证据：TrustPolicy 的第一条字段规则

> 状态：用户已确认开工（2026-10-18："批准，先按你建议来吧"；重编译预算 ≤ 30 次 deepseek-flash） ｜ 作者：Claude Code
> 依据：蓝图 §7.3（材料角色与 TrustPolicy：按"字段 × 材料角色"裁决采信）、硬边界 6；S4i Spec
> 分支：`slice/s4j` ｜ 工作目录：`.worktrees/s4j` ｜ 实现方：Codex ｜ 审核方：Claude

## 1. 问题与用户裁定

- **S4i 的效果**：按用户 2026-10-17 的裁定，费率表整份不作证据。理由是之前高亮框住了一大片数字，"看不出啥内容"。
- **代价**：5 款 Golden 产品的可选交费期间（趸交、3/5/6/10/15/20/30 年交等）只写在费率表的表头里，条款和说明书只写"由您与我们约定"。因此"缴费期限"（`premium_payment_term`）全部变成 unknown，产品页上不再显示交费期间。
- **用户 2026-10-18 的裁定**：同意按建议处理。"缴费期限"可以引用费率表顶部的表头；费率数字仍然不作任何字段的证据；其他字段仍不能引用费率表。

这一片落地蓝图 §7.3 的 TrustPolicy：材料能否作证据，按"字段 × 材料角色"裁决，不再只按角色整份决定。

## 2. 现状（`main@47ee37d56`）

- **材料角色**：`identity/material_roles.json` 中 `rate_table` 为 `evidence: false`。`evidence_pages` 把费率表整份剔除；`source_map.load_pages`、`product_sources.source_pages` 与 `golden_remap` 都用它。
- **分段**：`evidence/segments.py` 中，没有句末标点的连续行（表格）按 300 字在行尾切开。所以费率表第一段是"表头 + 前几行数字"。
- **发布**：`claims_from` 对不在 `source.pages` 中的文档报 `EVIDENCE_DOCUMENT_NOT_READ`。
- **Golden**：5 款的 `premium_payment_term` 因证据只在费率表上被清空为 unknown，列在 manifest 的 `pending_semantic_review` 中，另外 3 个字段同理。
- **字段卡**："缴费期限"的 `unknown_rule` 写的是"说明书与条款都没有列出缴费年期时为 unknown"（S4i 验收 `test_field_cards_rate_tables.py` 固定了这句）。

## 3. 设计

### 3.1 表头（`evidence/segments.py`，通用规则）

```python
def header_block(text: str) -> tuple[int, int] | None
```

- **数据行**：去掉首尾空白后按空白切分，至少 2 个记号，且每个记号都是数字（`^[+-]?\d+(?:[.,]\d+)*%?$`）。
  - 例：`0 408 275 222 157` 是数据行。
  - `10年交 15年交`、`单位：人民币元`、`- 10年 20年`、`1 人 100%`、单独的页码 `12` 都不是。
- **表头块**：从页首第一个非空字符，到第一条数据行之前最后一个非空行的末尾，返回 `(start, end)` 字符区间。
  - 页面没有数据行，或第一条数据行之前没有文字（续页），返回 `None`。
  - 数据行之后的文字（如注释）不属于表头。
- 用真实 14 个材料目录的费率表核对过：每页表头块正好是"标题、计价单位、性别、计划或保险期间行、交费期间、列名"，不含任何费率数字。

### 3.2 TrustPolicy（`catalog/trust_policy.py` 与 `catalog/trust_policy.json`，版本化数据）

```python
class TrustPolicyError(ValueError): code: str           # TRUST_POLICY_INVALID
class HeaderRule(BaseModel): role: str; fields: tuple[str, ...]
class TrustPolicy(BaseModel):
    version: str
    header_rules: tuple[HeaderRule, ...]
    def header_fields(self, role: str) -> frozenset[str]   # 可引用该角色材料表头的字段
    def header_roles(self) -> frozenset[str]               # 有表头规则的角色
def parse_trust_policy(text: str) -> TrustPolicy      # 任何不符都抛 TrustPolicyError
def load_trust_policy() -> TrustPolicy               # 随包数据，经 parse_trust_policy

@dataclass(frozen=True)
class TrustedPages[P]:
    evidence: list[P]                    # 整份可作证据的材料页，同 evidence_pages
    table_headers: dict[str, list[P]]    # 角色 → 只读表头的材料页（只含有表头规则的角色）
def trusted_pages[P](pages: Sequence[P]) -> TrustedPages[P]
```

- **数据**：`{"version": "2026-10-18.1", "header_rules": [{"role": "rate_table", "fields": ["premium_payment_term"]}]}`。
- **校验**（严格模式，任何不符都抛 `TrustPolicyError("TRUST_POLICY_INVALID")`）：
  - 角色必须是 `material_roles.json` 中 `evidence: false` 的角色；对可作证据的角色写表头规则没有意义。
  - 同一角色只出现一次；字段非空、互不重复、不能为空白。
- **`trusted_pages`**：整份证据照 `evidence_pages`。有表头规则的角色，其材料页按角色放进 `table_headers`，顺序不变。任何一份材料未识别，仍抛 `MaterialRoleError("MATERIAL_ROLE_UNRESOLVED")`。
- **保留现有入口**：`evidence_pages`、`load_pages`、`source_pages` 的行为不变，S4i 验收继续成立。新增的读取入口：
  - `ingest/source_map.load_trusted_pages(reader, space_id, entries) -> tuple[TrustedPages, dict[str, SourceRevision]]`：版本号包含表头材料，引用要能回跳到费率表文件。
  - `eval/product_sources.trusted_source_pages(directory) -> TrustedPages`。

### 3.3 来源（`SegmentedSource`）

```python
SegmentedSource(pages, *, table_headers: Mapping[str, Sequence[PageTextLike]] | None = None)
def header_role(self, document: str) -> str | None   # 只读表头的文档 → 角色；其余为 None
```

- **编号**：表头材料排在整份证据材料之后编号（按 `table_headers` 的角色顺序，再按页序）。整份证据材料的段号与不传 `table_headers` 时完全相同。
- **只切表头**：表头材料的每页只取 `header_block` 区间，按现有规则切段，引文仍是页文本的精确切片。
  - 表头块之外的文字不成段，不出现在 `listing()` 里，任何 id 都指不到费率数字。
  - 没有表头块的页面不产生段。
- **不传 `table_headers` 时**，行为与现在完全相同。
- 同一文档不能既是证据材料又是表头材料（抛 `ValueError`）。

### 3.4 编译与发布的字段裁决

- **编译**（`SchemaFieldsCompiler.compile/build_requests` 增加关键字参数 `table_headers`，默认 `None`）：
  - 选段结果中，一个字段引用了表头段，而该字段不在 `policy.header_fields(source.header_role(doc))` 中时，这条引用按无效引用丢弃，计入 `dropped_refs`，同字段的其他引用照常保留；
  - 提示词与列段格式不变。
- **发布**（`claims_from`）：
  - 证据所在文档是只读表头的文档，而该字段不受信 → `BundleError("EVIDENCE_ROLE_NOT_TRUSTED", index)`；
  - 文档既不是证据材料也不是表头材料 → 仍为 `EVIDENCE_DOCUMENT_NOT_READ`；
  - 其余核对（段号、引文、页码、指纹）不变。
- **调用方**统一改用 `load_trusted_pages` / `trusted_source_pages` 并把 `table_headers` 传给 `SegmentedSource` 与编译器：
  - `eval/compile_run.py`、`compilers/schema_fields/publish.py`、`eval/segment_score.py`、`eval/golden_remap.py`；
  - 以及其他构造来源的生产代码。
  这样编译、发布、计分和 Golden 用的是同一份来源。

### 3.5 字段卡与 Golden

- **字段卡**：只改"缴费期限"的 `unknown_rule` 开头一句："说明书与条款都没有列出缴费年期时为 unknown（原因：材料未提及）。"改为"说明书、条款与费率表表头都没有列出缴费年期时为 unknown（原因：材料未提及）。"，其余文字不动；`cards_version` 升为 `draft-2026-10-18a`。
  - S4i 验收 `test_field_cards_rate_tables.py` 固定了旧句子，由 Claude 在 RED 中单独提交修正并写明原因，其余断言不变。
- **Golden**：用 `eval/golden_remap` 从 S4i 之前的 Golden（`d73a58f18`）按新规则确定性重新生成：
  - 受信表头字段在费率表页上的旧证据，若与该页表头块有重叠，映射到同页的全部表头段；与表头块没有重叠（只在数据行上）则丢弃该条；
  - 该字段恢复 S4i 之前的值与状态，并从 `pending_semantic_review` 移除；
  - 与当前 `main` 相比，只有 5 款的 `premium_payment_term`、manifest 的待复核清单与修订记录、以及随卡片版本变化的 `cards_version` 有变化，其余逐字节不变；
  - 另外 3 个待复核字段（`coverage_period`、`entry_age_range`、`premium_payment_frequency`）保持现状。

### 3.6 不在本片

其他字段 × 角色的规则、产品版本与有效期维度（TrustPolicy 后续扩展）、概念页上的通用"交费期间"解释（S6）、1828 重新发布（本片合并后单独执行）。

## 4. 验收

受保护验收（Claude 写，RED 单独提交）：

- `harness/tests/catalog/test_trust_policy.py`：
  - 随包策略可加载，`header_fields("rate_table") == {"premium_payment_term"}`，`header_roles() == {"rate_table"}`；
  - 非法策略（未知角色、对证据角色写表头规则、角色重复、字段为空或重复、多余键）报 `TRUST_POLICY_INVALID`。
- `harness/tests/evidence/test_table_header.py`：
  - `header_block` 对单行列名、多行（保险期间行加交费期间行）、续页、没有数据行、页码行、`1 人 100%` 的判定；
  - 带 `table_headers` 的 `SegmentedSource`：证据材料段号不变，表头材料编号在后，段落只覆盖表头块、引文是页文本精确切片，`listing()` 中没有任何数据行；`header_role` 正确。
- `harness/tests/identity/test_trusted_pages.py`：
  - `trusted_pages` 分组与顺序；未识别材料仍停止；
  - `load_trusted_pages` 保留表头材料的版本号；
  - 用 1828 真实材料：`trusted_source_pages` 的表头页每页一个表头块，含"10年交 15年交 20年交 30年交"，不含费率数字。
- `harness/tests/compilers/schema_fields/test_trusted_header_evidence.py`：
  - 编译时"缴费期限"引用表头段被保留，"投保年龄"引用同一表头段被丢弃并计入 `dropped_refs`；
  - 发布时"缴费期限"引用表头段生成 Claim，其他字段引用报 `EVIDENCE_ROLE_NOT_TRUSTED`；
  - 来源中没有表头材料时，仍报 `EVIDENCE_DOCUMENT_NOT_READ`。
- `harness/tests/eval/test_golden_payment_term.py`：
  - 5 款的 `premium_payment_term` 为 present，证据都在费率表上、每条引文落在该页表头块内、不含数据行；
  - manifest 的待复核清单不再含该字段，其他 3 个字段仍在。
- S4i 验收修正（单独提交）：`test_field_cards_rate_tables.py` 中"缴费期限"的 `unknown_rule` 断言改为新句子。
- 门禁：Harness `pytest -m "not live and not integration_postgres"`、`ruff`、`mypy src tests`；架构守卫；CI 全绿。

## 5. 改动范围

- **允许**：
  - 新增 `catalog/trust_policy.py`、`catalog/trust_policy.json`；
  - 修改 `evidence/segments.py`、`ingest/source_map.py`、`eval/product_sources.py`、`compilers/schema_fields/engine.py`、`compilers/schema_fields/claims.py`、`compilers/schema_fields/publish.py`、`eval/compile_run.py`、`eval/segment_score.py`、`eval/golden_remap.py`，以及其他构造来源的生产调用点；
  - 修改 `field_cards.json` 中"缴费期限"的 `unknown_rule` 与卡片版本；
  - 修改 `dataset/golden/v2/*.json` 与 `manifest.json`，只能由 `golden_remap` 生成；
  - 新增实现所需的非保护测试。
- **不改**：
  - 材料角色数据（`rate_table` 仍为 `evidence: false`）、编译提示词、其他字段卡、Go、前端、`contracts/`。
- **受保护**：本片与 S4i 的验收文件、`docs/design/`、蓝图。

## 6. 预算与执行

- 实现与测试无真实调用。
- 合并后由 Claude 重新编译 5 款 Golden 产品与 1828：deepseek-flash 预计约 20 次，**上限 30 次**（用户 2026-10-18 已批准）。按 S4i 口径计分，并在 Issue 中报告缴费期限前后对比。
- 1828 重新发布另行执行。

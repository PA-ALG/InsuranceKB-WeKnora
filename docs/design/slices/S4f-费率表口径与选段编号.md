# S4f · 费率表口径与选段编号

> 状态：用户已批准预算（2026-10-16"25 次调用 允许"） ｜ 作者：Claude Code
> 依据：S4e Spec 与 PR #163 的真实验证评论；用户 2026-10-15 裁定"费率表算证据"
> 分支：`slice/s4f`（叠在 `slice/s4e` 上，S4e 合并后 merge main） ｜ 工作目录：`.worktrees/s4f` ｜ 实现方：Claude ｜ 审核方：Codex（评分口径与运行输出格式属复杂改动）

## 1. 根因与最小机制

S4e 用新卡片做的真实验证把召回从 0.861 提到 0.905，同时暴露两个问题：

1. **费率表的用法没写清。**
   - 现象：S4e v1 运行共选了 524 段费率表，其中 146 段不在 Golden 里。
     - 缴费期限、缴费方式两个字段占 118 段：模型连表内的费率数值行也选了，而 Golden 只选列出交费期间的表头。卡片只写了"费率栏也是证据"。
     - 另外 28 段在其他字段，而且都只是表头：
       - 保险期间 12 段：表头列出了可选的保险期间。按用户裁定这是证据，但 S4e 没有重标这个字段，Golden 缺这些段；
       - 产品搭配 6 段：表头列出"未附加／附加计划一／计划二"。用户 2026-10-16 裁定这不算产品搭配的证据，产品搭配只认条款、说明书中的组合规定；
       - 保额范围 10 段：表头只有"每万元基本保险金额"这个计价单位，属于误选。
   - 最小机制：卡片按"费率表的表名和表头列出的选项是证据，表内费率数值行只用于投保年龄"写清各字段；受影响字段的 Golden 按同一口径重标。
2. **预测证据不带段落编号。**
   - 现象：编译结果只保存切好的引文，计分时要按引文在页内重新定位。1816 两栏表里同页重复的文字让 20 条预测引文无法唯一定位，相关字段的分数因此不可信。
   - 最小机制：编译结果同时保存选中的段落编号；计分时编号能原样切出保存的证据才用编号，否则仍按引文定位。

## 2. 设计

### 2.1 字段卡 `draft-2026-10-16a`（只改数据）

- **缴费期限、缴费方式、保险期间**：费率表只选表名与列出该字段选项的表头段落（交费期间、交费方式、保险期间），表内按年龄列出的费率数值行不选。保险期间的 `sources` 加费率表。
- **投保年龄**：保持 S4e 口径，按交费期、性别等列出的年龄行都选。
- **产品搭配**：excludes 加"费率表中列出的附加险计划或费率组合 → 不入本字段"（用户 2026-10-16 裁定"不算，只认条款规定"）。
- **保额范围**：excludes 加"费率表（每万元基本保险金额只是计价单位）→ 不入本字段"。

### 2.2 Golden 修正（`dataset/golden/v2/`）

- 保险期间由独立 GPT-6 Astra xhigh 会话按新卡片重标，每款产品一个会话，标注提示与 S4e 相同。
- 缴费期限、缴费方式、投保年龄、保额范围、产品搭配的 Golden 已符合新口径，不重标，审计结论记入 manifest。
- `manifest.json` 追加一条修订记录（`cards_version`、各产品字段、会话编号）。

### 2.3 编译结果带段落编号（`compilers/schema_fields/engine.py`、`eval/segment_score.py`）

- `FieldResult` 增加 `segment_ids`：第一步选中并解析后的段落编号，按阅读顺序排列；unknown 为空。旧的 `output.json` 没有这个键，读取时视为空。
- 计分时，`segment_ids` 非空、全部存在于当前分段，且 `source.evidence(segment_ids)` 与保存的 `evidence` 逐条对应：文件、指纹、页码相同，原文忽略空白与宽度后相同（与 Golden 段落编号同一规则；S4c-1 起页文本保留 `\r\n`，换行符差异不是内容差异），才直接用这些编号；否则按引文定位，定位不到的仍计入 `unmapped_predicted_quotes`。
- 候选包读取端忽略未知键，`to_candidate` 不受影响。

## 3. 验收

- 受保护验收（RED 单独提交）：`tests/compilers/schema_fields/test_selected_segment_ids.py`、`tests/eval/test_golden_rate_table_revision.py`。
- `harness/` 下门禁（`-m "not live and not integration_postgres"`、`ruff check .`、`mypy src tests`）通过；守卫通过；CI 全绿。
- 真实验证：用 `draft-2026-10-16a` 编译四款产品一次，用新计分器对修正后的 Golden 计分，与 S4e v1（同一计分器、同一 Golden）对比；报告无法映射的预测引文数。

## 4. 改动范围

- 允许：`compilers/schema_fields/engine.py`、`compilers/schema_fields/field_cards.json`、`eval/segment_score.py`、`dataset/golden/v2/`、对应实现方测试。
- 受保护：本片验收文件、既有受保护验收、`docs/design/`、蓝图。

## 5. 真实调用预算

- `deepseek-flash`：上限 25 次（用户 2026-10-16 批准），四款产品一次运行约 22 次。
- 评委：GPT-6 Astra xhigh，Golden 重标每款 1 个会话（共 4 个）。

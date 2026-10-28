# QA3 · 已发布字段按问法匹配

> 状态：Claude 2026-10-28 提出 ｜ 作者：Claude Code
> 依据：
> - QA2 线上复核（#385 issuecomment-6460509760）：q05"保额每年按多少增长"没有选中已发布字段 `sum_assured_growth_rate`（标题"产品利率"）；
> - 原因：`knowledge.QuestionFields` 只有在问题里出现完整的字段标题时才选中字段。用户的问法和标题常常对不上。
>
> 实现方：
> - Go 部分（§4）由 **Codex** 实现；
> - Harness 部分（§2 合同、§3 词表与导航刷新命令）由 **Claude** 实现。
>
> 审核方：Codex 实现的部分由 Claude 审，Claude 实现的部分由 Codex 审。
>
> 真实调用：实现阶段为 0；上线后的复核（§7）另行决定。

## 1. 离线测量（0 次模型调用）

- **数据**：#286 r2 的 30 道题，取有字段答案的 21 道；其中单轮题 18 道。
- **对照**：线上 Active（epoch 81）中，被点名产品已发布的字段。产品范围直接取题目标注的产品，只比较"选字段"这一步。
- **问法词表草稿**：40 个常问字段，按字段卡的标题和定义编写；评估集是已知的，所以下表数字偏乐观。
- **脚本**：`~/insurancekb-runs/qa3-field-match-20261028/`。

| 规则 | 单轮 18 题：全部答案字段都选中 | 精确率 | 召回率 |
|---|---|---|---|
| 现状：问题里出现完整标题 | 12 | 0.92 | 0.60 |
| 只拆标题（按"和、与、及、或"拆开后任一部分出现） | 14 | 0.82 | 0.70 |
| **标题 + 问法词表**（本切片） | **18** | **0.87** | **1.00** |

**被纠正的题**：

| 题 | 问法 | 现在选中的字段 |
|---|---|---|
| q05 | 保额……增长 | `sum_assured_growth_rate` |
| q04 | 多少种重大疾病／中症／轻度疾病 | 三个疾病清单字段 |
| q06 | 身故 | `death_benefit_rules` |
| q11 | 续保 | `coverage_and_renewal_terms` |
| q18 | 交费期间 | `premium_payment_term` |

**新增的多选**：
- q05 同时选中相关字段 `sum_assured_growth_rules`；
- q06 选中 `premium_payment_term`，因为问题里提到了"交费期"；
- q16 仍选中 `premium_adjustment_rules`，这是 QA2 已冻结的行为。

**没有字段答案的题**：选中的字段都和题意相关：
- q21、q30 选中分红规则；
- q23 选中健康告知；
- q24 选中保单权益。

## 2. 合同（Harness 导出，增量）

`NavigationProfile` 增加一个可选字段 `question_terms`：

```json
"question_terms": {"<field_key>": [["保额", "增长"], ["增长比例"]]}
```

- **结构**：每个字段键对应若干"词组"，每个词组由 1–3 个词组成。问题里出现某个词组的**全部**词，就算问到了这个字段。
- **规范化**：与平台 Go 的 `normalizeQuestionTerm` 完全相同，依次是：
  - NFKC，转小写；
  - 去掉空白：Go `unicode.IsSpace` 认定的全部空白（含 TAB、LF、CR、NEL、NBSP、全角空格），以及 BOM；
  - 去掉 Unicode 标点（P 类）。符号（S 类）保留。
- **校验**（Harness 侧）：长度和去重都按规范化之后的词判断。
  - 字段键必须在 schema 目录中；
  - 每个词规范化后不少于 2 个字；
  - 词组不能为空，也不能超过 3 个词（按原始项计）；
  - 一个词组里不能有规范化后相同的词；
  - 同一字段内不能有重复的词组。去重时把词组看作规范化后的词的集合，不计顺序：词组按"全部出现"匹配，`["保额","增长"]` 和 `["增长","保额"]` 对任何问题都等价。

> 2026-10-28 修订（#414 审核 R2、R3，Owner 裁定）：原文"NFKC、去空白和标点"没有写明空白的边界，实现用 Unicode Z 类判断空白，漏掉了 TAB、LF 等控制字符。现在逐字对齐 Go；原来的去重按词组有序比较，现在按词的集合比较，并补上"同组重复词"。
- **导出**：用 `uv run python -m insurance_harness.contracts.export` 重新生成 `contracts/navigation_profile.schema.json`。旧导航没有这个字段，仍然合法。

为什么放在导航里：
- 词表按字段键定义，不随险种变化；
- 导航是整个 Space 唯一的一个成员，刷新一次就够了；
- 放进 presentation profile 的话，要刷新约 11 个成员。

## 3. Harness 数据与导航刷新

1. **词表**：放在 `catalog/navigation.json` 的 `question_terms` 中，`navigation_version` 升到 `2026-10-28.1`。
   - 编写依据是字段卡的标题、定义和 includes 里的常见说法，**不得**按评估题目逐条编写；
   - 至少覆盖 §1 草稿中的 40 个字段；
   - 草稿见 `~/insurancekb-runs/qa3-field-match-20261028/data/question_terms.draft.json`，实现时按字段卡复核后再采用。
2. **导航刷新命令**：`python -m insurance_harness.catalog.publish_navigation --space <space_id> [--dry-run]`。
   - 平台地址和凭据从环境变量 `HARNESS_WEKNORA_BASE_URL` / `HARNESS_WEKNORA_API_KEY` 读取；
   - 读 Active，比较 `navigation/<id>` 成员的摘要和当前导航数据。不同时，以当前 Head 为基础提交一个**只含这个导航成员**的候选；
   - 以机器决定发布：`mode=machine`，`policy_ref=navigation:<navigation_version>`，理由写"导航与问法词表更新，不含事实"。然后激活；
   - **激活后读回核对**：按激活回执的 Release id 读回该 Release。同时满足以下三条才报 `published`：
     - 激活回执和读回的 `candidate_id` 都是本次提交的候选；
     - 读回的 Release id 与回执相同；
     - Release 含 `navigation/<id>` 成员，摘要等于本次导航的摘要。
   - 读回失败或核对不符时停止，报 `{"stopped": <code>, "status": "unknown", ...}`，退出码 2，不再发送任何写请求。这时激活可能已经生效，所以不能报"已发布"，也不能当作"未发布"直接补发。处理办法是重跑命令：它先读 Active，导航已经上线就报 `current`，不是最新时才重新提交；
   - 摘要相同则什么都不做。dry-run 不写任何东西；
   - 平台认证失败（401/403）、没有 Active、平台不可用、目录或导航数据无效时，都在写入前停止；
   - 导航不含产品事实，所以不走字段评分门槛。这是唯一一种不经审核分数就上线的候选，只限导航成员。

> 2026-10-28 修订（#414 审核 R4，Owner 裁定）：入口由 `--registry …` 改为 `--space`。导航是 Space 级成员，与产品无关，不需要登记表把产品绑定到 Space，直接指定目标 Space 即可；范围和认证照常在写入前失败关闭。同时把"读回核对"写明为上面三条，核对不通过时报 `unknown`（#414 审核 R1）。

   现有的产品发布只在 Head **没有**导航时才带上它（`publish_changes.delta_bundle`），版本升级没有发布途径。本命令补上这条途径。

## 4. Go：`QuestionFields`（平台通用，不含领域词汇）

1. `navigationPayload` 读取 `question_terms`（`map[string][][]string`），缺失时为空。
2. 一个字段算"问到了"，满足下面任一条：
   - 现有规则：规范化后的标题在问题中，且不少于 2 个字；
   - 新规则：该字段键的某个词组里，每个词规范化后都不少于 2 个字，并且都出现在问题中。词组里只要有一个词不足 2 个字，整组忽略（失败关闭）。
   - 词表里有、但本版本没有发布的字段键，忽略。
3. **点名产品补概览**：QA2 的规则扩展到词组。
   - 原规则：标题本身是被点名产品名称的一部分时，补上概览字段；
   - 扩展：凡是**只因为**产品名称里的文字才命中的字段（标题，或词组中的全部词都在某个被点名产品的名称里），一样补概览。
   - 其余顺序、去重、`limit` 都不变。
4. **兼容**：没有 `question_terms` 的版本，行为与现在完全一致。QA2 和 Q1b 的冻结验收都不改。

## 5. 改动范围

| 实现方 | 文件 |
|---|---|
| Codex | `internal/enterprise/knowledge/index.go`（导航载荷）、`questions.go`；实现方自己的测试 |
| Claude | `harness/src/insurance_harness/contracts/knowledge.py`（`NavigationProfile`）、`contracts/navigation_profile.schema.json`（导出生成）、`catalog/navigation.py`（校验）、`catalog/navigation.json`、新文件 `catalog/publish_navigation.py`；实现方自己的测试 |

不改前端，不改 `release` / `releasestore`，不新增成员类型。

## 6. 验收（RED，Claude 编写，受保护）

1. **Go**：`internal/enterprise/knowledge/question_terms_test.go`
   - "保额每年按多少增长"通过词组 `["保额","增长"]` 选中标题为"产品利率"的字段；
   - 只出现"保额"一个词时不选中；
   - 含不足 2 字的词的词组整组无效；
   - 没有 `question_terms` 的导航，行为与现在相同；
   - 词组命中算作"问到了字段"，范围仍限于被点名产品；
   - 只因产品名称而命中的词组会补概览。
2. **Harness**：
   - `tests/catalog/test_navigation_question_terms.py`：
     - 合同接受合法的 `question_terms`；
     - 拒绝空词组、超过 3 个词、不足 2 字的词、未知字段键和重复词组；
     - 规范化与 Go 一致：TAB、LF、CR、NEL、NBSP、全角空格、BOM 都按空白去掉后再算长度和去重；符号保留；
     - 顺序不同的同一组词算重复；同一组里有规范化后相同的词时拒绝；真正不同的词组可以并存；
     - `navigation.json` 的版本为 `2026-10-28.1`，并且含 `sum_assured_growth_rate` 的词组；
   - `tests/catalog/test_navigation_publication.py`：离线下用实际的 `PlatformClient` 经 fake HTTP 运行命令（`--space`）：
     - Head 导航不同时，只提交导航成员，以 `navigation:<version>` 机器决定、激活，读回核对通过后报 `published`；
     - 读回不符（缺导航成员、摘要不同、读回或回执的候选不是本次候选）或读不到时，报 `unknown`、退出码 2，激活之后不再有写请求；
     - 相同时不做任何事；dry-run 零写入。

**门禁**：
- Go：`go test ./internal/enterprise/...`，以及 golangci-lint；
- Harness：`uv run pytest`、ruff、mypy；
- 守卫。

## 7. 上线

1. Codex 和 Claude 两部分都合并、App 部署之后，运行导航刷新命令（只发布导航成员）。
2. 复核：#286 的 q04、q05、q06、q11、q18，再加 3 道对照题，用快问快答，最多 30 次调用。由 Claude 决定是否执行（用户已授权全部审批）。

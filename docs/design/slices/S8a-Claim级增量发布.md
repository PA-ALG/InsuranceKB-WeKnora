# S8a · Claim 级增量发布：新材料只发布真正变化的字段，冲突不改线上

> 状态：Claude 2026-10-21 提出，用户同日批准排期（"批准，继续吧"：增量更新优先）｜ 作者：Claude Code
> 依据：蓝图 §5.1、§6.1、§6.5，§11 S8
> 实现方：Codex（Harness）｜ 审核方：Claude ｜ 实现阶段真实模型调用：0

## 1. 问题（代码核对，`main@6f14852e2`）

蓝图 S8 的完成标准是：第二批材料生成新 Release 时，判定符合预期、无关 Claim 的 digest 不变、冲突不改线上、回退 A 保留 B。今天的发布路径做不到：

1. **整产品重发**：`compilers.schema_fields.publish` 每次把产品的全部字段作为成员重发，并把 Active 中多出的字段作为 removals（S5a）。没有判断哪些字段真的变了。
2. **digest 必然变化**：审核标签（reviewer、reviewed_at）、provenance 和带解析次数的 `source_ref` 都在 payload 里。值没变的字段每次发布也得到新 digest，"无关 Claim digest 不变"无法成立。
3. **没有冲突概念**：新编译结果直接覆盖线上值。新旧两份仍然有效的材料说法不一致时，不会进入人工处理。
4. **编译结果按产品复用**：`eval.compile_run` 只要看到 `<run_root>/<product>/output.json` 就复用，不核对材料是否变化。新材料到了也会沿用旧结果。
5. **旧判定器不可用**：`knowledge_compiler/incremental_changes.py`（以及 `source_authority.py`、`retractions.py`）的输入是已退役的 `VerifiedFactV1` 与 052 MaterialProfile，生产路径不可达（守卫 `KEEP_UNREACHABLE` 标注"S8 REWIRE → changes/"）。

## 2. 设计

新增 `harness/src/insurance_harness/changes/`（守卫已预留的目标目录）。输入是已发布的 Claim 与新编译出的 Claim，输出 Claim 级变化。变化之外的成员不重发，由平台从 base Release 原样带入，digest 自然不变。

### 2.1 判定 `decide_changes`

```python
decide_changes(
    active: Release,                    # bundle.client.Release：当前 Active（可含多个产品）
    entity_id: str,                     # 只判定这一个产品
    incoming: Sequence[Claim],          # 该产品新编译出的 Claim（contracts.knowledge.Claim）
    current_knowledge: Collection[str], # 该产品当前材料集的 knowledge_id（来自 source map）
) -> ChangeSet
```

- **base**：Active 中 `kind == "claim"` 且 `payload.subject_ref == entity_id` 的成员，按 `Claim` 解析。按 `logical_key` 与 incoming 配对。
- **文档**：Evidence 的文档取 `source_ref` 中的 knowledge_id（`source:v1:<knowledge_id>:<attempt>:<sha>`）。
- **仍有效**：base Claim 的证据文档中，至少一个在 `current_knowledge` 里。
- **新文档**：`current_knowledge` 中没有被该产品任何 base Claim 引用过的 knowledge_id。
- **等价**（同时满足两条）：
  - state 相同；
  - 值等价，即 `values_equal` 为真（数字含中文单位、日期、文本宽度、标点与空白、枚举同义词），或两边证据的 `quote_sha256` 集合相同（同一原文、措辞不同）。
  - `values_equal` 从 `eval/normalize.py` 移到 `changes/` 内的共享位置，eval 改为从那里导入，不保留两份。

逐个 `logical_key` 判定，取第一个成立的：

| # | 条件 | 判定 | 结果 |
|---|---|---|---|
| 1 | 没有 base | `add` | 发布 incoming（含 unknown，字段页保持可见） |
| 2 | base 有、incoming 没有 | `retract` 或 `keep` | base 有证据、不是 `expert_lock`、且证据文档全部不在当前材料中 → `retract`，作为 removal；否则 `keep` |
| 3 | base `expert_lock` 且不等价 | `conflict` | 不发布，生成 ReviewItem |
| 4 | 等价 | `refresh` 或 `unchanged` | base 有证据且证据文档全部不在当前材料中 → `refresh`，发布 incoming，把证据换到当前材料；否则 → `unchanged`，不发布 |
| 5 | 不等价，base 为 unknown | `fill` | 发布 incoming |
| 6 | 不等价，base 的证据文档全部不在当前材料中 | `supersede` | 发布 incoming；incoming 为 unknown 时同样替代，表示新材料不再支持该值 |
| 7 | 不等价，base 仍有效，incoming 为 unknown | `keep` | 不发布：新编译没找到，不推翻仍有效的材料 |
| 8 | 不等价，base 仍有效，incoming 没有引用任何新文档 | `keep` | 不发布：同一批材料的编译差异，不是增量变化 |
| 9 | 不等价，base 仍有效，incoming 引用了新文档 | `conflict` | 不发布，生成 ReviewItem（`kind=conflict`），线上保持 base |

"仍有效"只对有证据的 base 成立：证据文档中至少一个在当前材料里。unknown 的 base 没有证据，按第 2、4、5 行处理。

本切片先用"文档是否仍在当前材料集中"判断谁更新，不引入 TrustPolicy 权威排序。权威排序（同时有效的条款与说明书不一致时由策略裁决）留给后续切片；在那之前，这类情况一律作为冲突交人工。

### 2.2 ChangeSet 与维护记录

`ChangeSet` 提供：

- `items`：每个 `logical_key` 一项，包含 `logical_key`、`verdict`（`Verdict` StrEnum：`unchanged/add/fill/supersede/refresh/keep/conflict/retract`）、base 成员 slug（没有时为 None）、一个固定的 `reason` 代码；
- `members`：要发布的 Claim（判定为 add/fill/supersede/refresh），已写好维护记录；
- `removals`：判定为 retract 的成员 slug；
- `review_items`：每个冲突一条 `contracts.compile.ReviewItem`：
  - `kind=conflict`、`target=` base 成员 slug、`status=open`；
  - `evidence` 为两边证据的 `quote_sha256`；
  - `resolution_candidate` 为 incoming 的值（unknown 时为空）。

维护记录（`Claim.maintenance`）：

| 判定 | `revision_no` | `first_release_id` |
|---|---|---|
| supersede、fill | base + 1 | 沿用 base |
| refresh | 与 base 相同（值没变） | 沿用 base |
| add | 0 | 空 |

- 所有发布的成员都写：`changed_by=compile`；`changed_at` 为 UTC ISO 时间；`reason` 为判定代码。
- `last_changed_release_id` 在提交前未知，本切片不填。

只判定 `entity_id` 这一个产品；其他产品的成员不出现在 `members`、`removals` 或 `items` 中。

### 2.3 增量发布命令

`python -m insurance_harness.changes.publish`：参数与 `compilers.schema_fields.publish` 相同，另加 `--dry-run`。

1. 按现有方式读取材料页并生成 incoming Claim（复用 `claims_from`），`current_knowledge` 取 source map 中该产品的条目。
2. 读取 Active 并调用 `decide_changes`。
3. 审核路由只对 `members` 打分和路由。没有变化的字段保留原审核标签。
4. 组装 CandidateBundle：
   - 只含 `members` 与 `removals`；
   - 产品实体、展示配置与导航只在 Active 中缺失时附带；
   - base 为读取时的 Active。
5. `members` 与 `removals` 都为空时，不提交，退出码 0，报告"无变化"。
6. 输出 JSON，包含：
   - 各判定的计数，以及每个冲突的 `logical_key`；
   - `review_items` 写入 run 目录下的 `review_items.jsonl`（只写 slug、判定与哈希，不写原文与模型输出）；
   - `stale_concepts`：Active 中 `based_on` 引用了本次变化成员 slug 的概念成员（只报告，不重算）；
   - candidate、decision 与 release 的标识。
7. `--dry-run` 只做第 1–4 步并输出报告，不提交。

现有的 `compilers.schema_fields.publish` 保留，用于产品首次发布。产品在 Active 中已有 Claim 时，该命令输出 `{"stopped": "ALREADY_PUBLISHED"}`、退出码 2、不提交，由操作者改用 `changes.publish`，避免整产品重发让无关 digest 变化。S5a 的受保护验收 `test_publish_retires.py` 已在单独提交中按此规则修订（保留首次发布与跨产品边界）。

### 2.4 编译结果按材料复用

`eval.compile_run` 写出的 `output.json` 记录本次材料集：

- 每个文档的 `knowledge_id:parse_attempt:file_sha256`，排序后保存；
- 字段卡版本。

复用前比对这两项，任一项不同就重新编译该产品。没有记录的旧 `output.json` 视为不可复用。

### 2.5 不在本切片

- **平台侧**（S8b）：
  - Head 已前进、但本 Candidate 涉及的实体没变时自动 rebase。今天仍返回 `NEEDS_REBASE`，命令按原样停止。
  - 实体级回退。
- **新材料自动发现**：事件或轮询都不做，本切片由操作者更新 source map 后运行命令。
- **其他**：
  - 冲突在页面上的展示（RV5 人工队列页）；
  - TrustPolicy 权威裁决；
  - 按字段的定向重编；
  - 原生 Wiki 页面与概念的增量更新。
- **旧判定器**：`knowledge_compiler/incremental_changes.py`、`source_authority.py`、`retractions.py` 被本切片取代。但 `source_authority` 仍被其他不可达模块引用，删除统一放到 S7 清理；本切片只更新守卫中的说明。

## 3. 上游补丁

无。只改 Harness。

## 4. 验收（RED：`harness/tests/changes/test_incremental_acceptance.py`，Claude 编写，受保护）

合成数据：

- 产品 P 的材料从"条款 v1 + 说明书"换成"条款 v2 + 说明书"；
- 另有产品 Q 不受影响；
- 不调用模型，不访问网络。

1. **逐字段判定**：

   | 字段 | base | incoming | 判定 |
   |---|---|---|---|
   | 等待期 | 条款 v1 "90日" | 条款 v2 "90 日" | `refresh` |
   | 宽限期 | 条款 v1 "60日"，revision 1 | 条款 v2 "30日" | `supersede` |
   | 犹豫期 | 条款 v1 | unknown | `supersede` |
   | 保额上限 | 说明书 "100万元" | 说明书 "1,000,000元" | `unchanged` |
   | 某保障责任 | — | 同一原文、不同措辞 | `unchanged` |
   | 免赔额 | 说明书 "1万元" | 条款 v2 "5000元" | `conflict` |
   | 续保 | 说明书 | 说明书上的不同说法 | `keep` |
   | 职业 | unknown | 条款 v2 有值 | `fill` |
   | 专家锁定字段 | 锁定值 | 条款 v2 不同值 | `conflict` |
   | 只在条款 v1 的字段 | 有 | 没有 incoming | `retract` |
   | 新字段 | — | 有值 | `add` |

2. **成员与维护记录**：
   - `members` 恰好是 refresh、两个 supersede、fill、add 这几个字段；
   - 宽限期 `revision_no=2`，`first_release_id` 沿用 base；
   - 职业 `revision_no=1`；等待期 `revision_no` 与 base 相同；新字段为 0；
   - 每个成员都有 `changed_by=compile`、`changed_at` 与 `reason`。
3. `removals` 只有那个只在条款 v1 的字段；两个冲突各有一条 ReviewItem（`kind=conflict`、`status=open`、`target` 为 base slug）。
4. 产品 Q 不出现在 `members`、`removals`、`items` 中。
5. 用现有 `bundle.assemble.assemble(members, removals=...)` 能组装成 Candidate，成员与 removals 不重叠；unchanged 与 keep 的 base 成员不在 Candidate 里。
6. **边界**：
   - incoming 为空、材料不变时，全部为 keep，没有成员与 removals；
   - 材料全部撤下时，有证据且未锁定的 Claim 全部 retract，unknown 与专家锁定的 Claim 为 keep；
   - incoming 是 unknown 且 base 也是 unknown 时，为 unchanged。

实现方另补：

- `changes.publish` 的报告与"无变化不提交"；
- `schema_fields.publish` 遇到已发布产品时拒绝；
- `compile_run` 按材料复用；
- `values_equal` 迁移后 eval 测试保持通过。

## 5. 改动范围

- 新增 `harness/src/insurance_harness/changes/`（判定、ChangeSet、发布命令、共享的值比较）；
- `harness/src/insurance_harness/eval/normalize.py`（`values_equal` 迁出后改为导入）及其调用方；
- `harness/src/insurance_harness/eval/compile_run.py`（按材料复用）；
- `harness/src/insurance_harness/compilers/schema_fields/publish.py`（已发布产品拒绝整产品重发）；
- 实现方测试；
- 守卫基线只在数字下降时用脚本更新。

## 6. 上线与验证

本切片不涉及 App 或 UI 部署。合并后的真实验证需要第二批材料，例如某款已发布产品的新版条款，需用户提供或指定，并另行批准调用额度：

- 一次编译约等于该产品字段数次 DeepSeek 调用，外加审核打分；
- 先 `--dry-run` 看判定报告，再提交。

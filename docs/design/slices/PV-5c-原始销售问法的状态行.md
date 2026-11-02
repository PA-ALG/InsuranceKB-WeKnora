# PV-5c 原始销售问法的状态行不能被检索重写抹掉

> Issue #535；实现 Codex，审核 Claude。用户授权 Spec → 独立 RED → 实现 → PR。
> 补充 PV-5 §1 的状态判定输入边界，不改 PV-0 版本方向；真实 QA/模型/评委/平台请求 0，不部署或修订线上知识。

## 1. 离线诊断与修复范围

#531 E 保存的固定 Release 投影：目标有可见 Entity、原始问题全名点名且仅销售意图，无 lifecycle 时读取服务本来能生成 unknown。
缺 product_code 不能解释这次全名点名缺行。生产 `publishedHits` 目前仅使用 RewriteQuery；合成反例经真实 FilterPipeline 证明：
rewrite 去掉销售问法后，字段仍可检索，但状态消失。引用 SSE 直接交付 MergeResult，不只返回模型实际引用的成员。
历史响应未保留该次 query-understanding rewrite；本片不冒称已还原历史 rewrite，也不将重新 QA 当作离线诊断的一部分。

三个事实偏差只记录在 Issue 的脱敏诊断表，不修改已发布知识、不复制私有题答/标题/引文进测试。修复状态行不等于事实项质量通过。

## 2. 最小行为与接口

- `knowledge.Service.QuestionReferences` 保持既有调用兼容，增加可选的原始问题输入（一个 string，供企业 quick-answer 调用）。
  同一次 `s.read` 构造 index：字段仍按原 `question`（检索重写文本）求值，字段内容/顺序/12条预算不改。
- 原始问题经现有 `index.statusLines` 求值：只有现有导航判定为单一销售意图、现有产品点名规则能命中**真实 Entity**时才有结果。
  非空结果优先用于状态行；没有结果（含空、指代、无产品、非销售、双意图）则保持原 question 的状态行逻辑。
  不把原问题任意词强制当销售，不新加品牌/编号/险种规则，不从模型 rewrite 猜新身份。
- `chatsource.publishedHits` 保留 Query/RewriteQuery 的原字段检索选择，但把 `ChatManage.Query` 一并传入。原问题明确点名的每款
  产品先给状态；无 lifecycle 仍“销售状态：未知”。状态无 Evidence/index、按实际 Entity slug 生成完整固定版本元组。
- 没有可独立点名的原问题（旧指代/旧调用）仍使用现有 rewrite 路径，不改变已认可的查询行为。原问题与 rewrite 一致时不重复状态。
- 不改 RAW 检索/QuestionProducts 的现行语义、问题理解、提示词或导航。状态、字段均读取同一 pinned Release，沿用每轮一次
  字段注入缓存，两次 FilterPipeline 交付不重读/不重复。单接口依然一次读取，不把本片变成回合级缓存改造。

## 3. 失败关闭与保护

- `wholeToken`、最小标识长度、方法排除、placeholder 无 Entity 不造状态、既有名称规则均不变；状态优先不能绕过这些边界。
- 读取错误、取消、无权限与错误 Release 身份沿原错误路径，无原文/当前 Head 兜底。
- 前端完整元组、malformed sale_status 不降级普通 CitationPanel、unknown 只预览；服务端 pinnedOnly/ownsPinned 仍过滤旧版本。
- 事实 Claim、证据、审核、编译身份、版本归属、发布生命周期均不变，不修 three fact cases 的实际线上内容。

## 4. 写域与验收

运行时仅 `internal/enterprise/knowledge/questions.go`、`internal/enterprise/chatsource/published.go`。
新增 RED：`internal/enterprise/knowledge/original_status_acceptance_test.go`、
`internal/enterprise/chatsource/original_status_acceptance_test.go`（独立提交后冻结）。本 Spec 独立提交。
不改旧保护、蓝图/守卫/基线、contracts、导航/提示词、上游、Harness 或前端运行时；手写文件 ≤500。

合成验收（至少不同产品/状态/结构）：
- 原销售点名 + rewrite 去掉销售词/增加服务词/缩成字段 → unknown 或已知状态仍在，字段仍按旧 rewrite；
- 原多产品点名 + rewrite 只保留一个 → 原点名状态各一次，固定 Entity/Release 元组，无 evidence_index；
- 空原问题/指代/旧 API/原问题未独立点名 → 旧 rewrite 正控；原问题与 rewrite 相同不重复；
- 标识长码误命中、双意图、方法-only、placeholder、无意图、旧版本、读取错误/取消不放宽；
- 真实 FilterPipeline 双交付只有一次发布读取，后续 source/ref 不改；相关 PDF/Office/非法状态引用旧测试保持。

## 5. 实施与交付清单

1. Issue 发布脱敏诊断和计划，独立提交 Spec。
2. 单独提交新 RED，并在旧实现复现失败；冻结后只改获准运行时，不弱化断言。
3. 最小实现，必要 Go 包测试/受影响组件门禁、架构/合同 check/diff；全量与实库以 CI，不重复无关全量。
4. merge 最新 main 不 rebase、开 Closes #535 PR，精确 head CI 全绿后交 Claude 审核。工作树保留待审，不自行 merge 或线上复核。

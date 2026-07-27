# 041 · P5a0+ ProductVersion Resolver Kernel

> 状态：规格修订与 TDD 重放中（Dev Lane A，2026-07-27）。
> 授权：用户批准 Mission Card P5a0+-A。
> 权威设计：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> 与
> `docs/superpowers/specs/2026-07-27-enterprise-llm-wiki-knowledge-compilation-amendment.md`。

## 为什么做

当前 change 003 的确定性路由只归属到 `InsuranceProduct`，不能在同一产品的多个
备案版本间选择 exact `ProductVersion`。同名产品、备案重发、拼接费率表或自动
生成的短别名若被误当成身份，会把不同版本的事实编译到同一 Wiki subject。

现有 schema 已有 `ProductVersion.terms_revision`，足以承载版本级备案/注册锚点，
无需新增表或 migration。本 change 只建立只读解析内核，不建立新的 authority。

## 做什么

- 输入一个已加载并 attested 的 `KnowledgeScope` 与文档/章节判定证据；
- 按固定优先级解析：**版本级备案/注册编号 → exact product code/name →
  仅人工批准 alias**；
- 只有候选唯一且所有强身份信号相容时返回 exact `ProductVersion`；
- 返回 resolver version、固定 policy hash、C0 canonical result hash 与完整判定
  basis；
- 多强锚点冲突、跨 Space、无版本、同名/同别名歧义均以 typed quarantine
  fail closed；
- fragment 只继承文档/章节决议，不再次解析或调用模型；
- `ProductAlias(alias_type="manual", source="manual")` 是本 PR 唯一的持久
  管理员 alias allowlist 编码；该规则进入版本化 resolver policy hash；
- fuzzy/embedding/LLM/任何 `source="auto"` alias（包括
  `alias_type="registration_no"`）只能提供候选提示，不能铸造 identity；
- 产品主数据 category/channel/region 只允许否决候选，不能创造候选。
- 只有 `ProductVersion.terms_revision` 能承载版本级备案/注册锚点；
  `InsuranceProduct.filing_no` 与产品级 registration alias 不得降级选版本；
- 新建 `ProductVersion` 时，注册服务从同一版本目录的 `ProductMeta` 将备案号
  （缺失时才使用注册号）写入 `terms_revision`；已有版本永不原地改写。

## 非目标

- 新表、migration、receipt 持久化、P3 API、UI、通用 Entity Registry；
- 负向记忆、历史路由清理、模型或 provider 调用；
- 修改 029a/031/PR44/外部 PR #53 现场；
- Tencent/WeKnora 上游债务。

## 阻断条件

仅当备案/注册编号无法通过现有 `ProductVersion.terms_revision` 唯一映射，或实现被
证明必须新增持久化表时停止。其他范围外问题只记录为 BACKLOG 或 REJECTED。

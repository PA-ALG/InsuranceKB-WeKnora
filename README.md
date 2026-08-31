# InsuranceKB · Enterprise LLM Wiki

InsuranceKB 把保险条款、产品说明书、费率表和人工审核结果编译成可版本化、
可追溯、可由人阅读也可由 Agent 精确消费的知识制品。WeKnora 负责企业平台、
权限、文档载体与检索；本仓库的 Python Harness、Go 服务和 Vue 页面负责保险领域
的 canonical authority、发布治理、只读 Schema Wiki 与原文引文。

> [!IMPORTANT]
> 开始开发前先读 [`AGENTS.md`](AGENTS.md)，再读 [`HANDOFF.md`](HANDOFF.md)
> 和当前任务适用的 OpenSpec。旧设计、旧控制板与历史 OpenSpec 只保留审计价值，
> 不能覆盖这三个当前入口。

## 当前 MVP（2026-08-31）

MVP-815 最终代码已由
[PR #123](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/123) 以一个提交进入
`main`：

| 身份 | 值 |
|---|---|
| MVP code commit（已在 main） | `ef47bee2b93d6a9cb4511133deaef6e700d915ce` |
| tree | `d868e8f2fd51250c71366c8c723f500482e7de44` |
| parent | `dfa87e11d5a434b6823582285c17498e715dd8f1` |
| 工程交接文档 | [PR #124](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/124) |
| PR #124 合并后的最终 main HEAD | `DEFERRED-UNTIL-PR-124-MERGE`；以 PR 合并元数据与总控终态报告机械解析 |
| OpenSpec | `120-schema-wiki-medical-596-1-mvp` |
| C7 | FLOW PASS / UI PASS / 7 分类 / 67 字段 / 17 of 17 citations / 3 PDFs |
| C4 | DEFERRED；必须从最新 main 新开 Mission |

这次交付从当时最新 main 重建最终有效代码，**没有合入或整体 squash 149 条中间
迭代提交**。旧 C4 实验也没有进入 main。

## 用户应打开什么

正式体验对象是知识库 **`medical-insurance-mvp`** 中的“产品 Schema Wiki”。页面
应显示：

- 产品“平安 e 生保（尊享版）医疗保险”；
- `当前 MVP · 只读`；
- `7 个分类 · 67 个字段`；
- 中文字段名为主标签，英文 `field_id` 为次级技术标识；
- `present / absent_explicitly / unknown` 三态；
- “原文来源”、来源切换、固定页码/bbox/引文和三份 PDF 高亮。

`C6-ISOLATED-R1-ACCEPTANCE-*` 是历史隔离验收库，不是正式产品入口。“产品
Schema Wiki 暂不可用”是 fail-closed 状态，不表示功能代码不存在。若整个页面不可
用，先检查前端 entry/serving 映射、当前用户可访问的唯一 Active Head/release members
以及 Wiki + RAW 双 ACL；若只有引文正文不可用，再检查 native revision/source custody
与 citation-token 运行时签名环。

`schema_wiki_frozen_release_scope`、named-human decision ring 和
publish-authorization ring 只服务 Candidate 决策/发布，不是只读体验前置条件；只读
演示应保持这些写链路禁用或为空。Golden quality evaluator ring 属于未来 C4 质量
评估，同样不属于 C7 只读体验。

端口不是版本号。C7 时 `18085` 是 UI、`18094` 是隔离后端，旧生产 `8081` 明确
保持不变。版本必须用 Git commit/tree、制品 SHA、release ID 和 activation epoch
共同确认。

## 系统边界

```text
原始 PDF / 人工权威
        │
        ▼
Python Harness
ParsedDocument → Candidate/Evidence → review/release custody
        │
        ▼
Go + PostgreSQL + WeKnora
唯一 Active Head / exact release pin / immutable citation reader
        │
        ▼
Vue Schema Wiki
中文 7/67 → 来源切换 → exact PDF page/bbox/quote
```

关键约束：

- Candidate、Evidence、release、receipt 与 Head 全链 fail closed；
- UI 只读 exact active-current 或 explicit-pinned，不做 current/latest fallback；
- citation bytes 只能经短期 token 读取并先校验 SHA；
- provider/model、DB 写、审批、签名和发布均是显式外部动作，未运行必须写
  `NOT RUN`；
- 不另建第二套 route、DTO、viewer、service、table 或 platform 旁路现有合同。

## 开发与验证

仓库以 OpenSpec + TDD + CI lane 为交付门禁。精确命令以 [`AGENTS.md`](AGENTS.md)
和工作流为准，常用入口如下：

```bash
cd harness
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live and not integration_postgres" -q
```

```bash
go test ./internal/application/repository ./internal/application/service \
  ./internal/handler ./internal/router ./internal/container ./internal/config
go vet ./...
```

```bash
cd frontend
npm test
npm run type-check
npm run build
```

PostgreSQL integration lane 必须证明 tests > 0 且 skipped = 0。不要用 deterministic
测试替代 PostgreSQL、live、provider 或 model 证据。

## Chrome 可见验收

复用用户现有 Chrome 登录态时，使用 Computer Use 直连 `com.google.Chrome`
（`node_repl` + `@oai/sky`）。它不依赖 ChatGPT/Codex 浏览器扩展，也不要求切换
Profile。若页面跳到 `/login`，这是站点 session 问题；由用户在可见页面自行登录，
自动化不得读取/代填凭据或注入 token。

## 接手顺序

1. [`AGENTS.md`](AGENTS.md)：贡献规范、权限和门禁；
2. [`HANDOFF.md`](HANDOFF.md)：当前运行与交付状态；
3. [MVP-815 工程接手卡](docs/insurance-kb/26-mvp-815-engineering-handoff.md)：
   代码地图、部署配置、验证入口和 C4 Mission 起点；
4. [仓库清理清单](docs/insurance-kb/27-mvp-815-repository-cleanup.md)：归档、保护项
   与分阶段清理；
5. [OpenSpec 120](openspec/changes/120-schema-wiki-medical-596-1-mvp/)：MVP 合同与
   验收证据。

更完整的背景文档索引见
[`docs/insurance-kb/README.md`](docs/insurance-kb/README.md)。WeKnora 上游说明见
[`README_CN.md`](README_CN.md)。

## 下一项：C4 定制质量闭环

旧提交 `6d56618d0d9796e10d87f93e6b04188a49da9296` 仅作历史参考，结论为
`QUALITY_FAIL`，且绑定旧 Candidate 与固定 reviewer/attestor；它不在 main。

后续 C4 必须从执行时最新 `origin/main` 新开 OpenSpec/Mission，重新冻结业务目标、
Metric ID、Golden/Candidate/Evidence 身份、人工责任、provider/model 边界和预算。
不得复制旧哈希或把旧失败改写成 PASS，也不得影响已验收的 C7 serving release。

## License

本仓库继承 WeKnora 上游许可证与第三方声明；新增或迁移资产必须同时满足仓库
provenance、隐私和许可证门禁。

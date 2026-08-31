# 26 · MVP-815 工程接手卡

> 面向下一位开发者。贡献流程、权限和门禁只引用根目录
> [`AGENTS.md`](../../AGENTS.md)；本文只解释已交付系统、演示入口和下一项 C4。

## 1. 已交付基线

MVP 代码由 PR #123 作为一个提交进入 main：

| 身份 | 值 |
|---|---|
| MVP code commit（已在 main） | `ef47bee2b93d6a9cb4511133deaef6e700d915ce` |
| tree | `d868e8f2fd51250c71366c8c723f500482e7de44` |
| parent | `dfa87e11d5a434b6823582285c17498e715dd8f1` |
| 工程交接文档 | [PR #124](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/124) |
| PR #124 合并后的最终 main HEAD | `DEFERRED-UNTIL-PR-124-MERGE`；以 PR 合并元数据与总控终态报告机械解析 |
| OpenSpec | `120-schema-wiki-medical-596-1-mvp` / SWM1–SWM11（含 SWM9A） |
| C7 状态 | FLOW PASS / UI PASS / 17 of 17 citations / 3 PDFs |
| C4 状态 | DEFERRED / new Mission required |

历史验收分支 `9fcf3386` 是 C7 运行参考；后续开发起点只能是最新 main，不能从
该历史分支继续堆提交。

## 2. 代码地图

| 责任 | 主要位置 | 当前不变量 |
|---|---|---|
| Python canonical authority | `harness/src/insurance_harness/knowledge_compiler/` | Candidate/Evidence/revision/native PDF/manifest 全链 fail closed |
| Python 验收与 lane 隔离 | `harness/tests/` | task-private replay 不污染 deterministic/PostgreSQL collection |
| Go repository | `internal/application/repository/schema_wiki_formal_candidate_preview.go`、`wiki_release.go` | 只读 current/pinned 与 persisted custody |
| Go service | `internal/application/service/schema_wiki*.go` | frozen scope、Unicode offset、parent→canonical child、overlap owner |
| Go HTTP/DI | `internal/handler/schema_wiki.go`、`internal/router/routes_schema_wiki.go`、`internal/container/` | 既有 route/ACL/Head/CAS；无第二套平台 |
| 部署配置 | `internal/config/config.go`、`config/config.yaml` | serving、citation token、decision/publish、Golden evaluator 四域分离；各自在适用动作中 fail closed |
| Vue 产品体验 | `frontend/src/views/knowledge/schema-wiki/` | 中文 7 分类/67 字段、Active pin、无 current/latest fallback |
| PDF 引文 | `frontend/src/components/schema-wiki/` | token-only bytes、SHA 后打开、页码/bbox/quote 固定 |
| 前端运行映射 | `frontend/public/config.js`、`frontend/docker-entrypoint.sh` | entry KB 与 serving KB 显式映射；未配置即不冒充 MVP |

不要新增第二个 route/DTO/page/viewer/service/table/platform 来旁路这些边界。若 C4
需要新的产品行为，先用 OpenSpec 证明为什么现有扩展点不足。

## 3. 演示入口与配置

体验对象是知识库 `medical-insurance-mvp` 的“产品 Schema Wiki”，不是
`C6-ISOLATED-R1-ACCEPTANCE-*`。

前端需要同时配置：

- `SCHEMA_WIKI_MVP_ENTRY_KB_ID`
- `SCHEMA_WIKI_MVP_SERVING_KB_ID`

后端配置必须按用途拆开：

- **只读 serving**：使用数据库中既有 release/Head/members、native revision/source
  custody 与当前用户的 Wiki + RAW 双 ACL；不创建、不推进任何发布对象。
- **引文正文**：需要 citation-token 运行时签名环来签发短期读取令牌。私钥只由
  部署层注入，仓库没有默认私钥。
- **Candidate 决策/发布**：`schema_wiki_frozen_release_scope`
  （tenant/space/raw/wiki 四项）、named-human decision ring 与
  publish-authorization ring 只在显式决策/发布时需要；只读演示必须保持禁用或为空。
- **未来 C4**：Golden quality evaluator ring 只服务质量评估，不是 C7 serving
  前置条件。

四个信任域在启用时必须互异；不得复用 key，也不得把任何私钥写进配置文件、Git
或回执。

正常页面特征：

- `当前 MVP · 只读`；
- `7 个分类 · 67 个字段`；
- 中文字段名在上，英文技术 ID 在下；
- 字段状态和值；
- 有证据的字段可打开“原文来源”，切换来源并查看 PDF 高亮。

“产品 Schema Wiki 暂不可用”是 fail-closed 状态。整个页面不可用时按顺序检查
runtime mapping、当前用户可访问的唯一 Active Head/release members 与 Wiki + RAW
双 ACL；只有引文正文不可用时，再检查 native revision/source custody 与
citation-token ring。不要打开 decision/publish/C4 配置来修复只读页面，也不要改
前端做 generic fallback。

## 4. Chrome UI 验收

需要已有 Chrome 登录态时，使用 Computer Use 直接控制 `com.google.Chrome`
（`node_repl` + `@oai/sky`）。不依赖 ChatGPT/Codex 浏览器扩展，也不切 Profile。

如果页面停在 `/login`，那是站点 session 失效；由用户自行可见登录。自动化不得
读取/代填凭据、注入 token 或把密码写入回执。登录恢复后只执行只读 FLOW/UI
验收。

## 5. 验证入口

精确命令仍以 [`AGENTS.md`](../../AGENTS.md) 和 CI workflow 为准。常用入口：

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

PostgreSQL integration 必须由独立 lane 证明 tests > 0 且 skipped = 0；live、provider、
model 和部署未运行时必须写 `NOT RUN`，不能用 deterministic 代替。

## 6. C4 定制开发 Mission 起点

旧 `6d56618d` 的 EC-02 实验不在 main，结论是 `QUALITY_FAIL`，且把 reviewer、
attestor、Candidate 与 artifact SHA 固定在代码里。它只可用于理解曾经测量过的
指标和失败模式，不可 cherry-pick、merge 或复制常量。

建议新 Mission Card：

### C4 Schema67 定制质量闭环

- 业务目标：针对已验收 Schema67 MVP，定义可复现、可解释、可由指定人负责的
  定制质量评估与改进闭环。
- 起点：执行时最新 `origin/main`。
- 唯一写 Owner：新 Mission 指定，且与 MVP serving release 隔离。
- 先冻结：目标产品/字段范围、Metric ID 与阈值、Golden identity、Candidate
  identity、Evidence 判定、人工 reviewer/attestor 选择方式、provider/model 与预算。
- 输入：当前 canonical Candidate/Evidence/Golden 合同；禁止重用旧 Candidate SHA、
  reviewer/attestor 字面量或旧 `QUALITY_FAIL` 报告作为当前事实。
- 输出：不可变评估报告和清晰的 PASS/QUALITY_FAIL；失败不得推进 Candidate、
  release、receipt 或 Head。
- TDD：先证明旧固定身份、Golden 漂移、Evidence 断链、指标缺项、provider 越权和
  报告自哈希篡改均 fail closed。
- 外部动作：provider/model、DB、审批/签名、发布分别授权；默认全部 NOT RUN。
- 非目标：本任务不扩建通用评审平台，不修改 C7 reader，不重做 67 字段 UI。

## 7. 允许清理与必须保留

允许后续删除的是已归档、clean、可从 Git bundle 恢复、且无任务私有资产的历史
worktree。必须保留：

- dirty 工作区；
- 当前 main/handoff 工作树；
- mode-0600 运行回执和发布证据；
- 可能含忽略凭据或不可再生构建证据的目录，直到人工复核；
- Git bundle 与其 SHA 记录。

精确盘点见 [27 · repository cleanup](27-mvp-815-repository-cleanup.md)。

## 8. 历史材料如何使用

`mvp_handoff_jlx.md`、`jlx_enterprise_llm_wiki_complete_728_v3.md`、旧控制板和旧
OpenSpec 都保留审计价值，但不能覆盖本文件、当前 `HANDOFF.md`、适用 OpenSpec
和最新 main。看到“NOT RUN”“BLOCKED”“planned”时必须结合其日期与后续 validation
report，不得把历史状态抄回当前交付说明。

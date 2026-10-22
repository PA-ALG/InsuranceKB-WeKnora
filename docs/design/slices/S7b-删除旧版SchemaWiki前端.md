# S7b · 删除旧版 Schema Wiki 前端（830 时期页面、接口适配与引用查看器）

> 状态：Claude 2026-10-22 提出；用户同日同意删除旧版 Schema Wiki 页面（"可以删"）｜ 作者：Claude Code
> 依据：蓝图 §10（前端三套 Schema Wiki 页面家族、5 个 API adapter、2 套引用查看器 → RETIRE，保留 pdf.js 高亮）、§11 S7
> 实现方：Claude ｜ 审核方：Codex（复杂改动：前端，涉及受保护验收测试的预期变更）｜ 真实模型调用：0
> S7a（#193，删除不可达的 Harness 模块）已完成。S7 其余部分另起切片：S7c Harness `knowledge/`，S7d G3/830 链路，S7e 收尾

## 1. 目标与现状

**目标**：删除知识库页里已被"企业知识"入口替代的 830 时期前端。删除后：

- 知识库页默认打开"文档"标签；
- 受管知识库切到原生 Wiki 标签时，回到"文档"标签，不再回到旧的 Schema Wiki；
- 企业知识页的 PDF 高亮照常工作。

**现状**：共 56 个文件、约 11.8k 行，包括：

| 目录 | 内容 |
|---|---|
| `frontend/src/views/knowledge/schema-wiki/` | 页面：SchemaWiki 浏览器、字段页与 Golden 审核；830 G1 实体页；G2、G3 概念页、目录与 pack 目录 |
| `frontend/src/api/schema-wiki/` | 5 个接口适配 |
| `frontend/src/components/schema-wiki/` | 2 套引用查看器，以及 `pdfJsPort` |

还有几处引用它们的地方：

- **`KnowledgeBase.vue`**：
  - 有 `schema` 标签；
  - 默认打开 `schema`；
  - 引入 `SchemaWikiCatalogEntry830G2`。
- **`frontend/src/router/index.ts`**：6 条 `/knowledge-bases/:kbId/schema-wiki*` 路由。
- **`useReleaseCustody.ts`**：受管知识库切到 `materials` 或 `graph` 时改回 `schema`。
- **`product-ingestion-status.vue`**：G3 产品导入面板。它给已发布产品生成的链接只接受 `/schema-wiki/...` 路径，删除后这些链接会指向不存在的页面。
- **企业知识**：`SourcePageViewer.vue` 及两个测试从 `@/components/schema-wiki/pdfJsPort` 引入 pdf.js 端口。这部分要保留，蓝图明确保留 pdf.js 高亮。

## 2. 设计

1. **移动 `pdfJsPort`**：`frontend/src/components/schema-wiki/pdfJsPort.ts` 及其测试原样移到 `frontend/src/enterprise/`。企业知识改为从 `./pdfJsPort` 引入，行为不变。
2. **删除三个目录**：`views/knowledge/schema-wiki/`、`api/schema-wiki/`、`components/schema-wiki/`，其中的测试一并删除。
3. **路由**：删除 6 条 `schema-wiki` 路由。旧书签按路由表现有的未匹配处理，不另加兼容跳转（删除优于兼容）。
4. **`KnowledgeBase.vue`**：
   - 标签只剩 `materials`、`documents`、`graph`；
   - 默认 `documents`；
   - 地址里 `?tab=schema` 视为无效，按默认处理；
   - 删除 `schema` 标签的面包屑项、内容区与引入。
5. **`useReleaseCustody.ts`**：受管知识库切到 `materials` 或 `graph` 时改为 `documents`。
6. **`product-ingestion-status.vue`**：已发布链接只接受知识库首页 `/platform/knowledge-bases/<wiki_kb>`，不再接受 `/schema-wiki` 子路径。安全校验的其余规则不变：同源、无控制字符、知识库身份一致。整个面板随 G3 链路在 S7d 删除。
7. **`package.json`**：删除只是别名的 `test:schema-wiki-component` 脚本。

不做：
- 不删除这些页面使用过的语言包键。键值多、与其他页面共享的情况需要逐条核对，放到 S7e 收尾一并处理。
- 不改后端路由，也不改 G3 产品导入后端（S7d）。

## 3. 上游补丁

- `KnowledgeBase.vue`、`router/index.ts` 已登记，本片只减少改动。
- 补丁文件数不增加（G10 不变）。
- 被删除的文件都是项目新增文件，G3、G4、G11 的基线下降，由脚本重新记录（只降不升）。

## 4. 验收（RED，Claude 编写，受保护）

**新增 `frontend/src/enterprise/legacyFrontendRemoved.spec.ts`**：

- 三个旧目录下没有任何源文件（`import.meta.glob` 为空）；
- 路由表源码不含 `schema-wiki`；
- `KnowledgeBase.vue` 源码不引入 `schema-wiki` 目录，标签列表不含 `schema`，默认标签为 `documents`；
- 企业知识只从 `./pdfJsPort` 引入 pdf.js 端口，`frontend/src/enterprise/pdfJsPort.ts` 导出 `createPdfJsPort`。

**改动已有的受保护测试**，在 RED 提交中单独说明：

| 测试 | 原预期 | 新预期 |
|---|---|---|
| `releaseRead.spec.ts` | 受管库回到 `schema` | 回到 `documents` |
| `SourcePageViewer.spec.ts`、`sourcePageLifecycle.spec.ts` | 模拟 `@/components/schema-wiki/pdfJsPort` | 模拟 `./pdfJsPort` |
| `product-ingestion-status.spec.ts` | `/schema-wiki/...` 链接生效 | 不再生成该链接；知识库首页链接生效 |

**移动**：`components/schema-wiki/pdfJsPort.spec.ts` 移到 `enterprise/pdfJsPort.spec.ts`，内容不变，只改引入路径。

## 5. 改动范围

- 删除：`frontend/src/views/knowledge/schema-wiki/`、`frontend/src/api/schema-wiki/`、`frontend/src/components/schema-wiki/`（`pdfJsPort` 移走）；
- `frontend/src/enterprise/pdfJsPort.ts`（移入）、`SourcePageViewer.vue`、`useReleaseCustody.ts`；
- `frontend/src/views/knowledge/KnowledgeBase.vue`、`frontend/src/router/index.ts`；
- `frontend/src/components/knowledge-base/product-ingestion-status.vue`；
- `frontend/package.json`（删除别名脚本）；
- `tests/architecture/baseline.json`（脚本重新记录，只降）；
- `docs/design/upstream-patches.md`：`KnowledgeBase.vue` 与路由登记行补一句"S7b 删除 Schema Wiki 标签与路由"（追加说明，不改原意）。

## 6. 上线与验证

- 只换 UI 镜像。部署另开 Issue，需用户确认。
- 浏览器核对：
  1. 知识库页默认显示"文档"，没有 Schema Wiki 标签；
  2. 企业知识页打开出处，PDF 高亮正常。

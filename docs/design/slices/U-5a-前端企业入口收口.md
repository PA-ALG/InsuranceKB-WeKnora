# U-5a 前端企业入口收口：路由、侧栏与语言包改为启动时注册

> 状态：Spec 冻结（2026-10-31，Claude）。实现方 Claude，审核方 Codex。属于 U-1 阶段 c（Issue #451）。
> 真实调用：0。不部署；随下一次 UI 镜像上线即可，无迁移。

## 1. 为什么选这一片

阶段 c 当前 `main@a4c972719`，G10 = 163（基线 `f17ee8a8d` = v0.9.0）。按"每审一行能真正恢复的上游文件数"比较剩余候选（族与行数见附录 A 末尾"阶段 c 起点盘点"）：

| 候选 | 能恢复的上游文件 | 需审核的改动 | 结论 |
|---|---|---|---|
| U-3 问答挂接改 chat pipeline 插件 / ToolRegistry | ANSWER 族里 `into_chat_message.go`、`references.go` 等是上游插件**内部**的分支；v0.9.0 的 EventManager 只能追加插件，不能替换或跳过上游插件，`session_knowledge_qa.go` 的检索阶段也没有注册点 | 问答主链路 Go 代码，数百行 | 恢复不了文件，只能缩短行数；要先向上游提扩展点 |
| U-4 来源固定接缝收进自有文件、只留一行调用 | 0：G11 禁止在上游包里新增 Go 源文件，调用行仍留在上游文件中 | 数百行 Go | 只降行数，不降文件数 |
| U-6 部署覆盖层 | DEPLOY / FE-DEPLOY 最多 24 个 | 构建与部署脚本 | 与在途 I1 修复分支（`.github/workflows/images.yml`、`scripts/app_*`、`docker/`）写域重叠，暂缓 |
| **U-5a 前端入口（本片）** | **3 个**恢复上游字节：`router/index.ts`、`stores/menu.ts`、`i18n/index.ts`；新增 1 个两行补丁 `main.ts` | 生产约 130 行，其中约 100 行是原样搬迁；另有测试 | **G10 −2**；去掉的 `router/index.ts` 是冲突风险最高的前端文件之一（v0.9.0 上游改了 110 行） |

本片用到的都是**上游依赖已有的公开扩展点**：Vue Router 的 `router.addRoute(父路由名, 路由)`、vue-i18n 的 `i18n.global.mergeLocaleMessage`、Pinia setup store 暴露的响应式 `menuArr`。不需要上游 PR；新文件都在 `frontend/src/enterprise/`，不触及 G11。
写域检查：在途分支 `slice/s11c`、`slice/i3a`、`slice/i1fix`、`slice/docreader-swap` 都不改 `frontend/` 与 `tests/architecture/`。

## 2. 改动

1. 新文件 `frontend/src/enterprise/routes.ts`：从 `router/index.ts` 原样搬出 11 条企业路由（`materialsWiki` 旧书签重定向，以及 `enterpriseSpaces`、`enterpriseSpace`、`enterpriseChanges`、`enterpriseSpotChecks`、`enterpriseReviews`、`enterpriseConfirmations`、`enterpriseGraph`、`enterpriseConcept`、`enterpriseWikiPage`、`enterpriseEntity`）。组件路径从 `../enterprise/X.vue` 改为 `./X.vue`，path、name、props、meta、redirect 逐字不变；另导出父路由名 `ENTERPRISE_ROUTE_PARENT = 'Platform'`。
2. 新文件 `frontend/src/enterprise/install.ts`：导出 `installEnterprise({ router, i18n, pinia })`，按以下顺序执行：
   - 先校验接入点：父路由 `Platform` 存在，侧栏菜单里有 `knowledge-bases`。缺任一项直接抛错，且此时尚未注册任何东西。这样上游升级改了名字时会在 CI 里暴露，不会悄悄丢掉企业入口；
   - 对 i18n 实例的每个可用语言执行 `mergeLocaleMessage(locale, ENTERPRISE_MESSAGES[locale])`；没有企业文案的语言保持不动，与现在的 `withEnterpriseMessages` 相同；
   - 对每条企业路由，`router.hasRoute(name)` 为假时执行 `router.addRoute('Platform', route)`；
   - 侧栏没有 `enterprise` 项时，在 `knowledge-bases` 之后插入 `{ title: t('menu.enterpriseKnowledge'), titleKey: 'menu.enterpriseKnowledge', icon: 'enterprise', path: 'enterprise' }`。菜单 store 自带的语言切换 watch 会继续刷新这一项的标题；
   - 重复调用不产生额外效果（幂等）。
3. `frontend/src/enterprise/i18n/index.ts`：把 `ENTERPRISE_MESSAGES` 改为导出。`withEnterpriseMessages` 不变，`localeKeyAudit.ts` 仍在用它。
4. `frontend/src/main.ts` 作为新登记的上游补丁，**只加两行**：
   - `import { installEnterprise } from "@/enterprise/install";`
   - 在 `app.use(pinia);` 之后立即调用 `installEnterprise({ router, i18n, pinia });`

   这个位置早于 `app.use(router)` 触发的首次导航，所以深链接 `/platform/enterprise/...` 在首屏就能匹配；也早于挂载。
5. 以下三个文件恢复为 `f17ee8a8d` 原样：`frontend/src/router/index.ts`、`frontend/src/stores/menu.ts`、`frontend/src/i18n/index.ts`。
6. 受保护测试的必要改动，放在 RED 提交内并单独说明：`reviewPage.spec.ts` 与 `confirmationPage.spec.ts` 用 `?raw` 读取路由源码来核对路由登记。
   - 改为读取 `@/enterprise/routes.ts?raw`；
   - 正则里的组件路径同步改为 `./EnterpriseReviews.vue` 和 `./EnterpriseConfirmations.vue`；
   - 断言含义不变：仍逐项核对路由名、路径与组件。
7. 基线与登记：
   - G10 先手工新增 `frontend/src/main.ts` 一条（按 G10 逐项审查条款），再用 `record_baseline.py`（不带 `--init`）下调，163 → 161；
   - `docs/design/upstream-patches.md` 追加 `main.ts` 的登记行，以及 3 个文件的"已移除"行。

运行时语义：

- **路由匹配**：Vue Router 按路径得分排序匹配，与登记顺序无关。企业路由仍是 `Platform` 的子路由，`to.meta` 与全局守卫的行为不变。
- **语言包合并**：`mergeLocaleMessage` 用 vue-i18n 的 `deepCopy` 深合并（叶子覆盖），与 `mergeMessages` 规则相同。差别是它把企业键写进 i18n 实例持有的上游语言包对象。运行时读取这些对象的只有 `src/i18n/index.ts`（`localeKeyAudit.ts` 只被测试和脚本使用），所以没有可见差异。
- **侧栏菜单**：菜单 store 的 `chatMenuIndex` 在创建时取 `creatChat` 的下标（0）。企业项插在它之后，会话列表仍挂在 `creatChat` 下。

## 3. 验收

- **刻画测试**：单独提交，在 `main` 上先通过。文件为 `frontend/src/enterprise/appEntry.spec.ts`，用一个 `assemble()` 拿到"应用实际看到的" router、i18n 与菜单，核对：
  - 11 条企业路由：
    - 完整路径集合，父路由为 `Platform`；
    - `meta`；
    - props，包括 `?release=` 为空或为数组时 `releaseId` 为 `undefined`；
    - `materialsWiki` 的重定向结果；
    - 懒加载的组件就是对应的 `.vue` 模块。
  - 6 种语言的消息与 `withEnterpriseMessages(上游语言包)` 深相等。
  - 侧栏：
    - 顺序（`enterprise` 紧跟 `knowledge-bases`）与这一项的内容；
    - 中英文标题随语言切换；
    - 会话列表仍挂在 `creatChat` 下。
- **RED（受保护）**：
  - `appEntry.spec.ts`：`assemble()` 改为调用 `installEnterprise`，已有断言不改。新增以下用例：
    - 重复安装幂等；
    - 缺父路由、缺 `knowledge-bases` 时抛错，且没有注册任何路由或文案（校验先于注册）；
    - `main.ts` 在 `app.use(pinia)` 之后、`app.use(router)` 之前调用 `installEnterprise`；
    - 企业路由源码不含 `schema-wiki`（S7b 的 `legacyFrontendRemoved.spec.ts` 只读上游路由表，这里补上搬出去的部分）。
  - `tests/architecture/test_u5a_frontend_entry_restored.py`：
    - 3 个文件与 `f17ee8a8d` 逐字节一致；
    - `main.ts` 相对上游只多上述两行，没有删除；
    - G10 ≤ 161。
  - 上述两个受保护 spec 的源码来源调整（见 §2 第 6 条）。
- **门禁**：
  - 前端 `npm test` 与 `npx vitest run --config vitest.config.ts`（全部 spec），和 `main` 在同一环境逐项对比；
  - `npm run type-check`、`npm run build`；
  - `pytest tests/architecture`；
  - `git diff --check`。

## 4. 不做

- 以下文件保持现状，上游没有对应扩展点：
  - `components/menu.vue`：图标、激活态与顶部分组写死在组件里；
  - `i18n/localeKeyAudit.ts`：上游测试 `catalogToolDisplay.test.ts`、`localeKeyAudit.test.ts` 用 `LOCALE_BUNDLES` 核对每种语言的键集，必须包含企业键；
  - `test-utils/vueFixture.ts`、`assets/theme/theme.css`、`api/mcp-endpoint.ts`。
- 问答错误提示（`useChatStreamHandler.ts`、`views/chat/index.vue`）属于 ANSWER 族，另起一片处理。
- 不改任何页面的行为与文案。

## 5. 回滚

回退本片提交即可。纯前端改动，无迁移，无数据变化。

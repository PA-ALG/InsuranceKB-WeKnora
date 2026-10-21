# S3j · 字段标题、缺失字段标识与导航切换：字段标题与自由知识wiki 一样醒目，未抽到值的字段在导航中显示为灰色，在 schema_wiki 与自由知识wiki 之间切换时导航保持原样

> 状态：Claude 2026-10-21 按用户浏览器反馈提出 ｜ 作者：Claude Code
> 实现方：Codex（前端）｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 用户反馈（2026-10-21，截图）

1. 产品页 schema_wiki 的字段标题（如"投保年龄"）太小，"完全看不清"，希望参考自由知识wiki 页面的样式。目前字段标题是 13px 的次要灰色字。这是 S3d 时"值是重点、标题弱化"的取舍，用户现在改了主意。
2. 导航 schema_wiki 下的字段如果还没抽到值，希望用颜色（如灰色）标出来，方便看出哪些字段缺失。
3. 同一截图里，打开产品页时，导航中该产品的所有字段都是绿色高亮。原因是字段链接只靠 hash 区分，Vue Router 判断"当前页"时忽略 hash，于是每个字段都被标成 `aria-current="page"`。不修这个问题，灰色缺失标识会被高亮盖住。

## 2. 设计

### 2.1 产品页字段标题

- 字段标题改为三级标题 `<h3 class="ek-field__title">`，内容不变：有概念页时仍是链接。
- 样式与自由知识wiki 正文的三级标题一致：`font-size: 17px`、`font-weight: 600`、`color: var(--td-text-color-primary)`。
- 分组标题（`.ek-section__title`，20px）保持比字段标题大。
- 标题中的概念链接沿用现有规则：平时继承标题颜色，悬停时才变绿并加下划线。
- 字段值、出处按钮、展开/收起等其他排版不变。

### 2.2 导航中的缺失字段

- 字段状态为 `unknown`（页面显示"材料未提及"）的字段链接：
  - 加 `data-field-missing`；
  - 颜色为 `var(--td-text-color-placeholder)`，规则写在 `enterpriseNavigation.css`；
  - 链接内追加一段只给读屏软件读的文字"（材料未提及）"（视觉隐藏，不能只靠颜色表达）；
  - `title` 属性为"<字段名>（材料未提及）"。
- `absent_explicitly`（"材料明确没有"）是确定的答案，不算缺失，样式不变。
- 呈现配置里有、但版本中没有对应 claim 的字段，仍按现状不显示（不在本切片范围）。

### 2.3 导航中的当前字段

- 字段链接不再因为"在这个产品页上"而被标成 `aria-current="page"`。
- 只有与当前地址 hash 对应的字段（即刚点过、页面已滚动到的字段）标 `aria-current="location"`，并使用与当前页相同的高亮样式。
- 没有 hash 时，字段都不高亮。产品名链接与自由知识wiki 页面链接的现有规则不变。

### 2.4 在 schema_wiki 与自由知识wiki 之间切换时导航保持原样（用户同日报告的缺陷）

用户报告：
- 在 schema_wiki 里第一次点字段，整页会刷新；
- 切到自由知识wiki 点一个页面后，导航列会刷新，并自动切回 schema_wiki。

已用测试复现，根因有两个：

1. **同一版本被当成新版本重新加载**：从首页进入产品页时地址不带 `release`，打开的是 Active。点字段后地址带上 `release=<同一 id>`，`EnterpriseEntity` 的 `releaseId` 从空变成该 id，`load()` 把页面置为加载中并清空 release，导航随之卸载、重建。`EnterpriseWikiPage` 有同样的写法。
2. **导航状态随页面一起丢失**：产品页与自由知识wiki 页面是两个路由组件，各自渲染一份导航。切换页面时导航重建，schema_wiki 回到默认展开，用户收起的状态丢失；自由知识wiki 也只按"是否在 wiki 页面上"决定开合。

规则：

- 页面已显示的 release 与地址要求的 release 相同（同一 Space、同一 id）时，不重新加载，不出现加载状态，导航不重建。
- 每个产品的 schema_wiki 与自由知识wiki 开合，由读者手动操作决定，在本次会话中跨页面保留（按 Space、版本、产品区分）：
  - 读者没操作过时，用原默认：schema_wiki 展开，自由知识wiki 收起；
  - 打开自由知识wiki 的某个页面时，该组强制展开，并标出当前页；
  - 程序设置的展开不算读者的选择。
- 换成另一个版本时，回到默认。
- 不改路由结构。若实现方认为需要改成共享布局才能做到，先在 Issue 中说明，不自行换方案。

## 3. 改动范围

- `frontend/src/enterprise/EnterpriseField.vue`；
- `frontend/src/enterprise/NavigationEntry.vue`；
- `frontend/src/enterprise/EnterpriseEntity.vue`、`frontend/src/enterprise/EnterpriseWikiPage.vue`（只改"同一 release 不重新加载"）；
- 如需新增模块保存导航开合（例如 `frontend/src/enterprise/navigationMemory.ts`），放在 `frontend/src/enterprise/` 下；
- `frontend/src/enterprise/enterprisePage.css`、`frontend/src/enterprise/enterpriseNavigation.css`；
- 如需新文案，只加在 `frontend/src/i18n/locales/` 下各语言文件的 `enterpriseKnowledge` 段；
- 实现方测试。

不改 Go、Harness、Release 数据与其他页面。

## 4. 验收（RED：`frontend/src/enterprise/fieldReadability.spec.ts`，Claude 编写，受保护）

使用 S3e 的合成数据：M2 的犹豫期有值、等待期为 `unknown`；C1 的宽限期为 `absent_explicitly`。

1. 产品页：M2 的"犹豫期""等待期"都以 `h3.ek-field__title` 显示。
2. 样式：`enterprisePage.css` 中有一条规则包含 `.ek-field__title` 选择器，设置 17px、600、`var(--td-text-color-primary)`；没有任何规则把它设得小于 17px。`.ek-section__title` 的字号大于字段标题。
3. 导航（真实路由，产品页无 hash）：
   - M2 的"等待期"链接带 `data-field-missing`，文字含"材料未提及"，`title` 为"等待期（材料未提及）"；"犹豫期"不带该标识；
   - schema_wiki 中没有任何链接带 `aria-current`。
4. 导航（地址 hash 为 `#waiting_period`）：只有"等待期"带 `aria-current="location"`，没有字段带 `aria-current="page"`。
5. C1 的"宽限期"（`absent_explicitly`）不带缺失标识。
6. `enterpriseNavigation.css` 中有一条含 `[data-field-missing]` 的规则，设置 `color: var(--td-text-color-placeholder)`。

`frontend/src/enterprise/navigationContinuity.spec.ts`（真实路由，渲染真实的产品页与自由知识wiki 页面）：

7. 从不带 `release` 的产品页点 schema_wiki 中的字段：地址 hash 变为该字段；没有出现加载状态；schema_wiki 节点是同一个 DOM 元素，没有重建。
8. 在产品页收起 schema_wiki、展开自由知识wiki，然后依次操作，每一步 schema_wiki 都保持收起、自由知识wiki 都保持展开：
   - 点自由知识wiki 中的一页：当前页被标出；
   - 再点另一页：当前页被标出；
   - 点产品名回到产品页。

RED 提交同时修改两处与新规则冲突的已有期望（S6d-2/S6d-3 实现方测试）：

- `navigationSchemaState.spec.ts`：回到先前收起的产品时保持收起（原期望是重新展开）；
- `navigationWikiState.spec.ts`：读者展开后，切到一个不存在的页面键时仍保持展开（原期望是收起）。

已在一次性原型上验证：按 §2 实现后，`src/enterprise` 下 62 个测试文件、414 个用例全部通过，`npm run type-check` 通过。

其他已有前端测试保持通过；若已有测试断言了字段标题的旧标签名，由实现方在 PR 中逐条说明，并请 Claude 单独提交修正。

## 5. 上线与验证

合并后随下一次 UI 构建上线（需用户批准，只换 UI）。用户在浏览器中确认：

- 字段标题清晰；
- 缺失字段为灰色；
- 打开产品页时导航不再整片高亮；
- 点字段不再整页刷新；
- 在 schema_wiki 与自由知识wiki 之间来回点击时，导航不再自动切回。

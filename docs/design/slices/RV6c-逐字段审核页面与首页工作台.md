# RV6c · 逐字段审核页面与首页工作台

> 状态：Claude 2026-10-27 提出 ｜ 作者：Claude Code
> 依据：
> - 用户 2026-10-27 在线上页面提出两个问题：
>   - "现在啥都堆一起了，分都分不清"；
>   - "应该是一个审核点一个审核……都找不到审核第一个点的地方"。
> - 用户为此选了两个方案：
>   - 每个字段单独审：按产品分组，每个字段一张卡，按钮在字段旁边；
>   - 首页拆开："知识阅读"与"工作台"分开。
> - 依赖 RV6b（#367）提供的平台接口：审核点、`points/decisions`、`point_count`/`pending_points`；
> - 本切片替换 RV5b 的整份审核页面。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：0 ｜ 依赖：RV6b 合并后开工

## 1. 审核页（`EnterpriseReviews.vue`）

页面上仍有"待审核 / 已处理"两个页签。

### 1.1 待审核：按产品分组，第一个产品直接展开

- **每个待审候选一节**（`data-review-item=<candidate_id>`），按提交时间从早到晚排列。
  - 节标题：产品名称。沿用 RV5b 的做法，用当前版本里的实体名称，没有时显示 id。
  - 标题下方：提交时间、"待审 {pending_points} / 共 {point_count} 项"（`data-review-progress`）。
- **第一节自动展开，并立即读取详情**，其他节折叠。展开按钮是 `data-review-open`，点击时才读取详情。不在加载时一次读取所有详情。
- **展开后分三块**：
  1. **待审字段**：每个仍待决定、候选值不是 `unknown` 的审核点一张卡（`data-point=<slug>`）。卡片内容：
     - 标题：产品 · 字段名，沿用 `fieldLabels`；
     - "现在"：当前版本中的值（`data-point-before`）；
     - "改为"：候选中的值（`data-point-after`）；
     - 原文摘录（`data-point-quote`）；
     - 两个按钮：**批准**（`data-point-approve`）、**拒绝**（`data-point-reject`）。

     不同 `kind` 的显示方式：
     - `removal`：只显示"现在"，标明"删除这一项"；
     - `member`（非 Claim 内容）：显示"其他内容有更新"与 slug，不展开原始数据。
  2. **未找到的字段**（`data-point-unknown-group`）：候选值为 `unknown` 的待审点合成一块，列出字段名。
     - 整组只有两个按钮：全部批准（`data-unknown-approve`）、全部拒绝（`data-unknown-reject`），各发一次批量请求。
     - 组内单个字段也可以展开单独处理。
  3. **已处理**（`data-point-decided`）：默认折叠，展开后逐项显示状态，如"已上线 · 版本 N"或"已拒绝 · 理由"。
- **节末尾**：按钮"批准其余 {n} 项"（`data-review-approve-rest`）。
  - 第一次点击变成"确认批准其余 {n} 项"，再次点击才发送；
  - 发送的是所有仍待决定、且没有 `blocker` 的审核点，一次批量请求；
  - 有 `blocker` 的点不包含在内，页面上写明"另有 {m} 项需先处理冲突"。

### 1.2 理由

- **批准**：理由可以不填。不填时发送"核对无误"（`enterpriseKnowledge.review.defaultReason`，五种语言都要有）。每张卡上有"填写理由"链接，点开出现输入框。
- **拒绝**（单个或整组）：必须填写理由。点击拒绝后出现输入框和"确认拒绝"按钮（`data-point-confirm-reject`）。理由长度按 RV5b 的规则计算，1–2000 字时按钮才可用。

### 1.3 决定之后

- **成功**：这张卡原地变成一行状态（`data-point-state`，`role="status"`），焦点移到这一行。
  - 节内的计数同步更新；
  - 不重新读取整个列表；
  - 一节的待审点全部处理完时，显示"本产品已全部处理"。下次读取列表时，这一节移到"已处理"页签。
- **失败**按错误码处理：
  - `MEMBER_DECIDED`：重新读取这一节的详情，并提示"有字段已由他人处理"；
  - `NEEDS_REBASE`：重新读取这一节的详情，`blocker` 会显示出来；
  - `CANDIDATE_DECIDED`：重新读取列表并提示，与 RV5b 相同；
  - 其他错误：留在卡上，可以重试。
- **有 `blocker` 的点**：显示原因（`NEEDS_REBASE` 时显示"当前版本已改过这一项，需要重新编译后再审"），批准不可用，拒绝可用。

### 1.4 已处理

列出已处理的候选：产品名、状态、"共 {point_count} 项"。展开后读取详情，逐项显示审核点的状态与理由，没有操作按钮。

### 1.5 接口（`enterpriseApi.ts`）

1. 新增 `decidePoints(spaceId, candidateId, slugs: string[], outcome, reason)`：
   - POST 到 `.../view/candidates/:id/points/decisions`；
   - 请求体只有 `{slugs, outcome, reason}`，理由按 RV5b 的规则去掉首尾空白；
   - 返回 RV6b 的 `PointResult`。
2. 类型 `ReviewItem` 增加 `point_count`、`pending_points`；`ReviewDetail` 增加 `points: ReviewPoint[]`，字段与 RV6b §5.2 一致。
3. **删除** `decideReview` 及其调用，页面上不再有整份审核的入口；"批准其余"走 `decidePoints`。平台上 RV5a 的整份接口保留给其他调用方，不在本切片处理。

## 2. 首页（`EnterpriseSpace.vue`）：知识与工作台分开

- **知识部分**保持不变：
  - 标题、版本号、"本次更新"摘要；
  - 搜索、产品总览表、常用概念、关系图入口。
- **页头去掉三个入口**：抽检、待确认材料、审核。它们移到工作台。
- **新增"工作台"**（`<aside data-space-workbench>`，标题"工作台"）：
  - 宽屏时放在知识内容右侧，窄屏时放在页头下方，与知识内容在视觉上分开；
  - 有三个入口（`data-workbench-entry=reviews|confirmations|spotchecks`），各自是指向对应页面的链接，并带计数（`data-workbench-count`）：
    - 待审核的修改：`listReviews(space, 'pending')` 中各项 `pending_points` 之和；
    - 待确认材料：`listConfirmations(space, 'open')` 的条数；
    - 抽检：`listSamples(space, 'pending')` 的条数。
  - 三个计数在版本读取成功后并行读取，各自独立：
    - 返回 403 或 `RELEASE_ACCESS_DENIED`：隐藏这个入口（不是管理员）；
    - 其他失败：显示入口，不显示计数；
    - 读取中：计数位置显示"…"；
    - 计数为 0 时显示"无待办"。
  - 三个入口都隐藏时，不显示工作台。
  - 首页不因为计数而推迟显示，计数也不进入任何缓存。

## 3. 改动范围

- `frontend/src/enterprise/`：
  - `EnterpriseReviews.vue`、`ReviewCard.vue`（可拆分为产品节与审核点卡片组件）、`useReviews.ts`、`reviewView.ts`、`reviews.css`；
  - `enterpriseApi.ts`；
  - `EnterpriseSpace.vue`、`spaceHome.css`；
- `frontend/src/i18n/locales/*`：五种语言；
- 实现方自己的测试。

不改 Go、Harness 和 `contracts/`。

## 4. 验收（RED，Claude 编写，受保护）

1. `reviewPointsApi.spec.ts`：
   - `decidePoints` 的路径编码、请求体和理由去空白；
   - 结果原样返回；
   - 错误保留类型与状态码。
2. `reviewPointsPage.spec.ts`：
   - 第一节自动展开、其他节不读详情；
   - 审核点卡的现在值、改为值与原文摘录；
   - 单个批准发送 `[slug]` 与默认理由，卡片原地变成状态，计数更新，不重新读取列表；
   - 拒绝必须填写理由；
   - 未找到的字段合成一组，整组批准是一次请求；
   - "批准其余"需要确认，不包含有 `blocker` 的点；
   - `blocker` 点批准不可用；
   - `MEMBER_DECIDED` 重新读取这一节并提示；
   - 已处理页签只显示状态，没有操作按钮；
   - 五种语言的文案齐全。
3. `spaceWorkbench.spec.ts`：
   - 工作台与知识部分分开，页头不再有三个入口；
   - 三个计数及其加载、隐藏（403）、失败、为零四种状态；
   - 三个入口都隐藏时不显示工作台。
4. RV5b 的 `reviewPage.spec.ts` 中，整份审核的用例删除，路由、页签、空状态、失败重试等仍然适用的用例保留（在 RED 提交中修改并写明原因）。`reviewApi.spec.ts` 中 `decideReview` 的用例随函数一起删除。

**门禁**：
- `npm run type-check`；
- 相关 vitest；
- `npm run build`；
- 守卫。

## 5. 上线

与 RV6b、S5b-3d-2 一起部署，部署前请用户批准。

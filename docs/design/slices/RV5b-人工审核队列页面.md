# RV5b · 人工审核队列页面

> 状态：Claude 2026-10-26 提出 ｜ 作者：Claude Code
> 依据：
> - RV5a（#356）：会话接口 `GET /view/candidates`、`GET /view/candidates/:id`、`POST /view/candidates/:id/decisions`，以及状态、阻塞原因与预检的语义；
> - S3h-2：本版变化页用 `releaseChanges(current, base)` 计算字段的新增、修改、移除，并显示新旧取值；
> - S5b-3b：待确认材料页的做法（标签页、加载/空/错误状态、过时响应丢弃、409 后刷新）。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 目标

管理员在企业知识页面看到"待审核的修改"，逐份查看每个字段的新旧取值和原文引文，填写理由后批准上线或拒绝。做完这一片，人工路由的候选（例如 594、596 的补全）就能在页面上处理。

## 2. 接口调用（`frontend/src/enterprise/enterpriseApi.ts`）

```ts
export interface ReviewDecision {
  decision_id: string; outcome: string; mode: string; reason: string; subject: string; created_at: string
}
export interface ReviewItem {
  candidate_id: string; created_at: string; created_by: string; base_release_id: string
  status: 'pending' | 'approved' | 'rejected' | 'released'
  subjects: string[]; members: number; removals: number
  decision: ReviewDecision | null; release_id: string | null
}
export interface ReviewDetail extends ReviewItem {
  head_release_id: string | null; blocker: string
  bundle_members: ReleaseMember[]; bundle_removals: string[]
}
export interface ReviewResult {
  decision_id: string; status: 'released' | 'rejected' | 'approved'
  release_id: string | null; epoch: number | null
}
listReviews(spaceId: string, status: 'pending' | 'decided'): Promise<ReviewItem[]>
readReview(spaceId: string, candidateId: string): Promise<ReviewDetail>
decideReview(spaceId: string, candidateId: string, outcome: 'approve' | 'reject', reason: string): Promise<ReviewResult>
```

- 路径：`/api/v1/enterprise/spaces/<Space>/view/candidates?status=…`、`…/view/candidates/<id>`、`…/view/candidates/<id>/decisions`。Space 与候选编号都要 URL 编码；
- 用现有的会话读写方法，不缓存；失败保留类型化的 `EnterpriseError(code, status)`；
- 提交时发送去掉首尾空白后的理由，请求体只有 `{outcome, reason}`。

## 3. 页面（`EnterpriseReviews.vue`，路由 `enterprise/:spaceId/reviews`，名称 `enterpriseReviews`）

1. **入口**：Space 页面增加链接 `{ name: 'enterpriseReviews', params: { spaceId } }`，与待确认材料并列。
2. **两个标签页**：
   - "待审核"（默认，`listReviews(spaceId, 'pending')`）与"已处理"（`'decided'`）；
   - 加载中显示 `role="status"`；没有内容时显示空状态；读取失败显示错误与重试按钮。
3. **产品名称**：每次加载读一次当前发布版本（`readRelease(spaceId)`），用其中实体的名称显示 `subjects`。读不到时（例如还没有发布版本）退回显示编号。
4. **待审核卡片**：
   - 显示产品名称（多个用"、"连接）、提交时间和修改字段数；
   - "查看修改"按钮读取详情（`readReview`）；
   - 详情把候选成员按 slug 覆盖到当前发布版本上，删除移除项，再用 `releaseChanges(预览, 当前)` 得到新增、修改、移除的字段。每行显示产品名、字段标题、原取值和新取值，取值的显示方式与本版变化页相同；
   - 每行列出这个字段在候选中的引文（`payload.evidence[].quote`）。候选还没有发布版本，所以引文不能打开原文，只显示文字；
   - **阻塞原因**（`blocker` 不为空）：
     - `NEEDS_REBASE`：显示"内容已过期：当前版本改过这些字段，需要重新编译后再审核"；
     - `CANDIDATE_INVALID`：显示"这份修改无法合并到当前版本，需要重新编译"；
     - 其他：显示"这份修改暂时无法上线"并附错误码；
     - 有阻塞原因时"批准上线"不可用，"拒绝"仍可用。
5. **决定**：
   - 理由文本框必填。去掉首尾空白后计数，上限 2000 字，显示"n / 2000 字"；
   - 按钮"批准上线""拒绝"：理由为空、超长或请求进行中时不可用；
   - 成功后卡片显示结果，不再显示按钮：
     - `released`：显示"已上线（第 N 版）"；
     - `rejected`：显示"已拒绝"；
     - `approved`：显示"已批准，等待上线"；
   - **失败时**：
     - `NEEDS_REBASE`（409）或 `CANDIDATE_INVALID`（400）：重新读取详情，显示阻塞原因；
     - `CANDIDATE_DECIDED`（409）：重新读取列表，并提示"这份修改已由其他人处理"；
     - 其他错误：在卡片内显示错误，可以重试。
6. **已处理卡片**：
   - 显示产品名称、状态（`released` "已上线"、`approved` "已批准，未能上线"、`rejected` "已拒绝"）与决定理由；
   - 不显示按钮。
7. **不显示内部标识**：候选编号、摘要、提交者与决定者的编号都只用在数据属性里，不出现在文字中。
8. **过时的响应**：切换标签页或重新加载后才返回的列表、详情、决定结果，一律丢弃，做法同待确认材料页。
9. **文案**：`enterpriseKnowledge.review`，5 种语言键名一致。

测试使用的数据属性（冻结）：
- 列表与卡片：`data-review-tab`、`data-review-item`、`data-review-subjects`、`data-review-open`；
- 字段变化：`data-review-change`（值为 slug）、`data-review-before`、`data-review-after`、`data-review-quote`；
- 决定：`data-review-blocker`、`data-review-reason`、`data-review-approve`、`data-review-reject`、`data-review-state`；
- 其他：`data-review-status`、`data-review-decision-reason`、`data-review-notice`、`data-review-retry`。

## 4. 改动范围

- `frontend/src/enterprise/`：
  - `enterpriseApi.ts`：§2 的类型与三个函数；
  - 新的页面、卡片、组合式函数与样式，命名由实现方定；
  - `EnterpriseSpace.vue`：加入口链接；
- `frontend/src/router/index.ts`：注册路由；
- `frontend/src/i18n/locales/*.ts`：5 种语言的 `enterpriseKnowledge.review`；
- `docs/design/upstream-patches.md`：实现方按 AGENTS 的例外**追加**登记行（不改已有行）：
  - `frontend/src/router/index.ts`：注册审核队列会话页面路由，理由同 RV4b，退出条件"上游支持自有页面路由注册后移除接缝"；
  - 5 个语言文件：审核队列文案，理由与退出条件同 S3g 的语言包登记；
  - 这些文件都已在 G10 基线中，补丁文件数不变；
- 实现方自己的测试。

Claude 在单独的 RED 修正提交中，给两个既有的 Space 页面测试（`spaceHomeInteraction.spec.ts`、`spaceSearchRegression.spec.ts`）补上 `enterpriseReviews` 命名路由：Space 页面多了一个入口链接，这两个测试用的是只注册了已有命名路由的真实路由器。

不改 Go 平台、Harness 与 `contracts/`。

## 5. 验收（RED，Claude 编写，受保护）

- `frontend/src/enterprise/reviewApi.spec.ts`：路径与编码、拆包、请求体、类型化失败；
- `frontend/src/enterprise/reviewPage.spec.ts`（happy-dom）：
  - 列表与产品名称，不显示内部标识；
  - 详情中的新旧取值、引文与移除项；
  - 批准、拒绝及进行中的状态；
  - 阻塞原因；
  - 409 / 400 之后刷新；
  - 已处理列表；
  - 空状态与错误重试；
  - 理由计数；
  - 路由、入口与 5 种语言；
- 夹具：`frontend/src/enterprise/__tests__/reviewFixtures.ts`。

**门禁**（在 `frontend/`）：`npm run type-check`、`npm run test:component -- src/enterprise`、`npm run build`；架构守卫。

## 6. 上线

与 RV5a 一起随下一次 App/UI 部署上线（部署需用户批准）。上线后，在页面上处理 594、596 的两份待审修改。

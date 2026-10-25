# S5b-3b · 待确认材料页面

> 状态：Claude 2026-10-25 提出；用户 2026-10-24 决定"不确定的材料放在企业知识页给人确认" ｜ 作者：Claude Code
> 依据：蓝图核心原则 6（完整前端体验：加载、空状态、错误、重试、可访问性）；S5b-3a（#339）通用待确认项接口；RV4b 抽检页面的写法
> 实现方：Claude ｜ 审核方：Codex（前端；上游文件 `frontend/src/router/index.ts` 与 5 个语言包）｜ 真实模型调用：0

## 1. 目标

在企业 Space 页加入口"待确认材料"，打开后：

- **待处理**：列出未关闭的待确认项。人可以：
  - 读标题与说明，说明保留换行；
  - 在提交方给出的选项中选一项，可附备注；
  - 提交。提交后该项显示"已选择：某项，等待系统处理"，关闭前可以改选。
- **已处理**：列出已关闭的项。按关闭原因显示"已按「某项」处理"或"已无需处理"。

页面只显示接口返回的标题、说明与选项文字，不解释它们，也不在前端拼业务文案。

## 2. 改动

### 2.1 接口 `frontend/src/enterprise/enterpriseApi.ts`

```ts
export interface ConfirmationOption { key: string; label: string }
export interface ConfirmationAnswer { id: string; item_id: string; option_key: string; note: string; answerer: string; answered_at: string }
export interface ConfirmationClosure { reason: 'applied' | 'obsolete'; answer_id?: string; closed_by: string; closed_at: string }
export interface ConfirmationItem {
  id: string; space_id: string; subject: string; revision: string; content_digest: string
  title: string; detail: string; options: ConfirmationOption[]
  created_by: string; created_at: string; answer?: ConfirmationAnswer; closure?: ConfirmationClosure
}
export function listConfirmations(spaceId: string, status: 'open' | 'closed'): Promise<ConfirmationItem[]>
export function answerConfirmation(spaceId: string, itemId: string, optionKey: string, note: string): Promise<ConfirmationAnswer>
```

- `listConfirmations` 请求 `GET /api/v1/enterprise/spaces/:space/view/confirmations?status=`。
- `answerConfirmation` 请求 `POST …/view/confirmations/:id/answers`，请求体为 `{option_key, note}`。
- 路径各段都用 `encodeURIComponent` 编码；错误沿用 `EnterpriseError`（含 `status` 与 `code`）。

### 2.2 页面 `EnterpriseConfirmations.vue`、`ConfirmationCard.vue`、`useConfirmations.ts`

- **路由**：`enterprise/:spaceId/confirmations`，名称 `enterpriseConfirmations`。入口在 `EnterpriseSpace.vue`，与抽检入口并列。
- **标签页**：
  - "待处理"对应 `open`，"已处理"对应 `closed`；
  - 键盘左右、Home、End 键可切换；
  - 切换或换 Space 时，丢弃之前还没返回的响应。
- **状态**：
  - 加载中显示 `role="status"`；
  - 失败显示 `role="alert"` 并带"重试"；
  - 空列表时，两个标签各有提示；
  - 只显示 `space_id` 等于当前 Space 的项。
- **待处理卡片**：
  - 标题与选项在同一个 `fieldset` 里，`legend` 是标题；
  - 选项是一组单选，默认选中最新选择，没有选择时不选；
  - 备注默认为最新选择的备注，去首尾空白后最多 1000 字，显示字数；
  - 以下情况"提交"按钮不可用：
    - 没有选中选项；
    - 备注超长；
    - 正在提交；
    - 已有选择，且选项与备注都没有改动；
  - 提交成功后：
    - 该项留在"待处理"，显示"已选择：<选项文字>，等待系统处理"，按钮文字改为"修改选择"；
    - 不重新请求整个列表；
    - 焦点移到这张卡片的状态行（此时选项与备注未改动，按钮不可用，不能接收焦点）；
  - 失败时，只影响这张卡片：
    - 409 `CONFIRMATION_CLOSED`：页面顶部提示"「<标题>」已处理，列表已刷新"，然后重新加载当前标签，焦点回到当前标签；
    - 其他错误在卡片内显示，`role="alert"`：
      - 403 或 `RELEASE_ACCESS_DENIED`："需要管理员且有 Wiki 编辑权限"；
      - 400 `ANSWER_INVALID`："选项无效，请刷新后重试"；
      - 其他："提交失败，请重试"；
  - 返回的选择不属于这一项时，视为失败。
- **已处理卡片**：
  - `applied`，且关闭记录指向的就是该项的最新选择：显示"已按「<选项文字>」处理"；找不到对应选择时只显示"已处理"，不猜；
  - `obsolete`：显示"已无需处理"；
  - 附上选择人、备注与关闭时间；
  - 没有单选和提交按钮。
- **测试定位**：`data-confirm-tab`、`data-confirm-item`、`data-confirm-detail`、`data-confirm-option`、`data-confirm-submit`、
  `data-confirm-state`、`data-confirm-notice`。

### 2.3 文案

`enterpriseKnowledge.confirm.*` 加入 5 个语言包：

- 中文为准；
- 英、日、韩、俄给出对应译文；
- 键集合在 5 个语言包中一致。

**不做**：
- 不改接口、权限与 Go；
- 不做 Harness 推送与应用（S5b-3c）；
- 页面不提供新建、关闭待确认项的入口，这两件事由提交方完成。

## 3. 验收（RED，Claude 编写，受保护）

`frontend/src/enterprise/confirmationPage.spec.ts`（模拟 `./enterpriseApi`，用真实的中文语言包）与 `confirmationApi.spec.ts`（模拟 `@/utils/request`）：

1. **接口**：
   - 两个函数的地址、编码、请求体；
   - 返回 `items` 与 `answer`。
2. **待处理**：
   - 标题、保留换行的说明、选项文字都正确显示，不显示 `subject`、`revision` 等内部字段；
   - 只显示本 Space 的项。
3. **提交**：
   - 未选择时按钮不可用；
   - 选中后提交，请求参数为所选的键与备注；正在提交时按钮不可用；
   - 成功后显示"已选择…等待系统处理"与"修改选择"，不重新请求列表，焦点在这张卡片的状态行；
   - 已有选择的项默认选中最新选择、带出备注；不改动时按钮不可用，改动后可用；
   - 备注超过 1000 字时按钮不可用。
4. **失败**：
   - 403 →"需要管理员且有 Wiki 编辑权限"；
   - 400 `ANSWER_INVALID` →"选项无效，请刷新后重试"；
   - 其他错误，以及返回的选择不属于这一项 →"提交失败，请重试"，按钮恢复可用；
   - 409 `CONFIRMATION_CLOSED` → 页面提示"「标题」已处理，列表已刷新"，重新请求列表；
   - 失败不影响其他卡片。
5. **已处理**：
   - `applied` 显示被应用选择的选项文字；对不上最新选择时只显示"已处理"；
   - `obsolete` 显示"已无需处理"；
   - 没有单选与提交按钮。
6. **状态**：
   - 加载失败后可以重试；
   - 两个标签的空状态；
   - 键盘切换标签；
   - 切换标签与换 Space 时，旧响应不覆盖新结果；换 Space 后，旧 Space 的提交结果不写回页面。
7. **入口**：
   - Space 页有指向 `enterpriseConfirmations` 的链接；
   - 路由表登记了该路径、名称与页面组件。
8. **语言包**：5 个语言包都含 `enterpriseKnowledge.confirm` 下同一组键，且都不为空。

**门禁**：`frontend/` 下 `npm test`、`npx vitest run src/enterprise`、`npm run type-check`、`npm run build`；架构守卫。

## 4. 改动范围

- `frontend/src/enterprise/`：
  - `enterpriseApi.ts`；
  - `EnterpriseConfirmations.vue`、`ConfirmationCard.vue`、`useConfirmations.ts`、`confirmations.css`（新）；
  - `EnterpriseSpace.vue`（入口链接）；
- `frontend/src/router/index.ts`（一条路由）；
- `frontend/src/i18n/locales/{zh-CN,en-US,ja-JP,ko-KR,ru-RU}.ts`（`enterpriseKnowledge.confirm`）；
- §3 的测试；
- `frontend/src/enterprise/spaceHomeInteraction.spec.ts`、`spaceSearchRegression.spec.ts`：
  - 这两个测试用真实路由挂载 Space 页，只登记了已有的命名路由；
  - 新入口链接的路由名不在其中，渲染会报"No match"；
  - 两个测试路由表各登记一条 `enterpriseConfirmations`，不改断言（RV4b 加抽检入口时同样处理）；
- `docs/design/upstream-patches.md`（只追加一行）；
- `tests/architecture/`（基线）。

## 5. 上线

- 换 UI 镜像，与 S5b-3a 的 App 镜像和迁移 000010 一起部署。另开部署 Issue，需用户确认。
- 在 S5b-3c 推送之前，页面显示空列表。

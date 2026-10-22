# S9b · 专家编辑（界面）：字段页修改表单，出处里看得到修订记录

> 状态：Claude 2026-10-22 提出（用户同日决定：管理员及以上可编辑、保存即上线）｜ 作者：Claude Code
> 依据：蓝图 §5.1、§6.4、§11 S9；平台接口见 S9a（`docs/design/slices/S9a-专家编辑平台.md` §2.4、§2.5）
> 实现方：Claude ｜ 审核方：Codex ｜ 真实模型调用：0
> 依赖：S9a（PR #296）。本片测试用模拟接口，可先行；联调与上线在 S9a 合并、部署之后

## 1. 目标

- **修改**：管理员在实体页的字段上点"修改"，填写新值和原因，保存后立即生成新版本，页面切到这个版本。
- **出处**：点开专家修订字段的"出处"时，显示谁、何时、从什么改成什么、为什么改，不打开任何文件。
- **角色**：非管理员看不到"修改"。界面只按角色决定显示与否，是否放行由服务端判定（S9a 入口与处理函数各查一次）。

## 2. 设计

### 2.1 接口（`enterpriseApi.ts`）

- **提交**：`submitExpertEdit(spaceId, input)`
  - 发 `POST /api/v1/enterprise/spaces/:space_id/view/expert-edits`；
  - 请求体恰好六个键：`base_release_id`、`member_slug`、`base_member_digest`、`state`、`value`、`reason`；
  - 返回 `{ release_id, epoch, revision_record_id }`；
  - 失败沿用现有 `response()`，抛 `EnterpriseError(code, status)`。
- **读取出处**：`readCitation` 的返回类型改为 `Citation | ExpertCitation`。
  - `ExpertCitation` 的字段：`kind: 'expert_revision'`、`release_id`、`member`、`evidence_index`、`origin`、`quote`、`revision_record_id`、`actor`、`role`、`recorded_at`、`before`、`after`、`reason`；
  - 其中 `before`、`after` 都是 `{ state, value }`；
  - 原文出处没有 `kind` 字段，照旧。

### 2.2 谁能看到"修改"

- **判定函数**：新模块 `expertEditAccess.ts` 导出 `canOfferExpertEdit()`。
  - 租户角色达到 admin（`useAuthStore().hasRole('admin')`）时为真；
  - 没有活动的 Pinia 时视为角色未知，返回假，即失败关闭。
- **`EnterpriseField.vue`**：新增可选属性 `editable`，默认假。
  - 为真时，标题行出现"修改"按钮（`data-expert-edit`），点击发出 `edit` 事件；
  - 不传时行为与现在完全一致，已有测试不受影响。
- **`EnterpriseEntity.vue`**：判定为真时，给三组字段（分组、其他、模型补充）都传 `editable`。
  - "已更新"展开的旧值不传。

### 2.3 表单（新组件 `ExpertEditForm.vue`）

**属性与事件**：属性 `{ spaceId, release, slug, title }`；事件 `published({ releaseId, epoch })`、`reload()`、`cancel()`。

**界面元素**：

- **当前**：显示当前值（非"有值"时显示状态文字）。
- **状态单选**（`data-state`）：有值、材料明确没有、材料未提及；初始为当前状态。
- **新值**（`data-value`，只在"有值"时出现）：多行文本框，预填规则：
  - 当前值是字符串：原样；
  - 当前值是字符串数组：每项一行；
  - 其他情况：空。
- **原因**（`data-reason`）：必填，旁边显示 `已填 n / 2000 字`。
- **提示**一行：`保存后立即发布新版本；之后重新编译不会覆盖此字段。`
- **"保存并发布"按钮**（`data-submit`），以下情况禁用：
  - 正在保存；
  - 原因为空，或超过 2000 字；
  - 选了"有值"但新值为空；
  - 状态与新值都没有变化（新值去掉首尾空白后比较）。

**提交体**：

| 键 | 取值 |
|---|---|
| `base_release_id` | `release.id` |
| `member_slug` | `slug` |
| `base_member_digest` | 该成员的 `member_digest` |
| `state` | 所选状态 |
| `value` | "有值"时为去掉首尾空白的新值，否则为空字符串 |
| `reason` | 去掉首尾空白的原因 |

**保存中**：`role=status` 显示"正在保存…"。成功后发出 `published`。

**失败**：`role=alert` 显示下表文字，已填内容保留。

| 错误码 | 文字 | 附加操作 |
|---|---|---|
| `EXPERT_EDIT_STALE`、`MEMBER_NOT_FOUND`、`RELEASE_CONFLICT`、`NEEDS_REBASE` | 这个字段已有更新的版本，请查看最新版本后再修改 | 按钮"查看最新版本"（`data-reload`），发出 `reload` |
| `EXPERT_EDIT_INVALID` | 填写不完整，或与当前内容相同 | — |
| `RELEASE_ACCESS_DENIED`，或 HTTP 403 | 只有管理员可以修改字段 | — |
| `SERVICE_UNAVAILABLE`，或 HTTP 503 | 暂时无法保存，请稍后重试 | — |
| 其他 | 保存失败，请重试 | — |

### 2.4 实体页

- **打开表单**：点字段的"修改"，打开抽屉（标题"修改：<字段名>"），里面是表单。同一时间只开一个抽屉：打开表单会关掉出处抽屉。
- **`published`**：关闭抽屉；调用 `router.replace`，把查询参数 `release` 设为新版本 id，其余查询参数与锚点不变。新版本读到后，页面顶部显示 `role=status` 提示（`data-expert-notice`）：`已保存，已发布为第 N 版`。提示保留到换实体或换版本为止。
- **`reload`**：关闭抽屉；调用 `router.replace` 去掉 `release` 参数，回到当前 Active。
- **没有路由**（嵌入或测试）：只关闭抽屉。

### 2.5 出处面板（`CitationPanel.vue`）

`kind === 'expert_revision'` 时显示修订记录块（`data-expert-revision`），不显示原文页与文件。

| 项 | 显示 |
|---|---|
| 修订人 | `actor` 去掉 `web_user:` 前缀 |
| 角色 | `owner` 显示"所有者"，`admin` 显示"管理员"，其他原样 |
| 时间 | 本地时间 `YYYY-MM-DD HH:mm` |
| 修改前、修改后 | `present` 时显示值，其他状态显示状态文字 |
| 原因 | `reason` |

- 来源标签照旧，即"专家修订"。
- 失败时的文字沿用现有 `citationFailure`。

### 2.6 文案

新增键放在 `enterpriseKnowledge.expert` 下，五种语言都要有（键名审计会检查）。
中文文案以本节和 §2.3、§2.5 的表格为准。其他语言按意思翻译，测试只断言中文。

## 3. 上游补丁

不新增。语言包的五个文件已在 `docs/design/upstream-patches.md` 登记（S3g），本片只加键。其余改动都在 `frontend/src/enterprise/` 下。

## 4. 验收（RED，Claude 编写，受保护）

| 文件 | 验收内容 |
|---|---|
| `frontend/src/enterprise/expertEditApi.spec.ts` | 提交的地址与请求体；返回值；失败时抛带码的 `EnterpriseError` |
| `frontend/src/enterprise/ExpertEditForm.spec.ts` | 预填；各禁用条件；请求体；成功发出 `published`；§2.3 失败表逐行；"查看最新版本"发出 `reload` |
| `frontend/src/enterprise/expertEditPage.spec.ts` | 管理员看到每个字段的"修改"，贡献者看不到；表单发布后 `router.replace` 带上新版本 id，页面显示提示；`reload` 去掉 `release` 参数 |
| `frontend/src/enterprise/expertCitation.spec.ts` | 修订记录块的六项；不渲染原文页 |

实现方另补：`canOfferExpertEdit` 在没有 Pinia、贡献者、管理员、所有者四种情况下的结果。

## 5. 改动范围

- `frontend/src/enterprise/`：`enterpriseApi.ts`、`expertEditAccess.ts`（新）、`ExpertEditForm.vue`（新）、`EnterpriseField.vue`、`EnterpriseEntity.vue`、`CitationPanel.vue`、`ExpertCitation.vue`（新，可选：拆出修订记录块）、`fieldLabels.ts`、`enterprisePage.css`；
- `frontend/src/i18n/locales/{zh-CN,en-US,ja-JP,ko-KR,ru-RU}.ts`；
- 实现方测试。

## 6. 上线与验证

- 与 S9a 一起构建 UI 镜像并替换（部署另开 Issue，需用户确认）。
- 上线后在演示 Space 走一遍：
  1. 以管理员身份改一个字段，确认页面切到新版本、提示正确；
  2. 打开该字段的出处，确认修订记录六项正确；
  3. 以非管理员身份确认看不到"修改"。

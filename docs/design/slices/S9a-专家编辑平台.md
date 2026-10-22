# S9a · 专家编辑（平台）：保存即生成新版本的字段修订，记录谁、何时、把什么改成什么

> 状态：Claude 2026-10-22 提出；用户同日决定：管理员及以上可编辑、保存即上线；迁移 000009 只在本机测试环境执行（部署前再确认）｜ 作者：Claude Code
> 依据：蓝图 §5.1（ExpertRevision、expert_lock、EXPERT_REVISION）、§6.4、§11 S9
> 实现方：Claude ｜ 审核方：Codex ｜ 真实模型调用：0
> 界面另起 S9b（字段页编辑表单与出处面板中的修订记录）

## 1. 目标与现状

- **蓝图要求**：
  - 专家在字段页修改值，生成新 Release；
  - 来源点击后显示"谁、何时、把什么改成什么"；
  - `expert_lock` 的 Claim 遇到之后模型给出的新值，只产生冲突，不会被覆盖。
- **现状**：
  - 合同已有 `ExpertRevision`、`Locator.kind = EXPERT_REVISION`、`origin = EXPERT_REVISION`、`Claim.expert_lock`、`Maintenance.changed_by = expert`；
  - S8a 的判定器已把 `expert_lock` 处理为冲突；
  - 平台缺修订记录的存储、编辑入口、对这类证据的回验与出处展示。

## 2. 设计

### 2.1 存储（迁移 000009，只新增表）

```sql
CREATE TABLE enterprise_expert_revisions (
    id                 TEXT PRIMARY KEY,         -- revision_record_id
    tenant_id          BIGINT NOT NULL,
    space_id           TEXT NOT NULL,
    base_release_id    TEXT NOT NULL,
    member_slug        TEXT NOT NULL,            -- 合同中的 target
    base_member_digest TEXT NOT NULL,
    actor              TEXT NOT NULL,
    role               TEXT NOT NULL,
    recorded_at        TIMESTAMPTZ NOT NULL,
    before_json        TEXT NOT NULL,            -- {"state":..,"value":..}
    after_json         TEXT NOT NULL,
    reason             TEXT NOT NULL,
    record_sha256      TEXT NOT NULL             -- 合同 JSON 规范化后的 SHA-256
);
CREATE INDEX enterprise_expert_revisions_member_idx
    ON enterprise_expert_revisions (tenant_id, space_id, member_slug, recorded_at);
```

- 记录不可变，只插入、不更新、不删除。
- 回滚迁移只删这张表与索引。

### 2.2 编辑服务（新包 `internal/enterprise/expert`）

```go
Edit(ctx, p release.Principal, role, spaceID string, in EditInput) (Result, error)
EditInput{BaseReleaseID, MemberSlug, BaseMemberDigest, State, Value, Reason string}
Result{Release release.Release; Revision Revision}
```

**1. 先校验，未通过时什么都不写：**

- **Active 已前进**：`BaseReleaseID` 不是当前 Active，返回 `EXPERT_EDIT_STALE`。
- **成员已变化**：`MemberSlug` 不存在、不是 `claim`，或 digest 与 `BaseMemberDigest` 不同，同样返回 `EXPERT_EDIT_STALE`（前一种为 `MEMBER_NOT_FOUND`）。
- **输入不合法**，返回 `EXPERT_EDIT_INVALID`：
  - `State` 不是 `present` / `absent_explicitly` / `unknown` 之一；
  - `present` 时值为空；
  - `Reason` 为空，或超过 2000 字；
  - 新状态和新值都与原来相同（无变化）。

**2. 写入修订记录**：`before`/`after` 为 `{"state","value"}` 的 JSON；`record_sha256` 是合同 JSON 规范化后的摘要。

**3. 生成新的 Claim payload**：在原 payload 上修改，其余字段原样保留。

| 字段 | 新值 |
|---|---|
| `state`、`value` | 按输入；非 `present` 时 `value = null` |
| `origin` | `EXPERT_REVISION` |
| `expert_lock` | `true` |
| `unknown_reason` | `unknown` 时为 `NOT_IN_MATERIAL`，否则为空 |
| `evidence` | 非 `unknown` 时一条（见下表）；`unknown` 时为空 |
| `review` | `{mode: human, reviewer: actor, reviewed_at}` |
| `maintenance` | `revision_no + 1`，`changed_by = expert`，`changed_at`，`reason`；`first_release_id` 沿用 |

那一条 evidence 的内容：

| 字段 | 值 |
|---|---|
| `source_ref` | `expert:v1:<revision_id>:<record_sha256>` |
| `file_sha256` | `record_sha256` |
| `locator` | `{kind: EXPERT_REVISION, revision_record_id}` |
| `quote` | `present` 时为新值；`absent_explicitly` 时为原因 |
| `match` | `EXACT` |
| `access_scope` | 沿用原成员 |

成员的 `evidence_refs` 与 payload 中的 `source_ref` 一一对应。

**4. 通过现有发布流程上线**，即"保存即上线"：

- 用现有 `release.Service` 依次 `Receive`、`Decide`、`Activate`：
  - Candidate 的 `origin = expert_edit`，base 为当前 Active；
  - 决定为人工批准（`mode = human`，原因即编辑原因）。
- 中途失败时，修订记录保留（它是不可变的审计记录），返回错误；用户重试会产生新的修订记录。

### 2.3 证据回验与解析

- **引用解析**：成员 `evidence_refs` 中的 `expert:v1:` 引用由修订存储解析，记录必须在同一租户、同一 Space 下存在，且摘要一致。
- **证据回验**：`EXPERT_REVISION` 定位器的证据要求：
  - 记录存在；
  - `file_sha256` 等于 `record_sha256`；
  - `quote` 等于记录中的新值（`present`）或原因（`absent_explicitly`）。
- **其他证据**：照旧走 `PDF_TEXT_SPAN` 回验。
- **来源固定**：只处理 `source:v1:`，`expert:` 引用不固定任何材料。

### 2.4 出处接口

浏览器出处接口（现有 citation）遇到 `EXPERT_REVISION` 证据时，返回 `kind: "expert_revision"`，以及 `actor`、`role`、`recorded_at`、`before`、`after`、`reason`，不打开任何文件。前端展示放在 S9b。

### 2.5 浏览器入口

`POST /api/v1/enterprise/spaces/:space_id/view/expert-edits`

- **授权**：租户角色 Admin 及以上，并且对该 Space 的 wiki 库有编辑权限。沿用 `MountSessionSpotChecks` 的守卫组合，Viewer 守卫换成 Admin 守卫。
  租户 RBAC 未开启时路由守卫只记日志不拦截，所以处理函数再按调用者的租户角色检查一次 Admin，未达到返回 403。
- **请求体**：同 `EditInput`。
- **成功时**：返回新 Release 的 id、epoch 与修订记录 id。
- **失败时**：错误按现有 `writeError` 输出代码。

## 3. 上游补丁

- `internal/router/router.go` 已登记，本切片只增加一处挂载。
- 迁移在项目自有的 `migrations/enterprise/` 下。
- 其余都在 `internal/enterprise/` 下。

## 4. 验收（RED：`internal/enterprise/expert/edit_acceptance_test.go`，Claude 编写，受保护）

使用内存平台（release 包测试里的写法）和内存修订存储。

1. **把字段改为新值**：
   - 新 Release 的 base 是旧 Active；
   - 该成员的 `state=present`、`value`=新值、`origin=EXPERT_REVISION`、`expert_lock=true`；
   - `maintenance.revision_no` 加 1，`changed_by=expert`；
   - 证据是一条 `EXPERT_REVISION`，其 `revision_record_id` 指向已存的修订记录，`file_sha256` 等于记录摘要；
   - 其他成员 digest 不变；修订记录的 `before` / `after` / `actor` / `reason` 正确。
2. **改为"材料明确没有"**：证据的 quote 是原因。
3. **改为"材料未提及"**：没有证据，`unknown_reason=NOT_IN_MATERIAL`，修订记录照样保存。
4. **过期**：Active 已前进，或成员 digest 不符，都返回 `EXPERT_EDIT_STALE`，不写修订、不写 Release。
5. **非法输入**：`present` 无值、原因为空、没有变化、目标不是 claim、slug 不存在，各返回对应代码，什么都不写。
6. **证据回验**：
   - 伪造的 `expert:v1:` 引用（记录不存在，或摘要不符）在 `Receive` 时被拒绝；
   - 由 Harness 提交、带 `EXPERT_REVISION` 证据但 quote 不符的成员，也被拒绝。

实现方另补：

- PostgreSQL 修订存储的往返测试（集成标记）；
- 出处接口返回修订内容；
- 浏览器入口的 Admin 守卫与 Space 校验；
- 迁移的 up/down。

## 5. 改动范围

- `migrations/enterprise/versioned/000009_*.sql`；
- `internal/database/enterprise_migration.go`：打包的企业迁移头从 8 改为 9（否则启动时拒绝 000009）；
  原 `spotcheck_migration_test.go` 断言"000008 是迁移头"，随之改名为 `enterprise_migration_head_test.go` 并改为 9；
- `internal/enterprise/expert/`（新包）；
- `internal/enterprise/release/evidence.go`：`Locator` 增加 `revision_record_id`，回验才能读到修订记录 id；
- `internal/enterprise/releasestore/`（修订存储、证据解析与回验的扩展、容器注册）；
- `internal/enterprise/session*.go`（出处与浏览器入口）；
- `internal/enterprise/citation.go`、`internal/enterprise/mount.go`：出处接口按定位器种类分流到修订记录；
  `EXPERT_EDIT_STALE` 映射为 409、`EXPERT_EDIT_INVALID` 为 400；服务密钥的出处接口不变（遇到修订证据仍返回 `EVIDENCE_UNSUPPORTED`）；
- `internal/router/router.go`（`RouterParams` 增加一个字段，挂载一处）；
- 实现方测试。

> 2026-10-22 修正（Claude 实现时发现）：原清单漏了迁移头、`Locator` 字段与出处分流三处，实现必须改动，补列于上。

## 6. 上线与验证

需要：
- 迁移 000009：用户已批准只在本机测试环境执行，部署前再确认一次；
- App 构建与替换。

上线后，用演示 Space 的一个字段做一次真实修订：
- 确认新版本生成；
- 确认出处显示修订记录；
- 再把该产品的条款重新增量发布（S8a），确认该字段报告为冲突、线上值不变。

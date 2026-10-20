# S3i · 企业知识读取性能：发布版本按 ID 缓存，点产品和点出处不再重复读整版

> 状态：用户 2026-10-20 反馈"点击产品都很慢，点击来源也是"｜ 作者：Claude Code
> 实现方：Codex（前端 + Go）｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 现状（实测，本机，epoch 40/41）

- 一个发布版本有 1,728 个成员，其中 978 个是带全文的 `wiki_page`：
  - 整版读取原始 10.2 MB，gzip 后 1.7 MB；
  - 服务端首字节 0.7–0.8 s。
- **点产品**：产品页和 Space 首页每次都重新读整版，并且读两版（当前版与上一版，用于"本版变化"）。浏览器再解析 10 MB JSON，放进深度响应式对象，导航和字段视图遍历全部成员。
- **点出处**：出处接口 0.45–0.77 s，响应只有约 1 KB；随后取原文 PDF 0.5–0.6 s。两者在服务端都会重新读整版：`release.Service.Evidence` → `Store.ReleaseByID` 读出全部成员并逐个解码。
- 依据：发布版本按 ID 不可变。`GetReleaseMembers` 只返回不可变成员，变化的只有版本头上的退役状态。

## 2. 设计

### 2.1 前端（`frontend/src/enterprise/enterpriseApi.ts`）

- `readRelease(spaceId, releaseId)` 按 `(spaceId, releaseId)` 缓存成功结果：
  - 同一键的并发读取共用一个请求；
  - 失败不缓存；
  - 不同 Space 不共用。
- 不带 `releaseId`（读 Active）时每次都发请求，因为 Active 会变；但把结果按它的 ID 存入缓存，此后按 ID 读取不再发请求。
- 最多保留 4 个版本，按最近读取淘汰。
- 返回的版本对象用 `markRaw` 标记，不进入 Vue 深度响应式。版本内容不可变，页面只替换整个对象。
- 页面代码不改读取方式。当前版与上一版都经过同一缓存，切换产品时不再重复下载。

### 2.2 后端（`internal/enterprise/releasestore`）

- `Store.ReleaseByID` 缓存已解码的成员列表，键为 `(tenant, space, releaseID)`，进程内最多 4 个版本，按最近读取淘汰。并发加载同一版本时合并为一次。
- 版本头（`GetRelease`、preparation、`retiredAt`）每次仍然从库中读取，退役状态立即生效；只有成员列表来自缓存。
- 缓存只存成员列表，按 tenant 与 Space 隔离；读取失败不缓存。
- 出处与原文接口经 `Store` 读取，自然受益，接口本身不变。

### 2.3 原文文件的浏览器缓存

`/releases/:release_id/sources/:knowledge_id/attempts/:attempt/file` 的内容由 knowledge ID 与解析轮次唯一确定，并经哈希核对。成功响应加 `Cache-Control: private, max-age=86400, immutable`；错误响应不加。

## 3. 验收

- **RED**：`frontend/src/enterprise/releaseCache.spec.ts`（Claude 编写，受保护）：
  - 按 ID 只读一次，并发共用；
  - 不进入深度响应式；
  - Active 每次都读，读到的 ID 进入缓存；
  - 失败不缓存，Space 之间不共用；
  - 最多 4 个，最近读取的保留。
- **实现方另补**（Go 测试名以 `TestPostgres` 开头，在 PostgreSQL CI 中运行）：
  - 第一次读取后直接删除该版本的成员行，第二次读取仍返回原成员（证明命中缓存）；
  - 在两次读取之间把版本标记为退役，第二次读取能看到 `RetiredAt`（版本头是新读的）；
  - 不同 tenant 或 Space 的相同 release ID 不会互相命中；
  - 同一版本的并发读取只加载一次成员；
  - 原文文件成功响应带上述 `Cache-Control`，错误响应不带。
- **门禁**：现有的前端和企业包测试不新增失败。若有已有测试依赖"每次都发请求"，请停下说明，不要修改已有断言。

## 4. 改动范围

- `frontend/src/enterprise/enterpriseApi.ts`；
- `internal/enterprise/releasestore/`（`publisher.go` 或新文件）、`internal/enterprise/` 中原文文件处理；
- 实现方测试。

## 5. 上线与核对

合并后随下一次 App 与 UI 构建上线（需用户批准）。上线后实测：

- 同一版本第二次读取的服务端首字节；
- 出处与原文接口的耗时；
- 浏览器中切换产品不再下载整版（开发者工具中没有重复的 releases 请求）。

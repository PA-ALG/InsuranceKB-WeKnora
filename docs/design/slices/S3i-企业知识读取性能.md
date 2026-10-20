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

2026-10-20 修订（Codex 在 #276 指出）：浏览器不能在本地直接返回发布版本，否则权限撤销后、或在同一页面登出后换账号登录，仍会读到旧内容，绕过服务端的实时授权。修订后：

- 每次 `readRelease` 都向服务端发请求，经过现有的 Viewer 与 RAW/Wiki 读权限守卫。浏览器 HTTP 缓存按 §2.4 做条件请求，服务端未变时返回 304，不再下载整版。
- 同一时刻的相同请求（同一 Space、同一 releaseId 或同为 Active）共用一个进行中的请求；请求结束后不保留，下一次读取重新发请求。
- 返回的版本对象用 `markRaw` 标记，不进入 Vue 深度响应式。
- 不建模块级的版本缓存，也就不需要处理登出时的清理。

### 2.2 后端（`internal/enterprise/releasestore`）

- `Store.ReleaseByID` 缓存已解码的成员列表，键为 `(tenant, space, releaseID)`，进程内最多 4 个版本，按最近读取淘汰。并发加载同一版本时合并为一次。
- 版本头（`GetRelease`、preparation、`retiredAt`）每次仍然从库中读取，退役状态立即生效；只有成员列表来自缓存。
- 缓存只存成员列表，按 tenant 与 Space 隔离；读取失败不缓存。
- 出处与原文接口经 `Store` 读取，自然受益，接口本身不变。

### 2.4 发布版本读取的条件请求（`internal/enterprise` 读取处理与 `release` 服务）

- `GET .../releases/:release_id`（含 `active` 与 `/view/` 会话路由）的成功响应：
  - 带 `ETag: "<release_id>"`，已退役的版本为 `"<release_id>;retired"`；
  - 带 `Cache-Control: private, no-cache`，浏览器每次都要回服务端确认。
- 请求带 `If-None-Match` 时：
  - 先完成现有授权；
  - 再用轻量查询解析出本次要读的版本 ID 与退役状态：`active` 读 Head，指定 ID 时确认该版本属于此 Space，都不加载成员；
  - 与请求中的 ETag 一致时返回 304，不加载、不编码成员；不一致时返回完整内容。
- 为此在 `release.Service` 与发布存储上增加一个只读的版本引用查询，返回版本 ID 与是否退役，不读成员。
- 错误响应不带 ETag。

### 2.3 原文文件的浏览器缓存

`/releases/:release_id/sources/:knowledge_id/attempts/:attempt/file` 的内容由 knowledge ID 与解析轮次唯一确定，并经哈希核对。成功响应加 `Cache-Control: private, max-age=86400, immutable`；错误响应不加。

## 3. 验收

- **RED**：`frontend/src/enterprise/releaseCache.spec.ts`（Claude 编写，受保护，2026-10-20 按 §2.1 修订重写）：
  - 同一时刻的相同读取只发一次请求；
  - 先后两次读取各发一次请求（授权每次都经过服务端）；
  - 失败不会让后续读取共用；
  - 不同 Space 不共用；
  - 不进入深度响应式。
- **实现方另补（Go）**：
  - 指定版本：200 带 `ETag` 与 `Cache-Control`；`If-None-Match` 一致时 304 且不加载成员（用计数的假存储证明）；版本退役后 ETag 改变，旧 ETag 得到 200；
  - Active：Head 未变时 304，Head 前进后 200 并带新的 ETag；
  - 未授权时 403，不受 `If-None-Match` 影响；
  - 服务端成员缓存的测试（名称以 `TestPostgres` 开头）同原 §3：删成员行后仍命中缓存、退役状态是新读的、tenant 与 Space 隔离、并发只加载一次；
  - 原文文件的 `Cache-Control` 同原 §3。
- **门禁**：现有前端与企业包测试不新增失败。

## 4. 改动范围

- `frontend/src/enterprise/enterpriseApi.ts`；
- `internal/enterprise/releasestore/`（`publisher.go` 或新文件）、`internal/enterprise/`（版本读取与原文文件处理）、`internal/enterprise/release/`（版本引用查询）；
- 实现方测试。

## 5. 上线与核对

合并后随下一次 App 与 UI 构建上线（需用户批准）。上线后实测：

- 同一版本第二次读取的服务端首字节；
- 出处与原文接口的耗时；
- 浏览器中切换产品不再下载整版（开发者工具中没有重复的 releases 请求）。

# U-2a 修订来源只读守卫：还原 6 个上游测试文件

> 状态：Spec 冻结（2026-10-31，Claude）。实现方 Claude，审核方 Codex。属于 U-1 阶段 c（Issue #451）。
> 真实调用：0。不部署；随下一次 App 镜像上线即可，无迁移。

## 1. 为什么先做这一片

阶段 c 起点（`main@62d2f804b`，基线 `f17ee8a8d` = v0.9.0）共有 169 个上游补丁文件，按族盘点见附录 A 末尾“阶段 c 起点盘点”。

原计划先做 U-2（受管 KB 访问策略，KBPOLICY 族 18 个文件）。实际核对后改为先做本片，理由：

- KBPOLICY 的 18 个文件里，生产代码改动都是**上游处理函数内部的一行守卫调用**（MCP 读写工具、Wiki 写工具、IM 搜索、路由注册签名）。上游 v0.9.0 在这些位置没有可注册的扩展点；
  守卫 G11 又禁止在上游包里新增 Go 源文件。把守卫“搬走”只能缩短行数，文件仍是补丁，**补丁数不降**。真正去掉它们需要上游接受一个通用的 KB 访问策略接口（上游 PR），在那之前只能保持“一处一行”。
- 相比之下，有 6 个上游**测试**文件仅因我方修订来源守卫要求数据库里存在 `knowledge_revision_sources` 表而被改（给 SQLite 夹具补 `AutoMigrate(&types.KnowledgeRevisionSource{})`）。
  只要只读的“是否已钉住”查询在 **SQLite 且目录确认无此表** 时视为“没有钉住的来源”，这 6 个文件就能恢复成上游原样：**−6 个补丁，生产改动约 40 行，全部在已登记的补丁文件内**。

## 2. 改动

1. `internal/application/repository/task_queue.go`：把 R1（#460）引入的目录查询提炼成包内通用函数 `tableMissing(db *gorm.DB, table string) (bool, error)`；`deadLetterTableMissing` 改为调用它，行为与错误信息不变。
2. `internal/application/repository/knowledge.go`：新增 `pinnedRevisionSourceCount`，四个只读“是否钉住”计数改走它：
   `rejectPinnedRevisionSourceLocked`、`HasPinnedRevisionSource`、`HasPinnedRevisionSourceInKnowledgeBase`、批量删除前的钉住检查。
   规则与 `resourceRepository.MarkDeleted` 现有规则一致：
   - 查询成功：返回计数；
   - 查询失败且方言不是 SQLite（生产 PostgreSQL）：原样返回错误（守卫缺失即失败关闭）；
   - 查询失败且是 SQLite：读目录。目录确认无此表 → 计数 0（只有写入方会建表并钉住来源，无表即无钉住）；目录读取本身失败 → 两个错误合并返回；表存在但查询失败 → 返回原错误。
   写入路径（钉住、释放、封存）不变：无表时照常报错。
3. 6 个上游测试文件恢复为 `f17ee8a8d` 原样：
   `internal/application/repository/knowledge_list_filter_test.go`、`knowledge_transfer_test.go`、
   `internal/application/service/document_write_access_test.go`、
   `internal/router/task_processing_scope_test.go`、`task_dead_letter_attempt_test.go`、`task_dead_letter_utf8_test.go`。
4. 基线：只用脚本下调，G10 169 → 163；`docs/design/upstream-patches.md` 不涉及登记行变化（这些是测试适配，未单独登记）。

## 3. 验收（RED，受保护）

- `internal/application/repository/revision_source_pin_guard_test.go`：
  - SQLite 无表：`HasPinnedRevisionSource`、`HasPinnedRevisionSourceInKnowledgeBase` 返回 `(false, nil)`；
  - SQLite 有表且有钉住行：返回 `true` / `ErrResourcePinned`（正控）；
  - SQLite 连接已关闭：返回错误，不得返回 `(false, nil)`；
  - PostgreSQL 方言（sqlmock）查询报 “relation does not exist”：返回错误，且不发出目录查询。
- `tests/architecture/test_u2a_upstream_tests_restored.py`：6 个文件与 `f17ee8a8d` 逐字节一致；G10 ≤ 163。
- 6 个恢复的上游测试在实现后全部通过；其余测试结果与 main 同环境逐项一致。

## 4. 不做

- 不改 PostgreSQL 上的失败关闭语义，不改写入路径，不改 `resourceRepository.MarkDeleted`。
- 不处理 `kgRepo` 为空时的知识库删除守卫（3 个上游测试因此注入 `kgRepo`）：空依赖必须失败关闭，不为还原测试放宽。
- 不处理 MCP / Agent / 路由测试里注入受管分类器的改动：缺分类器必须失败关闭；这些等 KB 访问策略上游化。

## 5. 回滚

回退本片提交即可；无迁移、无数据变化。

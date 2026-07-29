# 045 · WeKnora Immutable Upstream Thin Adoption Design

> [!IMPORTANT]
> 2026-07-29 状态：upstream `80a5003...`、image build source
> `a8bf55ae...`、current main `529d72c...`；source adoption、migration bridge、
> trusted images 与 digest pin 已完成。Full Artifact/W1 runtime probes 与
> `source_reader` authority 仍未闭合。

## 1. 目标

045 采用一条薄升级轨道：

```text
approved manifest
  → immutable discovery proposal
  → finite check
  → exact-SHA Git merge
  → controlled W1/logger replay commits
  → dual migration + targeted gates
  → trusted multi-image Artifact
```

当前 manifest 指向 commit
`80a5003cc99a427098afe184eee6601916d3d156`、tree
`18fcf68e7a008ce69929e32233f0b6914040c223`，release ancestor
`v0.7.1@c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`。它们是当前数据，不是
检查器常量。未来升级替换 manifest 后复用同一流程。

设计优先级是：

1. 精确采用官方历史与 migration；
2. 无损保留 W1 与已有数据库；
3. 不扩大 Harness 权限；
4. 保持工具有限、可审计、可删除；
5. 用标准 Git 历史承载 merge/replay，不发明 patch 平台。

## 2. 权威输入

### 2.1 Target manifest

manifest 是唯一批准的 upstream identity 输入，至少记录 repository、commit、
tree、release ancestor、required capability ancestors 与 official migration
head。通用代码不得包含当前 commit/tree 的特判。

`discover latest-stable` 与 `discover mainline-head` 只查询并输出 immutable
proposal。proposal 包含 resolved commit/tree/ancestor/head，不能直接覆盖
tracked manifest、checkout、lock 或 workflow。

### 2.2 Harness plugin contract

machine-readable plugin contract 是 Harness↔WeKnora 边界的唯一可读合同：

- versioned public REST 与 lifecycle polling；
- `source_reader`、bounded test writer 等 principal；
- authoritative Space binding 与 tenant/RAW-KB ACL；
- allowed reads、denied mutations 与 failure zero-write；
- request/response envelope、typed errors、timeout、retry、idempotency；
- W1 runtime、consumer adaptation、source-reader authority、Artifact 状态；
- existing 与 planned validation nodes。

合同由 schema-v1 semantic digest 冻结。所有 Task 1B states 保持 false；
`source_reader` authority 保持 blocked。planned code node 只有后续真实测试落地
并改为 existing 后才能闭合，不能把 P4a/P4c 冒充 ready。

### 2.3 W1 planned path inventory

W1 path inventory 只登记 project-owned replay 路径、owner、理由、测试与 remove
condition。它不是 patch 文件、apply DSL 或 bundle manifest。路径 overlap 是
人工 review 的输入，不能由 inventory 自动生成代码。

## 3. 有限 `check`

`prepare_weknora_adoption.py check` 可以作为现有 prepare CLI 的子命令。它只
处理当前项目与 manifest 指定的 Tencent WeKnora target，不演化成任意仓库或
任意 patch engine。

### 3.1 输入

- tracked target manifest；
- 一个独立 target checkout；
- 当前 project checkout；
- tracked runtime lock；
- W1 path inventory；
- Harness plugin contract；
- target 与 project 中的 official migration files。

target checkout 必须 clean。它的 `HEAD`、tree、origin 与 manifest 一致，并能
证明 release ancestor 和 required capability commits 是 target ancestors。

runtime lock 只表示已部署/已构建 baseline。它不得被用作 source merge-base。

### 3.2 两组标准 Git delta

`check` 使用 Git 原生命令，不实现 collision engine：

1. 计算当前 project source 与 target 的真实 Git merge-base，再执行
   `git diff --name-only <merge-base>..<target>`；
2. 读取 runtime lock 后执行
   `git diff --name-only <runtime>..<target>`。

两组 path list 都与 registered W1 paths 求交集并排序输出。第一组回答“本次
source merge 会触及哪些 W1-owned 路径”；第二组回答“当前 runtime 到 target
的部署差距触及哪些 W1-owned 路径”。两组不能互相替代。

任一 registered overlap 只产生 `manual_review_required`。工具不解析 Go/SQL
业务语义，不判断自动保留哪一侧，也不生成 patch。

### 3.3 Migration 检查

official migration 以 target Git tree 为 byte authority。`check`：

- 枚举规范化 filename；
- 验证版本唯一、顺序连续到 manifest official head；
- 计算每个文件 SHA256；
- 在已合并 project tree 上验证 official files byte-exact；
- 拒绝 filename/head/checksum 漂移、dirty ledger fixture 或额外 project-owned
  official-chain migration。

这不是 SQL DDL parser。工具不提取 table/column/index，不做 schema semantic
collision。enterprise migration 由独立目录和 ledger 隔离，另由 PostgreSQL
定向测试验证。

### 3.4 Plugin contract 检查

`check` 调用现有 closed parser，验证：

- schema version 与 semantic digest；
- public endpoint/principal/Space/ACL/zero-write 合同；
- existing node 的真实 file/function；
- 唯一 planned code node 与 Artifact planned nodes 的如实状态；
- W1/consumer/source-reader/Artifact states 仍为 false。

plugin contract 失败属于 `block`，不能降级为人工忽略。

### 3.5 输出

stdout 只输出一份简短 deterministic JSON；不创建 tracked adoption report 或
receipt。固定字段为：

```json
{
  "schema_version": 1,
  "verdict": "pass",
  "target": {"commit": "...", "tree": "..."},
  "identity": {"clean": true, "origin": "official", "ancestors": "verified"},
  "deltas": {
    "project_merge_base_to_target": {"w1_overlaps": []},
    "runtime_to_target": {"w1_overlaps": []}
  },
  "official_migrations": {"head": 75, "files": [{"name": "...", "sha256": "..."}]},
  "plugin_contract": {"digest": "...", "existing_nodes": 0, "planned_nodes": 0}
}
```

实际计数从输入计算，示例不是固定 target 数据。JSON 使用固定 key/list order、
UTF-8 和无时间戳输出；不得包含绝对路径、环境变量、token、DSN 或文件内容。

verdict 规则封闭：

- `block`：identity、origin、ancestor、tree、migration、plugin digest/node 或
  输入完整性失败；
- `manual_review_required`：所有 hard checks 通过，但任一 delta 命中 registered
  W1 path；
- `pass`：hard checks 全通过且两组 registered overlap 为空。

没有第四种 verdict，也没有自动 semantic verdict。

## 4. 标准 Git merge 与受控 replay

source adoption 使用 official remote 的 exact manifest SHA 创建标准 Git merge。
merge-base 由 Git 根据 project history 与 target 计算。不得 squash 成无法证明
official ancestry 的 vendor dump，也不得用 runtime lock 替代 merge-base。

W1 与已有 logger redaction 只通过普通、可审查 replay commit 恢复。每个 replay
路径必须在 W1 inventory 中，overlap 由人审查，结果由 focused tests 证明。
045 不生成 `w1-*.patch`、bundle 或 receipt。Git commit/history 是唯一 patch
carrier。

普通 Wiki 单页 history、diff、manual edit、optimistic locking、revert 是
upstream 产品验收。它们不加入 W1 plugin endpoints，也不授予 Harness
`source_reader` 新权限。

## 5. Migration 设计

### 5.1 双 source、双 ledger

PostgreSQL 按顺序运行：

1. official `migrations/versioned` + `schema_migrations`；
2. enterprise `migrations/enterprise/versioned` +
   `enterprise_schema_migrations`。

official files 与 target tree byte-exact。项目不得修改、覆盖或复用 official
version。enterprise W1 migration 从独立 ledger 记账，后续 upstream head 增长
不改变这一边界。

### 5.2 Legacy W1 `000066` bridge

历史项目曾把 W1 写进 official `000066`。bridge 在普通 migration 前通过 raw
SQL 只读分类，并在 transaction/advisory lock 下重新确认：

- official ledger version/dirty；
- legacy W1 `000066` byte/checksum fixture；
- W1 schema/data fingerprint；
- official `000066` span expansion；
- enterprise ledger state。

已知 legacy 状态可幂等收敛到 official+enterprise 双 ledger；unknown、dirty、
partial、checksum mismatch 或 lock 前后漂移必须零写 `block`。legacy fixture
只服务兼容验证，不是 patch bundle 或通用 schema inventory。

## 6. 定向验证

### 6.1 Code gates

- `check` unit/mutation tests；
- exact official checksum/head tests；
- W1/plugin compatibility tests；
- disposable PostgreSQL origin/bridge/restart matrix；
- Wiki history/diff/edit/revert 产品验收；
- focused frontend type/test；
- OpenSpec strict、lint、type、diff/scope checks。

### 6.2 Workflow 与 images

trusted workflow 只从已合入 main 的 exact source 构建。server、worker、frontend
等多 image 必须共享同一 commit/tree/lock，并发布 digest、provenance 与 SBOM。
workflow 不下载或应用 project patch bundle。

### 6.3 Artifact

Artifact 阶段在 Code 合入后执行：

- exact image identity 与多 image 一致性；
- disposable PostgreSQL/backup clone migration；
- plugin/readiness/zero-write probes；
- product history/diff/edit/revert smoke；
- digest pin 与回滚证据。

Code gate 通过不等于 Artifact ready；consumer/source-reader/P4a/P4c 状态仍按
各自任务闭合。

## 7. 明确删除

045 不拥有以下文件或平台：

- `deploy/upstream/weknora-enterprise-schema-objects.yaml`；
- `deploy/upstream/weknora-adoption-report.json`；
- W1 replay patch/bundle/receipt；
- generic DDL parser、schema-object inventory 或 collision report；
- `bundle`、`verify-bundle`、patch DSL 或 arbitrary repository engine。

official checksum 与 W1 overlap evidence 由有限 `check` 的 stdout 和 CI log
提供，不再复制成 tracked report。

## 8. 决策结果

这条轨道故意不解决所有未来冲突。它只可靠地回答：

- 我们是否在采用 manifest 批准的 exact target？
- source merge 与 runtime gap 各触及哪些 registered W1 paths？
- official migrations 是否 byte-exact？
- plugin contract 与 validation nodes 是否真实？
- 是否可以继续、需要人工 review，或必须停止？

语义合并仍由人和定向测试负责。这是边界，不是缺失功能。

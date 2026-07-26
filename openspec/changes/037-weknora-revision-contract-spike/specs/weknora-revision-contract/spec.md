# 037 W0 Revision Contract Spike 验收规格

## ADDED Requirements

### Requirement: W0.1 证据先于合同

系统 SHALL 在 P4a/P4c 实现前完成本 spike。P4a/P4c 所依赖的
`SourceLifecycleContract` 与 `RevisionManifestContract`
SHALL 分别基于当前跟版基线上的可复现实验证据裁决为 `sufficient` 或
`insufficient`；SHALL NOT 以设计假设、时间戳比较、最终 M2 相等或客户端
重试替代原子合同证明。每个 probe SHALL 记录可复现步骤与观察证据；并发类
probe SHALL 至少重复 3 次。

#### Scenario: 裁决只有两种

- **WHEN** W0 evidence report 完成
- **THEN** 每份合同的结论是 `sufficient`（附 API 证据）或
  `insufficient`（附触发 W1 的缺口清单），不存在第三种模糊状态

### Requirement: W0.2 insufficient 必产 W1 草案

任一合同 `insufficient` 时，W0 SHALL 交付最小 W1 API 规格草案：revision
response 至少返回 `knowledge_id + parse_attempt + file_digest +
parser/chunker identity + ordered chunk manifest digest + completed_at`，
并保证读取内容与该 manifest 绑定；SHALL NOT 引入 webhook、共享数据库、
Asynq 耦合或第二套解析器。

#### Scenario: W1 草案字段完备

- **WHEN** RevisionManifestContract 被裁决为 insufficient
- **THEN** `w1-api-draft.md` 存在且覆盖上述全部字段与绑定语义，P4c 在
  W1 合入前保持 blocked

### Requirement: W0.3 spike 安全边界

spike SHALL 只操作自建的 `w0-spike-` 前缀 scratch 对象并在收尾清理；
SHALL NOT 打印凭据、修改 WeKnora 代码或触碰既有业务数据。

#### Scenario: 零残留

- **WHEN** T8 收尾完成
- **THEN** live 环境中不存在 `w0-spike-` 前缀残留对象，report 无凭据

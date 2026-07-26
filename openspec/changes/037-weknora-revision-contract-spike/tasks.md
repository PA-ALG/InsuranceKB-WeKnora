# 037 · Tasks / Probe 计划

## Contract Card

1. **单一职责**：只读证明两份合同并出具裁决；非目标见 proposal。
2. **权威/事务**：无写权威；scratch knowledge 自建自删。
3. **状态机**：无。
4. **威胁矩阵**：凭据泄漏（禁止打印 key/DSN，输出前脱敏复查）；污染既有
   数据（只操作带 `w0-spike-` 前缀的自建对象）；假阴性（每个 probe 必须
   记录完整可复现步骤，结论只基于观察到的证据）；把偶然时序当合同
   （并发类 probe 至少重复 3 次）。
5. **验收**：T1–T7 每项有证据段；两份合同各有明确 sufficient/
   insufficient 结论；insufficient ⇒ W1 草案存在且覆盖 033 §4.4 字段。
6. **路径预算**：仅 openspec/changes/037-*/ 下文档与 artifacts；零生产
   代码。

## Tasks

- [x] T1 stable identity：上传 scratch PDF，记录 knowledge_id 与全部
  可见版本/时间字段；重解析后对比——哪些字段稳定、哪些变化、是否存在
  单调 generation/attempt 可从公开 API 读取（非 trace span）。
- [x] T2 completed 绑定：解析完成态下，能否把「completed 状态」与
  「parser/chunker 精确身份 + 原文件 digest」绑定为一次不可变读取；状态
  字段与 chunk 集合的更新是否原子可见（metadata 双读窗口内观察）。
- [x] T3 chunk 枚举：chunk 列表的稳定排序键、分页游标语义、总数与
  manifest（是否有服务端 digest；无则记录客户端可计算性与其局限）。
- [x] T4 重解析竞争：分页读取过程中触发重解析（≥3 次重复）：客户端能否
  察觉集合被替换（id 全换？updated_at？计数跳变？）；能否证明"读到的是
  同一 attempt 的完整快照"，或证明不能。
- [x] T5 删除/禁用：删除与禁用的 API 枚举方式、返回形状、与 chunk 读取
  的竞争行为；KB/Source ACL 的粒度证据。
- [x] T6 裁决：分别冻结 `SourceLifecycleContract` 与
  `RevisionManifestContract` 的 sufficient/insufficient 结论与依据。
- [x] T7 条件产物：任一 insufficient ⇒ 写 `w1-api-draft.md`：revision
  response 至少含 `knowledge_id + parse_attempt + file_digest +
  parser/chunker identity + ordered chunk manifest digest + completed_at`
  且读取内容与 manifest 绑定；不引入 webhook/共享 DB/Asynq 耦合。
- [x] T8 收尾：scratch 对象清理证据；evidence report 脱敏复查；OpenSpec
  strict；更新 23 号控制板 W0 行与 HANDOFF 状态块（合入时）。

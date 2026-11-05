# ST-1 · Release 成员与准备记录存储

> 第1步调查与设计，**待 Claude 确认**。Refs #550；Codex 调查/拟实施，Claude 审核。
> 本提交不含 RED、运行时代码、迁移或合同变更，不是上线/清理许可。
> 依据：蓝图 §5.1「成员内容寻址」、§6.2/6.5、§7.4/7.5、§12；S4c-2a/2b-1/2b-2、S3i、S8b。
> 调查源码固定于 `76f06b695`；目录 `.worktrees/st1`，分支 `slice/st1`。

## 1. 结论与证据边界

推荐 **(a) 完整成员内容寻址 + (b) 激活准备记录引用同一不可变成员集合**，不采用 (c) 历史成员按年龄删除。
不是拿 payload digest 去合并“同文”，不是删准备记录整行，也不是把历史 Release 改成当前 Head。

容量基线为 [#547 报告](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/547#issuecomment-6659202624)
及其已保存只读聚合（2026-11-05 12:46–13:17Z），非恒定现场：

| 量 | 已保存聚合 |
|---|---:|
| database 大小 | 5,564,659,379 B ≈ 5.1825 GiB |
| 成员关系 total（含索引/TOAST） | 3,122,159,616 B ≈ 2.9077 GiB |
| 其中 table（含 TOAST，不含普通索引）/普通索引差额 | 2,929,270,784 / 192,888,832 B |
| 准备关系 total | 2,189,115,392 B ≈ 2.0388 GiB |
| 历史成员集合/成员出现次数 | 219 / 514,876 |
| 准备记录 | 223：draft 3、ready 220 |
| Active 成员数/报告 `row_bytes` 合计 | 3,639 / 18,840,950 B（17.9681 MiB） |

`row_bytes` 是旧聚合的行尺寸口径，不能冒充原始 payload 或关系物理大小。`pg_stat` 的 rows_est
不是上述精确 count；ready 与 Release 数的差值也不能证明哪些记录可删。

本轮两次必要轻量聚合尝试在连接阶段 EOF，未取数、未进入查询；随后总控明确暂停线上调查。
无活动查询/长事务，无线上写入。**完整存储身份的 count/字节加权重叠率尚未实测**，不以
相同文本、payload digest 数或“历史行数÷当前行数”代替。后续安全测量门见附录A §4。
没有访问 #549 的登记/编译/运行目录，不要求其暂停或测量；合法发布后的增长不据此判异常。

## 2. 当前实际写入与读取

### 2.1 写入和摘要含义

- `release.activationMembers/materialize` 生成完整目标集：继承 Active、应用 delta/removals、按 slug
  排序。`releasestore.snapshotsOf` 为每个成员生成 snapshot 和 manifest。
- `wiki_release_members` 每 Release/slug 一行，含 kind、slug、revision_id、member_digest、title、
  content TEXT、payload JSONB。企业 content 是 v1 封套：**原 payload 文本**、EvidenceRefs、AccessScope；
  JSONB 是额外投影。只继承的成员仍整块重复写入。当前两个大列都不等同于只存一个 digest。
- `wiki_release_preparations.members` 再存完整 snapshot 数组（含上述 content 和 payload）；manifest
  含 candidate/decision/bundle 身份和有序 `[slug, member_digest]` 列表。激活事务同时插入准备、
  Release、全部成员、CAS Head、receipt、来源链接和逐点决定；失败整体回滚。
- `MemberDigest` 是 frozen 的 `json.Unmarshal(any/float64) → json.Marshal → SHA256(payload)`；
  payload 内 provenance/编译版本/审核/maintenance 等变化均可改变它。它**不绑定**独立的 kind、slug、
  revision_id/title、封套 EvidenceRefs/AccessScope，也不保留 JSON 空白/键序，不能单独做存储主键。
- manifest digest 与 preparation digest 均保持原规则。后者绑定 ID、manifest digest、decision、
  expected Head/epoch；不是完整 snapshot 的新摘要，不能拿它替代完整内容验证。
- 原字节从封套读回，再验证原 MemberDigest；JSONB 重排不能据此改外部 payload 字节。成员集合顺序、
  manifest 数组顺序、外部 bundle/decision/source binding/exact3 snapshot 摘要均不得重算成 ST-1 身份。

### 2.2 全部生产依赖梳理

| 路径 | 当前依赖 | ST-1 必须保留 |
|---|---|---|
| `repository.WikiReleaseRepository.Activate` | 插入前比较 preparation.Members 与写入 Members；完整快照→成员行；同一事务 CAS/receipt | 完整目标校验和事务/锁顺序；幂等提交不可二次移动 Head |
| `releasestore.releaseHeader` | 每次读 Release + **preparation.manifest** + retirement | 准备头、manifest、作用域与原摘要不能删除；304 也依赖它 |
| `ReleaseByID` / `MembersOf` | header 后读成员（前者解码并验证，后者仅 slug/digest） | 指定历史版本完整可读；按 slug 排序；轻量读取不能变成逐成员 N+1 |
| `ReleaseReference`、Release/citation/file 条件请求 | 每次授权后读 header；缓存只省不可变成员 | 同一 ID/退役状态 ETag；304 仍检查身份/权限/来源，不以对象存在即授权 |
| `committed`、`PublishedCandidate`、`replay` | receipt 或 candidate→历史 Release→header/成员 | Head 前进、退役后仍返回原提交，不重激活/重新 pin |
| candidate 预览/详情、逐点审核、rebase | 原 candidate bundle/决定 + 对应 base/current Release | 基准与目标不能漂移；关闭/拒绝不是删除准备行的证据 |
| 实体回退、专家修改、版本比较、知识/问答/MCP/引用 | 各自固定 Release，经同一成员读取适配器 | 原值/来源/metadata/历史回跳与审计，不借新 Head 补旧数据 |
| `managed.custodyLookup.FindScopes` | preparations/releases/heads/receipts 的四段 scope 元数据 | 无 Head 时仍不能重开受管 KB 写入口 |
| `Retire` / SourcePins | release header、retirement、`enterprise_release_sources` | 退役仅释放来源 pin；**不删除历史成员**。原件被合法清除后仍按既有 typed 失败，不伪造可回跳 |

全仓生产检索只发现激活端读取内存 preparation.Members 作校验；已提交准备行的生产读取只选 manifest
或 scope。未发现当前运行时代码从其持久 members 恢复完整 Release；但这是精简该列的依据，**不是
删除 manifest/审计头或未关联准备项的依据**。draft/未关联 ready 可能来自旧阶段，状态不推断为可删。

依据入口：`internal/types/wiki_release.go`、`internal/application/repository/wiki_release.go`；
`internal/enterprise/releasestore/{publisher,reference,candidate_publication,source_pins,reviews,points,member_cache}.go`；
`internal/enterprise/release/{publish,activation,point_queue,point_views,retire}.go`；`internal/enterprise/managed/classify.go`。

## 3. 三类方案

| 方案 | 收益 | 约束/判断 |
|---|---|---|
| (a) 完整内容对象 + 小型成员集合引用 | 未变的大 content/payload 跨 Release 不重复；历史版本仍完整 | 推荐。对象身份必须覆盖完整 snapshot，集合引用仍有 `O(版本×成员)` 开销，不能说总量线性或自动节省某固定百分比 |
| (b) 已提交准备项精简 | 不再存第二份完整成员数组 | 与(a)组合：准备项和 Release 可引用同一集合；保留 manifest、原身份与审计。单独清空 members 虽可能省一份，但没解决成员表增长，也不能泛化到 draft/未关联 ready |
| (c) 非 Active、未 pinned、超回滚窗删除成员 | 删除历史可能省更多 | 本片拒绝。外部历史 ID/引用/审计/replay/rebase 仍依赖；无 pin 不是无消费者。现有退役也明确保留成员。需要改变历史保留合同与用户裁定，不能作为 ST-1 隐式 GC |

不改 CandidateBundle、Harness 输出/编译、审批策略、Source 生命周期或外部 REST/MCP 合同。
保留候选 raw_bundle、决定/逐点决定、receipt 与 manifest；它们是审计/重放来源，不因大列优化被抹掉。

## 4. 推荐的物理模型（待确认后才实施）

### 4.1 作用域与两种内容身份

所有对象/集合键均带**完整四段 scope** `(tenant_id, space_id, raw_kb_id, wiki_kb_id)`；不跨 tenant、
Space 或 KB 合并，即使字节相同。没有按 digest 直接读内容的新外部接口。查询仍先确认 Release 属于该 scope。

- 新 `storage_digest` 与 MemberDigest 分离、带 codec 版本。存储对象覆盖完整七字段 snapshot：
  kind、logical_slug、revision_id、member_digest、title、content **精确 UTF-8 字节**、payload。
- payload 保存为 TEXT `payload_json`：新写入先批量经数据库 `jsonb::text` 得到与现有 JSONB 投影同义的
  固定表示；回填使用原 JSONB 的 text。随后将该文本作为**字符串字节**保存/哈希，不经过 float64，
  不在读时重新格式化。对象读回可还原 `json.RawMessage`；外部原 payload 仍从 content 封套取得。
- codec v1：前缀 `enterprise-member-content.v1\0`，七个字段依次以“uint64 big-endian 字节长度 + 字节内容”编码，
  SHA256；不得 delimiter 拼接、Unicode/空白归一或只 hash 引文。DB 版本将来输出不同的等价 JSON 表示
  最多降低新旧对象复用，不得改已存对象身份；已存 `payload_json` 不重排。
- 相同键插入冲突时校验完整字段相等，任何不等/损坏失败关闭，不能 `DO NOTHING` 后无条件信任赢家。
  企业封套仍按现有读法核验 MemberDigest；不趁迁移改 frozen 的业务摘要规则或“修复”旧坏行。

### 4.2 对象、集合和映射

新增自有表（均有上述 scope、FK/唯一约束；名字在 RED 前按最终迁移编号冻结）：

1. `enterprise_member_contents`：storage_digest + 完整 snapshot（payload_json TEXT），不可变。
2. `enterprise_member_sets`：set_digest、codec、member_count，不含大正文。
3. `enterprise_member_set_items`：set_digest、ordinal、slug、storage_digest；slug/ordinal 在集合内唯一，
   对内容对象是完整 scope FK。集合摘要前缀 `enterprise-member-set.v1\0`，绑定 member_count 后按
   **有序** `(uint64 ordinal, slug, storage_digest)` 长度编码计算；不能排序后冒称原序不变。
4. Release 与 preparation 的 storage 映射分别指向集合；其外键绑定对应原行的 ID **和完整 scope**。
   只有完整字段和顺序都相同才复用一个集合；旧准备数组可与 Release 不同（例如既有
   `materializeMembers` 将空 kind 变成 `page`，或数组顺序不同）。分别保留各自有序集合，仅共享
   真正相同的内容对象，不能把 Release 行反写成原准备数组或为节省引用改序。

保留原五张表中所有头/manifest/身份字段。已激活准备项改为集合引用后，不再重复大 members 数组；
其原 manifest/摘要保持。旧 members 列可在验证后置 JSONB `[]`（不是null），但新/旧格式必须由
明确映射标记选择，不能把 `[]` 当作“已迁移”或“确实空集合”的判据。
所有 legacy draft 和未证实已提交的 ready 保持原样，不设年龄清除定时器。
新模型没有内容 GC：对象即使暂时不可达也不在本片自动删除；未来 GC 必须检查全部集合/迁移中状态。

### 4.3 真实读写路径

- 唯一 Head/epoch 权威仍为原 `WikiReleaseRepository.Activate`；成员存储经明确的存储适配接缝接入，
  不复制第二套发布事务/Head。内存完整目标和现有 preparation 等价校验保持在任何持久副作用之前。
- 对象、集合、两个映射、Release、来源 pin/links、决定、CAS 和 receipt 均在**同一现有事务**提交。
  任一步失败整体回滚。保持 review-candidate→candidate digest→来源知识/来源行→Head 的锁顺序；
  内容键按稳定顺序写入，不引入跨 scope 的共享对象锁或全局锁。
- `MembersOf` 只读引用与摘要；完整读通过集合 join 一批还原 snapshot，不逐对象请求。payload 的
  DB 归一和对象写入按批处理，不新增每成员一个 SQL 的路径。受影响查询性能在未来测试验证。
- `ReleaseByID` 保留原 decode/digest 校验、授权、退休状态、缓存键和深拷贝行为。新格式标记存在但
  缺对象/错 scope/顺序/计数/摘要时失败关闭，沿用存储错误的 `INTERNAL_ERROR`/500 脱敏映射
  （配置不可用仍按既有 `SERVICE_UNAVAILABLE`/503）；不能退回旧副本掩盖损坏，
  更不能读 Active 代替指定版本。只有**未迁移且明确 legacy 格式**才走旧读取路径。
- manifest/MemberDigest、所有外部 ID/epoch、candidate/decision/source 指纹不变。迁移不刷新任何业务
  时间、审核标签、专家锁或内容，不重新评审/激活/封存/pin，也不解锁来源。

## 5. 迁移、并发与回滚

线上升级/整理/备份/空间回收必须另开运维 Issue，本阶段无执行。本设计采用**有退出条件的过渡**，
不是永久双存或新旧双 Head。

1. **expand**：新增表/完整 FK 与唯一约束、迁移进度/格式元数据，不动旧列；迁移号从当前 head12
   的下一空号开始，实施前 Owner 锁定，不能与其他片抢号。大表索引/约束的在线/短锁步骤在运维预检
   计划中明确，不能把重型回填藏在应用启动 DDL 里。
2. **短期桥接**：一个明确版本的应用，在原事务内同时保持旧快照和新对象引用；对外仍一个 Head。
   对新发布强制同时生成完整新映射，便于随后切换和二进制回退；这一阶段暂时增加而非释放空间。
3. **分批回填**：仅从既有不可变成员/明确已提交准备读取，按发布/行批次和字节上限断点推进。
   不整库长事务/长快照，不锁线上 Head。每个映射只有在对应完整集合验证成功后才标记可读；
   失败/中断留下的 staged 对象不进入读路径。准备快照的完整内容/行版本需核前后未变，不能仅信
   PreparationDigest（它不覆盖 members）。draft/无可信提交关联的行跳过并报计数。
4. **核验/追平**：逐版本核四段 scope、全部字段、计数/唯一性、原数组顺序、manifest 对应、
   原企业 payload digest 与封套字节。历史成员、引用、pins、retirements、receipt/决定总数和身份不变。
   校验进度持久化且可重复；增量新发布由桥接写保证，不只依赖 created_at 水位推断“没有漏行”。
5. **cutover**：读方按已验证的格式标记切新，未标记只读 legacy；新写转为 reference-only 前确保
   所有运行实例支持新格式。观察期建议7天供 Owner 确认，**不是历史保留期**，不自动执行删除。
6. **退出旧副本**：全量核验、恢复演练、容量预检、观察期和 Owner 运维批准都满足后，才移除
   已验证映射对应的冗余旧大列/行；保留所有历史逻辑内容及旧准备头/manifest，未关联旧准备不动。
   只有所有原本可读 Release 都完成迁移后，才移除迁移用 fallback/双写能力；不能把未迁移的
   可读版本改为报错来完成切换。原已损坏的行报阻塞并保留，不静默遗漏或自行修复。

回滚：桥接阶段直接保留旧读写数据，但先停用新格式写入；reference-only 后须先用不可变对象/有序集合
分批**完整重建**旧成员行和旧准备数组，核摘要/顺序/身份后才能换旧二进制。down 不得先 DROP 新表或
声称“空旧表也能回滚”；验证失败拒绝 down。整个恢复不改 Head、epoch、决定或 pin。原件缺失/摘要不符
仍报原 typed 错误，不能因数据重排恢复已失效来源。断点/结果未知先读进度和映射核对，不盲目重写。

容量峰值预检必须包括旧副本 + 新内容/引用 + 回填临时索引/TOAST + WAL + 当前备份/其他业务空间；
没有这些余量就不做在线回填，改在另行批准的停写维护窗分阶段。DELETE/UPDATE 的 dead tuples、普通
VACUUM 可复用页与 OS/VM 真正可用空间分开报告；rewrite/VACUUM FULL/REINDEX 等另需运维许可。

可观测：记录按格式的版本/集合/对象/引用计数与字节、已核验/跳过/失败/待恢复批次数、查询/锁等待与
超时、完整性错误计数、桥接期新旧对照差异；关系/TOAST/索引、WAL、备份和文件系统各自列账。
指标/错误日志不含正文、凭据或对象原文。共享对象受损会影响引用它的多个历史版本，必须完整验证、
失败关闭并从经过核验的备份修复，不能由另一个 tenant/Scope 或“相似文本”补齐；修复另走运维授权。

## 6. 未来 RED 验收矩阵（此阶段只描述）

| 类别 | 将来独立 RED 必须反驳 |
|---|---|
| 字节与身份 | 同文不同 metadata/version/审核/EvidenceRefs/AccessScope/kind/slug/revision/title 不合并；JSON 键序/数字/空白差异保留旧业务 hash 和原 payload 字节；对象损坏/摘要冲突拒绝 |
| 去重与隔离 | 多 Release 同 snapshot 只一对象；不同 tenant/Space/KB 绝不串用；含空集/相同最终集复用；集合顺序不同不错误等同 |
| 完整历史 | 历史/Active/pinned/retired 同成员与同序；PDF/Office 引用/HTTP文件/MCP、304、专家记录、实体回退与 SourcePins 边界不变；冷缓存也覆盖，不能靠热缓存掩盖丢行 |
| 准备依赖 | 激活后 manifest/custody/header/审计/replay 可用；draft/未关联 ready 不精简；准备与 Release 顺序不同可逆；关闭/拒绝记录不能仅按时间删 |
| 发布并发 | 同 nonce/同候选不同决定重试只一次提交；不相干 rebase、同实体冲突、首次 Head 竞争、事务各故障点、点批量与整包两路径均保持 CAS/rollback；不死锁 |
| 迁移 | mixed legacy/new、断点/短批/源行漂移、桥接时发布/退休/重放；缺一映射/对象/FK/count/顺序时不能标完成或读旧副本掩盖；幂等回填 |
| 回滚与容量 | bridge 可回旧；ref-only 先恢复旧行/数组再 down，坏对象/空间不足/部分恢复拒绝；固定合成规模夹具验证对象/引用数量，不以 TOAST 压缩偶然值断言业务正确 |
| 接口/性能 | 原公开合同/状态/授权输出不变、MembersOf 不载大内容、完整读批量 join 无 N+1；snapshot 与来源摘要不漂移 |

RED 必须覆盖两种以上结构和完整生产存储/事务入口，含 PG 适配器与纯合成历史，非仅 hash helper。
未来门禁按受影响 Go/PG、迁移升降、架构与合同漂移；不改旧保护断言遮错，不加 skip/xfail。

## 7. 阶段与拟写域

本阶段仅本 Spec、[附录A](ST-1-附录A-容量与测量.md)及仓库外必要调查脚本/私密证据。
将来如确认设计：自有 `internal/enterprise/releasestore/` 及必要成员存储子包；既有
`internal/application/repository/wiki_release.go`、`internal/types/wiki_release.go` 的存储接缝；
`migrations/enterprise/versioned/` 新迁移与 `internal/database/enterprise_migration.go` 迁移头；自身测试。
三处既有扩展文件在固定上游 `f17ee8a8d` 不存在，不新增上游 patch 数；新模块只在自有 enterprise 路径、
≤500行。具体端口/迁移号与独立 RED 仍需确认后冻结，保持原公开 repository/Publisher 签名。

不改 Harness、编译身份/值协议、contracts/前端/导航/领域规则、蓝图或守卫/基线；不删除审计或
修改 Source 生命周期；不把未来存储实现混进本次 Spec 提交。

### 待 Claude 明确确认

1. 是否按(a)+(b)对象/有序集合引用推进，并明确拒绝本片历史年龄 GC？
2. 是否接受完整 snapshot 存储身份、四段 scope 隔离和有界桥接；建议7天观察窗由后续运维再定？
3. 是否接受附录A的显式容量情景与当前去重率未知；精确历史重叠/目标物理大小待稳定后的安全测量，
   未完成测量前不据此批准大规模放量或承诺释放磁盘？

Spec 发出后暂停于设计门，等 Claude 明确确认才启动后续 RED/实现；第1步交付不表示 ST-1 已实现、
已合并或已迁移。线上迁移/整理、重型离线副本实验和构建仍各需明确运维安排。

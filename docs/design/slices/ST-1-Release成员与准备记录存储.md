# ST-1 · Release 成员与准备记录存储

> r5，r2 已获确认并已进入实施；依 Claude [顺序裁定](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/550#issuecomment-6666799749) 澄清内部布局与 SQL 读序。Refs #550。
> Codex 实现，Claude 审核；本提交独立修正文档事实，不含运行时修改。
> 本提交不含 RED、运行时代码、迁移或合同变更，不是上线/清理许可。
> 依据：蓝图 §5.1「成员内容寻址」、§6.2/6.5、§7.4/7.5、§12；S4c-2a/2b-1/2b-2、S3i、S8b。
> 调查源码固定于 `76f06b695`；目录 `.worktrees/st1`，分支 `slice/st1`。

## 1. 结论与证据边界

已确认采用 **(a) 完整成员内容寻址 + (b) 准备记录引用**，不采用(c)年龄历史GC。
r2 将集合改为**共享内容块 + 小型块列表**，取代 r1 全量逐成员引用表；未改已确认的身份/隔离/历史方向。
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

上一调查阶段两次必要轻量聚合尝试在连接阶段 EOF，未取数、未进入查询；随后总控明确暂停线上调查。
无活动查询/长事务，无线上写入。**完整存储身份的 count/字节加权重叠率尚未实测**，不以
相同文本、payload digest 数或“历史行数÷当前行数”代替。线上迁移前的安全测量门见附录A §5；它不阻塞设计确认后的 RED/实现。本轮不做测量。
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
| (a) 内容对象 + 内容定义块 + 根块列表 | 内容与未变块跨版本共享，历史版本完整；新增块规模受本次改动邻域约束 | 采用。块列表仍有 `O(版本×成员/块长)` 小型开销，不宣称总存储完全 O(delta) |
| (b) 已提交准备项精简 | 不再存第二份完整成员数组 | 与(a)组合：准备项和 Release 可引用同一集合；保留 manifest、原身份与审计。单独清空 members 虽可能省一份，但没解决成员表增长，也不能泛化到 draft/未关联 ready |
| (c) 非 Active、未 pinned、超回滚窗删除成员 | 删除历史可能省更多 | 本片拒绝。外部历史 ID/引用/审计/replay/rebase 仍依赖；无 pin 不是无消费者。现有退役也明确保留成员。需要改变历史保留合同与用户裁定，不能作为 ST-1 隐式 GC |

不改 CandidateBundle、Harness 输出/编译、审批策略、Source 生命周期或外部 REST/MCP 合同。
保留候选 raw_bundle、决定/逐点决定、receipt 与 manifest；它们是审计/重放来源，不因大列优化被抹掉。

## 4. 已确认的物理模型

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

### 4.2 选择：保留未变边界的局部内容定义分块（M1）

不选父 Release delta 链+定期全量检查点：它会把历史冷读变成回溯、检查点仍周期复制全量引用，
且同 base 分支/历史重放更复杂。选分块后每个根是自足的完整块列表，读时**不沿父 Release 链**。
父根只用于写时识别可共享块；缺失新格式父根失败，未迁移 legacy 父根只允许一次明确的布局引导。

**冻结分块 codec v1：**

- Release **内部布局**按 materialize 的 UTF-8 slug 字节字典序，根只用 `slug_asc`；它不是对外读序。
  所有新旧 Release 对外均沿用旧 reader 的 SQL `ORDER BY logical_slug ASC` 及原列 collation，
  在批量关联内容后由 SQL 排序；迁移将原列 collation 复制到内容列，部署不得另行改变其一致性。
  历史 preparation 保留原数组顺序，必要时用 `legacy_sequence`，不由 Release 读序反写。
  边界 hash 只用 slug，不看 payload/storage_digest/类型/产品编号。
- 首建或历史回填从头扫描：`H=SHA256("enterprise-member-boundary.v1\0" + LP(slug))`，LP同§4.1；
  块满32项后，H首8字节 big-endian 的低6位为0则自然切开；到128项强制切开。全局末块可少于32。
  目标平均64–128；均匀 hash 下修尾前期望约81.11，不把真实输入分布当随机保证。
- **只改值、slug不变：保留原分块边界**，只生成包含变化项的新块；块外引用不重写。
- 插删：从父列表与最终列表的一次diff（不依命令次序）标出真实增删键的连续区间；两个变化键间
  有未变键即分为不同区间。插入键归到父列表第一个较大键所在块，尾端归末块，空父集独立建块。
  取所有相交/插入点所在块，再加左右各一个未变完整邻块；重叠窗口合并，只对窗口内幸存键+
  新键按上述规则重切，外部整块原样复用。
  非末尾窗口若最后碎块不足32，合并末两碎块；合计≤128则一块，否则按 ceil/floor 两半拆开。
  只修这两块，不继续向窗口外借项。窗口数据为空时直接移除，整集合空时产生合法空根。
  同轮换值先随这些窗口应用，窗口外换值只替换原块，不因处理顺序重复重切。
- 这是**增量维护的布局**：最小/最大/修尾强制点可不满足自然 hash 条件，只依赖键序、窗口及父边界，
  不依赖内容值。同一父根+同一最终序列操作确定；不同历史可能得到同逻辑序列的不同布局根，允许，
  不改变任何业务/manifest/snapshot hash。无变化直接用父根。不能每次对全表从头重新切块。
- 设K为变化键数、J为分离的键序区间数、Lmax=128：只改值重写的条目数
  `Wm≤min(N,K+2J(Lmax−1))`；插删窗口新条目保守界 `Wa≤min(N_new,K+4J·Lmax)`。
  因此散布修改也有 `W≤K·Lmax` 的只改值界，不能承诺总是只改一块或两组任意125键的块字节相等。
  删除自然切点/触及最小最大/短尾也只影响所选窗口；无自然切点不引发全表强制边界移位。

**紧凑存储与校验：**

1. `enterprise_member_scopes` 将完整四段 scope 唯一映射为内部 bigint；scope_id不是授权依据，
   每次必须由已授权四段 scope解析并核对。所有内容/块/根主键均为 `(scope_id, BYTEA32 digest)`。
2. `enterprise_member_contents` 保存§4.1七字段，索引按上述完整身份。内容/版本/访问范围不同不可合并。
3. `enterprise_member_chunks` **一块一行**，列含codec、count及`refs BYTEA`（恰好count×32字节的
   storage_digest序列）；不建逐成员关系表、不在每项重复scope或hex。chunk_digest前缀
   `enterprise-member-chunk.v1\0`，绑定count及有序 `(LP(slug), storage_digest32)`；slug从同scope
   内容对象元数据取得，读取时批量核存在/唯一/order/hash。无逐项FK不代表可跳过完整性验证。
4. `enterprise_member_sets` 一根一行：codec、order_mode、member_count、chunk_count、`blocks BYTEA`；
   每项固定36字节（uint32块count+32字节chunk_digest），无逐成员行。set_digest前缀
   `enterprise-member-chunk-set.v1\0`，绑定mode、uint64成员数、uint32块数及完整有序块列表。
5. Release/preparation 映射保留原ID及完整scope关系，指同scope根；FK/约束核映射和原行四段scope一致。
   内容、块、根键冲突都核全部字段/有序数据，不一致失败关闭，不能盲目忽略冲突。

新写 materialize 和既有 kind 默认处理**只做一次**，以最终同一有序七字段列表同时构造准备和Release，
调用一次Put、共享同一根；Release 读出时另作 SQL 排序，不产生新“空kind/page”差异。只有历史准备数组顺序/字段确有差别时才保留
独立准备根；不能拿Release行反写历史准备。根、块只读即可完整还原，结构摘要不能取代业务摘要。

保留原五表的头/manifest/身份。已验证准备members可置JSONB `[]`而非null，但只依明确格式映射读取；
不能把`[]`当迁移完成或真正空集的判据。draft/未证实已提交ready保持原样，不设年龄清理或内容GC。

### 4.3 冻结端口、真实路径和查询（M1/M2）

不改原 Publisher/REST/MCP 合同，也不改现有 repository 构造/公开方法参数。只新增内部存储端口：

```go
// internal/types/wiki_release.go
type WikiReleaseMemberSetWrite struct {
    Scope WikiReleaseScope
    PreparationID, ReleaseID, ParentReleaseID string
    Members []WikiReleaseMemberSnapshot // 已materialize的同一最终列表
}
```

```go
// internal/application/repository/wiki_release.go
type WikiReleaseMemberStorage interface {
    Put(context.Context, *gorm.DB, types.WikiReleaseMemberSetWrite) error
    Read(context.Context, *gorm.DB, types.WikiReleaseScope, string) ([]types.WikiReleaseMemberSnapshot, error)
    Digests(context.Context, *gorm.DB, types.WikiReleaseScope, string) (map[string]string, error)
}
func (r *WikiReleaseRepository) WithMemberStorage(WikiReleaseMemberStorage) *WikiReleaseRepository
func (r *WikiReleaseRepository) GetReleaseMemberDigests(context.Context, types.WikiReleaseScope, string) (map[string]string, error)
```

`WithMemberStorage`返回新实例，不可修改共享实例；`NewWikiReleaseRepository(db)`原签名不变。
生产`releasestore.New`及其事务内repository实例都接入同一成员存储实例，不是只接测试；无端口的
legacy repository不得在ref-only生产scope服务。新模块不反向调用repository，接口依赖在repository，
实现只依types/GORM，避免循环。`releasestore.NewMemberStorage()`向底层构造注入企业历史验证函数，
复用原 decodeMember/MemberDigest，并核 manifest/准备/Release 对应及 JSONB 投影；未知协议的纯存储实例
不得认证、切换或精简历史。该内部构造不修改冻结三方法端口。ParentReleaseID是本次既有Expected Head，不补读更新后的Head。

- 唯一Head仍由原Activate事务负责；输入等价/最终列表校验先于持久写。内容、块、根、两个映射、
  原头/receipt、点决定和Source pin/links同一事务提交。保持review-candidate→candidate digest→
  来源知识/来源行→Head锁顺序；对象/块稳定键序插入，不引入跨scope共享锁或全局锁。
- Read先过现有scope/header权限，批量读映射+根、块、内容：存储阶段最多3组集合查询，无按块或
  按成员N+1。完整读校验内容storage_digest、块hash/count/引用长度、根hash/总数/序/slug唯一，
  再走原decode/MemberDigest校验。Digests只取对象元数据，仍核块/根/存在性，不载大正文。
- 新格式缺块/对象、错scope/hash/count/order时`INTERNAL_ERROR`/500脱敏失败；配置不可用仍503。
  不能退回旧副本/当前Head掩盖损坏。只有未迁移且明确legacy格式才走旧路径；保留缓存键/深拷贝、
  header每次授权/退役检查及ETag规则。
- manifest、原MemberDigest、全部ID/epoch、candidate/decision/source/exact3指纹不变；不改审核、
  业务时间、专家锁、来源生命周期，不重新评审/激活/pin。新写两映射必须同根，不各自重建一份。

### 4.4 Publisher 的有序输入前提（后续明确裁定）

依据 [Owner确认](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/550#issuecomment-6668635086)，
`Publisher.Activate` 的成员必须按 materialize 的 Go UTF-8 slug 字节序严格递增；空集合仍合法。
入口在任何 DB 读取/写入、pin、决定或幂等提交查询前检查；无序或重复 slug 返回既有
`CANDIDATE_INVALID`，不悄悄排序，不改 manifest/准备数组以掩盖输入错误，所有写入0。
合法有序输入仍走原完整校验/事务/CAS/幂等路径。此为明确的内部 Publisher 行为收紧，不能宣称
所有旧调用行为不变；不改变外部 CandidateBundle 合同，真实 materialize 本已排序。
旧 pointActivation 测试 helper 独立适配为生产顺序，保留原所有竞态/回滚/决定/Head/pin断言。
新增独立反例锁住无序 typed 拒绝、无SQL/所有持久化状态不变及合法排序正控。

### 4.5 观察失败、记录缺口与计算缓存（PR557 R1/R2）

读取完整性覆盖存储哈希与生产方 decode/MemberDigest，不能只记底层块损坏。迁移13增加独立的
验证预约表和只追加失败表，两表均保存完整四段scope，**不引用/更新scope行**，不含正文或成员ID。
失败表的记录时间由数据库生成；同一预约最多一条失败，失败/记录缺口不因进程重启消失。

- 验证前在根连接池的独立autocommit登记随机预约，完成后成功删除预约；完整性错误或取消/SQL
  可用性缺口，以同一原子语句追加`integrity`/`gap`并删除预约。结果写失败则预约保留，ERROR只记固定
  类型，不输出数据库错误/正文。调用方事务回滚/取消不能撤销预约或失败记录。
- 嵌套的ReleaseByID→Read复用同scope预约，覆盖最终decode；作用域不同不得复用。预约登记失败
  时不开始验证，返回脱敏失败并ERROR，不能先读再假装没有记录缺口。无故障完整读增加两条SQL，
  新查询数仍须满足旧适配器2倍；成功预约不永久累积成逐次读取审计。
- Begin与维护门以四段scope帧化哈希对应的事务advisory锁串行化：开始登记取共享锁，维护最终检查
  取独占锁直至原事务提交；终结预约/追加失败不取scope行或该锁。因此激活的FOR UPDATE不会挡失败
  记录；维护不能漏过检查前已登记的读取。哈希仅作锁域，不替代四段scope查询/授权。
- ReferenceOnly/CompactLegacy同时检查旧`read_failures`、当前窗内失败事件和全部未完成预约；缺表、
  写通道不可用或任何未完成预约均失败关闭。门自身的验证必须在改变mode/删除旧行**前**完成持久
  成功结算，并探测失败通道，不能先提交再发现日志失败。StartObservation也拒绝未完成预约。
- 记录失败留下的预约没有年龄超时自动清除。恢复需另获运维授权：暂停该scope读取/维护并核对原
  进程已终止，逐个确认未完成预约；同一短事务按原四段scope和随机预约ID追加`gap`并删除对应预约，
  然后StartObservation重新全历史核验并从零开始七天。未确认归属/仍活动的预约不得核销。
  已完成的历史失败保留，重新开始只移动观察起点，不删除失败；迟到的实际失败按记录时点计入。

计算memo仅保留每成员原始七字段的帧化SHA256、规范内容storage_digest与独立克隆slug；不留原始
snapshot、payload/content或contentRow。命中还须同四段scope、父Release和数据库父索引；当前事务
仍核验全部复用内容的数据库哈希。缓存不是Head、提交或内容完整性的凭证；事务回滚后的条目不能
绕过数据库父对象检查。约100B/成员是含slug的目标量级，实测说明字节/分配与端到端耗时口径。

## 5. 迁移、并发与回滚

线上升级/整理/备份/空间回收必须另开运维 Issue，本阶段无执行。
**RestoreLegacy开始后该scope发布暂停，直到down完成并换回旧二进制；三个步骤放同一维护窗，
不能在还原中间恢复发布，也不回退业务epoch。**本设计采用**有退出条件的过渡**，
不是永久双存或新旧双 Head。

1. **expand**：冻结迁移 `000013_enterprise_member_chunks.{up,down}.sql`，包含scope/内容/块/根/两映射
   与迁移进度/格式表，head12→13；本轮核origin/main仍head12、开放PR数0，没有并行占号证据。
   这只是文档预留，不执行DDL。后续若发现冲突先协调，不私自改号。新增schema不动旧列；索引/
   约束的在线短锁步骤另列运维计划，不能把重型回填藏在应用启动里。
2. **短期桥接**：一个明确版本的应用，在原事务内同时保持旧快照和新对象引用；对外仍一个 Head。
   对新发布强制同时生成完整新映射，便于随后切换和二进制回退；这一阶段暂时增加而非释放空间。
3. **分批回填**：仅从既有不可变成员/明确已提交准备读取，按发布/行批次和字节上限断点推进。
   不整库长事务/长快照，不锁线上 Head。每个映射只有在对应完整集合验证成功后才标记可读；
   游标绑定scope/原行身份/完整列表摘要与批次，记录对象/块/根各阶段；重复批次只复用全字段相同内容。
   格式映射只在完整根验证的同一事务里发布；失败/中断的staged对象不进入读路径，也不自动GC。
   准备快照的完整内容/行版本需核前后未变，不能仅信
   PreparationDigest（它不覆盖 members）。draft/无可信提交关联的行跳过并报计数。
4. **核验/追平**：逐版本核四段 scope、全部字段、计数/唯一性、原数组顺序、manifest 对应、
   原企业 payload digest 与封套字节。Release 新 reader 与旧 reader 在**同一 DB**逐项/逐字段/逐序比较，
   不拿 Go 排序代替旧 SQL 真值。两个 Release 业务等价按唯一 slug→完整成员内容比较，不能比较根摘要。
   历史成员、引用、pins、retirements、receipt/决定总数和身份不变。
   校验进度持久化且可重复；增量新发布由桥接写保证，不只依赖 created_at 水位推断“没有漏行”。
5. **cutover**：读方按已验证的格式标记切新，未标记只读 legacy；新写转为 reference-only 前确保
   所有运行实例支持新格式。默认观察窗**7天**，部署运维可事先调整；退出硬条件为**全部映射
   验证通过且整个观察窗读校验失败0**。任一读校验失败先调查并重新开始完整观察窗，不能以
   缓存命中或平均错误率豁免。这不是历史保留期，不自动删除。
6. **退出旧副本**：全量核验、恢复演练、容量预检、观察期和 Owner 运维批准都满足后，才移除
   已验证映射对应的冗余旧大列/行；保留所有历史逻辑内容及旧准备头/manifest，未关联旧准备不动。
   只有所有原本可读 Release 都完成迁移后，才移除迁移用 fallback/双写能力；不能把未迁移的
   可读版本改为报错来完成切换。原已损坏的行报阻塞并保留，不静默遗漏或自行修复。

回滚：桥接阶段直接保留旧读写数据，但先停用新格式写入；reference-only 后须先用不可变对象/有序集合
分批**完整重建**旧成员行和旧准备数组，核摘要/顺序/企业身份后才能换旧二进制。
最终 down 仅停服后使用：同一事务锁定原头/成员及新表，核双向映射、完整内容/块/根hash、
旧成员七字段集合和准备数组原序，校验到DDL提交间阻止漂移。down 不得先 DROP 新表或
声称“空旧表也能回滚”；验证失败拒绝 down。整个恢复不改 Head、epoch、决定或 pin。原件缺失/摘要不符
仍报原 typed 错误，不能因数据重排恢复已失效来源。断点/结果未知先读进度和映射核对，不盲目重写。

容量峰值预检必须包括旧副本 + 新内容/引用 + 回填临时索引/TOAST + WAL + 当前备份/其他业务空间；
没有这些余量就不做在线回填，改在另行批准的停写维护窗分阶段。DELETE/UPDATE 的 dead tuples、普通
VACUUM 可复用页与 OS/VM 真正可用空间分开报告；rewrite/VACUUM FULL/REINDEX 等另需运维许可。

可观测：记录按格式的版本/集合/对象/引用计数与字节、已核验/跳过/失败/待恢复批次数、查询/锁等待与
超时、完整性错误计数、桥接期新旧对照差异；关系/TOAST/索引、WAL、备份和文件系统各自列账。
指标/错误日志不含正文、凭据或对象原文。共享对象受损会影响引用它的多个历史版本，必须完整验证、
失败关闭并从经过核验的备份修复，不能由另一个 tenant/Scope 或“相似文本”补齐；修复另走运维授权。

## 6. 未来 RED 定量矩阵（M2，本轮不写测试）

### 6.1 增长隔离与边界控制

- N=3600与37500两个独立合成scope/同字节宽度身份，从同样局部分块布局出发；大的版本用普通
  追加流程在编辑邻域外增加整块数据，保留修改邻域及其外侧完整保护块；不按产品编号分派边界。
  两者修改同一连续125个slug、七字段变化完全相同：新增内容对象125，内容与被重写块的字节
  **必须相等**。只有根块列表长度可不同，差额≤`36×(floor(37500/32)+1)=42192 B`；固定根头/映射
  元数据宽度相同。若出现按N复制的条目/块则失败，不用物理压缩掩盖。
- 这条对照隔离的是远处总量，不把“任意散布125键”假装同邻域。另以随机散布125键验证
  `W≤125×128`、只改值最多125个块；报告实际块字节，不能声称它与连续125键同成本。
- 插删（首/中/尾、删切点、无自然切点、密集自然点、32/128边缘、空集/短尾）验证局部窗口界
  `Wa≤K+4J×128`及外部块地址不变；最小/最大强制点不向全表传播。初建自然hash/强制点另锁，
  修改路径不能偷偷从头重分块。不同历史布局可异根，但每次同父输入确定且内容一致。

### 6.2 规模、完整历史、读取性能

- 300款×125成员，按slug分组的合成通用键序逐款激活；再10轮，每轮固定轮换10%产品，修改其全部
  125成员（每成员只生成一次新完整身份、每款一次激活）。另有多类型/不连续键控制，不能把本夹具
  的局部性推广为所有输入。统计**所有唯一内容、块、根、scope及两映射的全部逻辑列字节**；集合
  结构总字节≤内容对象总字节10%。包括根块列表/元数据，不能只报块blob；不包括PG压缩/索引/WAL，
  这些单列实测。内容对象统一5KiB（含身份/列元数据）的合成尺寸，不能用私有大正文抬高分母。
- 同夹具用旧格式序列化/列宽计数器给完整历史出现次数与旧两份数据对照；无需实际存数百GiB旧
  重复数据。计数器复用旧格式逐对象字节长度并按各历史成员出现次数加权，准备数组标点/转义亦计；
  模型中的`2×内容字节`只是近似，未来报告必须给实际旧逻辑列计数，物理尺寸另列。
- 每个历史Release（上述600次激活）冷缓存还原，七字段和原序逐字节对旧格式真值比对；同时覆盖
  历史准备异序/空kind与page、PDF/Office/专家引用、退役/Source pin和304，缺块/错摘要必须失败。
  逐版本流式验证、限制峰值内存，不把全历史旧payload复制到DB，不靠热对象缓存掩盖缺失。
- 采集未来基准：隔离合成PG环境、同硬件/schema/数据与连接池，N=3600/37500分别比较冻结旧适配器
  与新生产Read链。冷应用成员/对象缓存（不用清生产DB缓存），ABBA交替30次，记SQL数、全读字节、
  wall-clock p50/p95；DB缓冲状态和预热步骤两侧一致。两档**查询数、p50、p95各≤旧2倍**，否则失败，
  不能标成“需要上线观察”后放行。此轮无基准实测，RED/实现阶段采集，不恢复线上副本跑基准。

### 6.3 必须保持的保护矩阵

| 类别 | 反例/正控 |
|---|---|
| 内容/块/根身份 | 同文异metadata/version/refs/access/kind/slug/revision/title不合并；数字/JSONB/Unicode/空白保持业务hash和原字节；同键异字段冲突拒绝 |
| 隔离/结构 | 四段scope、缺对象/块、count/长度/序/hash错、重复slug、根块列表截断；不同scope同摘要不串用；无变化与prepare/Release同根 |
| 历史/准备 | 全历史、pinned/retired、冷缓存、manifest/custody/replay/rebase/回退及详情不变；draft/未关联ready不精简，历史两套集合可逆 |
| 并发 | 同nonce/同候选不同决定、点批量/整包、独立rebase/同实体冲突、初始Head、各事务故障点保持CAS与全回滚；分支读不依赖父链 |
| 迁移/回滚 | mixed格式、重入/断点/源漂移、桥接时发布/退役/重放、映射未完整不得标完成；ref-only先完整恢复旧行/准备数组再down，坏对象/容量不足拒绝 |

完整PG适配入口和原公开合同均需覆盖；不改旧保护断言遮错、不新增skip/xfail。定量增长先按逻辑
字节验收，不将其等同物理压缩或VM释放；线上迁移前测量另过M3门。

### 6.4 两层执行（Claude 后续裁定）

依据 [两层CI裁定](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/550#issuecomment-6667872744)，
常规 postgres job 保持20分钟，不删除上述全规模门。相同参数化测试默认用375/3750成员、
30款×125字段、逐款30次+10轮每轮3款，共60历史；每次局部仍改125键，内容仍5KiB。
小规模局部变化起点64，全规模保持500；散布125键步长分别30/299。32/128等结构边界不缩。
小规模根列表差额上界为 `36×ceil(3750/32)=4248B`，完整规模仍42192B；内容/新块相等断言不变。
两层都计全部结构列、旧格式实际列/数组文本，比例≤10%；每历史冷缓存七字段+顺序相等；
各自两档读取仍ABBA15、30次、SQL/p50/p95≤旧2倍，不能用小规模数据冒充全规模。

`ST1_SCALE=1`明确选择原3600/37500与600历史；非法值测试失败，未使用skip/xfail。
常规CI始终跑小层及完整迁移/回滚/CAS/安全保护；仅 workflow_dispatch 的独立90分钟job跑完整层。
合并前必须在该手动作业或本机隔离PG完整通过一次全规模并附环境、全部字节、资源/时间与限制。
此执行预算不改变线上迁移许可，不再把常规job延至60分钟。

## 7. 阶段与拟写域

调查/修订阶段只改本 Spec、[附录A](ST-1-附录A-容量与测量.md)及仓库外证据。
r2 已获确认，当前 RED→实现→PR 的写域：自有 `internal/enterprise/releasestore/` 及必要成员存储子包；既有
`internal/application/repository/wiki_release.go`、`internal/types/wiki_release.go` 的存储接缝；
`migrations/enterprise/versioned/000013_enterprise_member_chunks.{up,down}.sql` 与
`internal/database/enterprise_migration.go` 迁移头；自身测试。
三处既有扩展文件在固定上游 `f17ee8a8d` 不存在，不新增上游 patch 数；新模块只在自有 enterprise 路径、
≤500行；端口与迁移号已在r2冻结。独立RED在Claude确认M1–M3后写，原公开方法签名保持；Publisher 输入前提收紧见§4.4。

不改 Harness、编译身份/值协议、contracts/前端/导航/领域规则、蓝图或守卫/基线；不删除审计或
修改 Source 生命周期；不把未来存储实现混进本次 Spec 提交。

### 已确认的阶段门（M3）

既定a+b、完整身份/四段scope、唯一Head/同事务、历史与审计保留、不做年龄GC已获确认，不重新
申请这些方向。Claude 已明确确认M1结构共享/布局取舍、M2定量标准与新公式、M3测量门位置。

完整重叠率/U0/目标物理大小是**线上迁移前门**，不是设计确认后RED/实现的前置；工程可先用合成
数据做。本轮 RED/实现另有明确授权；它不包含任何线上部署/回填/测量。
当前不测线上DB/Docker、不恢复541副本、不与549编译/摄取争资源。线上迁移/空间回收与部署仍另开运维。

r2 阶段快照中的等待确认已由后续实施授权解除；r3 仅修正读序事实，不改变定量门槛或本轮线上禁令。

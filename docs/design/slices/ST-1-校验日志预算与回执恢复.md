# ST-1 校验日志预算与回执恢复

状态：2026-11-06，Codex 实现 / Claude 审核；Refs #559。
依据：[Owner工程意见](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/559#issuecomment-6683777934)、
[判断授权](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/563#issuecomment-6683373299)。
本片修订主 Spec §4.5 的日志预算及未知回执处理，其他 ST-1 存储、观察与维护不变量保持。

## 1. 问题与范围

隔离彩排两次在维护 probe 返回前失败，而读回发现本次 probe 已提交、对应还原事务没有提交。
第二次外部诊断确证 `*pgconn.errTimeout` / `context.DeadlineExceeded`，耗时 2.001954 秒；
不能把 RowsAffected=0 当作未提交。副本 checkpoint 曾有单文件同步 10.616 秒，但它不等于
该 probe 的具体等待时间；15秒是有界默认选择，不保证消除更长尾延迟。

只增加有界配置和精确回读，不重发日志写、不生成第二 attempt，不关闭同步持久性，
不以重试/清预约/删事件/回拨观察起点掩盖失败。仅加长预算仍不能处理回执未知；仅加回读仍会
频繁触及旧2秒预算，故两者一起落地。

不改 Member 七字段/布局/业务摘要、Head/CAS、发布或来源生命周期，不新增外部合同、领域规则、
上游补丁、依赖或数据库迁移。现有三方法存储端口及 Validate/维护方法签名不变。

## 2. 配置与调用上下文

- 环境变量 `ENTERPRISE_MEMBER_JOURNAL_TIMEOUT_SECONDS`，未设置默认15秒。
  只接受规范十进制整数1–60；空串、空白、符号、前导零、单位、小数、越界/溢出均非法。
- Store 构造时解析并保存本实例策略，attempt 再持有同一不可变策略；异步 RetainValidation
  与嵌套验证不能在结算中途读出另一个配置。非法配置使需要日志的入口在预约/业务读取或写入前
  返回原 ErrState 并记固定 ERROR，不回落旧2秒；明确 legacy/bridge 的正常只读入口仍不依赖日志。
- 记配置预算为 W，回读/格式补查预算 R=min(W,5秒)。每次持久写最多一次 W，若结果未知再做
  最多一次 R 的只读对账；不循环轮询、不补写。无错误时不额外读回，正常 SQL 数保持。
- 日志及对账仍使用独立根连接池、context.WithoutCancel 加自己的 deadline；调用方原 context
  继续控制业务读取/事务，不能借恢复日志回执把已取消的业务变为成功。
  admission+terminal 的额外时间上界为2×(W+R)，格式失败补查再至多R；默认分别40/45秒，
  最大配置分别130/135秒。这不改变HTTP/调用方 deadline，结算可能有界地晚于客户端取消。
- 已进入 singleflight 的取消调用方仍及时返回；后台租约持有到真实解码结束，再按原协议结算。
  不在持有全部业务连接后才创建额外日志连接，不改原锁序或连接池限制。

| 真实入口 | 使用策略的位置 |
| --- | --- |
| Validate / Put / Backfill / 激活 | admission、最后一次 terminal；同scope嵌套复用原 attempt |
| ValidateRead / Read / Digests / ReleaseByID | 只有观察中的新格式预约，生产 decode/业务digest包含在租约内 |
| StartObservation / ReferenceOnly / CompactLegacy / RestoreLegacy | admission及首次业务修改前的同步probe |
| RecordReadFailure | 固定scope/Release的有界格式补查R，确认新格式后沿同一日志策略记原失败 |
| RetainValidation | 异步工作沿原attempt和原策略终结；不另建票据或重算失败分类 |

标准 I4 换装脚本增加同名 managed env：设置值同样仅允许1–60；非法值在触碰容器前拒绝，
后续普通换装保留当前值，公开摘要仅键名/既有指纹。未显式配置则用镜像内默认值，
不能为配置它手改不受管 env 或覆盖镜像 contracts。
无当前容器/可信记录或记录属于别处时，仍按原安全规则要求每个managed key显式set/unset；
不豁免新键。旧成功测试夹具只为新键补显式unset，独立提交，原断言不变。
若曾显式设置新键，回滚旧App仍使用本片换装工具并显式unset该键；旧换装工具会拒绝含未知键
的记录，不能为绕过它手改/删除意图记录。默认未设键的既有记录保持v1省略语义，不另迁移。

## 3. 未知回执的证明

只有返回了错误且不能确认为服务器明确拒绝的写入，才进入一次回读；例如 deadline、连接断开
可能已经提交。明确数据库拒绝（如权限/约束拒绝、序列化失败、死锁、锁超时、服务器确认取消）
直接失败关闭；不能把“存在SQLSTATE”当确定拒绝，连接类或40003完成未知等仍须对账。
不在已知确定拒绝集合中的错误保守视为未知；无错误但影响行数不为1也不冒充成功。
影响行数在有错误时不是提交证明。回读成功只恢复“日志写已完成”，不改变原业务错误。

用原 attempt_id 和完整四段scope，在单条只读SQL的一致快照中读取预约与终结的全部身份字段。
不读正文/成员，不只按 attempt 或 Space 判断。结果还要逐字段字节相等核对，终结 kind 必须精确；
不存在、查询失败、跨scope/attempt、仅预约、错误kind、同时存在两者或其他不一致都不能成功。
同SQL另核该attempt在两表的全局存在性布尔值，防止scope过滤把同attempt的异scope矛盾记录隐藏；
只返回全局存在性，不返回他scope身份或正文。任何全局存在性与本次投影不符均拒绝。

| 本次写的预期 | 回读唯一可接受状态 |
| --- | --- |
| admission | 本次预约身份完整相同，终结不存在 |
| integrity/gap终结 | 预约不存在，本次终结身份完整相同且kind等于本次原分类 |
| maintenance probe | 预约不存在，本次终结身份完整相同且kind=probe |
| 普通成功清理 | 正常ACK且影响1行才成功；未知回执即使两表都无记录也不能证明成功 |

普通成功清理原本是异步持久性的 DELETE，没有持久终结回执。不能把“两个表都查不到”改成成功，
也不为消除这类保守失败新增永久逐次读取审计。它仍按原合同记ERROR/返回ErrState；已实际提交的
成功清理可能没有遗留预约，这不等于已知完整性失败被删。其他失败/未知记录继续阻止维护。

实际 admission、integrity/gap 和 probe 保留语句事务的 synchronous_commit=on；普通成功清理
保留原语句局部 off，仅其丢失会使预约复现并保守阻止维护。任何设置都不泄漏给后续业务事务。
回读不补造事件、不删除残留预约、不自动重启观察；未知仍停报并按运维进度对账。

并发约束：日志表仍不引用/更新scope行；维护门仍持有原四段scope对应的advisory独占锁直到业务提交。
回读只读独立日志表，不索取scope锁。a.done/refs/kind仍在原互斥协议中决定，每个终结只尝试一次；
读回的 kind 使用该次不可变预期，不能采信另一个验证的成功。旧读、错误码和脱敏语义保持。

## 4. 写域与职责

| 路径 | 改动 |
| --- | --- |
| `internal/enterprise/memberstore/journal_config.go` | 私有预算策略/规范配置解析 |
| `internal/enterprise/memberstore/journal_receipts.go` | 单次有界执行/精确回读证明 |
| `internal/enterprise/memberstore/validation.go` | admission/终结接入预算和证明，保留现有租约/锁/日志语义 |
| `internal/enterprise/memberstore/validation_ports.go` | 固定Release格式失败补查使用同实例策略 |
| `internal/enterprise/memberstore/records.go` | Store保存私有策略；不改现有公开方法 |
| `deploy/local-live/swap_app.py` | managed env校验/后续换装保留，仍≤500行 |
| memberstore/releasestore 新测试文件 | 配置/公共PG链路/结果未知反例与边界 |
| `harness/tests/service_shell/test_swap_app_journal.py` | 无Docker的合成标准部署入口验收 |
| 同目录既有`test_swap_app*`必要成功夹具 | 仅独立补新managed key的显式unset，不改原断言 |
| 本Spec、主Spec §4.5引用 | 独立文档提交；实现后冻结 |

不改迁移13/新增迁移，不删改旧验收断言、蓝图、contracts、架构守卫/基线、字段卡、Harness产品逻辑、
Go上游或前端。确需既有夹具增加新行为的期待，必须独立披露，不删/放宽原断言。

## 5. RED与验证矩阵

新RED独立提交，旧实现须因行为而失败，不能以新私有helper缺失/编译错误代替反驳：

1. 真实PG admission已提交，测试边界在执行后回传deadline/RowsAffected=0；用独立连接先证明提交，
   再经真实ReleaseByID新格式路径成功。原attempt只写一次，不能重发创建第二身份。
2. 真实维护probe同样“提交后回执超时”，公共StartObservation/ReferenceOnly/RestoreLegacy至少
   两种入口能够对账后继续；mode/旧行变化只能在可靠确认之后。
3. 实际未提交、回读失败、只有预约、错误kind、跨scope/attempt、同时预约和终结、两表均缺失：
   本次操作仍拒绝，维护不改mode/删旧行。记录故障ERROR不含原始错误/SQL/参数/内容。
   同时存在的负控含“精确本次预约+同attempt异scope终结”，不能被scope过滤隐藏。
4. integrity/gap终结的回执恢复不吞原业务错误；记录保留、观察门仍拒绝。
5. 普通成功清理回执未知且两表均无记录仍拒绝，正常ACK成功正控保持。
6. 默认/自定义预算通过真实执行context观察；配置超过旧2秒的合法慢语句可正常完成；非法值在
   业务及预约前拒绝。异步/嵌套仍用原策略，原调用方取消/回滚与记录完整性保持。
   含admission已提交但恢复时调用方取消，业务不能成功；probe恢复时业务context已取消，事务仍回滚。
7. legacy和bridge在不可写日志/非法日志配置下仍正常只读，PG驱动实际SQL写入观测为0；
   chunks/未知格式不能降级或绕过预约。既有取消、并发激活、decode/业务digest、维护门回归保留。
8. 标准换装入口接受/保留合法managed值，非法值拒绝；旧其他配置和contracts不变。

PG提交后回执故障只能在测试适配器中注入，且必须在真实写结束后独立证明该attempt已提交；
生产代码不加测试钩子。配置测试不使用真实私有数据或业务ID。

本地运行受影响Go/PG、相关service_shell测试、ruff/mypy、架构/合同必要检查及diff检查；
不重复600历史/全量build。全量PG17/ParadeDB及其他组件以精确head CI为准，主机PG15证据单列。

## 6. 实施计划与运维衔接

- [ ] 独立Spec提交并推送；设计检查只读，不重复请求已授权的方向确认。
- [ ] 独立RED提交/推送，执行旧实现、保存预期失败和正常正控。
- [ ] 实现最小配置/回读/部署接线，冻结RED；必要自有测试事实修正另提交披露。
- [ ] 受影响验证、合入最新main（不rebase）、开Refs #559的PR；Claude审合，不自动关闭运维Issue。
- [ ] 合并后从已验证备份新建隔离副本，以实际合并SHA完整演练；旧半还原副本已清理，不能复用。

旧副本的118已还原/115未还原及两次维护通道失败证据保留；不把主动边界停止当第三次产品失败。
新副本必须完成迁移→Backfill→全映射/逐集合核验→StartObservation→20历史真冷对照→正常短窗/
真实等待→ReferenceOnly→CompactLegacy→RestoreLegacy与读回，才继续最终容量峰值+25%及线上部署。

#559线上观察配置仍为86400秒，完整主动核验/零失败零预约缺口及原维护门通过后，ReferenceOnly→
CompactLegacy已获预授权。不得改时钟/删事件穿门。线上变更仍与其他运行任务实际无在途交接；
本PR不部署、不触线上DB/模型/QA/评委/embedding。数据丢失风险或线上故障仍交Claude介入。

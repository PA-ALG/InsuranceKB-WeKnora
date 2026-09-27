# G3.5 R6：完整多窗口增量依赖闭包与一次重审

Owner root；基础12fae12319149e3bd4880a27919bc3b1dfac252e。用户已授权G3.5全项，
继续采用Deep Modules与Tracer Bullet；质量/覆盖度语义调优后置。
本页为原R6的实现设计，不新增产品Goal或另一套审核/发布权威。

## 已有能力与边界

原生collect_native_discovery为每个成功窗口保存一个snapshot；完整性必须为全部计划窗口
成功。原v2/v4 admission投影已有单窗口v1 selection，处理candidate depends_on、
共享member与page→definition、环/孤定义固定点。现normal pipeline只允许单窗口
isolation，final review组内任一成员不通过则整组不发布。

本纵切只支持同一材料、同一实体和版本、全部窗口完整、普通page/definition。
未知/缺失窗口、多实体和typed business_relation保持整组围栏。不是任意跨窗口语义发现；
模型candidate依赖仍只允许本窗口，wire也禁止跨窗口member_ref。page→definition
先在各窗本地解析；仅当这些引用解析到同一正式definition ID时，聚合图形成共享结构边。

## R6-AGG-1：服务端跨窗口闭包

新增native-dependency-selection.830.v2聚合合同，保存有序validated window dependency domains，
与v1 selector同源。多窗口保持原isolation_enabled=false模型输入不变，投影内部保留
原本已计算但未返回的domain及全部projected成员，供服务端聚合。单窗仍走原v1 selection；
不为取得selection把false改true，因此原成功多窗admission调用仍可按exact request复用。
完整context/raw/snapshot身份及局部member_ref→正式member_id/内容hash绑定。
domain和映射在native_admission的projected映射仍存在时显式导出至内部projection，
不向旧v1 selection加字段；恢复时由原raw经过同一preflight/projection重新派生。
局部candidate按window snapshot+entity命名空间，正式member identity全局稳定。
共享member的所有candidate owners为原子组；相同identity不同内容拒绝整组，禁止覆盖。
每个候选的review disposition ID与member归属必须显式记录，禁止解析字符串前缀反推。

从局部隔离种子开始，沿反向依赖传播，并执行未被保留page使用的新definition的孤项
固定点清理。聚合后保留的精确成员/候选/依赖边及原始隔离原因进入selection hash。
不得把来自失败或未知窗口的缺失视作空集合，不得裁剪Schema字段或已有发布正文。
旧v1 selection wire保持；新v2只由聚合模块构造和验证，不让调用者拼接内部图。
window namespace包含knowledge_id、parse_attempt、source_snapshot_sha256、window_id、
snapshot_sha256与entity_id，不用数组下标。

## R6-REVIEW-1：精确审核与最多一次局部裁剪重审

新增review context v10，复用现有dependency review prompt/purpose（不改全局model-policy），
沿原StageCall executor与JobStore。完整各窗context/response留审计，模型只见经验证的紧凑
aggregate视图及本次必需原文；上下文变化由输入/完整request hash约束。
初审完整比较最终合成正文、原文、现有知识、v2聚合selection及全部明确disposition。
沿用现有评分与来源门槛，不为MODEL_GENERATED/某样本改分。

仅经完整schema/hash/scope验证的初审，且存在member score<80或某disposition的
REJECT/NEEDS_HUMAN时，才能生成机械局部失败种子。只有全局REJECT/NEEDS_HUMAN、
传输/schema错误、无法精确归属的理由，不允许猜测裁剪或再调用。
复用同一闭包算法剔除依赖项和孤definition；零survivor保留未通过终态，不重审。

有survivor时重新合成字段+原有成员+保留增量，计算新final hash；生成版本化
native-review-pruning.830.v1回执，绑定初审context/raw/proof、种子、裁剪闭包和新hash。
仅再进行一次独立审核。初审proof不能授权新集合；二审完整通过才发布survivor。
二审拒绝/失败不再裁剪，原字段与失败UPDATE的旧正文仍保留。

## R6-RECOVERY-1：持久、复用与唯一编排

新增artifact contract/version注册覆盖聚合selection、裁剪回执和初审原始记录。
初审未发生裁剪时沿现product artifact key；发生二审时初审转为initial:<final_hash>审计key，
最终唯一一次仍使用product key，避免API/compose误选两套final。
每次review以真实输入/完整请求/输出hash独立绑定，同一run重启不得重复发送已记录调用。
未知dispatch沿既有围栏，不以重试恢复名义补发。模型策略或实际输入变更造成的旧调用不兼容如实标记；成功原生调用按既有exact
StageCall复用，不在新scope/request间强行借用。

native_dependency_selection模块负责多窗口依赖域构造/校验/闭包；
discovery_review_compilation.py提供单入口compile_reviewed_discovery，封装初审、
裁剪、重合成和一次重审，返回最终delta与严格review证明。返回delta、review或None、drafts、state；pipeline只消费最终结果，
不要求上层逐步拼接；复用原merge_discovery_delta/compose_discovery_review及唯一Active。
discovery_stage保留一次review的唯一StageCall/校验/proof Owner，可抽出内部ReviewAttempt
以延迟artifact定名；summary与reviewed_discovery_delta仅有一份product。深模块不直接
持久化、不发布、不重新实现模型重试。不启用现有未提交coverage WIP，不增加队列或平台。

## 验证与交付顺序

1. 设计独审后冻结接口与write set；RED覆盖跨窗同名局部ref、共享member、内容冲突、
   依赖传播/环/孤定义、多实体/缺窗/typed拒绝、旧selection字节不变。
2. 初审A独立NEW、B失败UPDATE、C依赖B：裁掉B+C，二审只审A的新hash；保留旧B。
   反例覆盖仅全局拒绝不再审、空集合不再审、二审失败无第三次、旧proof不授权新hash。
3. 持久worker纵向回归覆盖checkpoint复用、未知发送、重启后仅必要review调用、
   surviving成员沿正常Candidate/Review/Active发布与来源可读。
4. 按受影响组件验证/独审/精确构建、可回滚交付，然后有界真实验证；真实未执行
   项记NOT RUN。不得以局部图算法测试声称R6完整完成。

### R6 独审修订（2026-09-26，revision1）

初审的无member REFERENCE处置也可能单独失败；此时新审核上下文改变但最终正文hash
不变。二审使用明确refined operation identity，绑定实际上下文hash，独立proof记录并由
replay custody核验；原首次/旧版本operation不变，不借唯一键冲突跳过二审。

v10审核输入按保留disposition的evidence source_ref过滤routed sources，并重新验证全部
原文引用；二审按新disposition集合再次构造同一视图。成员自身provenance引用仍完整
保留，原所有窗口context/raw仍在aggregate审计。不得用提高预算替代剔除无关原文。

### R6-ROUTE-1：聚合资格不得误吞旧多材料单窗路径（2026-09-27）

CI收口发现旧三材料恢复fixture被错误路由进单材料多窗口聚合：三个window_id=0、
window_count=1的snapshot触发source window coverage mismatch，恢复点退回discovery。
旧typing前fixture同样失败（29.36秒），这是通用coordinator回归，不能改旧fixture断言。

聚合深模块复用同一source-window校验提供纯组分类：aggregate必须至少两窗、exact同scope/
knowledge/parse/source snapshot/window_count，窗口0..n-1完整、snapshot hash唯一。只有每份材料各一个完整单窗、
材料ID不同且scope一致才返回independent；其余invalid保留原FAILED围栏，不能降成PENDING。
pipeline在完整collection/无失败/全部材料绑定基础上，仅同一实体版本且每个非空窗口
恰有一个admission group时选择该能力；不同材料的独立单窗保留原逐窗准入路径。
最后聚合校验不放宽；不吞聚合失败、不扩大到跨材料聚合，不改变模型输入或checkpoint。

root唯一写者；实现写域native_dependency_aggregate.py、native_pipeline.py；新增纯资格
反例测试，保留旧两项wire升级恢复回归及现有multiwindow worker。软件独审后只构建和
替换Harness（沿原回滚部署），不重跑已闭合业务/逐case模型。App/UI/config/Head保持。

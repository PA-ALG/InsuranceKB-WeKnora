# G35-R4 现有实体与正式关系能力核验

核验源码：`47c0c6af6a3d104a337c22cd48983ae829d469f8`。root负责后续实现；`r4_reuse_boundary_review`在同一冻结身份独立只读复核。本文为设计/范围证据，不是已完成实现，不改变线上配置或Active。本轮模型调用、构建、部署、业务写入均0。

## 已证实的边界

| 既有模块 | 可复用内容 | 不能由它推导的能力 |
|---|---|---|
| `batch_entity_resolution_830_g3.py` | 已命名保险产品的身份/版本/原文校验、当前产品REFERENCE | 不能把保险公司或未命名险种类别按产品CREATE |
| `service_schema_catalog_830_g3.py` | 已审定的service_line、service_line_version、service_item字段定义及展示Profile | 当前是STRUCTURE_ONLY_NOT_PUBLISHED，不是已接通的服务实体解析/发布，也不是保险公司Schema |
| `entity_page_graph_830_g1.py` | overview/section/field/free_wiki页面与来源展示 | 页面导航拓扑不等于正式业务关系图 |
| 原生`graph.go`的Relationship、Wiki链接 | 召回、候选发现、导航 | 缺少正式主客体身份、版本、条件、Evidence、Review和Release绑定 |
| G2/G3 CompileOutput、PageMember、Go投影/发布重放 | 现有定义/字段/自由页和唯一Candidate→Review→Release链 | 目前没有relation成员合同，不能直接声称R4已完成 |

计划中的“复用既有Schema与实体图”应理解为复用各自已有职责；R4的正式关系仍需新增版本化成员并接入同一发布链。不得把关系塞进不受审核的metadata或wikilink，也不新建第二图谱权威或发布库。

## 推荐的最小正式关系切片（设计草案，未冻结生产协议）

1. 主体只使用当前已MATCH的具体产品及其可信EntityCompileBinding。
2. 未命名“提前给付型重疾险”作为普通类别/概念候选处理，不制造具体产品身份；仅在独立义项、价值及Evidence硬门通过后形成ConceptDefinition，也可能REFERENCE/PENDING/REJECT。
3. 仅在材料明确支持时形成产品到通过准入的该概念的关系；predicate必须表达材料实际支持的责任联动含义，不能用“相关”替代业务语义。具体predicate和值域须在原OpenSpec冻结，不能从共现推导。
4. 明确版本化的G3 relation extension或新合同至少包含：稳定关系身份、typed主客体、产品版本、关系含义、条件/例外/有效期、精确Evidence、增量处置。旧无扩展对象的canonical bytes保持。
5. 关系进入输出hash、独立审核、manifest member、Go精确校验与来源复核、不可变snapshot、唯一Release及读取/导航。关系正文和证据都参与审核身份；任一环节尚未接通即不得标R4 PASS。
6. 第一切片不新增insurance_company Schema，也不将服务Schema改名套用。保险公司实体及issued_by需要另行明确其身份、别名、版本、Schema/Profile与已有issuer标量的并存规则。

必要反例：同名不同版本、跨空间主客体、未命名类别误建产品、关系predicate与证据不符、丢条件、悬空客体、错误版本、关系修改后旧审核重用、伪造引文、失败更新破坏旧关系。原生图有边不构成通过依据。

## 与R6的先后关系

R4不是原计划预期的薄适配。建议优先完成已批准R6并验证非空知识完整链路，再实现上述R4合同；这不取消R4验收项。已向用户发出顺序选择，尚未收到选择时不记录为已获同意。

与顺序选择无关的R6设计约束已核实：旧native admission v1没有候选间依赖表达，不能简单删除整个组的失败围栏；新协议必须显式声明依赖，旧v1仍保守。依赖需覆盖共享成员/定义、环、更新和跨窗口冲突；移除未决项后仅保留依赖闭合的集合。旧页由既有增量组合器保留，不能把失败UPDATE写成删除。裁剪后重新计算最终候选hash并执行现有独立审核；旧集合审核不可授权新集合。未知响应不得重发、成功raw不丢、来源覆盖状态与可交付成员数量分开。

本轮仍无R4/R6源码实现、RED或真实业务效果。后续不能用本设计核验冒充软件/交付通过。

独立结果文档复核已完成：0 BLOCKER。本文及HANDOFF/执行计划的状态同步适用G35-R4/R6只读事实核验、审查和不改变行为的结果记录豁免，不另做RED；reviewer为r4_reuse_boundary_review。不得据此豁免后续生产协议/实现/部署的Spec、RED与独立审查。

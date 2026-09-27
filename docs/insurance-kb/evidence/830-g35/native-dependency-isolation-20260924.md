# R6 首切片：显式候选依赖隔离

2026-09-24；Owner=root；基线 87f73ea1b85b1c13beb886f27a9bf5f8b9859aa5，工作树 830-g35-knowledge-admission。用户“可以”批准 R6 先行。适用 OpenSpec 129 G35-R5/R6 首切片。复用原生 discovery、StageCall、现有 merge/review/checkpoint 和唯一 Release，无新数据库/队列/发布器。

## 当前结果与边界

- 配置显式 `candidate-dependencies.830.v1`，使用 v2 准入和新 prompt；省略配置保留 v1。
- 完整响应先验证成员、来源、版本、实体，再由纯模块求依赖不动点。显式边、共享成员、页面到新定义结构边及孤定义清理统一传播；健康环保留，坏环及依赖者隔离。
- 只有整次运行恰好一个完整 admission response/窗口/实体域才允许保留独立成员。多窗口即使调用成功也不推断跨窗口独立；失败、未知、未绑定来源、冲突继续整组围栏。依赖 REJECT 也不能绕过围栏。
- 失败 UPDATE 不进入 delta，原组合器保留旧页。完整 context/response/依赖图及回执保留，回执绑定来源快照、实体、窗口、原始响应 hash 和选择 hash。
- v6 独立审核看到完整隔离计划，只对保留成员评分，检查模型漏写依赖；审核绑定裁剪后真实最终 hash，新模板身份/输入身份阻止旧审核复用。
- 存在隔离项时摘要可保持 PENDING 并显示已通过成员；未验证发布时 published=0，仅 exact Release 验证后显示真实部分发布数量。没有独立发布器。

首切片不支持跨窗口最小隔离、审核失败后二次最小裁剪，尚无真实非空业务验收，不能宣称全部 R6 或 G3.5 完成。

## 验证矩阵

| Requirement | 实现 | 本地证据 | 状态 |
|---|---|---|---|
| G35-R5/R6 显式协议与保守兼容 | native_admission / configuration / native_pipeline | v1/v2、缺依赖/未知/自引用、单响应与多窗口围栏 | PASS |
| G35-R6 依赖隔离与旧页 | native_dependency_selection / 既有 merge | A未决、B独立、C依赖；共享定义、环、孤定义、顺序变化、失败更新保留旧页 | PASS |
| G35-R5/R6 完整计划重审与回放 | discovery / stage / composition / replay_metrics | v6完整可见性、隔离回执改动拒绝、旧prompt拒绝、审核拒绝/待人工、exact重放 | PASS |
| G35-R6 部分发布状态 | api | PENDING+accepted，发布验证前0、验证后N | PASS |
| G35-R5 checkpoint合同 | checkpoints / native policy | native_dependency_selection注册版本；既有原生恢复与policy drift回归 | PASS |
| G35-R5/R6 独立代码审查 | 冻结manifest | /private/tmp/g35-r6-review.json | PASS（0 BLOCKER） |
| G35-R1—R7 真实非空流程与质量 | 正常平台 | 未部署，未调用新模型 | NOT RUN |

RED：首轮新协议 9 failed（接口缺失）；接线 4 failed（整组清空/计数/配置）；完整边界 18 failed；拒绝前置项多窗口反例 1 failed。测试环境/路径错误不计 RED。
GREEN：核心原生/运行/审核回归 70 passed；扩展隔离、stage 与 replaymetrics 64 passed。两组有重复，不相加作为独立用例数。生产11文件 mypy PASS，改动文件 ruff PASS。日志分别为 /private/tmp/g35-r6-core-green.log、g35-r6-custody.log、g35-r6-mypy.log；冻结源码列表在审查 manifest。

## 交付维度

software 本地检查与独立审查 PASS；container health / provider probe / provisioning / local live / GitHub live 均 NOT RUN。本轮新增模型调用、构建、部署、业务写入 0；正式 Active 本轮未 GET。先前运行镜像身份不代表当前源码已部署。

私密离线配置：insurancekb-private-evidence/g35-r6-isolation-20260924/dependency-runtime.private.json；SHA256=624e393d4d98f50d079c8267a44020b9c79632c986184538b2af43158679286e。ProductRuntimeSettings 校验 PASS，较 exhaustive 准备配置仅新增依赖策略、替换准入 prompt hash、新增依赖审核模板；其他配置逐值一致，未应用线上。

本报告、HANDOFF 与计划仅机械同步用户已确认顺序和已有测试事实，申请文档 RED 豁免；不扩展部署权限。独立 Reviewer 已确认文档 RED 豁免；冻结源码和文档两份 manifest 末次复核 OK。

## 独立复核结论

Reviewer /root/r6_contract_review（gpt-5.6-sol high），只读：0 BLOCKER。单一 BACKLOG 为 selection 自哈希校验之外的图/闭包防御性重算；当前 selection 仅由服务端创建，原子持久化并有 payload/dependency/producer custody，无外部或模型写入口，自洽伪造内部对象不是可达发布漏洞。后续在既有纯模块加固，不新建验证平台。缺依赖审核模板或准入旧 prompt 的两项离线负例均被配置校验拒绝。

只读交付前置检查：现有 APP、DocReader、UI 正在运行，g3-platform-product-product-api-1 与 product-worker-1 均报告 healthy，Harness 显示镜像前缀 cfaa2155d630。此为旧运行环境的进程观察，未做新版本部署/健康验证，也未检查任务队列静默或当前 Active；切换前仍须按交付窗口复核。

## 真实展示纵切补齐与设计（同日后续）

用户继续要求 tracer bullet/deep modules。从真实页面反向核对发现 Go bridge 丢新摘要字段、Vue 仅 ACCEPTED 展示发布；追加同一Spec窄写域，先 HTTP RED 1失败及组件 RED 4失败/43通过，再补三可选白名单字段及 PENDING 已验证发布/待处理共显。Go `TestProductIngestionBridge` 定向回归 PASS，组件47 PASS；独立增量审查0 BLOCKER/0 BACKLOG，冻结 /private/tmp/g35-r6-display-review.json 7文件复核OK。旧Harness冻结源码未改。

既有质量收口计划新增“R6后第一条真实非空纵切设计”：明确8个责任模块输入/输出与失败边界，保持唯一发布权威；APP/Harness/UI各至多一次必要构建、DocReader与DB不变、静默切换及失败回滚。当前仅设计/软件验证与只读前置检查；不能视为已部署或真实纵切通过。

实际运行API/worker配置相同。准备配置与当前运行的差异仅field_template_id、templates、原生Purpose/粒度/依赖策略；字段模板v2对应此前field-boundary修复且hash匹配当前源码，模型/endpoint/凭据与scope不变。私密只读快照及安全回执位于insurancekb-private-evidence/g35-r6-delivery-20260924。

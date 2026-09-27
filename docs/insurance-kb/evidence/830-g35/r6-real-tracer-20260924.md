# R6 集中交付与首条真实纵切（2026-09-24）

## 结论

DELIVERY PASS；BUSINESS BLOCKED。源码 `37ae768ba3392d49ae389c5754f283d9a802e6d5` 已在既有本地 G3 环境交付；正常网页同文件任务 `33dd1349-e821-4d9c-b712-171e4fcb566c` 已实际运行并失败，未生成新正式发布。13:51:29Z 只读 GET 仍为 epoch17 / release-b8d07e76-da52-4446-9c37-fb6f8a1cb2d6。不可把本轮称为非空发布、R6 全完成或 G3.5 完成。

## 交付身份与验证

- APP、Harness、UI 各实际构建一次，均 PASS；DocReader/DB/向量库未构建，无 migration。
- APP image `sha256:93d296c0b17153049aa59a53f5a1da55792fad6cfb65e11685b5509cf18af00e`；Harness image `sha256:221e575cc6d89aa350de5a17cb0a99be0104db2762ee46773f32626241787b8b`。
- UI 静态目录 `/usr/share/nginx/html.g35-37ae768ba339`，index SHA `3a729c5c0a538ce9063bd46cf9afdbb68e277fa06d58ff83f5588f36a3c8c13a`。
- 配置 SHA `624e393d4d98f50d079c8267a44020b9c79632c986184538b2af43158679286e`；仅既定字段/准入/审核模板、Purpose、粒度、依赖策略调整，正式 Gemini 模型/endpoint/凭据保持原值。
- 切换独立审查 0 BLOCKER/0 BACKLOG，冻结 5 文件 SHA 匹配。10:48:03Z—10:48:25Z 一次切换 PASS：新容器 healthy、完整 Env/安全配置/挂载校验、精确 UI、Active 不变、队列静默、调用台账不变；旧容器和配置保留。切换本身模型/业务写入为 0。
- 软件验证沿 native-dependency-isolation-20260924.md；当前真实 provider 调用见下文；GitHub live NOT RUN。

## 真实输入、成本与结果

同账号/来源库正常 UI 单次上传同 PDF，SHA `d4c9611b7a0b0f59e9b37aef6ff0e5d12d42b00ba20daff670630f2d04e5c08a`，354102 bytes。平台复用已有 knowledge `90607f68-eaa7-4520-a66e-423c32865f7b` / parse_attempt1 / 7 页 / 18 块（6123 字符含重叠）。原件相同，但解析身份为历史完整 capture，不是 DeepSeek 原生基线的 17 块/5014 去重字符；比较必须保留此差异。

窗口事前冻结一次 UI 提交、无人工重试；参考 79 字段/8 窗口+身份1+原生发现/引用2+准入1+最终审核1，至多13次。实际8字段窗口、5字段发送，另外身份1/发现1/引用1/准入1：本次新模型发送共9次，均 recorded、无诊断错误；供应商报告 total_tokens 合计240067，未出现截断终止。最终独立审核未调用。UI 总调用12包含原来源处理回执3次（历史时间戳），不能作为本次新发送数；这一计数归属差异待单独收口。

字段26 verified /51 not_provided /2 extraction_failed；失败字段为 eligible_occupation_classes、special_coverage_and_exclusion_tags，均 FIELD_VALIDATION_FAILED。51不是已人工证明的“确实无信息”。模型输出14个原生候选；准入原响应拟保留11 definitions+2 pages，并将2个结构实体标为待解析，但严格投影失败，因此正式接受/发布成员为0。这些草稿不是质量通过的知识。

任务10:53:01Z启动、12:33:48Z失败；100分46秒包含宿主休眠，不可报告为正常处理性能。

## 根因证据

1. 准入不是模型断联。三处 evidence 的 quote 在指定 source_ref 中均唯一、逐字存在，但 start 分别97→91、136→129、156→149。当前严格投影因此报 original quote/offset mismatch。原始响应与调用成功回执完整保留。
2. root离线反事实只改上述三个整数后，仍报 foreign concept reference。两页填了 canonical_key（age_misstatement_handling、disclosure_duty），合同要求本响应 definition.member_ref。
3. 独立完整边界复核继续发现：即使再对这两引用做唯一映射，11 definitions中9个没有被页面使用，违反 definition lacks page use。不能自动造页、删定义或改decisions来“修好”模型内容；仅坐标修复不足以闭环。其余已复核成员归属/provenance渲染及索引覆盖正常；没有执行最终语义审核，不等于正文质量通过。
4. compilation 的3代 lease_expired 与 Mac 电源日志吻合：18:55:35+0800 Clamshell Sleep；18:58:15和19:40:49 Maintenance Sleep。唤醒后分别回收10:56:06Z、10:58:41Z、11:41:14Z已过期租约。睡前心跳loop delay为毫秒级，数据库正常；当前证据不支持为此修改心跳或放宽租约。

## 下一条设计边界

沿原质量计划新增“真实回执驱动的准入边界”设计；先做完整离线协议预检与针对概念页面职责的提示合同澄清，再集中交付。当前不继续真实重试，不激活旧候选。来源支持须精确定位，模型补充须保留标识，完整质量/18项覆盖与实际点击仍 NOT RUN。

完整私密回执位于 `insurancekb-private-evidence/g35-r6-delivery-20260924/`；包含原始响应/上下文/调用、部署、离线反事实与宿主休眠证据，公共报告不包含凭据。此报告与 HANDOFF/计划只作已授权范围事实和设计记录，机械记录部分豁免 RED；新行为尚未实现，须先冻结 OpenSpec 对应增量与 RED。

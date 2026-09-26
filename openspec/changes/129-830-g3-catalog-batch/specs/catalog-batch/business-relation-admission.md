# G35-R4-REL-5：原生准入正常生成接线

2026-09-26；继续已批准 G3.5 和 business-relation.md，root 唯一写者。
本切片只扩同一原生准入 wire，不新增模型 pass、实体发现器或恢复器。

## 输入、输出与身份

显式 wire `native-knowledge-admission.830.v4` 与独立 template/purpose `g3-native-admission-v4`。
旧 v1/v2/v3 输入 canonical 和接受域保持；未启用 v4 不展示也不接受关系提案。
复用 v3 evidence_refs 的既有展开能力；旧 NativePage/ResponseV2、v3 renderer/decoder 不扩域。
新增 capability 专属 page/response DTO（内部 v2 envelope），可省略 `relation` 字段
仅在带服务端 `product-concept-relation.830.v1` capability 的 context 下合法。没有能力的
context 即使收到字段也拒绝，包含显式 null 亦拒绝。能力进入 context/input/StageCall 身份；
checkpoint 继续复验原 execution policy/raw/request，不跨模板复用准入或审核。

关系提案只带 `predicate` 与 `object_ref`（同响应 definition.member_ref 或明确提供的
existing concept_id）。承载页 concept_refs 恰好是这个引用，stable_key 固定占位 `$relation`；
模型不得生成实体 ID、版本、目标 revision 或最终稳定键。服务器从可信 current binding、
最终候选定义和来源创建 typed business_relation；主体版本、目标 revision、稳定键由已有
领域模块计算。关系内容及条件/例外/有效期必须有原文，仍逐段 SOURCE_SUPPORTED。

NativePage 的普通字段保持，不因普通知识页与关系页共用原子成员而把两者语义混淆。
新版本 prompt 明确只有材料支持的责任联动才能提案；原生未命名类别可形成概念定义，
不能造具体附加产品。其他真正需实体解析的候选仍 REQUIRES_ENTITY_RESOLUTION。
审核上下文携带服务器冻结的 predicate 语义与完整关系 payload，独立 reviewer 核对原文，
不能将结构正确或原生 description 当作真实性证明。

## 增量、恢复与组合

- relation→definition 复用现有 concept_ids 结构依赖，不另起图。
- 首切片关系只允许完整单窗口依赖域，含 relation 的投影必须 isolation_enabled=true；
  最终关系审核必须有完整 dependency_selection 和 exact relation capability，无则拒绝。
- 历史 v7 已被早期 coverage 使用，当前 v8 仍为 coverage，故新增关系使用 v9；
  replay metrics 不得将旧 v7 映射为 relation prompt，v4回放须保持全部原 custody 校验。
- 同一关系 ID 的 UPDATE 必须 old/new 都是 typed relation，expected_revision exact，
  主体版本保持当前 binding 且与旧版相等。当前 G3 明确不支持同主体跨版本迁移；
  关系遵守同一限制，只允许正文、条件和证据等内容修订，不另放宽 projector。
- 普通页↔关系页的 UPDATE 永久拒绝；NEW 不覆盖旧对象。坏更新不改正式旧 Release。
- 当前 v2 dependency selection 的完整 context/response 均保存；回放验证也校验 capability。
- 包含正式关系的正常最终审核使用独立 v9 context 与 `g3-relation-discovery-review` purpose/prompt；
  无正式关系的输出仍沿原 provenance/dependency 审核选择；v6 的 bytes/prompt/replay 不变。v9 包含完整 typed relation 与服务端固定 predicate 释义，
  normal/replay/metrics 均绑定版本。本切片不得改 quality 门的结论。
  若深度 coverage 尚不认识该新增提案合同，配置必须明确拒绝组合，不能静默丢关系。

## RED 与交付顺序

1. v4 正常 preflight 生成新概念及同一原子关系；old v3 同 payload 拒绝；错误 target、
   无来源、capability 漂移、模型伪造稳定键均失败。
2. 既有 stage executor 实际派发 v4 identity；恢复 exact raw 复用；配置漂移不误复用。
3. 同关系同主体版本内容 UPDATE 成功/旧 revision 不符失败/所有页跨版本均拒绝。
4. 已有 compiler/reviewer/composition 接受该候选并生成完整 bundle；绑定 predicate 语义。
5. 独审后集中部署必要组件，在正常网页对既有材料有界恢复，真实非空关系发布、导航和
   原文回点分别记账。当前本切片 RED/实现/交付/真实业务全部 NOT RUN。

## 写域

新增 `product_ingestion/native_relation_admission.py` 封装 capability DTO、提案语义和领域绑定；
新增 `native_relation_wire.py` 负责 v4 wire，与 v3 共享提取后的 native_evidence_wire.py 纯 evidence refs 绑定原语；各自拥有
protocol/schema/原 envelope/receipt，不向 v3 wrapper 传伪装的 v4 envelope；
提取 `native_admission_contract.py`（旧 DTO/prompt 原样）和 `native_admission_context.py`
（可信上下文构造）使原投影模块小于500行，不新增转发 shim；
新增 `relation_review.py` 封装关系审核语义及 v9 prompt；
既有 `native_admission.py`、`native_admission_wire.py`、`native_admission_preflight.py`、
`native_admission_policy.py`、`native_admission_stage.py`、`native_dependency_selection.py`
做接口接线；只有现有配置检查/原 call replay 实际需要时扩到 `configuration.py`、
`native_call_replay.py`、`discovery.py`、`discovery_stage.py`、`discovery_composition.py`、
`discovery_replay_metrics.py`，新增定向 tests。已冻结 REL-1—4 代码不并行修改。
各职责深模块不超过500行，新接线若触及旧超限文件按该职责提取，不做全仓重构。

预算：软件阶段模型/构建/部署 0；真实窗口在软件闭合后冻结输入、模板和有限调用数。

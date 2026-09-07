# C MULTI 身份判断与自动候选资格分离：重新设计

状态：DESIGN_REVIEW_PENDING，不授权补丁。适用已有 G3-R4，原 Owner 两文件写域不变。当前 source commit68669f9e5、源码SHA e9158e1c707fdedc9e783947d51ab110ae706d3d37d656edb965f9d66f4d1425、test c601f77c23f8545f69cef02870af3f8fd9357845c16cf9e728f157b563650b47 暂时冻结。本次在一轮集中修复后回到合同设计，不延长旧复审轮或删除失败证据。

## 问题与原合同裁决

原 lane-c-batch-contract-draft.md 明确允许父 MULTI、子版本待审；amendment-1 第2项要求不同稳定实体key及独立有效name/code Evidence，没有要求所有子满足自动Candidate的version/classification/pack资格。当前 `_multi_children_valid` 调用 `_automatic_decision_valid` 过强。独立review已撤回B2 PASS，其余6项保持；39及56测试结果保留，但不能宣称C全合同PASS。

两个不同code、独立name/code依据且identity过阈值的产品，若只缺version，应产父MULTI+人工队列，两个子NEEDS_CONFIRM/VERSION_UNRESOLVED，Candidate均null。官方source21仅是此真实输入形态的来源候选，实际SourceRevision/model尚未运行，不冒充真实MULTI结果。

## 最小合同

1. 维持 `_automatic_decision_valid` 以及 MATCH/CREATE 的身份、版本、发行人、双阈值、pack、Evidence/trust规则完全不变。仅分离父级“含有几个不同产品”判断。MULTI仍为人工队列，不能自动变成Active或替孩子创建Candidate。
2. `EntityDecisionV1` 新增两个必传集合（允许空tuple，排序去重；wire显式[]而非omitted）：`multi_identity_name_evidence_ids`、`multi_identity_code_evidence_ids`。纳入decision及上层hash。禁止通过ID前缀、模型自报purpose或新的布尔/成功reason来冒充验证。
3. resolve从同proposal已经引用的identity Evidence中提取两个集合，分别要求purpose=name/product_code、proposal_ref匹配、exact source/quote/offset/manifest有效、规范化anchor与对应quote匹配、对应identity TrustRule有效；必须复用既有检查，不因classification/version失败而跳过身份Evidence校验。任一source/scope/model全局失败，两集合均为空。有效ID必须仍在该child.evidence_ids中。
4. 一个child可作MULTI身份簇的必要条件：非QUARANTINE；name/product_code anchors非空；identity confidence>=identity threshold；两个有效集合各非空；无来源/scope/model错误，无IDENTITY_ANCHOR_CONFLICT/EVIDENCE_JOIN_FAILED。name/code缺失或无有效Evidence由对应anchor/集合直接判定；通用IDENTITY_EVIDENCE_MISSING若仅由issuer缺失产生，不取消父MULTI。issuer缺失或共享仅保留child人工状态；可信issuer冲突仍veto，MATCH/CREATE issuer规则不变。`VERSION_UNRESOLVED`、classification低阈值/pack未解析本身不取消已成立的身份簇。不能因为这些原因而跳过name/code的信任校验。若对应name/code目的的TrustRule失败，该目的集合不得填入有效ID；version/classification目的的trust失败不得清空已经有效的name/code集合。
5. 稳定簇key只取当前scope+normalized product_code。同key多个proposal至多一个簇，不因名称、版本或重复行增加数量。该key内部如存在可信的互斥name/code身份，则不得作为合格簇；缺version不会造成身份冲突，version竞争保持子人工状态。exact-input resolve还必须按canonical Evidence occurrence（完整SourceIdentity、block/page/start/end/quote_hash，忽略evidence_id/purpose/proposal_ref别名）验证跨不同key簇独立性；同一locator/span换ID不得增加独立证据。发生这种跨簇复用时清空受影响簇的上述有效集合，使父/单参wire统一不计这些簇；保留原证据/child理由供人工查看，不能改写quote或伪造新locator。至少两个合格key、原始occurrence独立且其有效name/code ID集合互斥，才得到父MULTI/MULTI_ENTITY_REVIEW及具名人工队列。共享发行人或通用分类依据不取消不同产品的独立name/code证据，不要求整个SourceBlock独占。
6. parent判定与wire validator必须复用同一纯MULTI资格函数，不能resolve接受而validate拒绝。单参wire验证两个集合的canonical/subset/nonempty/跨簇独立性、anchors/key、阈值、阻断状态；不能宣称仅凭ID重验外部purpose/quote/TrustRule或不同ID实际指向不同locator/span。任何完整外部语义检查仍在resolve(exact inputs)及D build重算/既有来源复验中完成。
7. 两个集合为此次唯一wire扩充；不改自动Candidate ID/key、classification assignment、阈值、PolicyReceipt、Catalog、Profile、serving状态。D只消费父MATCH/CREATE/MULTI中的自动合格MATCH/CREATE子；父NEEDS_CONFIRM/QUARANTINE中的子全部不得进入D字段编译。父MULTI中人工子也不得进入D字段编译。G3 v1尚未对外部署，此次未发布合同更新需新fixture/hash，不重写历史输出/日志。

## RED与实施边界

独立设计review通过后，由原Owner新写针对当前冻结源码的行为RED，先保存原日志再改两文件：

- 两独立name/code+缺version → 父MULTI，子NEEDS_CONFIRM且Candidate null。
- identity合格但classification低/pack未解析 → 父MULTI，子仍人工。
- identity低、name/code purpose/trust/quote无效、跨proposal证据、同code、可信互斥身份或共享name/code Evidence → 不计虚假MULTI。
- 同一Block独立产品quotes允许；共享或缺失issuer/classification但name/code各自独立允许；同一locator/span别名为不同Evidence ID必须不计MULTI。
- 两个集合 omitted/duplicate/unsorted/non-subset/跨key共用，及层层rehash伪造 → wire拒绝。可自洽替换为另一现有ID但无法仅wire证明purpose的情况，要由exact-input resolve/D build拒绝，不伪称wire能证明外部事实。
- 原39 checks不得删减；A/C联合检查、ruff/strict mypy与独立复审有界执行。旧自动候选公式/身份证据隔离/日期/receipt/去重/B1/B3–B7回归保留。

本重新设计只解决明确的身份簇语义，不做推测性重构。若再出现同域基础合同问题，停止继续修补并由总控重新拆分设计；不得更换真实材料或预期标签掩盖失败。模型/上传/DB/部署/发布仍NOT RUN。

## 设计复核修订记录

原设计SHA ba40d6cb85e02c4be901ae9eee6262566977a27925f511e14f0355591dae1f81 被reviewer指出2项BLOCKER：issuer非空过强、ID互斥不能证明locator独立。总控在实现前按上述规则修订；没有改C源码或旧测试。

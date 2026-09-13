# G3 两款新产品增量流程实施计划

> 执行采用 existing G3 独占 worktree、TDD 与有界独立复核；用户已明确要求挑两款新产品跑流程，此前合理 Gemini 调用、本机来源导入、签名/发布授权持续有效，不重复发起授权。Owner=root。

**Goal:** 在当前 epoch9 的 7 产品上增加福满分1820（年金82字段）与爱满分1818（两全79字段），保留旧结果与证据，实际执行新增材料的流程。

**Architecture:** 沿用唯一 WeKnora Release 与 Harness Candidate。首页正式名称复用 g3_title_routing 决定 Schema，身份/备案独立核验；C 的 native 页映射先选择首页，完整来源块保留给 D。旧 C 真实回执与新 C 真实回执组合重放，不重新调用旧材料模型。已有字段机械继承，仅新增字段调用分组抽取/审核；拒绝损坏旧字段/来源/跨实体混用。

**Tech Stack:** Python 3.12 Harness、现有 Go API、Gemini 网关；embedding保留原Qwen，rerank不变。DOCKER_ACTION=REUSE，只有影响APP的必要代码变更在定向验证通过后 BUILD_AFFECTED，不重建UI/数据库。

## 范围与已复现缺口

输入：/Users/houjing/Downloads/shouxian_product 下两款各条款、说明书、费率表共6PDF，exact清单在 /private/tmp/g3-two-products-20260913/source-selection.json。条款首页含1820/1818及平安人寿〔2025〕年金保险142号/两全保险140号。当前正式名称路由已覆盖两个名字，模型调用0可得到正确Schema。

已确认旧 PUBLISHED_G3 base 要求 existing==all，不能添加实体；C reuse只支持单源链；旧上传工具限定15材料且embedding仍指向旧一次性19030代理。这些是本次增量流程的真实阻断，不伪称现有入口可直接运行。

## Requirement / 写域 / 步骤

- G3-INC1：既有实体快照完整且可验证，允许新实体作为增量；旧entity/version/字段不得丢失或变更；普通来源核验、同版Catalog/Profile与Head CAS继续执行。
  - Owner子lane：harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py、对应tests；internal/types/concept_free_wiki_830_g3.go及tests；如service父版比较确有必要，先报告root再列精确函数。
  - [ ] 在当前epoch9已发布快照加一个新实体构造RED；拒绝旧字段缺失/旧实体改版、新增实体混入existing。
  - [ ] 最小Python/Go镜像修复；验证旧342/493及增量场景；保留source authority与发布审核要求。
- G3-INC2：分类来源可组合、可追溯，旧C复用+新C执行；来源集合不得重叠冲突，当前策略重放和完整签名/ledger重开均保留。
  - Owner=root：g3_classification_reuse.py及定向tests，g3_bounded_model_execution.py和现有materializer的必要接线。
  - [ ] 先读/复用现有来源验证器；组合两份真实origin的RED；只扩数据组合而不重新造模型网关。
  - [ ] 数据按exact receipt/hash组合；原raw/model output不改写；模型仅处理新范围。
  - 2026-09-13 实证补充：ModelReceiptBinding.input_sha256 绑定原 C 的完整 corpus，不能直接用合并 corpus 校验。INC1 写域已冻结并验证；INC2 作者追加拥有 batch_entity_resolution_830_g3.py 的 receipt 验证与 Go concept_free_wiki_830_g3.go 对应镜像（独立新增 tests），按真实 PolicyReceipt 的 admission/run identity 分组重建每个原 corpus，再校验原 input hash。V3 的签名历史 verifier 必须证明这些分组确为对应成功 C；单源行为保留。不得改写原 ModelReceiptBinding 或放宽为任意 input hash。
- G3-INC3：可重复使用的本机来源/阶段执行由清单驱动，避免写死本次数字。
  - Owner=root：docs/insurance-kb/evidence/830-g3 本次runner/元数据；private evidence保存原始材料与回执；旧历史runner保持。
  - [ ] 新增6材料先本机native解析，再配置已授权embedding可用路由，upload→parse→revision/chunks→source/backfill逐件登记，不碰生产。
  - [ ] C只发所需首页，D按Schema字段分组并保存结果/证据/页码。确认调用输入、schema、模型及输出预算，调用失败保留且不盲重试。
- G3-INC4：实际新版与历史验证。
  - [ ] 只抽取161新增字段，旧493逐字保留；9产品/654字段的候选通过完整校验与实际发布。请求容量按实测检查，不用补造字段或删除历史满足大小。
  - [ ] 新产品页面、字段、source/PDF页码、检索及旧版读回独立复核，计时分别记录，不把软件测试替代真实效果。

## 非目标及停止边界

不进入G4/Q0/生产，不做1000文档压力测试，不更换embedding/rerank/模型，不重抽旧493字段，不覆盖第9版历史。不得以“全量重跑旧材料”掩盖增量缺口。若发现新的独立子系统/生产问题，仅报告事实，不扩大为本轮平台重构。

## 2026-09-13 实际D失败的有界恢复

第一次D compile000成功，compile001被既有校验拒绝：absent_explicitly同时value=null，证据只列一般保险责任，不能证明明确不保障。这是原响应的真实RED，保持校验和失败回执。Owner=root仅追加现有 g3_d_compile_v1.txt 的三态语义提示（present/absent均有非空value与直接证据，未提及必须unknown），不修改字段结果/投影校验；使用已存在字段级projection recovery验证并继承可用结果，新parent只调用失败/未执行字段。提示词为Harness输入，Go应用代码不变，继续消费已冻结49023120b的唯一APP构建；最终分别记录模型source与APPsource，不重复构建。

恢复请求的独立复核发现真实 Gemini 路径选择 g3_d_compile_references_v1.txt，a107 的补充只进入通用模板，18份已物化请求仍缺少三态约束，形成接线 RED。D2 仅 import/prepare，不执行 provider。Owner=root 将相同语义规则补入实际 references 模板，以新 source 和新签名重新物化18请求并检查真实 system body。只继承原成功的1个 ENTITY_SYNTHESIS，失败窗口不继承任何字段，161字段完整重做；不更改 projector，不重建 APP。

D3第一字段窗实际响应的age_segment_tags引用删除原文CRLF，触发既有offered-span校验RED。Owner=root仅在实际references模板明确优先短单行充分引用、多项事实使用多条独立证据，保留原始响应和严格校验；既有projection机制整体校验并复用其余9字段，不逐字段重复重渲染。下一物料组合多个已验证manifest（库已支持），仅调用剩余字段；APP构建和烟测已PASS，不重建。

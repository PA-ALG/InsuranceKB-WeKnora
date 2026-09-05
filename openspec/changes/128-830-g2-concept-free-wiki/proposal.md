# 128 · G2 共享定义与开放知识准入

## Goal与触发依据

唯一Goal为29号文档G2，用户已明确授权实施，Owner为830-G2总控。
base=`e7f57b3628adf97929471de9b4add3ff75c29b8b`。
真实旧编译结果和无法接线的原因已先保存于
`docs/insurance-kb/evidence/830-g2/initial-gap.json`：G1产出76成员，free_wiki为空且不支持concept links。
126冻结空分组，009的五表/current revision方向已失效；不能放宽旧合同假装支持G2。

## 实现选择

在同一WeKnora preparation的Manifest/Members JSONB中承载新版本G2 bundle。
定义、实体字段、free_wiki、别名/义项、关系分别有稳定身份；聚合只读一个固定Release的成员集合。
Harness只编译和独立审核，不保存在线Head；沿现有Draft→human review→Release/CAS。
新候选有自己的candidate digest及审核输出，绝不复制G1旧candidate digest冒充新发现。
Content只能从同member的结构化payload确定性派生，供既有Search/Agent使用。
G1及815旧合同、历史payload、来源和Release不改。

## Owner matrix

总控独占 `HANDOFF.md`、`docs/insurance-kb/evidence/830-g2/**`、本OpenSpec、
`docs/superpowers/plans/2026-09-05-830-g2-concept-free-wiki.md` 与所有commit/D2/外部对象。
实施lane按切片签发，默认唯一非空产品写域；未派发前产品写域关闭。允许路径如下，不能自行加文件：

- Harness新增 `harness/src/insurance_harness/knowledge_compiler/concept_free_wiki_830_g2.py`、
  `harness/src/insurance_harness/knowledge_compiler/concept_compile_830_g2.py`；
  同名 `harness/tests/test_concept_free_wiki_830_g2.py`、`test_concept_compile_830_g2.py`，
  `harness/tests/fixtures/concept_free_wiki_830_g2_contract_vector.json`。
- Go新增 `internal/types/concept_free_wiki_830_g2.go`、`internal/application/service/concept_free_wiki_830_g2.go`、
  `internal/handler/concept_free_wiki_830_g2.go` 及各自 `_test.go`。
- 最小dispatch接线：`internal/handler/schema_wiki.go`、`internal/application/service/schema_wiki.go`、
  `internal/application/service/wiki_release.go`、`internal/router/routes_schema_wiki.go` 及各自 `_test.go`。
- 前端：新增 `frontend/src/api/schema-wiki/conceptFreeWiki830G2.ts`、对应 `.spec.ts`，
  `frontend/src/views/knowledge/schema-wiki/ConceptFreeWiki830G2.vue`、对应 `.spec.ts`；
  `frontend/src/router/index.ts`、`frontend/src/views/knowledge/KnowledgeBase.vue`、
  `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.vue`及现有对应tests。

当前列出跨栈接线预计触发YELLOW，分串行小切片评审；不据此授权大面积重构。
任何不在此清单的真实接缝需求先交总控复核写域；新表/新服务/第二authority直接STOP。

## 非目标与验证

不实现G3 Catalog/自动批量实体识别、G4完整增量/回滚、G5专家编辑流程、Q0语义指标。
协议允许EXPERT_REVISION_RECORD来源，但不能恢复“未另附文件就无来源”规则。
精确合同见spec.md，分步执行和命令见计划；首切片D0/D1，最终D2/D3。
调用、构建、数据/运行身份及STOP只以G2 execution记录和章程为准。

# G3 接缝只读复核与总控裁决

Reviewer：g3_seam_audit；base `075d9c38c01e48abfe7985985dc503099cf9b19a`；2026-09-07。
只读，无模型/DB/构建/发布/文件写。A 合同与计划启动审查 BLOCKER0，详见 contract-plan-review.json。

## 当前首切片

G1 PresentationProfileV1、Python/Go 通用页图已经支持可变节点。A 负责真实 workbook 导入；B 只有在 A GREEN、完整输出 shape/向量/hash 冻结并独立复核后才能启动。候选 B 最小接法：生成 JSON 配置资产、strict TS parser、通用 Catalog 组件、修改已有 SchemaWikiCatalogEntry830G2.vue。这个配置浏览面与已发布目录并列，不依赖 current Release，不产生知识正文或第二审核入口。

上述前端静态资产方案经追加权限审查被拒绝，尚未派写。`internal/router/static.go` 在认证中间件前提供静态资源，内部801行说明进入前端包会被匿名读取。总控采用既有双KB ACL exact GET：原样Catalog仅嵌入Go handler构建输入，路由复用 `routes_schema_wiki.go` 的activeGET（Viewer/Wiki ACL/当前scope/RAW ACL/seal），响应private/no-store，前端只消费鉴权响应。沿当前G2 Head完成本次联调，不增加无Head目录授权规则。

A→只读复核→B→真实目录观察顺序保持串行，避免两个 lane 猜接口。B exact paths 及向量须另存派工记录后才开放写权。

## 全卡后续接缝

1. G1 actual 输入链仍绑定 schema67-candidate.v2 / Schema67CandidateEvidenceAuthorityV1：`harness/src/insurance_harness/knowledge_compiler/entity_page_graph_830_g1.py`、`internal/application/service/entity_page_graph_830_g1.go`、`internal/application/service/schema_wiki.go`。通用页图可复用，旧医疗 actual 入口保留兼容。
2. G2 当前 bundle 支持多实体/字段，但只有标量 SchemaIdentity/ProfileIdentity：`internal/types/concept_free_wiki_830_g2.go`。overview payload 只有 member_ids，前端 `frontend/src/api/schema-wiki/conceptDirectory830G2.ts` 严格校验该结构。总控选择沿现役 G2 多实体合同增加版本化逐实体 Catalog/pack/Profile 绑定，不同时泛化 G1 actual 内容权威。具体 DTO/向量在下一实际切片前冻结。
3. 当前普通/Agent release search 只匹配 slug/title/content：`internal/application/service/wiki_release.go`、`internal/agent/tools/wiki_release_830_g2.go`；G2 field content 仅值/unknown reason。G3 要验证条件命中及同版来源，需最小扩展已存在读取索引或同一内容投影；不另建搜索产品。来源定位/hash 本身可搜索不是额外验收要求，必须返回正确来源。
4. `product/version_resolver.py` 的 exact anchor/隔离依据可复用；`product/classify.py` 未满足五结果及双阈值/MULTI。后续冻结 disposition、阈值、fragment Evidence；当前配置 classification 不是自动分类输出。

这些是预期 G3 实现缺口，不是已运行批次的失败，不改写成 live RED 或产品失败。真实 RED 仍须在对应切片实施前保存。

## 资产处置与范围复核

- KEEP：G1 Profile/通用页图、G2 唯一 Candidate/Review/Release/source 回验、旧医疗入口与历史证据。
- REWIRE：G2 后续逐实体绑定和条件读取接线；本切片 WeKnora 同页只读配置浏览。
- FREEZE：旧 schemas.loader/baseline YAML 仅历史参考，不能充 v5 数据源。
- REJECTED：Catalog 塞进内容 Release、双 Schema authority、重写通用 Profile/route、第二 Wiki/Head。

YELLOW 范围预审更新：A 1 个生产文件，加 B 6 个生产文件（其中1个为总控机械生成的服务端配置资产），达到章程5文件提示线。总控维持A/B串行小GREEN边界；B仅新增受既有ACL保护的配置GET，零新DB表/服务，不增加发布/Active，仍只服务当前可打开Catalog结果。静态方案尚未实施，替换属于派工前设计修正，不是掩盖已执行失败。待实际diff再复核行数及影响，不用文件数代替产品进度。

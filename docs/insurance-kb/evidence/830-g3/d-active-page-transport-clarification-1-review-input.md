# D Active page transport：既有响应复用澄清

状态：DESIGN_REVIEW_PENDING；适用OpenSpec129 G3-R3、D v2 §6。仅澄清已冻结的既有concept-page transport复用，不修改已冻结D Python/Go bundle及容量向量，不提前开放handler/service/UI。

Active G3页面明确沿用现有 `concept-page-read.830.g2.v1` envelope，保持键集合和原生语义：contract、read_mode、release_id、activation_epoch、candidate_hash、space_id、raw_kb_id、wiki_kb_id、member、related_members、citations、definition_hash、aggregate_hash。沿用handler的success/data包装，不增加第二响应hash或新的逐字段接口。

`candidate_hash`是被读取的G3 release对应outer candidate hash；release/epoch来自同一PinnedRead，所有member/related/citation只取该版已验证的G3 manifest。服务器必须先dispatch并完整重验G3 preparation及stored member closure，不能把G3 outer强转为G2候选绕过验证。已有G2分支和载荷不变。

概念、FieldAssertion、free_wiki_item继续使用原G2 domain payload；G3 entity_overview使用D v2冻结的entity-directory-entry.830.g3.v1。新batchConcept830G3解析器对G3 overview/sections/Profile作显式分派及严格校验，禁止放宽旧G2解析器来吞未知载荷。概念聚合继续原DefinitionHash/ConceptAggregateHash830G2公式与同版field集合，非概念两hash按既有空字符串语义；原citation ID与现有token运输保持不变，签发绑定outer candidate和exact release/epoch。

Preparation只使用D v2冻结的batch-concept-preparation-read.830.g3.v1整包响应，从frozen manifest选择字段并显示quote/page；不复用Active envelope，不签未激活release token。G3导航显式pin release后再读页，release_id/preparation_id互斥。

未来最小验证：G2旧载荷兼容；G3字段/概念/overview正向；同版related/source约束；错误outer candidate/release/epoch拒绝；未发布preparation不能进入Active路径。仅在Python/Go/342容量独立门禁通过后派精确服务和前端写域。

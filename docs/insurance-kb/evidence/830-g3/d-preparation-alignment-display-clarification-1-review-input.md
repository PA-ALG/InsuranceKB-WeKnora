# G3 待审整包的两条字段对齐展示澄清

状态：DESIGN_CANDIDATE，尚未授权前端实现。适用D consolidated v2 §4.1、§5.3、§6；不修改Python、Go候选、preparation response或历史G2。

## 信息边界

`batch-concept-preparation-read.830.g3.v1`仅返回已冻结的scope、preparation identity、status、candidate SHA、expected base release/epoch、page_manifest与read SHA。它不含完整unknown_field_key_alignments。服务端必须从存储的完整候选重验两条14字段lineage；前端没有足够响应数据独立重验old_member_digest、source_candidate_sha256或alignment_sha256。

D v2中“前端验证两条alignment lineage”在本首切片精确定义为下述展示绑定检查，不声称客户端重做服务端的完整lineage校验。不增加响应字段，不从Harness或RAW读取候选，也不引入第二份可变lineage authority。

## 唯一展示数据

消费已冻结`unknown-field-key-alignment-exact-fixture.json`，SHA256 `89eda07c37c8e0859bc97d121bf9e5e067123afc3f1b19d04d5c96f95b1960d4`。前端可在新增batchConcept830G3.ts中机械保留恰好两行只读展示投影：entity_id、entity_version、old_field_key、new_field_key、old_member_id、new_member_id。实现时逐值与冻结文件比对，不能从数量或字段相似度推断第三行，不建立通用alias或迁移器。

这两行是已审查首切片的静态展示数据；它们不授予迁移资格，不能替代服务端重验，也不代表真实候选已生成或发布。

## 展示前必须满足的绑定

1. 已完成完整preparation response/read SHA、scope、manifest/member与Catalog/Profile验证，状态为DRAFT或READY。
2. 响应expected_base_release_id必须逐字等于`release-9cb493e3-8d27-4a0f-8f29-93e2a078725b`，expected_base_activation_epoch必须等于5。不得用当前Head替代。
3. 两行各自entity_id/entity_version必须在同一manifest中恰好命中一个医疗overview，其pack/Profile必须为D §2.5固定medical映射。其他新产品overview可以存在，不将整包限制为两个产品。
4. 每行new_member_id必须在同一manifest唯一命中该owner/version的`social_insurance_requirements`字段页，且overview的Profile字段引用指向该member。旧singular key不得作为当前Profile字段页存在。
5. 任一绑定不满足则不展示可确认的迁移摘要，并将当前preparation判为不能完整审核；不使用备用来源、不显示不受验证的历史链接。

## 用户可见内容

仅在待审核整包中展示两行：“旧字段 social_insurance_requirement → 当前字段 social_insurance_requirements”，关联产品正式名及“旧版字段”链接。说明此次仅调整两个空缺字段的名称，其余旧事实保留。不要把hash或内部类型名作为默认产品文案。

历史链接使用现有`conceptPage830G2`路由：member_id来自该行old_member_id，release_id来自已通过精确绑定的expected_base_release_id。当前字段链接使用同一preparation_id和该行new_member_id。旧版链接明确是查看旧已发布版本，不能把旧member当作新Candidate成员。不得给preparation字段签发Active来源token。

完整14字段lineage由服务端创建、刷新重开、Review和Activate各次验证负责。前端测试必须分别证明“两行展示绑定正确”与“没有伪称客户端完整lineage重验”。Active普通目录不新增历史额外字段或迁移节点。

## 有界验证

正向使用当前冻结5产品/342字段manifest，恰好展示两行且两种链接分别带旧release与当前preparation。负向覆盖base release/epoch漂移、缺少任一医疗owner、版本/pack/Profile漂移、重复overview、new member缺失/错owner/错key以及旧singular混入当前Profile；均不能给出完整审核状态。旧G2页面与历史链接仍走原校验分支。

本澄清没有provider、HTTP、DB、部署或产品代码效果。独立设计复核PASS且Go镜像/容量门禁全部通过后才进入既有D UI写域。

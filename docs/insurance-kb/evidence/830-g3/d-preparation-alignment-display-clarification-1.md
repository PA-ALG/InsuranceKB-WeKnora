# G3 待审整包的两条字段对齐展示澄清

状态：DESIGN_CANDIDATE，尚未授权前端实现。适用D consolidated v2 §4.1、§5.3、§6；不修改Python、Go候选、preparation response或历史G2协议。原静态ID方案及独立两项发现保存在review-input与review-1中。

## 信息与权限边界

`batch-concept-preparation-read.830.g3.v1`不含完整unknown_field_key_alignments。服务端必须从存储的完整候选重验两条14字段lineage；前端没有足够响应数据独立重验old_member_digest、source_candidate_sha256或alignment_sha256。

D v2中“前端验证两条alignment lineage”在本首切片限定为两代已验证snapshot的展示绑定，不声称重做完整lineage校验。客户端不包含任何tenant-specific entity/version、release/preparation/member ID常量或fixture，也不把仓库docs作为运行时静态资产。客户端只保留已冻结的非私有字段名规则：social_insurance_requirement → social_insurance_requirements，以及medical pack/Profile合同身份。

## 唯一运行时来源

1. 先通过human preparation-scope bootstrap及immutable preparation GET，完整验证scope、read SHA、manifest/member、Catalog/Profile和DRAFT/READY状态。
2. 从响应expected_base_release_id与expected_base_activation_epoch取得历史pin；不调用/current，不以当前Head替代。通过现有双KB ACL/seal保护的GET `/api/v1/knowledgebase/:wiki_kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id/releases/:expected_base_release_id/search?q=`读取该历史base。
3. 复用已导出的`parseConceptCatalog830G2`，传入已认证响应里的expected base release/epoch。必须得到严格G2结果，所有成员同一candidate revision/hash且scope/pin一致。不得因解析失败改用宽松JSON或另一release。
4. 从准备包的医疗overview中按已确认medical pack/Profile、owner/version及plural字段引用识别恰好两个base医疗owner。历史G2目录必须恰好有同一两个entity/version，各有唯一singular字段，并且历史集合不存在其他未映射base实体。所有tenant-specific标识只能来自这些授权响应。
5. 每个old member从历史同owner/version+singular key唯一解析；new member从当前preparation同owner/version+plural key唯一解析，并核overview字段引用。两行均须满足空缺字段形状：attempted=true、unknown、null value、空Evidence/conditions/exceptions/concept_ids、空valid_time；新旧unknown_reason逐字一致。当前Profile不得含旧singular字段。
6. 对于旧/new assertion的完整载荷按上述规则仅允许field_key与相应identity变化。客户端验证这项显示所需的实际前后内容，不声称从缺失的alignment对象重算14字段lineage。完整canonical lineage及exact首切片base常量仍由服务端权威验证。
7. 任一授权、历史pin、严格parse、集合/owner/version、唯一字段或载荷验证失败，当前preparation不能显示为完整可审核；不退回静态ID、另一release或未验证历史链接。

这只使用现有protected preparation GET与historical pinned search，不增加DTO、服务、数据表、公开静态资产或第二authority。不得将任意两个新建医疗产品误认成base：完整历史owner集合及逐entity/version交叉匹配为必要条件。

## 用户可见内容和链接

默认显示产品正式名及“两个空缺字段按新结构统一名称，原有内容保持不变”，每行提供“旧版字段”和“当前待审字段”。技术字段名只放在可展开的变更详情中。

历史链接复用`conceptPage830G2`，member_id来自严格验证的old member，release_id来自preparation响应的expected base pin。当前链接带同一preparation_id与同manifest的new member。明确旧版链接查看已发布历史版本，不把它当新Candidate成员，不给preparation字段签发Active来源token。

完整14字段lineage由服务端Create、刷新重开、Review和Activate分别验证。Active普通目录不增加历史额外字段或迁移节点。

## 有界验证

正向使用认证响应形式的当前342字段manifest与actual G2历史snapshot：恰好两行，历史/当前链接分别带expected base release和当前preparation。验证未登录/任一KB ACL失败不会取得元数据，前端构建产物没有固定tenant topology。

负向覆盖historical响应scope/pin/revision漂移、G2严格parse失败、缺少/新增base owner、版本/pack/Profile漂移、重复overview、new member缺失/错owner/错key、旧singular混入当前Profile、任一旧/新字段不满足全空unknown资格或unknown_reason漂移；均不提供完整审核状态。确认准备页不调用/current，但允许上述exact历史GET；旧G2页面和历史链接沿原分支验证。

本澄清没有provider、HTTP、DB、部署或产品代码效果。独立设计PASS且Go镜像/容量门禁全部通过后，才进入既有D UI写域。

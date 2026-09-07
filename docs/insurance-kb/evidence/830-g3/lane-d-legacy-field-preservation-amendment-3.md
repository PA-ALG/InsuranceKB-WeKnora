# D 旧字段差异保留修订3（实现前）

补充原D设计及修订1/2，冲突以本文为准。状态：INDEPENDENT_REVIEW_PENDING。新增事实见batch-d-base-profile-compatibility-readonly.json：actual G2两个医疗实体各67字段，与已确认v5医疗Profile仅66个key相交；旧`social_insurance_requirement`与新`social_insurance_requirements`不能当作同一payload identity。此前342只是集合相同的假设计数，未实测且不可用于实际容量或全量保留通过。

## 唯一处理规则

不改Catalog/用户结构确认，不重命名旧FieldAssertion或推断alias。每个base实体完整保留所有既有FieldAssertion payload/Evidence；新结构没有的旧字段仍作为历史字段独立成员存在，同一个旧member_id可继续由固定版本路由打开。新标准字段按Profile key存在，原文未给出新事实时依旧为unknown，不从旧key机械复制或宣称语义等价。

`EntityCompileBinding830G3V1`新增必传 `legacy_field_keys: tuple[Text,...]`，允许空数组，按key排序且唯一，进入binding_sha256。

- binding.required_fields保持只包含对应Profile全部标准字段，逐项逐序相等，不扩写Profile。
- legacy_field_keys必须恰好等于该entity的actual base existing FieldAssertion keys减Profile key set；CREATE或无差异实体必须显式[]。
- base_request.required_fields[entity]精确等于 `binding.required_fields + binding.legacy_field_keys`，即先完整Profile顺序、后canonical旧extra；这满足原G2 CompileOutput全字段闭包，无额外FieldAssertion，也不删旧成员。
- 原D关于required_fields集合/字段输出计数与binding完全相等的句子，改为上述连接公式；entity集合仍逐一相等，BASE_ENTITY_MATCH_REQUIRED等其它前置不变。
- legacy字段只可逐字carry实际base payload/Evidence，不得从模型新建、删改、变unknown或替换Evidence。所有旧字段（包括仍在Profile中的66项）均适用完整carry规则。
- 合法本批MATCH若选择了不能容纳旧字段的新pack，仍保留这些历史字段；但这不能成为静默换pack许可。原D同一实体不得借分类重排迁移pack的约束保持，未来真实pack迁移另行设计。

## 目录与字段成员

G3 entity-directory-entry在原exact keys之外增加必传 `legacy_fields` 数组，允许[]。每项与标准fields形状相同，exact keys为field_key/short_title/member_id；顺序与binding.legacy_field_keys相等。standard sections仍逐项保留已确认Profile的7/8等节点数，恰好覆盖标准required_fields一次；legacy_fields与sections无交集，并恰好覆盖其余实际required_fields。

- 标准field page标题、content投影沿原D。
- legacy field page的member_id/owner_id/title/content/payload均从actual base PageMember逐字carry；snapshot RevisionID/member digest按新G3外层candidate规则生成，不能误称旧release的snapshot bytes原样。
- Python outer bundle无需重复内联base PageMembers：legacy title/content按已冻结原G2 PageMember投影算法从exact旧payload重建，Go服务从actual base Head核它与原PageMember逐字相等；若原base是不能按该算法重建的其他contract则BASE_LEGACY_MEMBER_UNSUPPORTED，不能拼一个新标题。该首切片仅现G2 base支持；未来G3作base需复用其已有manifest投影明确扩展，当前不伪称通用迁移。
- legacy_fields.short_title就是经上述核实的旧member.title，不由模型重写。实体overview content保持原D的产品名/分类/Profile节点，并在legacy非空时追加固定行“历史字段（保留）”；不把历史字段当成第8个Profile节点。
- UI在标准Profile分组后单独显示可折叠的“历史字段（保留）”，注明其为旧版本已存在的字段；产品主计数显示标准字段数量，并单列历史字段数量。旧页面value/Evidence照常可读；preparation与active/pinned沿原模式，不创建第二知识页体系。
- 前端strict parser、manifest projection与cross-language fixture全部覆盖新增exact key，不接受omitted/null/duplicate/错owner/member引用。

## 必须验证与容量

旧G2 fixture、旧candidate与原Profile hash不变。追加RED：把单数旧字段改名覆盖、删旧字段、把旧单数字段放到标准Profile引用、新复数字段指向旧member、少传/伪造legacy key、更改legacy title/content/payload、重复字段、legacy字段跨owner均拒绝。合法旧66交集+1旧extra+1新标准字段时每医疗实体68个FieldAssertion，标准Profile仍67。

275字段fixture继续验证四类标准DTO，但不能代替actual base。原342可以作为明确“无历史差异”的合成fixture；实际容量必用当前完整base的344字段（2*68+67+79+62）、原definition/free page及导航、完整C输入/raw输出/page_manifest一起测量。8MiB限制保持，不删旧字段压容量。

公开拒绝至少 `BASE_LEGACY_MEMBER_UNSUPPORTED` 与 `BASE_LEGACY_FIELD_SET_MISMATCH`；其余结构或hash拒绝复用既有G3错误域。legacy只是现有FieldAssertion的保留表示，不引入别名表、schema registry、产品平台或新的authority。

# D source coverage：完整所选材料闭包

状态：DESIGN_REVIEW_PENDING；Owner=root；G3-R3/R4，D v2 §2.3/§2.4既有语义澄清。Python repair-1的B1/B2/B3已独立通过，冻结source5e472c98c4cb10929cf90689c03b105c68d02da74ca04f5fe12f554d0e6a7ef5。当前新指纹是所选同一material中未作为身份依据、但用于保障字段的另一个SourceBlock被请求拒绝；不是原来的同identity不同内容攻击。全部D实现先冻结，本设计通过前不追加代码。

## 唯一处置

`base_request.sources`固定为以下canonical并集，按(revision_id,block_id)排序去重：

1. `entity_bindings[*].source_material_ids`所选择的C corpus entries的全部SourceBlocks；material集合必须继续与exact C refs一致。C corpus本身是模型前冻结的实际输入范围，不在D阶段另行挑选、扩充或改写正文。
2. actual base的existing definitions/fields/pages所有Evidence所需SourceBlocks。它们必须与原base authority重开结果一致；C/base重叠identity完整内容不同仍拒绝。

“所需”在本切片明确为全部已选C材料块，不再以classifier恰好引用了哪些身份span来裁剪。source集合必须精确等于上述并集：漏掉任何所选材料块、混入未选材料块或无carry依据的其他块，都拒绝；同identity不同完整SourceBlock仍拒绝。共享块只内联一次，全文、ID、页和Unicode offsets不改。

D请求构造与反序列化使用同一集合语义；公开builder签名和outer DTO/hash域不变，不增加source-selector配置、隐藏加载器或新来源存储。调用方提供的base request仍须包含精确并集；本次最小实现不自动替调用方补全缺项。

Delta的owner allowlist继续是该实体所选materials的全部blocks及既有合同允许的carry证据范围；本设计不放宽跨产品借证、selected child Evidence、来源真实性或G1/C5继承门。字段必须经过现有verify_evidence及owner约束；仅在同材料并不证明字段语义正确，原编译/审核与Q0边界保持。

## 有限实现与验证

设计独立通过后，只重开D Python/test及D fixtures；C/common/Catalog/G2/两条exact alignment输入不变，Go与handler/service/UI继续冻结。先在当前冻结5e472c98实现复现一个正向行为RED：已选新产品材料含身份块A和保障正文块B，二者均在冻结C corpus且来源一致，base sources完整带A+B，D仍因identity-only集合报SOURCE_CLOSURE_MISMATCH。再作本处集合修复。

必须覆盖：A+B正向；新产品字段Evidence真实指向B并通过delta/合成；漏B拒绝；未选材料额外块拒绝；A/B或carry同identity不同完整内容拒绝；原三项攻击及actual134→132carry+2alignment+208delta=342保持。使用明确synthetic protocol材料测试，绝不当作真实资料或模型输出。

在既有主capacity fixture中增加上述第二块及相应字段Evidence，保存旧fixture原字节/原hash，不用新fixture覆盖历史审查结论。重新生成三个不同execution raw/context、candidate/provenance和完整preparation POST；actual G2 base134及alignment输入保持exact。重新测实际serializer完整POST≤8MiB；真实来源/模型候选之后仍必须重新测量自身完整请求，不以此fixture代替其容量验收。

本次是回设计后的单一source-union实现步骤，不增加服务、表、接口、队列、第二Wiki/Review/Head/Evidence authority，不重开source upload或外发窗口。交付仍为原Day2截止前的可审候选链；验证按已有24项耗时安排，仅运行新增正反例及受影响D回归/静态和独立复审，不重复全仓库构建。若本澄清实施复审后又出现同域基础问题，停止追加修复并报告用户裁决，不能再拆名延长。

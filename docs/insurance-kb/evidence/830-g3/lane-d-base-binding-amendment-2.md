# D 完整base绑定修订2（实现前）

补充lane-d-contract-design.md及lane-d-contract-review-amendment-1.md，冲突以本文为准。状态：INDEPENDENT_REVIEW_PENDING。只闭合D2既有实体缺本批C引用的合同缺口，不增加新的carryover DTO、registry或身份authority。

## 本首切片采用完整base MATCH前置

本G3 D首切片明确采用评审方案B：当前base Head中的每个existing entity/version，都必须在本批exact C输入和最终resolution中至少有一个自动合格MATCH child，且D entity binding实际选中该ref。必须在compiler/provider调用及Draft创建之前验证这一前置；不能默认批次恰巧覆盖。

- actual base实体集合从唯一base Head全成员/原base request重开；不能让caller删Existing*来缩小集合。
- 对每个base entity，存在唯一D binding，resolution_disposition必须MATCH，原entity_id/entity_version逐字保留；refs均满足完整C自动门槛、parent gate、同一身份/分类/pack/Profile一致性。
- 缺ref、只有NEEDS_CONFIRM/QUARANTINE、父处置不合格、版本不同、CREATE代替旧实体、MATCH指向别的entity，均返回BASE_ENTITY_MATCH_REQUIRED，不生成半包或去掉base实体。不存在“暂时跳过但完整通过”的状态。
- identity/display name/classification/pack/Profile仍按原C_RESOLUTION规则取经证据验证的MATCH anchors；旧FieldAssertion/definition/free page payload和Evidence机械保留规则不变。目录以该合法MATCH binding和Catalog Profile确定性重投影，不虚构base-only绑定或产品名。
- source_material_ids仍来自所选MATCH refs；owner allowlist在其基础上加入真实base carryover Evidence的source closure。base来源不必本次重新提出每条field事实；只需identity MATCH资格和完整旧事实保留。
- 实际v4选中01—04正是base两个医疗实体的既有条款/说明书，保持原W1修订；本前置不授权重传/重解析它们，也不声称真实MATCH已得到。目前actual C模型执行仍NOT RUN。
- 275是四实体合成合同fixture；真实当前base两医疗加新重疾/两全/意外仍需完整五实体342字段。两者fixture各自必须满足其声明base的全覆盖，不能用少一个base的fixture宣称当前真实输入通过。

此首切片不提供“本批完全没有旧实体身份MATCH仍自动迁移旧目录”的通用能力。实际缺MATCH应如实BLOCKED并保留全部base；不得另开前置平台或伪造模型结果。后续若需要放宽，必须另行明确base-only binding的身份/分类/Profile authority后修订，当前不实现两种互斥路径。

## 必须RED/GREEN

新增BASE_ENTITY_MATCH_REQUIRED公开拒绝原因及至少以下向量：删除base第二实体的本批proposal/ref；旧实体只有待审child；用CREATE或错误entity/version代替MATCH；caller省略对应Existing*；均拒绝。合法两base MATCH +三新CREATE保留342字段、原free page/definition/Evidence和base-only source通过；原G2 fixture/hash不变。以上资格由Python和Go机械校验一致执行，服务端仍从exact base Head复验全部成员。

D1/C输入闭包、D3 occurrence、D4 exact DTO/哈希、先DTO和跨语言类型再完整8MiB容量测量后handler/UI的顺序保持已审结论。

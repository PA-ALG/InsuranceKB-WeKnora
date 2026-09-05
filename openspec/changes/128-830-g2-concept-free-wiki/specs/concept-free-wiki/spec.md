# G2 验收合同

## ADDED Requirements

冻结实现判定：`concept_id`从Space、canonical_key、sense_key确定性派生，别名不改变该id；
相同名不同sense保持独立。definition hash只含稳定身份、定义正文、来源和定义修订元数据，
不包含实体集合/Release id/聚合计数。成员hash覆盖结构化payload及确定性Content。
CandidateBundle包含严格版本PageManifest（有序member集合及digest），拒绝/待处理/重复等处置
保留在manifest的audit集合而非正式Members；new/update/sense通过领域审核才进入拟发布成员。
60–79在独立审核中保持NEEDS_HUMAN；未决项不进入成员，人类决议必须随整个candidate hash一起
被既有whole-batch ReviewDecision绑定，不能通过逐项临时开关激活。首实现可保持全部此类项pending。
聚合纳入同版真实FieldAssertion的present/absent_explicitly/unknown三态并显式标记；unknown无值无证据，
不得作为肯定/否定的业务结论，也不得省略其独立页。概念链接是导航关系，不能冒充证据支持。

### Requirement: G2-R1 可替换编译与独立审核

系统 SHALL 接受版本化CompileRequest（原始材料/定位索引、Schema/Profile、已有知识快照、策略、预算、exact identity），输出CandidateBundle（完整字段attempt/state、Claim/Evidence、开放知识、关系/义项、缺口与编译identity）。
编译器与审核器 SHALL 为分别可注入替换的领域接口；模板/规则和LLM初始实现必须可运行。
审核上下文包含候选、原始来源、Schema、作用域/时间及策略，SHALL有独立execution id、输入hash及原始输出，不消费生成者自评分/推理。
平台 SHALL 校验版本/引用/权限/完整性；不得把字符串命中等同领域语义正确。

#### Scenario: 实现替换与真实出口

- **WHEN** 分别替换compiler或reviewer并回放同一冻结请求
- **THEN** 平台UI/Review/Release代码不变；三态和完整attempt集合仍通过同一合同
- **AND** 至少初始实现由真实材料经过独立审核、隔离发布产生可打开页面；fixture只证明协议

### Requirement: G2-R2 稳定定义与同版聚合

ConceptDefinition SHALL 有Space内稳定id、canonical key、sense、definition正文、来源及独立content hash；已有Schema/专家定义优先复用。
实体FieldAssertion SHALL 保持自己的主体、状态、值/条件/版本/时间和Evidence，仅链接concept id/sense。
动态聚合 SHALL 在一次WeKnora pinned read上从该Release成员查询引用关系，返回该release/epoch及被聚合assertion身份，不持久化为可编辑定义。

#### Scenario: 实体集合改变

- **WHEN** 两个真实FieldAssertion链接同一定义，隔离Active实体集合变化
- **THEN** 定义正文hash不变，聚合集合/hash改变；每个聚合项保留自身实体及来源
- **AND** 同名不同义项不误合并、实体条件不提升为通用定义、跨Space引用失败关闭

### Requirement: G2-R3 开放知识处置与价值硬门

准入 SHALL 先分析用途/材料，复用已有页并保守消歧，判断new_page/update/sense/field_rule/alias_link/pending/reject/mention/duplicate等明确处置。
Evidence和身份为不可抵消的硬门；独立页评分固定25/20/20/15/10/10，>=80入Candidate、60–79人工决定、<60 mention-only。
Schema required字段 SHALL 完整尝试并生成独立页，不受评分淘汰；unknown不等于无，不允许伪造值。

#### Scenario: 固定24项准入回放

- **WHEN** 执行运行前冻结digest和预期处置的24项Seed Cases
- **THEN** 24/24 attempted，覆盖晋级、更新、义项、字段补充、别名/提及、重复、广告、OCR、无证据及60/80边界
- **AND** 无来源/无身份/重复/拒绝不得晋级；短重要规则不按字数/页数淘汰

### Requirement: G2-R4 原文优先与来源精确定位

编译 SHALL 记录EXTRACT/NORMALIZE/COMPRESS/SYNTHESIZE方式，quote逐字保留原文，value允许语义等价。
数值、否定、条件、例外、主体、版本、时间 SHALL 保留；重编读取原材料而非旧摘要。
文档与专家修订记录来源 SHALL 类型明确，复用WeKnora SourceRevision/ACL/source viewer；失败typed，无current或第1页fallback。

#### Scenario: 引文漂移与信息丢失

- **WHEN** 引文、revision、locator/hash漂移或编译删除否定/条件/例外
- **THEN** 机械来源漂移拒绝；信息保留反例由独立审核拒绝/需人工，不由生成者自评通过
- **AND** 实际晋级项locator/quote精确回验100%，语义质量仍为Q0 DEFERRED

### Requirement: G2-R5 唯一Candidate与发布链

G2 SHALL 使用新版本严格manifest和独立candidate digest，包含完整领域输出/原始审核记录identity；不放宽G1 exact-key合同、不复制旧G1审核资格。
WeKnora SHALL 从验证后的结构化bundle派生同一preparation成员，沿既有ReviewDecision/Release/CAS发布；Content为可重建呈现。
Candidate/拒绝项 SHALL 不进入Active导航或默认检索；缺依赖、孤立页/断链和来源不完整在发布前lint失败。

#### Scenario: 发布前后边界

- **WHEN** G2新候选到达Draft、完成独立审核并经隔离发布
- **THEN** 激活前正式读取保持旧Release；激活后只读一份完整新Release；并发/旧Head不能覆盖其它成员
- **AND** 拒绝项保持候选审计记录但不成为正式成员，生产8081及其Active不变

### Requirement: G2-R6 Wiki、Search、Agent与来源同版

系统 SHALL 在既有平台路由增加concept/free_wiki详情，从FieldAssertion链接定义，开放知识留在实体free_wiki分组。
搜索 SHALL 覆盖定义/free_wiki正文；Agent消费相同release/epoch和作用域来源，不读Harness候选或RAW作为正式答案。

#### Scenario: 正文检索及来源点击

- **WHEN** 以只出现在正文的真实问题检索或通过Agent读取晋级页
- **THEN** 命中该Release内容并保留实体条件，source click重开同版准确来源
- **AND** 未发布/拒绝候选在默认导航和检索中零出现

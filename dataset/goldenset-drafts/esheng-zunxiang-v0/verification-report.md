# G0a 金标标注 DRAFT 校验报告 — 平安e生保（尊享版）医疗保险

状态：**DRAFT（非权威）**。依 D-2026-07-26-4：标注起草即时进行，正式冻结待 P4c/P5a2；依 D-2026-07-27-9 形态：模型标注 + 确定性校验，人工只复核分歧/高风险/抽样。

- Schema slice：golden-product-medical-schema-v0 (DRAFT; branch draft/golden-product-schema-content, PR #43)（71 字段，全量标注含三态，无选择性标注）
- 标注模型：claude-fable-5；调用形态：claude-session（HARNESS_JUDGE_MODE=claude-session；仓内唯一 API-key 模型为 deepseek-v4-flash/pro，均非最强档——最强可用模型即会话内 Claude，直读 PDF 分页全文标注）
- 源文档：dataset/shouxian_product/平安e生保（尊享版）医疗保险/（保险条款.pdf 39页 / 产品说明书.pdf 27页 / 费率表.pdf 2页；pdfplumber 抽取，同 harness goldenset.pdf）
- 校验器：harness `insurance_harness.goldenset.normalize.quote_in_page`（归一化逐字回验，与金标机线一致）

## 1. 覆盖与三态分布

- 字段覆盖：**71/71**，顺序与 schema slice 一致，无缺漏无重复
- present：45；absent_explicitly：7；unknown：19
- 三态纪律：present=值+证据；absent_explicitly=空值+证据（不得由未抽到推定）；unknown=空值+空证据（绝不伪造引文）。校验通过。

## 2. 引文回验（确定性）

- 引文总数：106；回验通过：106；**通过率 106/106 = 100.0%**
- 回验口径：归一化（去空白/全半角/标点归一）后逐字子串匹配对应文档对应页。
- 无失败引文。
- 表格断行说明：附录2/计划表为 PDF 表格跨列抽取，`zero_deductible`/`deductible` 采用表格原样片段引文（`计划一为1`/`计划二为0`），已在 flags 标记 `table_fragment_quote`。

## 3. 类型/枚举一致性（对 schema slice）

- `product_line`: 值 `医疗险` ∈ 草案枚举 ✓
- `premium_payment_term`: 多值枚举命中 [] / 草案集 ['10年交', '15年交', '20年交', '30年交']（草案枚举值无一出现——枚举闭集需按医疗险口径重定）
- `premium_payment_mode`: 多值枚举命中 ['趸交'] / 草案集 ['趸交', '年交', '半年交', '季交', '月交']
- `hesitation_period`: 数值型 `15`（单位 天）✓
- `waiting_period`: 数值型 `30`（单位 天）✓
- `covered_risks`: enum 目录未定义（undefined）→ 自由文本占位，待目录冻结
- `coverage_period_class`: 值 `短期` ∈ 草案枚举 ✓
- `zero_deductible`: bool 型为复合表述（单值 bool 不可表达/语义待裁决，见 flags）
- `covered_age_groups`: 多值枚举命中 ['儿童（0-17岁）', '成人（18-60岁）', '老人（60岁以上）'] / 草案集 ['儿童（0-17岁）', '成人（18-60岁）', '老人（60岁以上）']
- `guaranteed_renewal`: 值 `非保证续保` ∈ 草案枚举 ✓
- `social_security_unrestricted`: bool 型为复合表述（单值 bool 不可表达/语义待裁决，见 flags）
- `insurable_occupation_classes`: enum 目录未定义（undefined）→ 自由文本占位，待目录冻结
- `coverage_scale_type`: 值 `百万医疗` ∈ 草案枚举 ✓
- `deductible`: money 型为复合/分档表述（qualifier 化后拆 assertion；schema 该字段 required_qualifiers=3）
- `outpatient_inpatient_scope`: 值 `门诊+住院` ∈ 草案枚举 ✓
- `value_added_services`: 多值枚举命中 [] / 草案集 ['就医绿通', '费用垫付', '预赔', '闪赔', '线上理赔']（草案枚举值无一出现——枚举闭集需按医疗险口径重定）
- `benefit_limit`: money 型为复合/分档表述（qualifier 化后拆 assertion；schema 该字段 required_qualifiers=4）
- `reimbursement_ratio`: percentage 型为复合/分档表述（qualifier 化后拆 assertion；schema 该字段 required_qualifiers=4）
- `indemnity_principle`: 复合值含枚举值 `损失补偿型`（值为限定表述，assertion 拆分待冻结）
- `special_exclusion_relaxations`: 多值枚举命中 [] / 草案集 ['自杀可赔', '猝死可赔']（草案枚举值无一出现——枚举闭集需按医疗险口径重定）
- `high_end_medical_access`: 多值枚举命中 ['国际部'] / 草案集 ['特需病房', '私立医院', '国际部']
- `waiting_period_claim_handling`: 值 `等待期内（生效日起30日）经二级及以上医保定点医…` ∉ 草案枚举 ['返还保费', '返还现金价值'] —— 枚举重定/归一化待专家

结论：数值标量字段（犹豫期15天、等待期30天）类型合规；qualifier 重字段（免赔额/给付限额/报销比例等）为分档复合表述，待 qualifier 闭集冻结后拆分 assertion——这是 schema 草案自身待冻结项，非标注缺陷。枚举越集/命名差（趸交期限、特需部vs特需病房、等待期处理医疗险口径等）均已逐字段标 flag，构成对枚举闭集的一手校准证据。

## 4. product_meta 对账（信息性；meta 非文档证据）

- `product_code` vs meta.planCode=596: 一致 ✓
- `product_name` vs meta.clauseName=平安e生保（尊享版）医疗保险: 一致 ✓
- `regulatory_filing_no` vs meta.sccode=平安人寿〔2025〕医疗保险172号: 一致 ✓
- `clause_version`=unknown vs meta.versionNo=596-1: meta-only（文档无证据，externals 待受控 connector）
- `sales_start_date`=unknown vs meta.startDate=2025-09-08: meta-only（文档无证据，externals 待受控 connector）
- `sales_status`=unknown vs meta.planSalesStatus=在售: meta-only（文档无证据，externals 待受控 connector）
- `product_design_type`=unknown vs meta.planPlanType=普通型: meta-only（文档无证据，externals 待受控 connector）
- `sales_channels`=unknown vs meta.planSalesChannel=个人代理、电话销售: meta-only（文档无证据，externals 待受控 connector）

注：`平保寿发〔2025〕404号`（reportPreparedFileCode）三份文档均未出现，`regulatory_filing_no` 两类编号裁决为 schema 已列专家问题。

## 5. 与 wip-gs-v0.1 旧种子对比（本产品）

旧种子：dataset/goldenset/wip-gs-v0.1/平安e生保（尊享版）医疗保险/golden.jsonl（60 字段，旧 schema zh_* field_id，按 display_name 对齐）。**本 DRAFT 在本产品上取代（supersede）旧种子覆盖。**

- 可对齐字段：60/60；三态一致：52；**三态分歧：8（即未来人工复核队列）**
- 新 schema 新增字段（旧种子无覆盖）：11

### 三态分歧清单（人工复核队列①）

| field_id | 字段 | 旧种子 | 新DRAFT | 说明 |
|---|---|---|---|---|
| `product_design_type` | 产品类型 | present | unknown | 旧值“费用补偿型医疗保险”属补偿原则维度混淆（归 indemnity_principle）；产品设计类型文档无证据 |
| `eligible_services` | 可享服务 | present | unknown | 草案枚举为运营三大服务清单（external_sync），文档无枚举值；健康管理服务证据改由 value_added_services 承载 |
| `grace_period` | 宽限期 | unknown | absent_explicitly | 趸交形态宽限期不适用：以“一次性交清”条款结构证据标 absent；N/A 表示法未决通题 |
| `guaranteed_renewal` | 保证续保 | absent_explicitly | present | 三态语义陷阱修正：条款明示“不保证续保”=present（值=非保证续保），非 absent |
| `allowance_benefits` | 津贴 | unknown | absent_explicitly | 责任清单封闭列举无津贴类定额给付项+费用补偿型自述：结构性负证据标 absent |
| `rate_adjustable` | 费率可调 | unknown | absent_explicitly | 条款无费率调整节；判据未冻结（不得由产品名推定），低置信 absent 待裁决 |
| `reinstatement` | 复效条款 | unknown | absent_explicitly | 条款无复效条款；趸交1年期无效力中止语义：结构性负证据标 absent |
| `reduced_paid_up` | 减额缴清 | unknown | absent_explicitly | v1.1适用:长期险；短期趸交产品无减额缴清：占位 absent（或从 slice 移除留痕，待专家） |

### 值形差异（三态一致，present-present）

- `product_line`（产品类别）（值形不同：旧`医疗保险` vs 新`医疗险`）
- `product_summary`（产品简介）（值形不同：旧`平安e生保（尊享版）医疗保险，提供医疗费用保障` vs 新`平安e生保（尊享版）医疗保险产品提供医疗费用保障`）
- `premium_payment_term`（交费期限）（值形不同：旧`投保时一次性交清` vs 新`投保时一次性交清（趸交，1年期）`）
- `premium_payment_mode`（交费方式）（值形不同：旧`一次性交清` vs 新`趸交`）
- `hesitation_period`（犹豫期）（值形不同：旧`15日` vs 新`15`）
- `covered_risks`（可覆盖风险）（值形不同：旧`疾病或意外伤害导致的医疗费用风险` vs 新`疾病及意外伤害所致医疗费用风险（含恶性肿瘤特定药械、临床急需进口药品、海外特定药品及医疗等专项费用风险）`）
- `product_tier`（产品档次）（值形不同：旧`计划一、计划二（投保时选择确定）` vs 新`计划一、计划二（投保时选择确定，免赔额与费率不同）`）
- `insurable_occupation_classes`（投保职业）（值形不同：旧`按医疗职业等级承保：一级职业因子0，二级职业因子20%加费，经核保评估确定` vs 新`医疗职业等级一级、二级（一级职业因子0；二级职业因子20%加费，投保时经核保评估确定）`）
- `outpatient_inpatient_scope`（报销门诊住院范围）（值形不同：旧`门诊+住院（住院医疗费用、指定门诊医疗费用、住院前后门诊急诊费用）` vs 新`门诊+住院`）

### 新增字段（11，旧种子无对照）

- `product_code`（险种代码）→ present
- `target_customer_group`（适用人群）→ unknown
- `zero_deductible`（0免赔）→ present
- `social_security_unrestricted`（不限社保）→ present
- `coverage_scale_type`（额度类型）→ present
- `value_added_services`（增值服务）→ present
- `underwriting_mode`（核保方式）→ unknown
- `indemnity_principle`（补偿原则）→ present
- `high_end_medical_access`（高端医疗）→ present
- `product_conversion`（险种转换）→ absent_explicitly
- `sales_region_limit`（销售地区限制）→ unknown

## 6. 高风险字段与人工复核队列

- schema 高风险字段（high_risk=true）：**23 个**——依 D-2026-07-27-9 全部列入强制人工复核：
  - `waiting_period`（等待期）: present，confidence=high
  - `insurance_period_and_renewal`（保险期间和续保）: present，confidence=high
  - `zero_deductible`（0免赔）: present，confidence=medium
  - `cancer_medical_benefit`（癌症医疗）: present，confidence=high
  - `coverage_summary`（保什么）: present，confidence=high
  - `guaranteed_renewal`（保证续保）: present，confidence=high
  - `guaranteed_renewal_period`（保证续保期）: absent_explicitly，confidence=high
  - `social_security_unrestricted`（不限社保）: present，confidence=low
  - `deductible`（免赔额）: present，confidence=high
  - `outpatient_inpatient_scope`（报销门诊住院范围）: present，confidence=medium
  - `allowance_benefits`（津贴）: absent_explicitly，confidence=medium
  - `benefit_limit`（给付限额）: present，confidence=high
  - `reimbursement_scope`（报销范围）: present，confidence=high
  - `reimbursement_ratio`（报销比例）: present，confidence=high
  - `hospital_scope`（医院范围）: present，confidence=high
  - `indemnity_principle`（补偿原则）: present，confidence=high
  - `special_exclusion_relaxations`（特殊免责）: present，confidence=medium
  - `clause_version`（条款版本标识）: unknown，confidence=medium
  - `clause_effective_date`（条款生效日期）: unknown，confidence=high
  - `exclusions_official`（责任免除）: present，confidence=high
  - `waiting_period_claim_handling`（等待期内出险处理）: present，confidence=high
  - `pre_existing_conditions`（既往症定义与处理）: present，confidence=high
  - `discontinuation_renewal`（停售后续保安排）: present，confidence=high
- 记录级强制复核 flag（mandatory_human_review，判定含结构性负证据/语义两读/单值不可表达）：**11 个**：`grace_period`, `zero_deductible`, `social_security_unrestricted`, `outpatient_inpatient_scope`, `allowance_benefits`, `product_conversion`, `rate_adjustable`, `clause_version`, `clause_effective_date`, `reinstatement`, `reduced_paid_up`
- 三态分歧队列见 §5（8 个）。
- unknown 空证据字段（人工跟进确认“真无”）：19 个：`sales_start_date`, `sales_end_date`, `product_design_type`, `sales_channels`, `published_external`, `sales_status`, `primary_or_rider`, `target_customer_group`, `eligible_services`, `fees`, `policy_count`, `surrender_rate`, `claim_count`, `claim_paid_amount`, `high_risk_occupation_insurable`, `underwriting_mode`, `clause_version`, `clause_effective_date`, `sales_region_limit`

## 7. 问题清单（校验器输出全量）

- 无。

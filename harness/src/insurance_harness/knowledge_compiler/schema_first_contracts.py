"""Pure Schema67 field contracts, deterministic hardness and no-schema facts."""

# ruff: noqa: E501  -- approved workbook rows are retained verbatim for custody.

from __future__ import annotations

import hashlib
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]

FormationMode = Literal["source_extract", "rule_derive", "external_map", "llm_generate"]
ValueShape = Literal[
    "scalar",
    "number",
    "enum",
    "multi_select",
    "date",
    "range",
    "table",
    "narrative",
    "unknown",
]
TriState = Literal["present", "unknown", "absent_explicitly"]
HardnessBand = Literal["H0_EXACT", "H1_BOUNDED", "H2_SEMANTIC", "H3_EXTERNAL_AUTHORITY"]

APPROVED_PRODUCT_VERSION_ID: Final[Literal["596-1"]] = "596-1"
APPROVED_REVIEW_PACKAGE_ID: Final[Literal["596-2-golden-human-review"]] = (
    "596-2-golden-human-review"
)
APPROVED_SCHEMA_ID: Final[Literal["medical-schema67.v1"]] = "medical-schema67.v1"
APPROVED_WORKBOOK_SHA256: Final[str] = (
    "808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29"
)
APPROVED_BY: Final[Literal["linyao"]] = "linyao"
APPROVED_FIELD_COUNT: Final[int] = 67
APPROVED_ORDERED_FIELD_IDS: Final[tuple[str, ...]] = (
    "product_code",
    "product_short_name",
    "product_name",
    "sales_start_date",
    "sales_end_date",
    "product_type",
    "insurance_category",
    "sales_channels",
    "external_publication_status",
    "sales_status",
    "policy_role",
    "product_summary",
    "official_product_features",
    "target_customer_profile",
    "marketing_tagline",
    "product_overview",
    "entry_age_range",
    "insured_eligibility",
    "health_declaration_requirements",
    "geographic_eligibility_requirements",
    "social_insurance_requirement",
    "eligible_occupation_classes",
    "underwriting_method",
    "premium_payment_term",
    "premium_payment_frequency",
    "cooling_off_period",
    "waiting_period",
    "premium_grace_period",
    "coverage_period",
    "coverage_term_category",
    "surrender_and_cancellation_terms",
    "coverage_and_renewal_terms",
    "guaranteed_renewal_status",
    "guaranteed_renewal_period",
    "product_conversion_rules",
    "premium_adjustment_rules",
    "post_discontinuation_renewal_arrangement",
    "covered_risk_categories",
    "coverage_responsibilities",
    "coverage_summary",
    "cancer_medical_coverage",
    "age_segment_tags",
    "coverage_limit_category",
    "special_coverage_and_exclusion_tags",
    "exclusions",
    "pre_existing_condition_rules",
    "out_of_hospital_special_drug_coverage",
    "indemnity_principle",
    "zero_deductible_flag",
    "deductible_rules",
    "outpatient_inpatient_scope",
    "reimbursable_expense_scope",
    "reimbursement_rate_rules",
    "eligible_hospital_scope",
    "premium_medical_facility_coverage",
    "direct_billing_and_advance_payment_rules",
    "claim_application_deadline_and_documents",
    "policyholder_rights",
    "eligible_service_packages",
    "medical_service_benefits",
    "tax_qualified_status",
    "tax_benefit_rules",
    "product_bundle_rules",
    "objection_handling_scripts",
    "product_faq",
    "four_step_sales_script",
    "sales_pitch_script",
)
APPROVED_ORDERED_FIELD_IDS_SHA256: Final[str] = (
    "8ffe2a043dfae6e65d84f213d42818de3c6c1c39c1fcb0c9eccd14367a30db24"
)
APPROVED_SCHEMA_ROWS_SHA256: Final[str] = (
    "cb49f9e27356316a72c258b2b9030257bf434d47a988f61dc820b826c222a57c"
)
APPROVAL_STATUS: Final[Literal["EXPERT_APPROVED_NO_CHANGES"]] = "EXPERT_APPROVED_NO_CHANGES"
EXACT_APPROVAL_AUTHORITY_REF: Final[str] = (
    "user-message:019fda9b-schema67-approved-no-changes"
)

_ApprovedSchemaRowValues = tuple[int, str, str, str, str, str | None, str, str]
_APPROVED_SCHEMA_ROW_VALUES: Final[tuple[_ApprovedSchemaRowValues, ...]] = (
    (
        1,
        "02 产品主数据",
        "险种代码",
        "product_code",
        "产品在公司产品主数据中的唯一标识代码，用于关联产品元数据、条款、计划表及其他业务材料；优先从产品主数据获取，必要时可从条款首页核验。",
        None,
        "产品元数据，该字段允许从产品条款PDF第一页获取",
        "外部映射",
    ),
    (
        2,
        "02 产品主数据",
        "险种简称",
        "product_short_name",
        "产品对内或对外使用的规范简称；优先使用产品主数据中的正式简称，不由大模型自行缩写或改写。",
        None,
        "产品元数据，该字段允许从产品条款PDF第一页获取",
        "外部映射",
    ),
    (
        3,
        "02 产品主数据",
        "险种名称",
        "product_name",
        "产品经审批、备案或正式发布使用的完整名称，应与产品主数据或条款首页保持一致。",
        None,
        "产品元数据，该字段允许从产品条款PDF第一页获取",
        "外部映射",
    ),
    (
        4,
        "02 产品主数据",
        "开始使用时间",
        "sales_start_date",
        "产品开始允许销售或接受新投保申请的日期，不等同于单张保单的合同生效日期。",
        None,
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        5,
        "02 产品主数据",
        "结束使用时间",
        "sales_end_date",
        "产品停止销售或停止接受新投保申请的日期，不代表已生效保单的保障终止日期。",
        None,
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        6,
        "02 产品主数据",
        "产品类型",
        "product_type",
        "产品利益类型，如普通型、分红型、万能型、投资连结型等；以产品主数据为准，不建议仅依据产品名称推断。",
        "普通型、分红型、万能型、投资连结型、其他",
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        7,
        "02 产品主数据",
        "产品类别",
        "insurance_category",
        "产品所属保险业务类别，如医疗保险、疾病保险、意外伤害保险等；使用统一产品分类枚举，以产品主数据为准。",
        "意外伤害保险、医疗保险、定期寿险、终身寿险、两全保险、年金保险、疾病保险、护理保险、医疗意外保险、补充养老保险、失能收入损失保险、其他",
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        8,
        "02 产品主数据",
        "销售渠道",
        "sales_channels",
        "产品允许销售的渠道列表，如个险、银保、经代、互联网等；存在多个渠道时应以数组或多值形式保存。",
        "个人代理、银行代理、电话销售、网络销售、保险经纪、专业代理、兼业代理、其他渠道（可多选）",
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        9,
        "02 产品主数据",
        "发布外网",
        "external_publication_status",
        "产品信息是否已获准在公司外部网站或其他公开渠道发布；应直接读取权威系统状态，不根据是否能搜索到网页推断。",
        "是、否",
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        10,
        "02 产品主数据",
        "销售状态",
        "sales_status",
        "产品当前所处的销售生命周期状态，用于区分在售、停售等情形。",
        "在售、停售",
        '产品元数据，需要从"全量产品基础信息.xlsx"文件中获取（根据险种代码映射得到）',
        "外部映射",
    ),
    (
        11,
        "02 产品主数据",
        "主附加险",
        "policy_role",
        "产品在保险合同组合中的角色，包括主险、附加险；优先读取产品主数据，缺失时可依据正式名称及组合规则判断。",
        "主险、附加险",
        "险种名称",
        "外部映射；规则衍生",
    ),
    (
        12,
        "03 产品定位与摘要",
        "产品简介",
        "product_summary",
        "根据材料中的产品特色、保障责任、投保年龄等内容加工生成。要求：200字左右，需包含产品亮点、保额范围、保障期限、核心保障责任（如重疾/医疗/意外保障），请使用通俗易懂的语言，避免专业术语，重点突出产品核心价值，保障责任表述要完整，相关前提或者约束条件不能省略。",
        None,
        "产品说明书、培训材料等其他业务材料",
        "LLM生成",
    ),
    (
        13,
        "03 产品定位与摘要",
        "产品特色",
        "official_product_features",
        "优先提取产品说明书或官方材料明确列示的产品特色；材料未明确时，可基于已核验的保障事实归纳，但不得将通用功能表述为产品独有优势。",
        None,
        "产品说明书",
        "原文抽取；LLM生成",
    ),
    (
        14,
        "03 产品定位与摘要",
        "适用人群",
        "target_customer_profile",
        "优先提取培训或销售材料中的目标客群；材料缺失时，可依据投保年龄、职业、健康告知、保障侧重和产品特色生成50字以内的客群画像，不代表客户必然符合投保条件。",
        None,
        "培训材料、产品销售逻辑材料、产品说明书",
        "原文抽取；LLM生成",
    ),
    (
        15,
        "03 产品定位与摘要",
        "产品宣传语",
        "marketing_tagline",
        "官方宣传材料中使用的产品宣传语、传播口号或核心文案；只提取正式材料内容，不由大模型自行创作。",
        None,
        "产品宣传海报",
        "原文抽取",
    ),
    (
        16,
        "03 产品定位与摘要",
        "产品概览",
        "product_overview",
        "面向阅读展示的产品总览，聚合核心保险责任、起保点、保额、组合方案及关键规则，优先采用表格或一图流结构；仅作为展示内容，不作为其他字段的事实来源。",
        None,
        "产品销售逻辑PPT、产品培训材料",
        "LLM生成",
    ),
    (
        17,
        "04 投保与承保规则",
        "投保年龄",
        "entry_age_range",
        "被保险人首次投保时允许的年龄范围，应保留年龄计算口径、起止年龄及不同计划或渠道的差异。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        18,
        "04 投保与承保规则",
        "投保范围",
        "insured_eligibility",
        "对投保人、被保险人身份、关系及其他投保资格的规定；应完整列示适用对象和限制条件，不与投保年龄、地域限制重复。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        19,
        "04 投保与承保规则",
        "健康告知要求",
        "health_declaration_requirements",
        "投保时被保险人需要履行的健康告知要求，包括是否需要健康告知、健康问卷涉及的主要事项、免健康告知条件及特殊渠道差异；不得根据产品名称或经验推断。",
        None,
        "产品条款、、产品投保规则PDF",
        "原文抽取",
    ),
    (
        20,
        "04 投保与承保规则",
        "投保地区或常住地限制",
        "geographic_eligibility_requirements",
        "产品对投保地区、被保险人常住地、工作地或投保机构所在地等地域条件的限制，包括允许地区、限制地区及特殊适用条件；材料未明确时不得推断为全国可投保。",
        None,
        "投保规则、产品说明书、销售规则、投保页面",
        "原文抽取；外部映射",
    ),
    (
        21,
        "04 投保与承保规则",
        "不限社保",
        "social_insurance_requirement",
        "产品是否要求被保险人参加基本医疗保险，以及有无社保、是否使用社保结算对投保资格或赔付比例的影响；不得仅以“是/否”掩盖条件差异。",
        None,
        "产品条款",
        "规则衍生",
    ),
    (
        22,
        "04 投保与承保规则",
        "可投保职业",
        "eligible_occupation_classes",
        "产品允许投保的职业类别或具体职业范围，应同时保留除外职业、特殊职业及附加条件。",
        None,
        "产品投保规则PDF",
        "原文抽取",
    ),
    (
        23,
        "04 投保与承保规则",
        "核保方式",
        "underwriting_method",
        "当前适用的核保模式，如免核保、智能核保、人工核保或智能与人工结合；应记录适用渠道、触发条件及生效时间。",
        "免核保、智能核保、人工核保、智能+人工核保",
        "产品保全、核保规则PDF及其他业务材料",
        "原文抽取；外部映射",
    ),
    (
        24,
        "05 合同与交费规则",
        "缴费期限",
        "premium_payment_term",
        "投保人需要持续缴纳保险费的期限，如趸缴、1年、5年、10年等；存在多种缴费期限时应完整列示。",
        "趸缴、1年、5年、10年、15年、20年、30年等",
        "产品投保规则PDF、产品说明书",
        "原文抽取",
    ),
    (
        25,
        "05 合同与交费规则",
        "缴费方式",
        "premium_payment_frequency",
        "保险费的缴纳频率或方式，如趸缴、年缴、半年缴、季缴、月缴；应区分缴费期限与缴费频率。",
        "趸缴、年缴、半年缴、季缴、月缴",
        "产品投保规则PDF、产品说明书",
        "原文抽取",
    ),
    (
        26,
        "05 合同与交费规则",
        "犹豫期",
        "cooling_off_period",
        "投保人收到保险合同后，可按条款约定解除合同并退还相应款项的期间；只允许从正式条款中抽取，并保留起算方式。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        27,
        "05 合同与交费规则",
        "等待期",
        "waiting_period",
        "合同生效后，因约定疾病或医疗原因发生保险事故暂不承担责任的期间；只允许从正式条款中抽取，应分别记录不同责任的等待期及例外情形。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        28,
        "05 合同与交费规则",
        "宽限期",
        "premium_grace_period",
        "续期保险费到期未缴时，合同继续有效的宽限期间及其起算、终止和期间内责任承担规则，只允许从正式条款中抽取。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        29,
        "05 合同与交费规则",
        "保障期间",
        "coverage_period",
        "单个保险期间的具体长度或截止方式，如1年、至约定年龄或终身；应保留不同计划的差异。",
        None,
        "产品说明书",
        "原文抽取",
    ),
    (
        30,
        "05 合同与交费规则",
        "保障期间分类",
        "coverage_term_category",
        "根据保障期间映射产品期限类别：不超过1年为短期，超过1年且非终身为长期，条款明确保障终身时为终身。",
        "短期、长期、终身",
        "产品说明书",
        "规则衍生",
    ),
    (
        31,
        "05 合同与交费规则",
        "犹豫期及合同解除（退保）",
        "surrender_and_cancellation_terms",
        "犹豫期内外解除合同的条件、办理方式、退还金额、费用扣除及可能损失；应以条款为准并区分不同阶段。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        32,
        "06 续保与费率规则",
        "保险期间和续保",
        "coverage_and_renewal_terms",
        "综合记录产品保险期间及期满后的续保安排，包括是否可续保、是否需要审核、续保年龄限制和相关条件。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        33,
        "06 续保与费率规则",
        "保证续保",
        "guaranteed_renewal_status",
        "条款是否明确承诺在保证续保期间内，不因被保险人健康变化或历史理赔而拒绝续保；“可续保”不等于“保证续保”。",
        "保证续保、否",
        "产品条款",
        "规则衍生",
    ),
    (
        34,
        "06 续保与费率规则",
        "保证续保期",
        "guaranteed_renewal_period",
        "条款明确约定的保证续保期间、起算规则和适用条件；仅在产品明确保证续保时填写。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        35,
        "06 续保与费率规则",
        "险种转换",
        "product_conversion_rules",
        "产品是否允许转换为其他指定险种，以及可转换对象、时间、条件、是否重新核保和转换后的权益变化。",
        "是、否",
        "产品条款",
        "原文抽取",
    ),
    (
        36,
        "06 续保与费率规则",
        "费率可调",
        "premium_adjustment_rules",
        "产品费率是否允许调整，以及调整触发条件、频率、适用范围、通知方式和限制。",
        "是、否",
        "产品条款",
        "原文抽取",
    ),
    (
        37,
        "06 续保与费率规则",
        "停售后续保安排",
        "post_discontinuation_renewal_arrangement",
        "产品停售后，已投保客户是否仍可续保、可续保至何时、是否安排转保及相关条件。",
        None,
        "产品条款、培训材料等其他业务材料",
        "原文抽取",
    ),
    (
        38,
        "07 保障责任与额度",
        "可覆盖风险",
        "covered_risk_categories",
        "根据保障责任中的具体保险金映射得到，产品可覆盖的风险类别，如医疗、意外、重疾等；仅用于分类和检索，不替代具体保险责任。",
        "可选值“身故风险、养老风险、意外风险、医疗风险、重疾风险、财务风险、传承风险、子女教育风险”",
        "产品条款",
        "规则衍生",
    ),
    (
        39,
        "07 保障责任与额度",
        "保险责任",
        "coverage_responsibilities",
        "从正式产品材料中逐项提取全部保险责任，保留责任名称、触发条件、保障范围、额度和主要限制；不得遗漏或合并不同责任。",
        None,
        "产品说明书",
        "原文抽取",
    ),
    (
        40,
        "07 保障责任与额度",
        "保什么",
        "coverage_summary",
        "将各项保险责任、核心保障内容及给付限额转化为通俗摘要；责任名称和额度必须与原文一致，重要条件不得省略，建议使用表格展示。",
        "一般医疗保险金200万、恶性肿瘤医疗保险金200万等",
        "产品条款",
        "原文抽取；LLM生成",
    ),
    (
        41,
        "07 保障责任与额度",
        "癌症医疗",
        "cancer_medical_coverage",
        "判断产品是否包含恶性肿瘤、原位癌或相关疾病医疗责任，并保留对应责任名称、费用范围、额度和适用条件。",
        "是、否",
        "产品条款",
        "规则衍生",
    ),
    (
        42,
        "07 保障责任与额度",
        "保障人群",
        "age_segment_tags",
        "根据投保年龄范围映射年龄客群标签，仅用于分类检索；存在跨年龄段时可多选，不能替代正式投保年龄规则。",
        "儿童（0-17岁）、成人（18-59岁）、老年人（60岁及以上）（可多选）",
        "产品条款",
        "规则衍生",
    ),
    (
        43,
        "07 保障责任与额度",
        "额度类型",
        "coverage_limit_category",
        "根据产品主要医疗保障额度及业务口径映射为小额医疗、百万医疗等分类标签；分类阈值应由统一规则维护。",
        "小额医疗、百万医疗",
        "产品条款",
        "规则衍生",
    ),
    (
        44,
        "07 保障责任与额度",
        "特殊承保与除外标签",
        "special_coverage_and_exclusion_tags",
        "对容易与一般认知产生差异的特殊承保或除外情形进行标签化标记；每个标签须明确属于可保、条件承保或除外不保，并关联对应依据。",
        "条件承保、除外不保、猝死可赔、自杀可赔、既往症可赔、慢病可承保等（标签化，多选）",
        "产品条款",
        "规则衍生",
    ),
    (
        45,
        "07 保障责任与额度",
        "责任免除",
        "exclusions",
        "条款中不承担保险责任的全部情形，应保留原文，并可按疾病、行为、治疗、医疗机构、地域等主题进行结构化整理。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        46,
        "07 保障责任与额度",
        "既往症定义与处理",
        "pre_existing_condition_rules",
        "条款对既往症的定义，以及既往症是否除外、部分承保、特别约定承保或满足条件后承保。",
        None,
        "产品条款、产品说明书",
        "原文抽取",
    ),
    (
        47,
        "07 保障责任与额度",
        "外购药/特药责任",
        "out_of_hospital_special_drug_coverage",
        "对院外购药、特定药品或特定疾病药品的保障规则，包括药品范围、处方要求、购药渠道、审核条件、额度和赔付比例。",
        None,
        "产品条款、产品说明书",
        "原文抽取",
    ),
    (
        48,
        "07 保障责任与额度",
        "补偿原则",
        "indemnity_principle",
        "产品是否适用费用补偿原则，以及社保、公费医疗、其他商业保险或第三方补偿金额如何从赔付金额中扣除。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        49,
        "08 理赔与费用报销规则",
        "0免赔",
        "zero_deductible_flag",
        "判断产品是否存在免赔额为0的保障责任或计划；如仅部分责任或计划为0免赔，应明确适用范围，不得概括为全产品0免赔。",
        "是、否",
        "产品条款",
        "规则衍生",
    ),
    (
        50,
        "08 理赔与费用报销规则",
        "免赔额",
        "deductible_rules",
        "赔付前由被保险人自行承担的金额规则，包括金额、计算周期、按次或年度、家庭共享及可抵扣来源等。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        51,
        "08 理赔与费用报销规则",
        "报销门诊/住院范围",
        "outpatient_inpatient_scope",
        "产品覆盖的医疗场景范围，如门诊、急诊、住院、日间手术等，并概述各场景的核心内容与限制。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        52,
        "08 理赔与费用报销规则",
        "报销范围",
        "reimbursable_expense_scope",
        "可纳入赔付计算的医疗费用项目及目录范围，如床位费、药品费、检查费、手术费和社保目录内外费用。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        53,
        "08 理赔与费用报销规则",
        "报销比例",
        "reimbursement_rate_rules",
        "按保障计划、保险责任、是否参加及使用社保、医院类型和费用类别等条件分别记录赔付比例。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        54,
        "08 理赔与费用报销规则",
        "医院范围",
        "eligible_hospital_scope",
        "符合赔付条件的医院等级、性质、科室、地区和网络范围，以及条款明确不予认可的医院类型。",
        None,
        "产品条款",
        "原文抽取",
    ),
    (
        55,
        "08 理赔与费用报销规则",
        "高端医疗",
        "premium_medical_facility_coverage",
        "判断产品是否覆盖特需部、国际部、私立医院、昂贵病房等高端医疗资源，并记录具体适用范围和限制。",
        "特需部/国际部、私立医院、昂贵医院等（多选）",
        "产品条款、产品说明书",
        "规则衍生",
    ),
    (
        56,
        "08 理赔与费用报销规则",
        "直付或垫付规则",
        "direct_billing_and_advance_payment_rules",
        "产品是否提供医疗费用直付、住院费用垫付或理赔款预付服务，以及适用对象、医院范围、申请条件、额度、办理流程、限制和事前审核要求；该服务不等同于最终保险责任或理赔结论。",
        None,
        "服务手册、产品说明书、权益规则、理赔服务指引",
        "原文抽取；外部映射",
    ),
    (
        57,
        "08 理赔与费用报销规则",
        "理赔申请时效与申请材料",
        "claim_application_deadline_and_documents",
        "保险事故通知、理赔申请时限及不同责任所需的申请材料；应按责任或理赔类型分别列示。",
        None,
        "产品条款、产品说明书",
        "原文抽取",
    ),
    (
        58,
        "09 服务与权益",
        "保单权益",
        "policyholder_rights",
        "条款明确约定的保单红利、现金价值、保单贷款、自动垫交、减额交清等合同权益；允许为空，未约定时不得补充。",
        "保单红利、现金价值、保单贷款、自动垫交、减额交清（多选，可为空）",
        "产品条款、培训材料等其他业务材料",
        "原文抽取",
    ),
    (
        59,
        "09 服务与权益",
        "可享服务",
        "eligible_service_packages",
        "客户购买产品并满足准入条件后，可获得的公司级权益服务包；应根据最新准入清单映射，并保留适用条件。",
        "安有医、安有护、居家养老、高端康养、私董保健医、御享国医、臻享家医、就医通",
        "康养&居家养老等服务准入清单Excel表格",
        "外部映射",
    ),
    (
        60,
        "09 服务与权益",
        "增值服务",
        "medical_service_benefits",
        "随产品提供的就医绿通、费用垫付、预赔、闪赔、线上理赔等医疗或理赔服务；应明确服务内容、准入条件和适用限制。",
        "就医绿通、费用垫付、预赔、闪赔、线上理赔等（多选）",
        "产品保全、核保规则PDF及其他业务材料",
        "原文抽取；外部映射",
    ),
    (
        61,
        "09 服务与权益",
        "可享税优",
        "tax_qualified_status",
        "产品是否属于可使用个人养老金账户或享受相关税收优惠的合格产品，以正式销售规则或合格产品清单为准。",
        "是、否",
        "产品销售规则",
        "原文抽取；外部映射",
    ),
    (
        62,
        "09 服务与权益",
        "税优规则",
        "tax_benefit_rules",
        "产品适用的税优资格、购买账户、适用对象、缴费和税前扣除等具体规则；仅在可享税优时填写。",
        None,
        "产品销售规则",
        "原文抽取",
    ),
    (
        63,
        "10 销售赋能",
        "产品搭配规则",
        "product_bundle_rules",
        "产品与主险、附加险或其他产品组合销售时的必选、可选、互斥、顺序及额度关系。",
        None,
        "产品组合销售方案相关文档",
        "原文抽取",
    ),
    (
        64,
        "10 销售赋能",
        "产品异议话术",
        "objection_handling_scripts",
        "针对价格、续保、免赔额、既往症、医院范围等常见异议形成的话术集合，应按异议主题逐条保存并与产品事实一致。",
        None,
        "业务方提供的异议处理汇总内容、产品培训材料、产品常见问题清单",
        "原文抽取",
    ),
    (
        65,
        "10 销售赋能",
        "产品Q&A",
        "product_faq",
        "产品常见问题及标准答案，应逐条保存问题、答案、适用版本、依据来源和必要风险提示。",
        None,
        "产品Q&A清单、产品销售逻辑PPT",
        "原文抽取",
    ),
    (
        66,
        "10 销售赋能",
        "四步法讲解话术",
        "four_step_sales_script",
        "按观念导入、需求激发、方案呈现、讲解促成四个阶段组织的产品讲解话术及相关方案呈现内容。",
        None,
        "产品销售逻辑PPT、产品培训材料",
        "原文抽取",
    ),
    (
        67,
        "10 销售赋能",
        "Pitch话术",
        "sales_pitch_script",
        "面向完整销售沟通流程的结构化话术，包括建立联系、需求挖掘、价值呈现、异议处理、促成交易和后续服务。",
        None,
        "产品销售逻辑PPT、产品培训材料",
        "原文抽取",
    ),
)

_FIELD_ROWS_OBJECT_TYPE: Final[str] = "schema67-approved-field-rows.v1"
_SCHEMA_SNAPSHOT_OBJECT_TYPE: Final[str] = "schema67-approved-snapshot.v1"
_HARDNESS_OBJECT_TYPE: Final[str] = "schema67-hardness-vector.v1"
_FIELD_CONTRACT_OBJECT_TYPE: Final[str] = "schema67-field-contract.v1"
_CONTRACT_SET_OBJECT_TYPE: Final[str] = "schema67-field-contract-set.v1"
_GENERIC_FACT_OBJECT_TYPE: Final[str] = "generic-fact-envelope.v1"
_FORMATION_ORDER: Final[dict[str, int]] = {
    "source_extract": 0,
    "rule_derive": 1,
    "external_map": 2,
    "llm_generate": 3,
}
_FORMATION_MODE_BY_RAW: Final[dict[str, FormationMode]] = {
    "原文抽取": "source_extract",
    "规则衍生": "rule_derive",
    "外部映射": "external_map",
    "LLM生成": "llm_generate",
}
_DATE_FIELD_IDS: Final[frozenset[str]] = frozenset({"sales_start_date", "sales_end_date"})
_RANGE_FIELD_IDS: Final[frozenset[str]] = frozenset({"entry_age_range"})
_NARRATIVE_FIELD_IDS: Final[frozenset[str]] = frozenset(
    {"coverage_summary", "product_overview", "product_summary"}
)
_DEFERRED_UNKNOWN_FIELD_IDS: Final[frozenset[str]] = frozenset(
    {
        "sales_start_date",
        "sales_end_date",
        "product_type",
        "insurance_category",
        "sales_channels",
        "external_publication_status",
        "sales_status",
        "policy_role",
        "marketing_tagline",
        "geographic_eligibility_requirements",
        "premium_grace_period",
        "product_conversion_rules",
        "premium_adjustment_rules",
        "eligible_service_packages",
        "tax_qualified_status",
        "tax_benefit_rules",
        "product_bundle_rules",
        "objection_handling_scripts",
        "product_faq",
        "four_step_sales_script",
        "sales_pitch_script",
    }
)
_BROCHURE_ONLY_FIELD_IDS: Final[frozenset[str]] = frozenset(
    {
        "official_product_features",
        "target_customer_profile",
        "coverage_period",
        "coverage_term_category",
    }
)
_RATE_ONLY_FIELD_IDS: Final[frozenset[str]] = frozenset({"eligible_occupation_classes"})
_BROCHURE_TERMS_FIELD_IDS: Final[frozenset[str]] = frozenset(
    {
        "product_summary",
        "product_overview",
        "coverage_responsibilities",
        "coverage_summary",
    }
)
_RATE_TERMS_FIELD_IDS: Final[frozenset[str]] = frozenset(
    {"social_insurance_requirement", "underwriting_method"}
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SchemaFirstContractError(ValueError):
    """Typed fail-closed boundary for invalid Schema67 domain inputs."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _formation_modes_from_raw(raw: str) -> tuple[FormationMode, ...]:
    parts = tuple(raw.split("；"))
    try:
        mapped = tuple(_FORMATION_MODE_BY_RAW[part] for part in parts)
    except KeyError as exc:
        raise ValueError("unknown formation mode") from exc
    if len(mapped) != len(set(mapped)):
        raise ValueError("duplicate formation mode")
    return tuple(sorted(mapped, key=_FORMATION_ORDER.__getitem__))


def _value_shape_from_row(*, field_id: str, raw: str | None) -> ValueShape:
    if field_id in _DATE_FIELD_IDS:
        return "date"
    if field_id in _RANGE_FIELD_IDS:
        return "range"
    if field_id in _NARRATIVE_FIELD_IDS:
        return "narrative"
    if raw is None:
        return "scalar"
    if "多选" in raw:
        return "multi_select"
    return "enum"


def _source_roles_from_field_id(field_id: str) -> tuple[str, ...]:
    if field_id in _DEFERRED_UNKNOWN_FIELD_IDS:
        return ("deferred",)
    if field_id in _BROCHURE_ONLY_FIELD_IDS:
        return ("brochure",)
    if field_id in _RATE_ONLY_FIELD_IDS:
        return ("rate_table",)
    if field_id in _BROCHURE_TERMS_FIELD_IDS:
        return ("brochure", "terms")
    if field_id in _RATE_TERMS_FIELD_IDS:
        return ("rate_table", "terms")
    return ("terms",)


class ApprovedFieldRowV1(_FrozenModel):
    """One exact A:H Schema row, without candidate/Golden custody."""

    ordinal: PositiveInt
    category: NonBlankStr
    field_name: NonBlankStr
    field_id: NonBlankStr
    description: NonBlankStr
    value_shape_raw: NonBlankStr | None
    source_authority_raw: NonBlankStr
    formation_raw: NonBlankStr

    @model_validator(mode="after")
    def require_supported_raw_schema(self) -> Self:
        _formation_modes_from_raw(self.formation_raw)
        _value_shape_from_row(field_id=self.field_id, raw=self.value_shape_raw)
        _source_roles_from_field_id(self.field_id)
        return self

    @property
    def value_shape(self) -> ValueShape:
        return _value_shape_from_row(field_id=self.field_id, raw=self.value_shape_raw)

    @property
    def formation_modes(self) -> tuple[FormationMode, ...]:
        return _formation_modes_from_raw(self.formation_raw)

    @property
    def source_roles(self) -> tuple[str, ...]:
        return _source_roles_from_field_id(self.field_id)

    @property
    def evidence_required(self) -> bool:
        return True


def _schema_row_payload(row: ApprovedFieldRowV1) -> dict[str, object]:
    return {
        "ordinal": row.ordinal,
        "category": row.category,
        "field_name": row.field_name,
        "field_id": row.field_id,
        "description": row.description,
        "value_shape_raw": row.value_shape_raw,
        "source_authority_raw": row.source_authority_raw,
        "formation_raw": row.formation_raw,
    }


def _validated_rows(
    rows: tuple[ApprovedFieldRowV1, ...],
) -> tuple[ApprovedFieldRowV1, ...]:
    if type(rows) is not tuple:
        raise ValueError("field rows must be an exact tuple")
    return tuple(
        ApprovedFieldRowV1.model_validate(row.model_dump(mode="python", round_trip=True))
        for row in rows
    )


def approved_schema_rows() -> tuple[ApprovedFieldRowV1, ...]:
    """Return the non-sensitive A5:H71 workbook authority as exact DTOs."""

    return tuple(
        ApprovedFieldRowV1(
            ordinal=ordinal,
            category=category,
            field_name=field_name,
            field_id=field_id,
            description=description,
            value_shape_raw=value_shape_raw,
            source_authority_raw=source_authority_raw,
            formation_raw=formation_raw,
        )
        for (
            ordinal,
            category,
            field_name,
            field_id,
            description,
            value_shape_raw,
            source_authority_raw,
            formation_raw,
        ) in _APPROVED_SCHEMA_ROW_VALUES
    )


def schema_rows_sha256(rows: tuple[ApprovedFieldRowV1, ...]) -> str:
    checked = _validated_rows(rows)
    return canonical_hash(
        _FIELD_ROWS_OBJECT_TYPE,
        {"fields": tuple(_schema_row_payload(row) for row in checked)},
    )


def ordered_field_ids_sha256(field_ids: tuple[str, ...]) -> str:
    """Hash the approved XLSX order as UTF-8 IDs separated and ended by LF."""

    if type(field_ids) is not tuple or any(type(item) is not str for item in field_ids):
        raise ValueError("field IDs must be an exact tuple of strings")
    return hashlib.sha256(("\n".join(field_ids) + "\n").encode("utf-8")).hexdigest()


def approved_schema_snapshot_sha256(
    *,
    product_version_id: str,
    review_package_id: str,
    schema_id: str,
    workbook_sha256: str,
    approval_status: str,
    approved_by: str,
    authority_ref: str,
    schema_rows_sha256_value: str,
    ordered_field_ids_sha256_value: str,
) -> str:
    return canonical_hash(
        _SCHEMA_SNAPSHOT_OBJECT_TYPE,
        {
            "product_version_id": product_version_id,
            "review_package_id": review_package_id,
            "schema_id": schema_id,
            "workbook_sha256": workbook_sha256,
            "approval_status": approval_status,
            "approved_by": approved_by,
            "authority_ref": authority_ref,
            "schema_rows_sha256": schema_rows_sha256_value,
            "ordered_field_ids_sha256": ordered_field_ids_sha256_value,
        },
    )


class ApprovedSchemaSnapshotV1(_FrozenModel):
    product_version_id: Literal["596-1"]
    review_package_id: Literal["596-2-golden-human-review"]
    schema_id: Literal["medical-schema67.v1"]
    workbook_sha256: Sha256Hex
    approval_status: Literal["EXPERT_APPROVED_NO_CHANGES"]
    approved_by: Literal["linyao"]
    authority_ref: Literal["user-message:019fda9b-schema67-approved-no-changes"]
    fields: tuple[ApprovedFieldRowV1, ...]
    schema_rows_sha256: Sha256Hex
    ordered_field_ids_sha256: Sha256Hex
    snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_approved_snapshot(self) -> Self:
        if (
            self.workbook_sha256 != APPROVED_WORKBOOK_SHA256
            or self.authority_ref != EXACT_APPROVAL_AUTHORITY_REF
            or len(self.fields) != APPROVED_FIELD_COUNT
            or tuple(row.ordinal for row in self.fields)
            != tuple(range(1, APPROVED_FIELD_COUNT + 1))
            or tuple(row.field_id for row in self.fields) != APPROVED_ORDERED_FIELD_IDS
        ):
            raise ValueError("approved Schema67 identity mismatch")
        expected_schema = schema_rows_sha256(self.fields)
        expected_field_ids = ordered_field_ids_sha256(tuple(row.field_id for row in self.fields))
        expected_snapshot = approved_schema_snapshot_sha256(
            product_version_id=self.product_version_id,
            review_package_id=self.review_package_id,
            schema_id=self.schema_id,
            workbook_sha256=self.workbook_sha256,
            approval_status=self.approval_status,
            approved_by=self.approved_by,
            authority_ref=self.authority_ref,
            schema_rows_sha256_value=expected_schema,
            ordered_field_ids_sha256_value=expected_field_ids,
        )
        if (
            self.schema_rows_sha256 != expected_schema
            or expected_schema != APPROVED_SCHEMA_ROWS_SHA256
            or expected_field_ids != APPROVED_ORDERED_FIELD_IDS_SHA256
            or self.ordered_field_ids_sha256 != expected_field_ids
            or self.snapshot_sha256 != expected_snapshot
        ):
            raise ValueError("approved Schema67 digest mismatch")
        return self


class HardnessVectorV1(_FrozenModel):
    formation_modes: tuple[FormationMode, ...]
    value_shape: ValueShape
    source_count: PositiveInt
    cross_source: StrictBool
    evidence_required: StrictBool
    requires_rule_derivation: StrictBool
    requires_semantic_generation: StrictBool
    requires_external_authority: StrictBool
    band: HardnessBand
    vector_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_vector(self) -> Self:
        payload = _hardness_payload(
            formation_modes=self.formation_modes,
            value_shape=self.value_shape,
            source_count=self.source_count,
            cross_source=self.cross_source,
            evidence_required=self.evidence_required,
            requires_rule_derivation=self.requires_rule_derivation,
            requires_semantic_generation=self.requires_semantic_generation,
            requires_external_authority=self.requires_external_authority,
            band=self.band,
        )
        if self.vector_sha256 != canonical_hash(_HARDNESS_OBJECT_TYPE, payload):
            raise ValueError("hardness vector hash mismatch")
        return self


def _hardness_payload(
    *,
    formation_modes: tuple[FormationMode, ...],
    value_shape: ValueShape,
    source_count: int,
    cross_source: bool,
    evidence_required: bool,
    requires_rule_derivation: bool,
    requires_semantic_generation: bool,
    requires_external_authority: bool,
    band: HardnessBand,
) -> dict[str, object]:
    return {
        "formation_modes": formation_modes,
        "value_shape": value_shape,
        "source_count": source_count,
        "cross_source": cross_source,
        "evidence_required": evidence_required,
        "requires_rule_derivation": requires_rule_derivation,
        "requires_semantic_generation": requires_semantic_generation,
        "requires_external_authority": requires_external_authority,
        "band": band,
    }


def _derive_hardness(row: ApprovedFieldRowV1) -> HardnessVectorV1:
    external = "external_map" in row.formation_modes
    semantic = "llm_generate" in row.formation_modes or row.value_shape == "narrative"
    rule = "rule_derive" in row.formation_modes
    cross_source = len(row.source_roles) > 1
    if external:
        band: HardnessBand = "H3_EXTERNAL_AUTHORITY"
    elif semantic or cross_source:
        band = "H2_SEMANTIC"
    elif rule or row.value_shape in {"multi_select", "range", "table"}:
        band = "H1_BOUNDED"
    else:
        band = "H0_EXACT"
    payload = _hardness_payload(
        formation_modes=row.formation_modes,
        value_shape=row.value_shape,
        source_count=len(row.source_roles),
        cross_source=cross_source,
        evidence_required=row.evidence_required,
        requires_rule_derivation=rule,
        requires_semantic_generation=semantic,
        requires_external_authority=external,
        band=band,
    )
    return HardnessVectorV1(
        formation_modes=row.formation_modes,
        value_shape=row.value_shape,
        source_count=len(row.source_roles),
        cross_source=cross_source,
        evidence_required=row.evidence_required,
        requires_rule_derivation=rule,
        requires_semantic_generation=semantic,
        requires_external_authority=external,
        band=band,
        vector_sha256=canonical_hash(_HARDNESS_OBJECT_TYPE, payload),
    )


class FieldContractV1(_FrozenModel):
    ordinal: PositiveInt
    field_id: NonBlankStr
    field_name: NonBlankStr
    category: NonBlankStr
    description: NonBlankStr
    value_shape: ValueShape
    formation_modes: tuple[FormationMode, ...]
    source_roles: tuple[NonBlankStr, ...]
    evidence_required: StrictBool
    output_state_policy: Literal["evidence-gated-tristate.v1"]
    hardness: HardnessVectorV1
    field_contract_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_contract_hash(self) -> Self:
        payload = _field_contract_payload(self, include_hash=False)
        if self.field_contract_sha256 != canonical_hash(_FIELD_CONTRACT_OBJECT_TYPE, payload):
            raise ValueError("field contract hash mismatch")
        return self


def _field_contract_payload(value: FieldContractV1, *, include_hash: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "ordinal": value.ordinal,
        "field_id": value.field_id,
        "field_name": value.field_name,
        "category": value.category,
        "description": value.description,
        "value_shape": value.value_shape,
        "formation_modes": value.formation_modes,
        "source_roles": value.source_roles,
        "evidence_required": value.evidence_required,
        "output_state_policy": value.output_state_policy,
        "hardness": value.hardness.model_dump(mode="python"),
    }
    if include_hash:
        payload["field_contract_sha256"] = value.field_contract_sha256
    return payload


class FieldContractSetV1(_FrozenModel):
    product_version_id: Literal["596-1"]
    review_package_id: Literal["596-2-golden-human-review"]
    schema_id: Literal["medical-schema67.v1"]
    workbook_sha256: Sha256Hex
    approval_status: Literal["EXPERT_APPROVED_NO_CHANGES"]
    approved_by: Literal["linyao"]
    authority_ref: Literal["user-message:019fda9b-schema67-approved-no-changes"]
    schema_rows_sha256: Sha256Hex
    ordered_field_ids_sha256: Sha256Hex
    contracts: tuple[FieldContractV1, ...]
    contract_set_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_contract_set(self) -> Self:
        if (
            len(self.contracts) != APPROVED_FIELD_COUNT
            or tuple(item.ordinal for item in self.contracts)
            != tuple(range(1, APPROVED_FIELD_COUNT + 1))
            or tuple(item.field_id for item in self.contracts) != APPROVED_ORDERED_FIELD_IDS
            or self.schema_rows_sha256 != APPROVED_SCHEMA_ROWS_SHA256
            or self.ordered_field_ids_sha256 != APPROVED_ORDERED_FIELD_IDS_SHA256
            or self.authority_ref != EXACT_APPROVAL_AUTHORITY_REF
        ):
            raise ValueError("field contract set is not exact Schema67")
        payload = _contract_set_payload(self, include_hash=False)
        if self.contract_set_sha256 != canonical_hash(_CONTRACT_SET_OBJECT_TYPE, payload):
            raise ValueError("field contract set hash mismatch")
        return self


def _contract_set_payload(value: FieldContractSetV1, *, include_hash: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "product_version_id": value.product_version_id,
        "review_package_id": value.review_package_id,
        "schema_id": value.schema_id,
        "workbook_sha256": value.workbook_sha256,
        "approval_status": value.approval_status,
        "approved_by": value.approved_by,
        "authority_ref": value.authority_ref,
        "schema_rows_sha256": value.schema_rows_sha256,
        "ordered_field_ids_sha256": value.ordered_field_ids_sha256,
        "contracts": tuple(
            _field_contract_payload(item, include_hash=True) for item in value.contracts
        ),
    }
    if include_hash:
        payload["contract_set_sha256"] = value.contract_set_sha256
    return payload


def compile_schema_contracts(snapshot: ApprovedSchemaSnapshotV1) -> FieldContractSetV1:
    """Compile one already-approved snapshot without reading XLSX or candidate values."""

    try:
        if type(snapshot) is not ApprovedSchemaSnapshotV1:
            raise TypeError("snapshot must use exact DTO")
        checked = ApprovedSchemaSnapshotV1.model_validate(
            snapshot.model_dump(mode="python", round_trip=True)
        )
        contracts: list[FieldContractV1] = []
        for row in checked.fields:
            hardness = _derive_hardness(row)
            draft = FieldContractV1.model_construct(
                ordinal=row.ordinal,
                field_id=row.field_id,
                field_name=row.field_name,
                category=row.category,
                description=row.description,
                value_shape=row.value_shape,
                formation_modes=row.formation_modes,
                source_roles=row.source_roles,
                evidence_required=row.evidence_required,
                output_state_policy="evidence-gated-tristate.v1",
                hardness=hardness,
                field_contract_sha256="0" * 64,
            )
            contracts.append(
                FieldContractV1(
                    ordinal=row.ordinal,
                    field_id=row.field_id,
                    field_name=row.field_name,
                    category=row.category,
                    description=row.description,
                    value_shape=row.value_shape,
                    formation_modes=row.formation_modes,
                    source_roles=row.source_roles,
                    evidence_required=row.evidence_required,
                    output_state_policy="evidence-gated-tristate.v1",
                    hardness=hardness,
                    field_contract_sha256=canonical_hash(
                        _FIELD_CONTRACT_OBJECT_TYPE,
                        _field_contract_payload(draft, include_hash=False),
                    ),
                )
            )
        exact_contracts = tuple(contracts)
        draft_set = FieldContractSetV1.model_construct(
            product_version_id=checked.product_version_id,
            review_package_id=checked.review_package_id,
            schema_id=checked.schema_id,
            workbook_sha256=checked.workbook_sha256,
            approval_status=checked.approval_status,
            approved_by=checked.approved_by,
            authority_ref=checked.authority_ref,
            schema_rows_sha256=checked.schema_rows_sha256,
            ordered_field_ids_sha256=checked.ordered_field_ids_sha256,
            contracts=exact_contracts,
            contract_set_sha256="0" * 64,
        )
        return FieldContractSetV1(
            product_version_id=checked.product_version_id,
            review_package_id=checked.review_package_id,
            schema_id=checked.schema_id,
            workbook_sha256=checked.workbook_sha256,
            approval_status=checked.approval_status,
            approved_by=checked.approved_by,
            authority_ref=checked.authority_ref,
            schema_rows_sha256=checked.schema_rows_sha256,
            ordered_field_ids_sha256=checked.ordered_field_ids_sha256,
            contracts=exact_contracts,
            contract_set_sha256=canonical_hash(
                _CONTRACT_SET_OBJECT_TYPE,
                _contract_set_payload(draft_set, include_hash=False),
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise SchemaFirstContractError("SCHEMA_SNAPSHOT_INVALID") from None


class GenericEvidenceReceiptRefV1(_FrozenModel):
    contract: Literal["freeform-arm-evidence-binding-receipt.v1"]
    fact_key: Annotated[StrictStr, StringConstraints(pattern=r"^generic/[a-z0-9][a-z0-9._-]*$")]
    state: TriState
    receipt_sha256: Sha256Hex


class GenericFactEnvelopeV1(_FrozenModel):
    contract: Literal["generic-fact-envelope.v1"]
    product_version_id: NonBlankStr
    source_revision_id: NonBlankStr
    fact_key: Annotated[StrictStr, StringConstraints(pattern=r"^generic/[a-z0-9][a-z0-9._-]*$")]
    formal_field_id: None = None
    state: TriState
    value_snapshot: NonBlankStr | None
    evidence_receipts: tuple[GenericEvidenceReceiptRefV1, ...]
    release_eligible: Literal[False]
    envelope_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_non_authoritative_state_and_hash(self) -> Self:
        _validate_generic_state(
            fact_key=self.fact_key,
            state=self.state,
            value_snapshot=self.value_snapshot,
            evidence_receipts=self.evidence_receipts,
        )
        payload = _generic_fact_payload(self, include_hash=False)
        if self.envelope_sha256 != canonical_hash(_GENERIC_FACT_OBJECT_TYPE, payload):
            raise ValueError("generic fact hash mismatch")
        return self


def _validate_generic_state(
    *,
    fact_key: str,
    state: TriState,
    value_snapshot: str | None,
    evidence_receipts: tuple[GenericEvidenceReceiptRefV1, ...],
) -> None:
    keys = tuple((item.fact_key, item.state, item.receipt_sha256) for item in evidence_receipts)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("generic Evidence receipts must be canonical and unique")
    if any(item.fact_key != fact_key or item.state != state for item in evidence_receipts):
        raise ValueError("generic Evidence receipt binding mismatch")
    if state == "unknown":
        if value_snapshot is not None or evidence_receipts:
            raise ValueError("unknown generic fact cannot carry value or Evidence")
    elif state == "present":
        if value_snapshot is None or not evidence_receipts:
            raise ValueError("present generic fact requires value and Evidence")
    elif value_snapshot is not None or not evidence_receipts:
        raise ValueError("explicit absence requires Evidence and no value")


def _generic_fact_payload(value: GenericFactEnvelopeV1, *, include_hash: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract": value.contract,
        "product_version_id": value.product_version_id,
        "source_revision_id": value.source_revision_id,
        "fact_key": value.fact_key,
        "formal_field_id": value.formal_field_id,
        "state": value.state,
        "value_snapshot": value.value_snapshot,
        "evidence_receipts": tuple(
            item.model_dump(mode="python") for item in value.evidence_receipts
        ),
        "release_eligible": value.release_eligible,
    }
    if include_hash:
        payload["envelope_sha256"] = value.envelope_sha256
    return payload


def build_generic_fact_envelope(
    *,
    product_version_id: str,
    source_revision_id: str,
    fact_key: str,
    state: TriState,
    value_snapshot: str | None,
    evidence_receipts: tuple[GenericEvidenceReceiptRefV1, ...],
) -> GenericFactEnvelopeV1:
    try:
        draft = GenericFactEnvelopeV1.model_construct(
            contract="generic-fact-envelope.v1",
            product_version_id=product_version_id,
            source_revision_id=source_revision_id,
            fact_key=fact_key,
            formal_field_id=None,
            state=state,
            value_snapshot=value_snapshot,
            evidence_receipts=evidence_receipts,
            release_eligible=False,
            envelope_sha256="0" * 64,
        )
        return GenericFactEnvelopeV1(
            contract="generic-fact-envelope.v1",
            product_version_id=product_version_id,
            source_revision_id=source_revision_id,
            fact_key=fact_key,
            formal_field_id=None,
            state=state,
            value_snapshot=value_snapshot,
            evidence_receipts=evidence_receipts,
            release_eligible=False,
            envelope_sha256=canonical_hash(
                _GENERIC_FACT_OBJECT_TYPE,
                _generic_fact_payload(draft, include_hash=False),
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise SchemaFirstContractError("GENERIC_FACT_STATE_INVALID") from None


__all__ = [
    "APPROVED_FIELD_COUNT",
    "APPROVED_BY",
    "APPROVED_ORDERED_FIELD_IDS",
    "APPROVED_ORDERED_FIELD_IDS_SHA256",
    "APPROVED_PRODUCT_VERSION_ID",
    "APPROVED_REVIEW_PACKAGE_ID",
    "APPROVED_SCHEMA_ID",
    "APPROVED_SCHEMA_ROWS_SHA256",
    "APPROVED_WORKBOOK_SHA256",
    "ApprovedFieldRowV1",
    "ApprovedSchemaSnapshotV1",
    "FieldContractSetV1",
    "FieldContractV1",
    "FormationMode",
    "GenericEvidenceReceiptRefV1",
    "GenericFactEnvelopeV1",
    "HardnessVectorV1",
    "SchemaFirstContractError",
    "TriState",
    "ValueShape",
    "approved_schema_rows",
    "approved_schema_snapshot_sha256",
    "build_generic_fact_envelope",
    "compile_schema_contracts",
    "ordered_field_ids_sha256",
    "schema_rows_sha256",
]

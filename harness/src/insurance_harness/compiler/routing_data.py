"""抽取路由数据（004 T2；spec E2.3——独立数据模块，只含数据不含逻辑）。

来源（06-asset-migration.md 移植清单，移植方式=数据翻译，不复制 GPL 代码逻辑）：
- ``GROUP_ORDER`` / ``GROUP_KEYWORDS``：A5，译自 LLM-wiki-black
  ``frontend/src/lib/product-catalog-extractor.ts:2923-2945``（GROUP_ORDER / GROUP_KEYWORDS）；
- ``FIELD_NAME_ALIASES`` / ``FIELD_EVIDENCE_KEYWORDS``：A8，译自同文件 ``:150-307``
  （FIELD_NAME_ALIASES / FIELD_EVIDENCE_KEYWORDS），是定向补漏 pass 的同义词库种子；
- ``FIELD_NAME_TO_GROUP``：字段→组桥接（A2/A7 思想：模块分组数据译自
  ``frontend/src/lib/product-catalog-modules.ts:259-446``，按 schema 基线 v1.1 的
  字段名逐一桥接到 7 个抽取组；schema 中不存在于旧系统的新字段按同组语义归类）。

7 组语义（06 §3.1）：basic_info（基础信息/投保约束/时间周期）、coverage（保险责任，
扫描全部章节）、cost_rules（免赔/费率/续保/赔付比例）、exclusion_uw（免责与核保）、
claim_service（理赔与增值服务）、contract_admin（退保/复效/变更）、
disease_definition（疾病释义，内容最长、放最后）。
"""

import re
from typing import Final

# 组间处理顺序：basic_info 优先（多在文首），疾病释义最后（最长）——GROUP_ORDER 数据翻译
GROUP_ORDER: Final[tuple[str, ...]] = (
    "basic_info",
    "coverage",
    "cost_rules",
    "exclusion_uw",
    "claim_service",
    "contract_admin",
    "disease_definition",
)

# 组关键词路由正则源（GROUP_KEYWORDS 数据翻译；None = 扫描全部章节）。
# 实测效果：无关章节不进该组 LLM 调用，旧系统降约 70% 调用量（06 §3.3）。
_GROUP_KEYWORD_SOURCES_004: Final[dict[str, str | None]] = {
    "basic_info": (
        r"险种|产品|保险期|保险期间|交费|保障期|保障期间|投保|承保|年龄|简称|代码|主险|附加"
        r"|公司|计划|等待期|无等待期|犹豫期|宽限期|豁免|重新投保|届满|合同解除|退保"
    ),
    "coverage": None,  # 保险责任分布最广，扫描全部章节
    "cost_rules": r"免赔|费率|保费|费用|赔付|比例|限额|给付|计算|上浮|社保",
    "exclusion_uw": r"免除|免责|除外|既往|告知|核保|拒保|加费|延期|健康",
    "claim_service": r"理赔|报案|材料|垫付|绿通|就医|服务|赔付|给付|申请",
    "contract_admin": r"退保|复效|变更|受益人|投保人|解除|犹豫|终止|中止",
    "disease_definition": r"疾病|释义|定义|恶性|肿瘤|心肌|脑|重大|中症|轻度|轻症",
}

# 005 V6.1：漏抽归因驱动的零成本路由关键词补充（openspec/changes/005 validation-report
# 有 before/after 对比）。与 004 基线分开存放，保证归因工具能复算修复前路由：
# - basic_info：费率表首页的"交费期限"证据（趸交/年交费率表版式）密度不足未路由；
# - claim_service："保险金申请材料"条目式短章节（材料/申请仅 2 个不同关键词）未过
#   distinct_min=3——补充理赔材料清单的强特征词（入出院记录/出院小结/结算清单）。
# 补充后 13 份样本条款压缩比仍全部 ≤0.40（E2.2 预算复验见 005 报告，V6.2）。
GROUP_KEYWORD_SUPPLEMENTS_005: Final[dict[str, tuple[str, ...]]] = {
    "basic_info": ("趸交", "费率表"),
    "claim_service": ("入出院记录", "出院小结", "结算清单"),
}


def compile_group_keywords(
    supplements: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, re.Pattern[str] | None]:
    """由 004 基线关键词源（可选叠加补充词）编译组路由正则（005 V6.1）。"""
    out: dict[str, re.Pattern[str] | None] = {}
    for group, source in _GROUP_KEYWORD_SOURCES_004.items():
        if source is None:
            out[group] = None
            continue
        extra = (supplements or {}).get(group, ())
        pattern = "|".join((source, *extra)) if extra else source
        out[group] = re.compile(pattern)
    return out


# 004 基线路由（漏抽归因工具复算"修复前"用）
GROUP_KEYWORDS_004: Final[dict[str, re.Pattern[str] | None]] = compile_group_keywords()

# 当前生效路由 = 004 基线 + 005 补充
GROUP_KEYWORDS: Final[dict[str, re.Pattern[str] | None]] = compile_group_keywords(
    GROUP_KEYWORD_SUPPLEMENTS_005
)

# 字段名（schema 基线 v1.1 中文名）→ 抽取组桥接。
# 依据旧系统模块分组（product-catalog-modules.ts）：字段随其归属模块的组走；
# schema v1.1 新增字段按同组语义归类（如"演示利率口径"随费率/演示类 → cost_rules）。
FIELD_NAME_TO_GROUP: Final[dict[str, str]] = {
    # --- basic_info：产品基础信息 / 投保约束 / 时间周期 ---
    "险种代码": "basic_info",
    "险种简称": "basic_info",
    "险种名称": "basic_info",
    "产品别称": "basic_info",
    "开始使用时间": "basic_info",
    "结束使用时间": "basic_info",
    "产品类别": "basic_info",
    "产品类型": "basic_info",
    "销售渠道": "basic_info",
    "发布外网": "basic_info",
    "销售状态": "basic_info",
    "销售地区限制": "basic_info",
    "主附加险": "basic_info",
    "是否附加险": "basic_info",
    "产品简介": "basic_info",
    "产品特色": "basic_info",
    "QA": "basic_info",
    "适用人群": "basic_info",
    "可享服务": "basic_info",
    "交费期限": "basic_info",
    "交费方式": "basic_info",
    "犹豫期": "basic_info",
    "等待期": "basic_info",
    "等待期内出险处理": "basic_info",
    "宽限期": "basic_info",
    "产品搭配规则": "basic_info",
    "保障期间": "basic_info",
    "保障期间分类": "basic_info",
    "投保年龄": "basic_info",
    "投保范围": "basic_info",
    "投保职业": "basic_info",
    "投保门槛低": "basic_info",
    "保障人群": "basic_info",
    "高危职业": "basic_info",
    "产品档次": "basic_info",
    "保单件数": "basic_info",
    "退保率": "basic_info",
    "双被保人": "basic_info",
    "契调限制": "basic_info",
    "生效时间": "basic_info",
    "条款备案/批复文号": "basic_info",
    "条款版本标识": "basic_info",
    "条款生效日期": "basic_info",
    "购买限制": "basic_info",
    "投被保人豁免": "basic_info",  # 豁免关键词在 basic_info 组（GROUP_KEYWORDS 含"豁免"）
    "豁免条件": "basic_info",
    "保险期间和续保": "basic_info",
    # --- coverage：保险责任 ---
    "保什么": "coverage",
    "可覆盖风险": "coverage",
    "保单权益": "coverage",
    "癌症医疗": "coverage",
    "津贴": "coverage",
    "住院津贴": "coverage",
    "重疾赔付": "coverage",
    "疾病分组": "coverage",
    "赔付次数": "coverage",
    "多次赔付间隔期": "coverage",
    "恶性肿瘤二次赔条件": "coverage",
    "满期返还": "coverage",
    "轻中重症疾病种类": "coverage",
    "运动达标涨保障": "coverage",
    "特殊保额": "coverage",
    "特疾": "coverage",
    "特定疾病": "coverage",
    "轻症特定疾病": "coverage",
    "中症特定疾病": "coverage",
    "重症特定疾病": "coverage",
    "意外身故": "coverage",
    "意外伤残": "coverage",
    "意外医疗": "coverage",
    "综合意外": "coverage",
    "公共交通意外额外给付": "coverage",
    "全残保障": "coverage",
    "疾病身故": "coverage",
    "身故责任": "coverage",
    "身故保险金口径": "coverage",
    "最高保额": "coverage",
    "教育金": "coverage",
    "养老金": "coverage",
    "保证领取": "coverage",
    "领取规则": "coverage",
    "领取期间": "coverage",
    "年金领取起始年龄": "coverage",
    "领钱时间早": "coverage",
    "医院范围": "coverage",
    "护理保险金给付条件": "coverage",
    "护理保险金给付期限": "coverage",
    "护理保险金领取方式与规则": "coverage",
    "收入损失保险金给付条件": "coverage",
    "收入损失保险金给付期限": "coverage",
    "收入损失保险金领取方式与规则": "coverage",
    "收入损失关爱金给付条件": "coverage",
    "收入损失关爱金给付期限": "coverage",
    "收入损失关爱金领取方式与规则": "coverage",
    "特定疾病关爱金给付条件": "coverage",
    "特定疾病关爱金给付期限": "coverage",
    "特定疾病关爱金领取方式与规则": "coverage",
    "外购药/特药责任": "coverage",
    # --- cost_rules：免赔 / 费率 / 续保 / 赔付比例 ---
    "免赔额": "cost_rules",
    "0免赔": "cost_rules",
    "报销比例": "cost_rules",
    "报销范围": "cost_rules",
    "报销门诊住院范围": "cost_rules",
    "给付限额": "cost_rules",
    "补偿原则": "cost_rules",
    "不限社保": "cost_rules",
    "费率可调": "cost_rules",
    "费用": "cost_rules",
    "保证续保": "cost_rules",
    "保证续保期": "cost_rules",
    "停售后续保安排": "cost_rules",
    "起投金额": "cost_rules",
    "额度类型": "cost_rules",
    "有分红": "cost_rules",
    "红利分配方式": "cost_rules",
    "演示利率口径": "cost_rules",
    "产品利率": "cost_rules",
    "保证利率": "cost_rules",
    "初始费用": "cost_rules",
    "领取手续费": "cost_rules",
    # --- exclusion_uw：免责与核保 ---
    "责任免除": "exclusion_uw",
    "特殊免责": "exclusion_uw",
    "免责少": "exclusion_uw",
    "健康告知": "exclusion_uw",
    "核保方式": "exclusion_uw",
    "既往症定义与处理": "exclusion_uw",
    # --- claim_service：理赔与增值服务 ---
    "理赔件数": "claim_service",
    "理赔金额": "claim_service",
    "理赔申请时效与申请材料": "claim_service",
    "增值服务": "claim_service",
    "失能状态核验": "claim_service",
    "伤残评定标准": "claim_service",
    # --- contract_admin：退保 / 复效 / 变更 ---
    "犹豫期及合同解除（退保）": "contract_admin",
    "复效条款": "contract_admin",
    "部分领取": "contract_admin",
    "高流动性": "contract_admin",
    "保单贷款": "contract_admin",
    "现金价值": "contract_admin",
    "减额缴清": "contract_admin",
    "万能账户": "contract_admin",
    "险种转换": "contract_admin",
    "是否可加保": "contract_admin",
    # --- disease_definition：疾病释义 ---
    "疾病定义标准版本": "disease_definition",
    "特定疾病释义及对应丧失工作能力状态认定标准": "disease_definition",
}

# 字段别名（FIELD_NAME_ALIASES 数据翻译；补漏 pass 同义词检索用）
FIELD_NAME_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "意外豁免": ("无等待期情形", "等待期豁免情形", "无等待期/等待期豁免情形"),
    "保什么": ("保险责任", "保障责任", "保障内容", "我们保什么", "保险金责任"),
    "全残保障": ("全残保险金", "身体全残保险金", "全残责任", "身体全残责任"),
    "意外身故": ("意外身故保险金", "意外死亡保险金"),
    "疾病身故": ("疾病身故保险金", "非意外身故保险金"),
}

# 字段证据关键词（FIELD_EVIDENCE_KEYWORDS 数据翻译；补漏 pass 候选章节检索种子）
FIELD_EVIDENCE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "疾病等待期": ("等待期", "无等待期", "意外伤害", "重新投保", "上一保险期间", "届满",
                   "60日", "指定", "审核同意", "恶性肿瘤", "合同终止", "返还", "不承担"),
    "等待期": ("等待期", "30日", "天", "日"),
    "意外豁免": ("无等待期", "等待期豁免", "意外伤害", "重新投保", "上一保险期间", "届满",
                 "60日", "指定", "审核同意"),
    "等待期内出险处理": ("等待期内", "不承担", "给付保险金", "恶性肿瘤", "返还", "合同终止",
                        "一般疾病"),
    "犹豫期": ("犹豫期", "退保", "解除合同", "扣除", "无息退还"),
    "宽限期": ("宽限期", "60日", "逾期", "保险费"),
    "投保年龄": ("投保年龄", "出生", "周岁", "最低", "最高"),
    "产品别称": ("简称", "别称", "别名", "俗称", "推广名", "产品简称"),
    "产品简介": ("产品提供", "保障", "保险责任", "阅读指引", "产品"),
    "产品特色": ("产品特色", "产品亮点", "核心优势", "保障亮点", "特色保障", "产品优势"),
    "QA": ("Q&A", "QA", "问答", "常见问题", "客户问", "问：", "答：", "如何解释", "异议", "话术"),
    "保单权益": ("重要权益", "保单贷款", "自动垫交", "退保", "现金价值", "受益人"),
    "投保范围": ("投保范围", "被保险人", "投保年龄", "周岁"),
    "保障人群": ("投保年龄", "被保险人", "周岁"),
    "高流动性": ("保单贷款", "现金价值", "减保", "部分领取", "退保"),
    "部分领取": ("部分领取", "减保", "领取", "账户价值"),
    "保证领取": ("保证给付", "领取期间内身故", "养老保险金总额", "已给付"),
    "领取规则": ("领取方式", "一次性领取", "年领", "月领", "领取期间"),
    "领取期间": ("领取期间", "10年", "20年", "届满"),
    "养老金": ("养老保险金", "给付", "领取方式", "基本保险金额"),
    "保单贷款": ("保单贷款", "贷款金额", "现金价值", "贷款期限", "贷款利率"),
    "身故责任": ("保险责任", "身故保险金", "被保险人身故", "给付", "基本保险金额",
                 "所交保险费", "已交保险费", "现金价值", "合同终止"),
    "保什么": ("保险责任", "我们保什么", "保什么", "身故保险金", "全残保险金", "意外身故",
               "疾病身故", "给付", "基本保险金额", "现金价值"),
    "全残保障": ("全残", "身体全残", "全残保险金", "全残保障"),
    "意外身故": ("意外身故", "意外伤害", "身故保险金"),
    "疾病身故": ("疾病身故", "非意外身故", "身故保险金"),
    # 三态硬约束的豁免类核心字段（05 §、坑清单 #5）
    "投被保人豁免": ("豁免", "免交保险费", "免除交费义务", "保费豁免", "无需再交", "轻症", "重疾"),
    "豁免条件": ("豁免", "免交保险费", "免除交费义务", "保费豁免", "无需再交"),
}


def group_of_field(field_name: str) -> str:
    """字段名 → 抽取组；未登记的字段回落 coverage（全章节扫描，宁多勿漏）。"""
    return FIELD_NAME_TO_GROUP.get(field_name, "coverage")

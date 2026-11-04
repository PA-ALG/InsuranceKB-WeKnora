# SK-5：方法机器准入与产品信息

Issue #542；实现 Codex，审核 Claude；`slice/sk5`。依据蓝图 §5/6.2/7.3/7.5、SK-0 §3/5.4、SK-2/2b/2c/3，
以及 #542 用户 2026-11-04 校准裁定。本片真实调用/线上写入为 0；合并与上线不是本次实施动作。

## 1. 范围与设计

用户接受 4 方法/20 点业务校准结果，允许方法原文证据通过且不含产品信息的 present 点、合法 unknown 点机器决定。
只准入 `methods_sales`；不把该校准推广到产品 pack，不把评判分数转成人工事实或伪造独立模型分数。
产品信息原值保留，人工审核，方法提示仍为“以条款与已发布知识为准”，日期仍读来源。

采用版本化确定性路由及现有 Candidate/Decision/Release；不新建审核系统，不修改平台或合同。
平台服务密钥的 points/decisions 只允许 reject；机器 approve 是整包，所以不能对混合包直接整包机器决定。
§5 两阶段衔接已由 Owner 在 #542 评论 6629893889 确认（方案评论 6629870390），不改平台/合同。

## 2. 产品信息信号

方法卡版本 `2026-11-04.1`；新增 `product_info_terms`，首批通用责任词：理赔、赔付、报销、给付、保额、保费、免赔、等待期。
字段为非空且无重复的字符串序列。命中信号代码 `responsibility`；并列保留金额/比例/年龄/产品名信号，不按优先级互相覆盖。
词表是保守的人工路由提示，不判断责任真假；否定句同样标记，不删“不得/不能/不”等否定，也不改数字、百分号或比较符。
规则只扫描 Claim 值（文本或列表每项），不从引文、方法名或评判意见推填结果。

名称来自登记 `products[*].names` 全部名称（该字段已包含批准别名）；不从材料标题猜简称，不维护手写产品词表。
≥4 字名称保留原 NFKC/去空白后的包含匹配；1–3 字短名按 NFKC 后保留空白的文本匹配，左右必须是文本边界或非 Unicode
字母/数字/下划线（合成反例含中文长词、字母数字黏连）。别名本身的空白折叠；不做中文分词猜测；短名嵌在未分隔长句内
可能漏掉，由责任词与后续人工抽检兜底，不能声称语义全覆盖。私用排版码位按现有 fold 忽略。

标记单位是 Claim：列表任一项命中，该点整体人工，所有项和逐项 Evidence 原样保留。实体提示取“Active 旧 Claim + 本次
实际选入成员 − 实际 removals”的结果集合；KEEP/CONFLICT 保留的旧产品信息不能消失，替换/撤回后才随实际值移除。
报告同时列每个有效点的信号及本次路由，不将未提交的新回答替代保留旧值。

## 3. 政策、证据与身份

ReviewPolicy 升到 `4`：`admitted_packs=[methods_sales]`，`thresholds={}`；新增通用数据字段
`source_supported_packs=[methods_sales]`，必须是 admitted_packs 子集，唯一、非空名称。缺少该字段的旧政策按空集合读，
不会取得新能力。产品既有独立评分 route 不使用该字段；缺门槛/评分仍人工，其他 pack 未准入。

方法专用路由只在当前默认政策身份及此 pack 两项准入均满足时启用；非当前政策、卡片规则版本不符、冲突、expert_lock、
撤回/移出或无合法证据均人工。机器 present 必须 SOURCE_SUPPORTED、非空文本或非空字符串列表，列表逐项证据等长，
原始 source_ref/SHA 一致、quote hash 正确、非专家定位、TrustPolicy 限定的方法谓词。既有 compile 从固定 RAW 回验得到
证据；路由本身不冒充新原文读取，平台 #523 仍最终回验。无法取值/结构无效的整个方法保持 skipped，不伪造 unknown。
合法 unknown 必须无值/无证据、有 typed reason；包括编译丢完项后的 EXTRACTION_FAILED，只发布“未知”，不补成事实。
变更判定仍先行；UNCHANGED/KEEP 不重发旧 Claim，CONFLICT 不自动覆盖。旧版本升级 unknown 造成原事实撤除仍留人工。

机器候选 Claim 的 review.mode=machine、reviewer=版本化政策标识，score/reviewed_at 不捏造；这是候选路由标签。
真正的机器决定由合并后运维使用服务密钥与同 policy_ref 记录，审批主体/时间属于平台，不记为 human。
人工候选 review.mode=human、无政策批准或伪造分数；混合计划不可直接当机器整包执行。

新卡版本影响方法编译器身份及展示配置，但五张取值卡、提示、协议 `2026-11-01.2` 不改；路由词表/卡版本不在方法请求中。
同名称/材料/段落/标签的请求 system/user 字节不变，旧 LedgerAnswers 仍须完整核请求体 SHA、回答 bytes SHA、stage/model。
不修改旧回答/账本，缺失/篡改/新身份按既有规则停或报告缺回答，绝不补发；不改变产品编译身份。

## 4. 离线编译选择与报告

`compile_methods(..., review_route="all"|"machine"|"human")`，默认 all；CLI 同名 `--review-route`。
先完整准入、取值、变化判定及逐点路由，再选择本次成员。machine 只选合法机器点，不选 removals/冲突；human 只选人工点及
人工 removals；all 用于完整检查。只在有实际变化的主体携必要实体/展示配置，实体 notice 按选入后的实际投影重算。
不生成依赖人工成员才能满足闭包的机器包；仅元数据变化且无可机器 Claim 的主体保留人工，不借陪同实体旁路。
report 记录 route selection、policy_ref、每点 mode/reasons/signals、有效集 present/unknown/标记数量，全部不含值/引文。
三份计划的 report-last/摘要完整性、登记在计划之后、提交回执 contentSHA/Space、同内容幂等保持。
compile --live 仍仅 submit，不 Decide/Activate；all 混合路由时 typed 拒绝 live 提交并要求明确选择。

## 5. 旧候选与合并后上线计划（本片不执行）

1. 固定批准 Harness head、登记/候选/回答身份、原候选 ID/digest/成员/点集合和当前 Head；核旧 145 点仍全 pending，
   未有人工/机器决定或 Release。任意已处理点、内容或来源变化均停报，不能重写历史。
2. 按版本化 policy_ref 将旧包点全部机器 reject，理由为新规则替代，保留原包/回答；回执未知先 GET detail 对账，
   确认全 rejected 且未产生 Release 后才继续。不能伪造“用户已在页面点过”。
3. 当前基线上生成 machine 子集，人工点不入包；用独立 run-root 保存计划/提交/决定/激活回执；同结果重跑先核
   内容摘要/Space/基线/发布 digest，结果未知先对账，不能盲目再批准另一个候选。旧包未确认关闭不得提新包。
4. 机器包成功发布并读回精确成员/机器标识后，用新 Head 离线重编 human 余项并提交；机器已发布同值走 UNCHANGED，
   不重复挂点。人工包只含剩余变化与必要陪同实体，须基于刚核对的 Active；Head 冲突重新比对，未发布内容不作已知。
5. 来源/租户/Space/读取 Release 权限等原平台检查不变。人工余项留用户页面；读侧与至多 8 次平台 QA 只在后续派工预算内。
   此阶段无平台接口/存储/自动运维状态机改动；未知结果恢复由运维逐阶段回执和现有 API 对账，不宣称 exactly-once。

## 6. 写域与计划

- 本 Spec 独立提交。
- 新 RED：`harness/tests/compilers/methods/test_method_admission_policy.py`（信号/政策/来源与请求身份）；
  `test_method_review_selection.py`（实际 compile、两阶段投影/KEEP/CONFLICT/恢复）。必要命令反控置于后者或新独立文件。
- 运行源码：`catalog/method_cards.{py,json}`、`catalog/review_policy.{py,json}`；
  `compilers/methods/product_info.py`、`compile.py`、`cli.py`，新增 `compilers/methods/review.py`（路由/源约束/选择）。
- 保护测试独立修正：`tests/catalog/test_review_policy_pilot.py` 的政策版本/pack集合；
  `tests/compilers/methods/test_method_cards.py` 新责任信号并存预期；`test_method_changes.py`、`test_method_compile.py`、
  `test_method_compile_live.py` 的已过时“methods 未准入/全人工”预期。原身份、原文、变化/恢复断言保留，逐笔 PR 披露。
- 不改蓝图、其他 Spec、引文/变化判定/共享产品路由、平台/前端、合同、守卫/基线、Golden、提示/协议、模型配置或私有原件。

步骤：冻结 Spec → 单独 RED 并核旧失败/正控 → 独立保护政策预期修正 → 最小实现 → 本片+methods/review/catalog 定向，
ruff/mypy/contracts-check/architecture → fetch/merge main（不 rebase）→ PR Closes #542 → 精确 CI 绿交 Claude。
全量/PG/build 由 CI 覆盖，不新增真实调用。单个手写文件不超过 500 行。

## 7. 验收与证据限制

- 短名边界、长名/别名、金额比例年龄、否定与数字符号保留；八个责任词均通用合成正控，普通方法负控；源数据版本与
  未授权内容未改，模型请求同字节，合法保存回答零调用复用，篡改拒绝。
- 只 admit methods；旧策略/缺策略/缺证/非源码/错 hash/错来源/非方法角色/无值/全丢项/锁/冲突分别反控；其他 pack 原路由不变。
- mixed all、machine、human 选项；相同谓词不重复；机器部分不带人工事实；阶段一 Active 到阶段二余项的基线/成员/提示正确；
  KEEP/CONFLICT 旧信息不被清空；合法 replacement 提示消失；CLI 不调用 Decide/Activate、计划失败登记不变。
- 私有保存件只读：实际候选与点快照、评判输入一致性；R1–R4 匿名映射分别核；29 方法/145 点、present 分母、旧新标记数、
  各信号重叠与路由数。>50% present 被标或材料不完整先停报，不删词压比例。不公开原文/路径/标识，输入摘要留私有证据。
- 校准与确定性词表不证明语义全覆盖；原文核验只证明出处，不能保证概括正确。工程通过不代表线上已发布或 QA 通过。

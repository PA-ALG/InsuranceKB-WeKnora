# PB-A2：无书名号费率标题与无标题材料

Issue #571；Codex 实现，Claude 审核。基线 `7ac744afca06521bb258de0931a52c70bac5557a`。
依据蓝图 §6.1、§7.3、§8，PB-A1 规则 4，#497 的更正说明；Owner 裁定 #571 评论 6879091033。
本片模型、embedding、QA、线上平台请求与操作全部为 0。

## 1. 授权边界

首行与内容流后部的已有标题合成一条规则：仅前两页的完整单行。6份所谓无标题材料经原件核对均有标题，
本片不实现真正无标题归属或 #497 来源辅助归属；缺锚点继续隔离。
不改编译、字段卡、取值协议、TrustPolicy、材料角色数据、登记格式或平台合同。

## 2. 合并规则（Owner 已裁定）

1. 原有重复文件、人工指定、条款编码、开头及带书名号标题与多名称检查优先；已命中的判定保持原样。
   原开头及带书名号标题均未匹配到登记名称、且角色为 `rate_table` 或尚未确定时，才补充读无书名号标题。
   候选整行只作为 `role_of(..., more)` 追加信号，最终必须确定为 `rate_table`；文件名与文字双信号
   仍必需。混合信号不能被覆盖；条款/说明书角色不进入新增路径。
2. 只逐行检查 `Upload.head` 的前两页文本；不拼相邻行或跨页拼名称。现有生产入口
   `material_pages` 验证固定修订/SHA并排序，`head_text` 只取前两页、以换行保留页边界。新增路径先
   `splitlines()` 再规范化；直接 `attribute()` 调用的 `head` 仍须满足既有“前两页”输入合同。
   使用现有文本规范化（NFKC、去空白与字体私用字符），不去除名称年份、括号或其他有效字符。
   不新增公司名/标签剥离逻辑。已有剥离与带书名号标题识别保持原行为。
3. 每个候选整行必须由一个登记名称、限定语、费率类文档词和 PB-A1 允许的括号方式说明组成。
   名称与 `RegisteredProduct.names` 中一个完整名称规范化后完全相等；不缩写、纠错或模糊匹配。
   限定语沿用 `title_line_qualifier_chars=16`，禁止 PB-A1 的书名号、句读、引号与“的”；
   原 `title_line_exclusions`（解释、否定、参照等）对整行继续生效。
   尾部通过既有 `title_pattern` 验证，避免新增第二套限定语规则。登记名后立即接括号的候选
   拒绝；登记全名自身完整含括号可以接受，非起始括号限定语仍允许。多个不同登记名都能作同一
   候选行前缀时隔离，不按最长前缀消歧（即使短名后的括号不能当限定语）。
4. 文档词是版本化数据 `unbracketed_rate_documents`：费率表、成本表、金额表；
   必须是现有 `title_line_documents` 的非空子集。不把说明书或现金价值表纳入新增路径。
   文件名与开头文字（包含 `more` 追加的完整标题行）的角色双信号仍必需；不新增“成本表”文件名角色关键词。
5. 新匹配与未命中登记名的原带书名号标题行一起送入既有冲突逻辑：多个产品仍待确认；登记名加另一未知标题
   仍隔离；编码指向其他产品仍隔离；同角色已有不同材料仍待确认。登记表顺序不改变结果。
   多个登记名称都能解释同一候选行时不按最长/第一个擅自消歧，即使这些名称是同一产品的别名。
6. 只确认已有产品，永不创建产品或版本。无登记名、两位年份缩写、否定/句读/过长限定语、
   句中提及和跨行/跨页拼合版式都不因本规则获得产品锚点。

策略版本升到 `2026-11-14.1`，basis 追加 PB-A2 原因。原决定保留自身 `policy_ref`，
本片不重判保存登记或运行 ingest。新旧回放比较除 `policy_ref` 外的完整 Attribution。

## 3. 写域与保护适配

| 路径 | 用途 |
|---|---|
| `harness/src/insurance_harness/identity/title_lines.py` | 逐完整行精确登记名匹配，复用标题后缀验证 |
| `harness/src/insurance_harness/identity/attribution.py` | 策略新数据字段/校验，已有流程的受限补充接线 |
| `harness/src/insurance_harness/identity/attribution_policy.json` | 新文档词数据、策略版本与原因 |
| `harness/tests/identity/test_unbracketed_rate_titles.py`（新） | 公开 attribute() 合成 RED |
| `harness/tests/ingest/test_rate_title_pages.py`（新） | 页数、边界、固定来源入口合成 RED |
| 本 Spec | Owner 合并裁定后的冻结设计 |

独立保护提交只替换下列“当前版本”字面量：`test_attribution.py` 2处、
`test_attribution_title_lines.py` 2处、`test_attribution_policy_versioning.py` 1处、
`test_rider_classification.py` 1处、`test_attribution_deferred_layouts.py` 1处。
不改任何判断结构、历史版本、夹具材料或其他断言。理由先在 Issue 披露。
主模块已有497行；只压缩与本职责有关的说明文字，保留语义，不拆出空壳兼容层。

## 4. 验收与执行计划

执行使用 TDD 与 executing-plans；独立工作树 `.worktrees/pb-a2`，Python/pytest，既有依赖。

1. 提交此 Spec；独立提交上述保护版本适配；冻结新增 RED 并推送。
2. 新 RED 经公开 `attribute()` 覆盖两种合成险种/不同名称结构：
   - 年交费率表、年保障成本表、基本保险金额表；16字边界及括号方式说明；
   - 空白/NFKC、别名、未登记、近名/错名/两位年份缩写；
   - 17字限定语、各句读、“的”、每个原排除/否定词；
   - 首行/页尾/第二页完整标题，断行与跨页不拼合，第三页不参与，说明书/条款/混合角色；
   - 短名后紧邻括号拒收、完整括号名正控、多登记名前缀隔离；
   - 同名两产品、登记名+未知带书名号标题、条款编码冲突、同角色已存在；
   - 原精确标题/重复文件正控；策略数据与版本记录。
   运行 `uv run pytest -q tests/identity/test_unbracketed_rate_titles.py tests/ingest/test_rate_title_pages.py`，记录旧实现实际失败与正控。
3. 实现最小补充规则；实现提交不改冻结 RED/保护测试/Spec。
4. 用已授权8+6份费率表的原件与抽取文本检查本规则；981份在售 PDF 同输入、同登记表做新旧完整判定对比，
   原非隔离结论0变化。原件/抽取文本/结果保存在仓库外私密目录，公开只聚合计数。
   不使用目录名作本片生产归属依据；合成登记表的离线重放不是线上正确率证明。
5. 跑 `uv run pytest -q tests/identity tests/ingest`、`uv run ruff check .`、
   `uv run mypy src tests` 及本树 `harness/.venv/bin/pytest -q tests/architecture`。
   检查冻结 RED diff、文件≤500、git diff --check；全量以精确 head CI 为准。
6. merge 最新 main（不 rebase），发 Closes #571 交接 PR；不自行合并/部署。

## 5. 调查依据与边界

16份原件 SHA/Git blob 与固定来源清单一致，重抽前两页与981缓存逐字一致。
8份标题位于首行；另6份均为单页，视觉标题在表格上方、内容流在第12–14行：4份年交费率表、
2份年保障成本表，其中2份开头200字无角色词。1份年份缩写与1份内容自身矛盾保持隔离。
公开仅聚合统计，私有原件/页图/定位和结果保存在本单仓库外目录。

真正无标题材料未在本6份中出现；#497 已更正“目录即归属”。本片不实现任何来源辅助自动确认，
不得利用目录名称、文件名产品号或模拟登记回放的目标答案作为生产锚点。

# 实施任务

## 2026-09-15 当前独立平台收尾（原历史 FLOW 不等于本轮通过）

- [x] G3-AUTO-3/5/6：有界引用/增量候选传输，保持原完整候选及发布校验；共享跨语言及真实入口测试。
- [x] G3-AUTO-3/4/6：按有效检查点恢复，复用三态结果和原调用，轻量提交/状态，消除错误前缀决策主体。
- [x] 受影响组件部署，网页恢复当前失败任务，报告实际时长、调用、字段状态、检索及证据回查；不能用辅助脚本或 fixture 宣称独立验收。

已批准设计/Owner/RED边界见现有 platform-independent 设计和计划的2026-09-15修订。2026-09-22 本地平台FLOW已通过：既有任务网页增量恢复及全新3190-2三PDF首次网页上传至发布均完成；详见 `docs/insurance-kb/evidence/830-g3/task3bn-platform-closeout-20260922.md`。现代checkpoint身份失败raw零调用重投影、规模/质量为明确后续项，不能将本结论扩大到生产。

- [x] 核验 main/工作树/工作簿和 G2 终态，保存真实合同 RED。
- [x] 冻结首切片合同及向量；独立审查写域。
- [x] A：RED→无损工作簿 Catalog 编译/Profile 校验→focused GREEN；17 PASS、独立复审 BLOCKER0。
- [x] B：按冻结合同接入既有目录/Profile；17前端 checks、Go接口及类型检查通过，真实部署另记。
- [x] 生成真实 11 包及可审整包展示映射，用户已回复“结构确认”；后续用户“我本人”及已授权记录补齐确认人/队列负责人，旧回执保留。
- [x] 冻结真实 corpus、标签/阈值/采信及后续 G3 物理切片。
- [x] 完成 G3 真实批次/页面/隔离 Release/source/search 及只读独立复核。

- [x] C：设计2与集中修复、独立复核、root73 tests完成。
- [x] D：原合同及1/2/4/5/6修订无损整合；三hash公式补回后独立复核通过，冻结DTO/types/fixture写域。
- [x] D：strict DTO、机械继承与两unknown对齐、actual342跨语言fixture及完整8MiB容量检查；Python与Go均独立PASS。
- [x] D：既有handler/service/UI接线的软件实现和完整fixture互操作独立通过。
- [x] D：真实候选、来源与发布闭环完成，第 7→8→9 版及独立读回复核通过。
- [x] 来源准备：15实际native capture逐件校验；v3隔离脚本独立复核及本机只读preflight通过。
- [x] 来源执行准备：完整upload v2 runner独立复核及执行包复核PASS；具体验证窗口/预览已发用户。
- [x] 来源实际执行：用户已授权；15 份本机来源导入/登记及来源回读完成，PDF 保留本机。
- [x] D Python首轮三项修复及第二轮source覆盖修复已独立通过；原始RED与旧快照保留。
- [x] D Go完整镜像：初审2项BLOCKER经首轮集中修复独立PASS；原失败证据保留，四C反例/354跨语言snapshot及完整types回归通过。
- [x] D UI本地Task4：首轮修复独立PASS（26页面/46 G2回归），原失败保留，8文件冻结并提交b7a26b8aa；实际后端互操作另验。

- [x] D backend Tasks1/2/3：两轮有界修复后独立PASS（B1/B2关闭），完整回归/原反例/前后端互操作通过；11文件冻结，真实执行另验。

- [x] 原 R1—R5 最终矩阵、实际导航变更与恢复、读取/重启/DNS 故障修复、历史/检索/UI 独立验收完成。

结项：G3 FLOW PASS；QUALITY=DEFERRED_TO_Q0；NOT_FOR_PRODUCTION。完整结果见 `docs/insurance-kb/evidence/830-g3/g3-final-closeout-20260913.md`，保留历史失败与后续业务待办。

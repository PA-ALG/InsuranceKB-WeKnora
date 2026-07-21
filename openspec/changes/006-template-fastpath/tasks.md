# 006 任务

> [!CAUTION]
> **以下 checkbox 仅是历史记录。** 旧模板/fast path 及润色入口全部 production-disabled；可按 provenance 选择性重构，但 027/028/适用 admission 未通过前不可用于真实运行。

- [x] T1 specs/template.md（从 proposal + 11 §1-§2 + 12 #1/#4 推导可验证验收条款，SDD）
- [x] T2 族指纹修复：`sections.family_fingerprint` 无标题 fallback（文档类型+页数桶+表头 token；有标题路径不变，004 族 id 不漂移）（F6）
- [x] T3 表格结构 provider：`templates/tables.py` Protocol + `PdfplumberTableProvider`（表头行定位/列名枚举/列定位直取单元格）+ `PPStructureV3Provider` 接口与配置位 stub（F5）
- [x] T4 模板 schema 与注册表：`templates/models.py` + `templates/loader.py`（fail-fast 校验，机制对齐 schemas 注册表；`dataset/templates/` 为发布目录）（F1）
- [x] T5 模板归纳器（零模型）：`templates/induce.py`（表格列名/引文上下文正则锚点挖掘 + 全产品回放验证 + 草案 YAML + 归纳报告）+ `templates/polish.py` LLM 润色 stub（claude-session 队列形态）（F2）
- [x] T6 运行时 fast path：`templates/fastpath.py` 锚点定位与确定性抽取 → 既有校验链；pipeline 集成（命中字段跳过通用抽取/gapfill/投票；merge 优先级 judge>fastpath>vote>gapfill>extract；`data_quality` 入 PredRecord）；CLI `extract --templates-dir` / `induce-template`（F3）
- [x] T7 可喂性评分：`compiler/feedability.py`（确定性检查项+总分+阈值）+ manifest 逐文档记录 + 隔离区目录 `write_quarantine` + CLI `feedability`（默认 dry-run，`--apply` 落盘）（F4）
- [x] T8 留出验证脚本 `harness/scripts/validate_006.py`（归纳→发布→留出产品 fast path→v2 对照→调用节省估算）+ validation-report.md；盛世金越费率表模板入 `dataset/templates/tpl-04b9c55dc31e-费率表.yaml`（F7）
- [x] T9 文档与交接：compiler/templates/README.md、HANDOFF 更新（006 完成条目 + B 类新增 PP-StructureV3 部署）

状态：T1~T9 完成（2026-07-12）。零真实模型调用（确定性归纳/抽取 + 桩模型/注入 provider 夹具）；
新增 47 个测试（test_template_schema/tables/induce/fastpath/cli、test_feedability、
test_family_fingerprint_006），既有 192 测试不破坏（门禁 239 passed 全绿）。

## 实现裁决记录

1. **指纹 fallback 特征选择**：文档类型（全文归一化后模式匹配，容忍换行断词）+ 页数桶
   （xs≤2/s≤16/m≤40/l）+ 表头 token 集合（≥3 token 且 ≥80% 短 token 的行，去数字）。
   39 份样本 PDF 实测：盛世金越 3 份费率表正确同族、说明书/费率表分族、有标题文档（条款）
   指纹零漂移。fallback 刻意偏粗——族识别过粗不致错：锚点+校验链兜底，模板失配只降级
   不出错（11 §1.3）。
2. **发现：盛世金越两个分红产品的说明书版式不同构**（尊享分红 vs 创享分红，利益演示表
   列结构与换行差异 → 指纹不同族）——按 F2.1 拒绝跨族归纳，说明书模板本轮未产出；
   留出验证仅费率表模板生效（命中字段正确率 1.00 vs 通用管道 0.00）。
3. **正则锚点挖掘 = 引文内定位值 + 前文窗口 + 数字泛化 `\d+`**；锚点必须在全部归纳产品
   回放验证（values_equal）通过（hit_rate=1.0 硬门槛）才发布。长文本总结型金标值
   （产品特色/红利分配方式等，非原文子串）确定性不可锚定 → not_anchorable 进润色队列。
4. **fast path 校验失败 = 丢弃降级而非标 unknown**：字段留给通用管道继续抽（宁缺勿假 +
   回退路径永远存在）；fastpath 字段退出高风险投票（12 #1：确定性字段退出投票的成本优化）。
5. **可喂性评分只记录不拦截**（F4.2）：硬门禁需解析升级链 L1+（PP-StructureV3/MinerU）
   就位后才有"升级"可走；本轮打分进 manifest + 隔离区目录机制 + CLI 默认 dry-run/`--apply`
   （10 规范：批量写默认 dry-run，12 #5）。
6. **调用节省估算口径**（F7.3）：确定性计数模型（窗口×字段批 + 每 unknown 字段 1 次补漏），
   不重跑真实模型（token 成本纪律）。留出产品仅节省 1 次（≈1.7%）——本族锚定字段少，
   但命中字段正确率 0→1；节省随模板铺开与锚点覆盖增长（11 §1.4 闭环）。
7. **wip 金标行无产品元信息**：`induce-template` CLI 走 `load_wip_goldens` 宽松加载
   （以目录名补齐），正式 release 布局仍用 `goldenset.runner.read_jsonl`。

## 遗留（交主会话/其他会话推进，B 类）

- **PP-StructureV3 表格结构识别部署**（重依赖：paddlepaddle/paddleocr，进程隔离服务，08 选型）：
  接口与配置位已留（`templates/tables.py` `PPStructureV3Provider`、`HARNESS_TABLE_PROVIDER`）；
  部署后按 F5.1 协议实现 `extract_tables` 并用金标回归 A/B（11 §2 解析器 A/B 机制）→ 已列 HANDOFF ⓪-B。
- **模板铺开**：按 005 按族错误归因分数逐族立项（11 §1.4 闭环），非本 change 范围。
- **说明书族并族复盘**（裁决记录 #2）：分红型说明书两版式是否应并族由业务方判定；
  若并族需引入相似度聚类而非精确哈希（设计权威 11 §1.1 允许）。
- **主会话（T‑主会话）**：模板草案人工审核流程定版（11 §1.2"人工只审核"的 workbench 承接，
  排期在 workbench change）；data_quality 与 007 审核门禁的联合分流策略确认（12 #2）；
  润色队列（polish-queue.jsonl）批处理形态与裁决通道合并评估。

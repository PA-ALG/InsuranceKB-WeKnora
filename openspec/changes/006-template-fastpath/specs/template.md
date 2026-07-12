# 006 规格（验收条件）——模板抽取 Fast Path 与表格结构识别

> 由 proposal.md 推导的可验证条款；测试名引用条款编号（10 §2 TDD 约定）。
> 权威设计：docs/insurance-kb/11 §1（三层模板）、§2（解析升级链）、12-dayu-borrowings #1/#2/#4。
> 影响面：`harness/compiler`（templates/ 新包、sections 指纹、feedability、pipeline/models/cli）；
> 不动 `knowledge/`（007 刚交付）与 `goldenset/` 核心（只读金标）；**零真实模型调用**。

## F1 模板 schema 与注册表

- F1.1 模板为 YAML 数据文件（目录 `dataset/templates/`，一文件一模板）：
  `template_id / family_id / doc / template_version / status(draft|published) /
  induced_from(products+golden_release) / fields[]`；每个 field 含
  `field_id / field_name / anchors / few_shots[]`；anchors 支持四类：
  `section_title`（章节标题模式，正则）、`pages`（页位置提示）、
  `table_columns`（表格列名锚点：header_contains + op=join_headers|cell + join/row_label/column）、
  `regex`（恰含一个捕获组的正则）；
- F1.2 加载机制对齐 schemas 注册表（G1 同构）：`load_template_registry(dir)` 一次加载全部
  YAML，任何结构问题 fail fast（`TemplateLoadError`，消息含文件与字段定位）：缺必填键、
  status/op 非法枚举、regex 编译失败或捕获组数 ≠1、field_id 重复、family_id 格式非法均报错；
- F1.3 注册表版本 = 语义版本 + 内容 hash 前 12 位（同 G1.3）；`find(family_id, doc)` 只返回
  `status=published` 的模板；空目录/无目录 → 空注册表（fast path 整体旁路，004 行为不变）。

## F2 模板归纳器（确定性，零模型调用）

- F2.1 输入 = 同族 ≥2 个产品的金标记录（wip-gs-v0.1 evidence 页码+引文）+ 对应文档分页文本
  （+ 可选 pdf 路径供表格 provider）；产品数 <2 → 拒绝归纳（fail fast）；
- F2.2 对族内 ≥2 产品均 present 的字段确定性挖掘锚点，优先级：表格列名锚点（证据页表头行
  能按 join 规则复原金标值，values_equal 判定）→ 引文上下文正则锚点（金标值在证据行内定位，
  前文若干字符 + 值捕获组，数字段泛化为 `\d+`）；两者都失败 → 该字段记 `not_anchorable`；
- F2.3 锚点必须在**全部**归纳产品上回放验证（锚点命中且抽出值与该产品金标 values_equal）
  才进入模板草案；归纳报告逐字段记录锚点类型与族内命中率（hit_rate），命中率 <1.0 的锚点
  不发布；
- F2.4 产出 = 模板草案 YAML（status=draft，few_shots 取自金标真实 (page, quote, value)）
  + 归纳报告 markdown；草案经 F1.2 加载校验必须通过（自产自验）；
- F2.5 LLM 润色接口留 stub（claude-session 形态）：`write_polish_queue` 落盘
  polish-queue.jsonl（行含模板草案与 not_anchorable 字段清单），不做任何模型调用；
  `apply_polish` 读回裁决文件（无文件 → 原样返回草案）。

## F3 运行时 fast path

- F3.1 管道 split_route 已产出 family_id；extract 节点入口按 (family_id, doc) 命中
  published 模板 → 逐字段锚点定位 + 确定性抽取：`table_columns` 走表格结构 provider
  （op=join_headers 列名枚举直取 / op=cell 数字列定位直取，12 #1），`regex` 走捕获组直取；
- F3.2 fast path 候选值必须走**既有校验链**（`run_validation_chain`：quote 回验→占位清洗→
  类型校验）；校验不过 → 丢弃候选并降级通用管道（不是标 unknown——通用管道仍会抽该字段）；
- F3.3 锚点未命中/表格缺失/无模板的字段自动降级通用管道，行为与 004 完全一致
  （无模板注册表时 192 既有测试不破坏）；
- F3.4 fast path 命中字段**跳过**该产品的通用抽取（战场缩小：调用窗口按剩余字段计算）、
  跳过 gapfill（已 present）、跳过高风险投票（数字/确定性字段退出投票，12 #1 结论）；
  merge 时 fastpath 候选优先级高于 extract/gapfill/vote，仅次于 judge；
- F3.5 pred 记录新增 `data_quality ∈ {structured_direct, table_parsed, llm_extracted,
  llm_inferred}`（dayu #2；007 Claim 端已留位）：table_columns 锚点 → `table_parsed`，
  regex 锚点 → `structured_direct`，通用管道 → `llm_extracted`（默认值，既有 pred 兼容）。

## F4 文档可喂性评分（dayu #4）

- F4.1 解析产物进管道前确定性打分 `score_feedability(doc, pages, sections, tables?)`：
  检查项 = 乱码率（� 与 (cid: 占比）、空页比例、超大页/超大 section、截断尾部启发式、
  表格列名合法性（提供 tables 时：表头行非全空、无重复列名）；每项 ok/detail 可见，
  总分 ∈ [0,1]；
- F4.2 阈值（默认 0.75）以下 → `quarantine_suggested=true`；管道 split_route 将逐文档
  评分与建议写入 run manifest（DocManifestEntry 扩展字段），**只记录不拦截**（本 change
  先打分与报告；硬门禁待解析升级链 L1+ 就位）；
- F4.3 隔离区目录机制简单实现：`write_quarantine(dir, product, doc, report)` 落
  `<dir>/<product>/<doc>.rejection.json`（含评分明细审计痕迹，可救回）；CLI `feedability`
  默认 dry-run（只打印评分），`--apply` 才写隔离文件（10 规范：批量写默认 dry-run）。

## F5 表格结构识别 provider

- F5.1 `TableStructureProvider` 为 Protocol：`extract_tables(pdf_path, page_no) ->
  list[Table]`（Table=行×列字符串矩阵 + header 定位辅助方法）；fast path/归纳器/可喂性
  评分只依赖该协议，可注入假 provider 单测；
- F5.2 首个实现 `PdfplumberTableProvider`（零新增重依赖，pdfplumber 已在 002）；对
  盛世金越费率表真实 PDF：能取到表头行（含"趸交"）并按列名定位数字单元格
  （行键=投保年龄，列=交费期间 → 该行该列保费值，12 #1 列定位直取）；
- F5.3 `PPStructureV3Provider` 留接口 + 配置位（`HARNESS_TABLE_PROVIDER=pp-structure-v3`
  预留），实例化即抛 NotImplementedError 并指明部署交接（重依赖部署列 HANDOFF B 类 /
  tasks.md 遗留）；provider 选择函数按配置返回实现，未知值 fail fast。

## F6 族指纹修复（004 疑点）

- F6.1 已知缺陷：章节标题序列为空的文档（说明书/费率表无编号标题）全部退化为
  `fam-e3b0c44298fc`（空串 sha256 前缀）——无标题文档被混为一族；
- F6.2 修复：标题序列非空 → 指纹算法**不变**（004 既有 条款 族 id 不漂移）；标题序列为空 →
  fallback 指纹 = 文档类型特征（产品说明书/费率表/条款…，全文归一化后模式匹配）+ 页数桶 +
  表格列名/表头 token 集合（数字归一化）哈希，且与空串指纹必不相同；
- F6.3 验收（真实 PDF）：盛世金越 3 产品（尊享版26终身寿/其分红型/创享分红型）的 3 份
  费率表同 fallback 族、3 份说明书不再与费率表同族；e生保 等有标题文档指纹与 004 一致。

## F7 留出验证（零模型调用）与报告

- F7.1 用 盛世金越（尊享版26）终身寿险（分红型）+ 创享盛世金越（尊享版26）终身寿险（分红型）
  两产品金标归纳 费率表/产品说明书 模板；留出产品 = 平安盛世金越（尊享版26）终身寿险
  （唯一有 004 真实 pred 的族内产品）；
- F7.2 模板应用到留出产品：fast path 命中字段对照其金标计正确率，**≥** 通用管道（004 已有
  pred）同字段的 v2 分数（`evaluate(metric="v2")`，keypoints 同 005 口径）；
- F7.3 预估 LLM 调用节省数：按确定性调用计数模型（窗口×字段批 + gapfill 每 unknown 字段
  1 调用）对比 基线 vs fast path（命中字段退出该产品通用抽取与 gapfill），报告口径写明；
- F7.4 结果写 `openspec/changes/006-template-fastpath/validation-report.md`：指纹修复
  前后对照、归纳报告（锚点命中率）、留出字段级对照表、调用节省估算；
- F7.5 门禁：`ruff check` + `mypy src tests` + `pytest -m "not live"` 全绿，既有 192 测试
  不破坏；验证脚本 `harness/scripts/validate_006.py` 幂等可重跑。

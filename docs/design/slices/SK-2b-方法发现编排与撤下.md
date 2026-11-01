# SK-2b 方法发现编排、候选生成、撤下与失效接线

> 状态：Spec r2（2026-11-01，Claude；r2 实现时补命令参数与输出文件名）。设计依据：[SK-0](SK-0-销售方法与通用知识.md) §3.4、§4.1、§4.3 (b)(d)、§5.1；
> [SK-2](SK-2-方法登记准入与编译.md)（SK-2a：登记表方法段、准入、编译，PR #516，本片依赖它）。跟踪 Issue #507。
> 实现 Claude，审核 Codex。真实调用 0；不部署；不改 Go、前端与合同 schema。
>
> **拆分修订**（总控 2026-11-01）：SK-2 Spec 抬头原把“方法取值的线上模型阶段（调用台账、预算、原始回答留存）与
> `compile --live` 提交”列在 SK-2b；本片按总控给定的范围只做发现编排、撤下与失效接线，上述两项移到 **SK-2c**。

## 1. 目标与不做

做：

- `methods copies`：按登记表中 `active` 方法用途记录的三元组，把原始材料复制进方法发现库并维护复制映射
  （`method-copies.v1`）；记录失效后，其复制件从发现库删除（§3、§5）。
- `methods candidates`：读发现库的原生 Wiki 页面与所引 chunk，换算成原始材料上的命中块，写 SK-2a 准入读取的
  `method-candidates.v1`（§4）。
- `methods withdraw`：撤下一个方法：登记条目 `suppressed = true`，并生成只移出该方法成员的候选，由人决定（§6）。
- 失效接线：SK-1 写入的记录失效（撤回、修订、解除、忽略）贯穿复制、候选、编译三处，以端到端测试证明（§5）。

不做：发现库的创建与配置（原生 Wiki 开关、模型与思考模式、ExtractionInstructions）——SK-4 运维 Issue；方法取值的线上
模型阶段与 `compile --live`（SK-2c）；平台读取、方法页与问答（SK-3）；撤下的撤销（人工改登记表后重编译）。

## 2. 复制映射 `method-copies.v1`

```json
{"contract": "method-copies.v1", "space_id": "…", "discovery_kb_id": "…",
 "copies": [{"copy_knowledge_id": "…", "knowledge_id": "…", "parse_attempt": 2, "sha256": "…"}]}
```

- 一条映射 = 发现库中的一个复制件 → 一条原始三元组（SK-0 §4.1）；复制件 ID 唯一、三元组唯一，按
  `(knowledge_id, parse_attempt)` 排序。发现库不能是登记表的 RAW 库（`DISCOVERY_KB_INVALID`）。
- 复制件的摘要**不入文件**：每次从发现库清单读取平台对复制件字节算出的 `file_sha256`；候选文件的 `copy_sha256` 用它，
  由 SK-2a 准入与原始摘要比对（`COPY_MISMATCH`）。
- 文件旁边有锁文件（与登记表同一机制），一次只有一个命令写它；写回是原子替换。

## 3. `methods copies`

`--registry`（只读）、`--copies FILE`（不存在时视为空映射；旁边的锁文件同时只许一个命令）、`--discovery-kb`、`--run-root`
（写 `copy_report.json`）、`--live`。默认只出计划，不写平台、不写映射；`--live` 才执行。

1. 读发现库清单（与 RAW 清单同一读取：整份、按创建时间、总数一致）。
2. 已有映射：原始三元组不再是 `active` 记录 → 计划**删除**该复制件并去掉映射（`stale`）；复制件不在清单中
   （已被删除）→ 去掉映射（`gone`），按第 3 步重新复制。只删除清单中列出的复制件，从不删除其他知识。
3. 没有映射的 `active` 记录（按三元组排序）：
   - **对账**：清单中有已完成解析、`file_sha256` 等于原始摘要、且未被其他映射占用的复制件 → 采用（`adopted`），不上传；
   - 否则下载原始材料的当前文件（`GET /api/v1/knowledge/<id>/download`，上限 50 MiB，超过 `SOURCE_TOO_LARGE`），字节
     SHA-256 必须等于记录的摘要，否则 `SOURCE_CHANGED`（不复制；等 SK-1 按新修订重判）；上传到发现库
     （`POST /api/v1/knowledge-bases/<kb>/knowledge/file`，文件名用原名）；平台返回重复（409 `duplicate_file`）→ 采用
     它给出的已有复制件（`adopted`）。
   - 几条 `active` 记录摘要相同：只有第一条（按三元组）得到复制件，其余 `SAME_BYTES`。
4. 远端写入逐条执行，全部结束后原子写回映射。中途失败：已完成的上传由下一次运行按摘要或平台的重复回应采用，
   不会重复上传；已完成的删除在下一次运行中表现为 `gone`。
5. 报告与标准输出只有代码与计数（`copied`、`adopted`、`kept`、`stale`、`gone`、`SOURCE_CHANGED`…），不含文件名与正文。
6. **上传会让平台解析复制件并运行原生 Wiki 生成**（平台侧的 DeepSeek 调用）：`--live` 只在 SK-4 运维 Issue 批准的预算内
   使用；本片的测试全部用假传输层。

## 4. `methods candidates`（只读）

`--registry`、`--copies`、`--discovery-kb`（须与映射文件一致）、`--out FILE`（原子写出）。读取：发现库清单；原生 Wiki 页面及其所引 chunk（S6c 的读取，chunk 另带其
`knowledge_id`）；原始材料的固定修订页面（`reader_from_env`，与 SK-2a 编译同一读取）。

- `copies`：映射中复制件在清单里**已完成解析**的条目，`copy_sha256` 取清单值。
- 候选页面：`page_type` 为 `entity` 或 `concept`（与 S6c 同一范围）。每个页面按所引 chunk 的 `knowledge_id`（复制件）
  分组：复制件没有映射或未完成解析 → 该组不生成候选（`CHUNK_UNMAPPED`）；映射的原始记录不是 `active` →
  `METHOD_USE_NOT_ACTIVE`。
- 块定位：在原始材料按 `segments.v1` 切出的段落中只看记录的命中块；一个块算作被页面引用，当它的文字（NFKC、去空白）
  整段落在该组某个 chunk 的文字中，或该 chunk 的文字整段落在块中，且两者中较短的至少 8 个字符（同 S6c）。一个也定位
  不到 → `NO_RECORDED_BLOCKS`。
- 候选：`name` = 页面标题，`aliases` = 页面别名，`copy_knowledge_id`，`block_ids`（阅读顺序）。同一页面引用多份材料 →
  每份一个候选，准入按名称并入同一方法（SK-2a §3.2）。同一页面的重复组合只写一次。
- 候选文件与报告不含正文；页面与 chunk 的文字只用于定位。

## 5. 失效接线（SK-0 §4.3 (d)）

- 记录失效只由材料侧写入（SK-1：`uploads run` 的撤回/修订/忽略、`uploads detach`）；方法侧不改记录。
- 复制：失效记录的复制件在下一次 `copies --live` 中从发现库删除并去掉映射；新修订是新三元组，按 §3 重新复制。
- 候选：只为 `active` 记录生成（§4）。
- 编译（SK-2a）：失效记录的链接无效；方法只剩无效链接 → 退出（全部 Claim 与实体移出）；还有其他有效链接 → 按变化判定
  替换或撤回。

## 6. `methods withdraw`

`--registry`（持锁）、`--method-id`、`--run-root`、`--live`。

- 方法不在登记表 → `METHOD_UNKNOWN`；不是 v2 → `REGISTRY_NOT_V2`。
- 登记条目 `suppressed = true`；名称、别名、链接不变；对已撤下的方法再运行是幂等的。
- 移出候选：Active 中该方法的全部 Claim（`subject_ref` = 方法 ID，unknown 的也在内）与 `entity/<方法 ID>`，不含任何其他
  成员；`origin = compile`，`compiler_identity` 同编译，审核计划人工。Active 中没有该方法的成员 → 不生成候选。
- 顺序：锁内载入登记表 → 读 Active → 组包 → 写 `candidate.json` 与 `report.json` → 原子写回登记表 → `--live` 时提交候选
  （只提交；决定与激活由人在平台完成）。提交失败输出 `stopped` 代码，登记表已是撤下状态，下一次 `withdraw` 或 `compile`
  会给出同样的移出。

## 7. 平台接口

都是现有接口，不改 Go：知识库清单、知识下载、文件上传、知识删除（`DELETE /api/v1/knowledge/<id>`）、原生 Wiki 页面与
`chunks/by-id` 读取、固定修订页面、Active 读取、候选提交。缺少 `HARNESS_WEKNORA_BASE_URL`/`HARNESS_WEKNORA_API_KEY` →
`CONFIGURATION_MISSING`。

## 8. 改动范围

`harness/src/insurance_harness/compilers/methods/`（新增 `copies.py`、`candidates.py`、`withdraw.py`、`platform.py`，扩展
`cli.py`）、`compilers/wiki_pages/native.py` 与 `members.py`（chunk 带 `knowledge_id`，S6c 行为不变）、
`harness/tests/compilers/methods/`。

## 9. 验收（RED，合成材料，假传输层）

1. 复制：只复制 `active` 记录；下载摘要不符 → `SOURCE_CHANGED` 不上传；超过上限 → `SOURCE_TOO_LARGE`；清单已有同摘要 →
   采用不上传；上传 409 → 采用；同摘要多记录 → `SAME_BYTES`；失效记录的复制件 → 删除并去掉映射；复制件被删 → 重新复制；
   不在清单的 ID 从不删除；默认不写平台不写映射；中途失败后重跑不重复上传；发现库 = RAW 库 → 拒绝。
2. 候选：只 `entity`/`concept`；按复制件分组；块只来自命中块；两个方向的包含与 8 字下限；未映射、未完成、记录失效、
   定位不到各有代码；候选文件不含正文；候选经 SK-2a 编译成为方法（端到端）。
3. 撤下：`suppressed`、只移出该方法成员（含 unknown 与实体）、人工计划；无成员 → 无候选；先计划后登记表再提交；`--live`
   只提交不决定；未知方法 → `METHOD_UNKNOWN`。
4. 失效端到端：SK-1 `detach` 或清单撤回后，`copies` 计划删除复制件、`candidates` 不再生成、`compile` 移出该方法。

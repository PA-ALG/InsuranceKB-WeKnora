# SK-2c 方法取值的线上阶段与 `compile --live` 提交

> 状态：Spec r2（2026-11-01，Claude；r2 实现时发现每次编译都给 Claim 写新的编译时间 `maintenance.changed_at`，
> 同样的计划字节不同，§4.2 的提交回执改按去掉编译时间后的内容摘要比较）。设计依据：[SK-0](SK-0-销售方法与通用知识.md) §4.3 (c)、§5.2、§5.3；
> [SK-2](SK-2-方法登记准入与编译.md)（SK-2a：取值协议、保存回答的格式、离线 `methods compile`）抬头的拆分；
> [SK-2b](SK-2b-方法发现编排与撤下.md) 抬头的拆分修订。跟踪 Issue #507。实现 Claude，审核 Codex。
> 真实调用 0（测试用假传输层）；不部署；不写线上登记表；不改 Go、前端与合同 schema。

## 1. 目标与不做

做：

- `methods values`：方法取值的线上模型阶段。对编译将要发出的每个取值请求，已有保存回答就跳过，否则在预算内发给
  模型；每个原始回答留存在私有目录；结构合格的回答按 SK-2a §7 的保存格式写出（`<请求摘要>.txt`），由
  `methods compile` 回放（§3）。
- `methods compile --live`：计划与登记表写完后提交 CandidateBundle，只提交、由人决定；提交回执防止重复提交（§4.2）。
- `methods compile --model` 可省：从取值目录的调用台账得出写出这些回答的模型；给了而与台账不符则停止（§4.1）。
- `models/stages.json` 增加 `methods` 阶段（§3.4）。

不做：独立审核打分（`methods_sales` 未准入，方法一律进人工队列，SK-0 §5.2 (5)；SK-0 §5.3 估计里的审核打分留到
准入评估时再接）；发现库的创建与配置和线上实际运行（SK-4 运维 Issue）；平台读取、方法页与问答（SK-3）；
`methods withdraw --live` 的提交方式（不变）。

## 2. 取值与编译分成两个命令

- 编译必须在登记表锁内完成“准入 → 编译 → 组包”（SK-0 §4.3 (c)）。线上取值一次请求在思考模式下可达数分钟，几十个
  方法在锁内逐个发送会长时间挡住 `uploads` 的各个命令。所以发送放在 `values`，它**只读**登记表、不持锁；编译只回放。
- 两个命令之间的接口就是 SK-2a 已有的保存格式：文件名 = 请求摘要（`JudgeLikeRequest.sha256`，覆盖系统提示与用户
  载荷）。`values` 与编译用**同一组函数**做准入（内存中）与请求构造（§5），所以同样的登记表、候选文件与原始来源页
  得出逐字节相同的请求。
- `values` 之后登记表若有变化（新材料、记录失效、新候选），受影响方法的请求随之改变，编译对它们报
  `RESPONSE_MISSING`（只跳过这些方法，不发请求）；再运行一次 `values` 只补发这些请求。

## 3. `methods values`

参数：`--registry`（只读，不持锁；非 v2 → `REGISTRY_NOT_V2`）、`--candidates`（同编译）、`--responses DIR`（取值
目录）、`--stage-config FILE`、`--stage`（默认 `methods`）、`--max-sent N`（必填，非负整数）。原始来源页用编译同一读取
（`reader_from_env`）；缺少平台配置 → `CONFIGURATION_MISSING`。

### 3.1 取值目录

复用 `models/durable.py`，与产品编译、独立审核、概念页的运行目录同一套机制：

| 文件 | 内容 |
|---|---|
| `.lock` | 一次只允许一个运行使用该目录（被占用 → `RUN_ROOT_BUSY`） |
| `budget.jsonl` | 每次发送**之前**先记一行，进程在发送途中中断也计入 |
| `ledger.jsonl` | 每次尝试一条调用记录：阶段、模型、策略版本、请求摘要、结果、用量、实际服务的模型 |
| `raw/NNN.txt` | 每个原始回答按到达顺序留存（结构不合格的也留），只用于诊断 |
| `<请求摘要>.txt` | 结构合格的回答，SK-2a §7 的保存格式；只新建、不覆盖 |

- 目录必须在任何 git 仓库之外（`run_lock` 检查；否则或台账损坏 → `RUN_ROOT_INVALID`）。原始回答可能引用材料原文，
  只留在操作者的私有目录，不进仓库、日志、Issue 与 PR。
- 一个目录对应一个模型身份：台账已有记录的 `stage`、`model`、`policy_version` 必须与本次阶段配置相同，否则
  `RUN_ROOT_MODEL_CHANGED`（换模型或策略就换目录）。实际服务的模型版本在一个目录内只能有一个（`DurableLedger`）：
  变化后立即停止 `SERVED_MODEL_CHANGED`，变化后得到的那个回答不留存。

### 3.2 流程

1. 载入登记表与候选文件；内存中准入，得出在用的方法（未撤下且至少一条有效链接，SK-2a §4.1）；退出的方法不发请求。
2. 每个在用方法按登记顺序构造请求。段落读取失败的方法记其代码（段落或固定修订页面的代码），不发请求。
3. 取值目录锁内：检查模型身份；打开台账，`--max-sent` 计入该目录以往的全部发送。
4. **先查已保存的回答**（任何发送之前）：每个已有 `<摘要>.txt` 的请求做 SK-2a 的结构检查，通过 → `saved`；不通过 →
   `RUN_ROOT_INVALID`，整次停止（它曾经通过检查才被保存，说明被改动过）。
5. 再按顺序发送其余请求（第一次需要发送时才创建模型客户端，全部已保存时不需要模型密钥）：
   - 回答先写入 `raw/NNN.txt`；结构合格 → 写 `<摘要>.txt`，记 `answered`；不合格 → `VALUE_RESPONSE_INVALID`（不保存
     为回答，下次运行在预算内重发）。
   - 只影响该方法、继续下一个：回答被截断（结束原因不是 stop）→ `VALUE_TRUNCATED`；输入超过阶段的字符上限 →
     `INPUT_TOO_LARGE`（不计发送）。
   - 整次停止：预算用完 → `BUDGET_EXCEEDED`；配置或密钥无效 → `MODEL_CONFIG_INVALID`；不可重试的 HTTP 错误或重试用尽
     → `MODEL_ERROR`（附异常类型名）；服务模型变化 → `SERVED_MODEL_CHANGED`；中断 → `INTERRUPTED`。已写出的回答都留着，
     重跑只补缺的。
6. 不在一次运行内对结构不合格的回答自动重问：重跑即重问，同样受预算约束。

### 3.3 输出

一行 JSON，只有代码与计数：`model`（实际服务的模型，提供方未报告时为配置的模型名）、`methods`（发出或检查了请求的
在用方法数，含段落失败的）、`codes`（各代码的计数）、`failed`（方法 ID → 代码，只列没有得到可用回答的）、`sent`
（本次发送数）、`sent_total`（该目录累计发送数）。打开取值目录之后的停止为 `{"stopped": 代码, "sent": …,
"sent_total": …}`（`MODEL_ERROR` 另有 `error` = 异常类型名）；之前的停止（参数 `INVALID_ARGUMENTS`、阶段配置
`MODEL_CONFIG_INVALID`、登记表、候选文件）只有 `stopped`。不含正文、方法名、文件名与路径。

### 3.4 预算与阶段配置

- `--max-sent` 是硬上限：计入每一次尝试（含传输层重试，阶段配置的 `max_attempts`），按目录累计。SK-4 运维 Issue 写明
  数值（SK-0 §5.3 估计准入取值约 40–60 次）。用完前得到的回答都已保存，不浪费。
- `models/stages.json` 增加 `methods` 阶段：供应商、模型、思考模式、`json_object` 与 `schema_fields` 相同，复用其密钥
  环境变量名，不新增密钥；`policy_version = method-2026-11-01.1`。

## 4. `methods compile` 的修订

### 4.1 `--model`

- 可省。取值目录有台账且有成功的调用时，目录的模型 = 台账记录的实际服务模型（只能有一个）；提供方没有报告时为台账
  记录的配置模型。
- 给了 `--model` 而目录的模型不同 → `MODEL_MISMATCH`；省略而目录没有台账（手工准备的回放目录）→ `MODEL_UNKNOWN`；
  台账损坏或记录了多个模型 → `RUN_ROOT_INVALID`。这样 Claim 的 `provenance.model` 总是写出这些回答的模型。

### 4.2 `--live`

- 顺序：登记表锁内载入 → 读 Active → 准入、编译、组包（从不发请求）→ 写计划（SK-2a §7 的一套文件）→ 原子写回登记表
  → 提交计划中的 CandidateBundle（`PlatformClient.submit`）。方法 pack 未准入，审核计划为人工：只提交，决定与激活由人在
  平台完成。
- 提交回执 `submitted.json`（在 `--run-root`）：`{"content_sha256": <内容摘要>, "candidate_sha256": <所提交的
  candidate.json 的摘要，与该次 report.json 的 plan 相同>, "candidate_id": …}`，提交成功后原子写入。
- **内容摘要**：变化判定给每个成员 Claim 写本次编译的时间（`maintenance.changed_at`），成员摘要随之改变，所以同样的
  输入每次编译出的 `candidate.json` 字节都不同。内容摘要 = 去掉各成员的 `member_digest` 与 Claim 的
  `maintenance.changed_at` 之后，候选整体按键排序的紧凑 JSON 的 SHA-256；基线、成员、移出、审核计划与编译器身份都在内。
- 再次运行时计划的内容摘要等于回执 → 不再提交，输出回执中的 `candidate_id` 与 `"submitted": "already"`，回执不变；
  否则提交并写新回执，输出 `"submitted": "new"`。与产品发布的回执同一纪律：只记已成功提交的输出，同样的输出不重复提交
  （人拒绝后要重新提交，需换运行目录）。回执不是这三个非空字符串 → `RECEIPT_INVALID`，不提交。
- 没有变化（计划没有 `candidate.json`）→ 不提交，`"submitted": "nothing"`。
- 提交失败 → `{"stopped": 平台代码}`，计划与登记表已写，回执不写；重跑得出同一计划并再次提交。提交成功而回执写入前
  中断 → 重跑会再提交一份同样的候选，由人在审核队列中按同一基线处理（与产品发布相同的已知情形）。
- 不带 `--live` 时输出与 SK-2a 相同。方法实体与 Claim 不带版本引用、审核路由 `methods_sales`（SK-2a，不变）。

## 5. 改动范围

- 新增 `harness/src/insurance_harness/compilers/methods/values.py`：取值目录、身份检查、发送与留存、输出。
- `compilers/methods/compile.py`：抽出 `admitted_registry`（准入并校验登记表）与 `method_request`（段落 + 可选标签 +
  请求），`compile_methods` 改为调用它们，行为不变。
- `compilers/methods/responses.py`：读取目录模型（§4.1）。
- `compilers/methods/cli.py`：`values` 子命令、`compile --live` 与回执、`--model` 可省。
- `models/stages.json`：`methods` 阶段。
- 测试：`harness/tests/compilers/methods/test_method_values.py`、`test_method_values_cli.py`、`test_method_compile_live.py`。

不改：Go、前端、合同 schema、产品编译与发布、TrustPolicy、SK-2a/2b 的其他行为。

## 6. 验收（RED，合成材料，假传输层，真实调用 0）

1. 端到端：`values` 用假传输层取值，写出的回答由 `methods compile`（省略 `--model`）回放得到与内存假模型相同的方法
   成员；Claim 的 `provenance.model` 为实际服务的模型；回答文件名等于编译请求的摘要。
2. 已保存的回答不发送；全部已保存时不创建模型客户端（没有模型密钥也能跑）；被改动过的保存回答 → `RUN_ROOT_INVALID`
   且没有任何发送。
3. 结构不合格的回答：`raw/` 留存、不写 `<摘要>.txt`、代码 `VALUE_RESPONSE_INVALID`；重跑在预算内重发。
4. 截断 → `VALUE_TRUNCATED`、超长 → `INPUT_TOO_LARGE`，其他方法照常取值。
5. 预算：`--max-sent` 用完 → `BUDGET_EXCEEDED`，此前的回答已保存；按目录累计（第二次运行计入第一次的发送）；放宽
   上限后重跑只发剩下的。
6. 停止：重试用尽 → `MODEL_ERROR`；服务模型变化 → `SERVED_MODEL_CHANGED` 且变化后的回答不留存；台账记录了别的模型或
   策略 → `RUN_ROOT_MODEL_CHANGED`；目录在 git 仓库内 → `RUN_ROOT_INVALID`；目录被占用 → `RUN_ROOT_BUSY`。
7. 退出的方法（撤下、没有有效链接）不发请求；输出不含材料文字与方法名。
8. `compile --model`：省略时取目录的模型；与目录不符 → `MODEL_MISMATCH`；省略且没有台账 → `MODEL_UNKNOWN`。
9. `compile --live`：先写计划、再写登记表、再提交；回执与计划摘要一致；同样输入重跑（编译时间不同）不再提交
   （`already`）；取值变了的计划再次提交；没有变化不提交；提交失败 → 平台代码，回执不写，重跑再提交。
10. `stages.json` 的 `methods` 阶段：DeepSeek、思考开、不含密钥。

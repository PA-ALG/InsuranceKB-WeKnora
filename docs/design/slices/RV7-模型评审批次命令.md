# RV7 · 模型评审批次命令：编译变更 → 独立评委 → 机器发布

> 状态：Claude 2026-10-28 提出；同日按 Codex 审核 R1–R8 修订（PR #413），第 2 轮审核 R1、R2、R4 再修订 ｜ 作者：Claude Code
> 依据：
> - 用户 2026-10-27："需要审核的太多了，这版你借助 gpt6.0 或者 opus5.5 直接判断吧"，以及"你全部决定吧，不要我来批准了"。审核由独立模型评委（GPT-6 Astra xhigh）完成，结果按机器审核发布，并如实标注评审来源；
> - 参考运行：运维 #384（人工队列候选的评审与发布，2026-10-27）、#403（编译器升级批次，2026-10-28）。两次都靠仓库外的一次性脚本（收集、建题、`codex exec`、导入、建候选、发布、关闭遗留审核点），本切片把这条链路固化为有测试的命令；
> - 复用：`eval/judge_files`（文件交换与哈希校验）、`changes.decide_changes`（含 S12c-1b 的 UPGRADE）、`publish_changes.delta_bundle`、`review.routing.labelled`、`bundle.client`（含 RV6d 的机器通道拒绝）、`review.spot_check`（先发布后抽检）。
>
> 实现方：Claude ｜ 审核方：Codex ｜ 真实调用：0（命令本身不调用模型；评委会话由操作者另行启动）

## 1. 目标

把一次编译的产出变成**经独立评委逐点判定**、再按**机器审核**发布的变更，全程可复现、可中断续跑：

```
python -m insurance_harness.ingest.judge_batch prepare --registry R --compile-root C --run-root J [--products …]
#   操作者：bash J/run.sh            （每个会话一次 codex exec，命令本身不调用 codex）
python -m insurance_harness.ingest.judge_batch ingest  --run-root J
python -m insurance_harness.ingest.judge_batch publish --registry R --compile-root C --run-root J \
        --issue N [--live]
python -m insurance_harness.ingest.judge_batch close   --run-root J --product P --candidate ID \
        --candidate-bundle FILE --issue N [--live]
```

`--run-root` 必须在任何 Git 仓库之外（`judge_files.check_run_directory`）。

**信任边界**：运行目录根下的 `plan.json`、`manifest.json`、`data/`、`publish/` 由命令写，是可信记录；会话目录里的一切（题目、材料、答案）都按不可信输入处理。可信记录只在评委写不到时成立，这一点由沙箱设置保证并在启动前实测（第 2 轮 R2）：
- 只给 `workspace-write` 不够：它同时放开 `$TMPDIR`、`/tmp` 和配置里的额外可写目录，运行目录放在这些目录下时，评委能连同题目一起改写清单和 plan。所以 `run.sh` 启动的每个沙箱都去掉这些目录：`-c sandbox_workspace_write.writable_roots=[]`、`-c sandbox_workspace_write.exclude_tmpdir_env_var=true`、`-c sandbox_workspace_write.exclude_slash_tmp=true`，评委只剩自己的会话目录可写；
- 启动任何评委之前，`run.sh` 用完全相同的沙箱设置跑一次探针（`codex sandbox`，不调用模型）：必须能写本会话目录（否则探针不可信），且不能写运行目录根、`data/` 和 `sessions/`。任何一条不满足就以退出码 3 停止，不启动任何会话；
- 这比按路径拒绝临时目录更直接：检查的是这台机器、这份配置下评委实际能写什么，配置里额外加的可写目录也包括在内。生成脚本的代码在 `judge_batch/launch.py`。

## 2. 各步骤

### 2.1 prepare（只读线上）

- 对每个产品，用发布同一套代码重建 Claim：`registry_inputs`、`publication_entries`、`load_trusted_pages`、`claims_from`，再对当前 Active 运行 `decide_changes`。
- 需要评审的变更点为 `upgrade`、`add`、`fill`、`supersede`，其余不进入评审。
- 每个评审点记录以下内容：
  - slug、field_key、change；
  - 线上值：仅 upgrade/fill/supersede 有，取自 Active 中 `base_slug` 对应的 Claim，含 state、value、引文；
  - 新值：state、value、引文；
  - `content`：评委看到的内容指纹，由 state、规范化后的 value、每条引文的 `(source_ref, quote_sha256)` 组成。
- **评审依据**（R4）：每个产品在 `plan.json` 记下评委据以判断的全部输入：
  - 登记表给出的每份材料的身份 `knowledge_id:attempt:document_sha256`（不论是否被引用）；
  - 编译输出的 `materials`、`cards_version`、`value_protocol`；
  - 评委题目所用字段卡的版本；
  - **题目里实际给出的字段口径**（第 2 轮 R4）：每个评审点所属字段的标题、定义、来源指引和字段卡，按字段记 sha256，写在 `plan.json` 的 `fields`。题目和这份记录取自同一份数据，首次发布时对每个批准点重新计算，不一致返回 `INPUTS_CHANGED`。没有批准点依赖的字段可以改动。
- **材料全文**（R6）：每份材料逐页读出，页首标记为 `[page N]`，写到 `sources/<产品>/<knowledge_id>-<attempt>.txt`。文件名来自唯一的材料身份，不用原文件名。题目里列出该产品的材料（文件名 → 原文件名），每条引文也带对应文件。
- **会话划分**：
  - 产品按编号排序后依次装入会话，每个会话不超过 `--points-per-session` 个点（默认 40）；一个产品不拆到两个会话，单个产品超过上限时返回 `PRODUCT_TOO_LARGE`（R8）；
  - 每道题不超过 `--points-per-request` 个点（默认 12）；
  - 题目由 `JudgeRequest` 生成，写入 `requests/`（`write_requests`）；每个会话另写 `AGENTS.md`（只读规则）和 `run.json`。
- **写前预检**（R6）：
  - 所有远端读取和题目生成都在内存里完成后才开始写；
  - 运行目录必须不存在或为空，否则返回 `RUN_EXISTS`；解析符号链接后的运行目录必须在 Git 之外；
  - 所有目标路径不得重复。
- **可信清单**（R2）：会话目录写完后，在运行目录根下写 `manifest.json`，列出每个会话中 prepare 写下的每个文件（题目、材料、`AGENTS.md`、`run.json`）的 sha256，以及材料对照表。
- 最后写 `run.sh` 和 `plan.json`，`plan.json` 也是 prepare 完成的标志。`plan.json` 内容：
  - 输入：产品清单、Active 的 release/epoch、字段卡版本、提示词版本、`policy_ref`、`reviewer`、`model`；
  - 各产品的评审依据；
  - 每个会话包含的产品与 slug。
- `run.sh` 为每个会话启动一次 `codex exec -m <model> … -C <会话目录>`，并行执行，日志写到 `logs/`。**这一步由操作者执行。**
- 评委提示词（系统规则、AGENTS 规则、操作提示、拒绝类别）是版本化的数据文件 `ingest/judge_batch/prompt.json`。

### 2.2 ingest（离线）

- **先核对清单**（R2）：每个会话里 prepare 写下的每个文件必须与 `manifest.json` 逐字节一致，`requests/` 下不得多出或缺少题目。题目不一致返回 `REQUEST_CHANGED`，其他文件不一致返回 `SESSION_CHANGED`。题目文件自带的哈希不作为依据，因为评委可以连同题目一起改写它。
- 再按 `requests/` 重建题目，经 `FileJudgeClient.complete` 读答案。**答案是不可信输入**（R7）：
  - 按严格 JSON 解析：重复的键、NaN/Infinity 一律拒绝；
  - 先核对类型，再核对取值；
  - 格式严格为 `{"points":[{"slug","verdict","category","reason"}]}`，四个值都是字符串；
  - 题中 slug 每个恰好出现一次，顺序与题目一致；
  - `verdict` 为 approve 或 reject；approve 时 `category` 必须是"通过"，reject 时必须是 prompt.json 列出的拒绝类别之一；
  - `reason` 非空；
  - 任何不符都返回 `ANSWER_INVALID`。
- 任一会话存在未读到的题目，或 slug 覆盖与 plan 不一致，整个导入失败，返回 typed error，不写任何文件。
- 写出 `verdicts/<产品>.json` 和 `summary.json`，后者含每个产品的批准数、拒绝数、拒绝类别分布，以及导入时间 `ingested_at`。可以重复运行，同样的输入得到同样的输出。

### 2.3 publish（默认演练；`--live` 才写线上）

每个产品依次处理，遇到第一个错误即停。每次运行的结果写到 `publish-dry.json` 或 `publish-live.json`（运行报告）；**每个产品的发布状态另存于 `publish/<产品>/`**（R1），关闭和续跑以它为准。

1. **已有发布记录时先续跑**（R1）：
   - 记录已完成：记为 `already_published`，不再请求平台，也不改写该记录；
   - 记录未完成：先对账、再续跑，见下文"发布记录"。
2. **重算并核对**（没有记录或上一次尝试已确认未生效时）：
   - 按当前 Active 重算变更集（步骤同 2.1）。
   - 评审依据与 `plan.json` 不一致（材料增减或换版、编译输出、字段卡、取值协议）时，返回 `INPUTS_CHANGED`（R4）。
   - **已上线的判定**（R5）：Active 中该 slug 的 Claim 与评委所见内容完全一致（state、value、引文指纹），才算已上线并跳过；不能用 `decide_changes` 的 unchanged 代替。
   - 其余批准点必须仍是需评审的变更，且 `content` 与评委看到的完全一致，否则返回 `CONTENT_CHANGED`。
   - 批准点全部已上线的产品记为 `already_published`。
3. **构建候选**：
   - 候选只含批准点，用 `delta_bundle` 生成；
   - 审核标签为 `labelled(MACHINE, policy_ref)`；评分为 `Scores(reviewer, reviewed_at = summary.ingested_at, 批准点 1.0)`；
   - 随附成员只限 Head 中没有的非 Claim 成员；若会覆盖 Head 中已有的非 Claim 成员，停止，返回 `WOULD_OVERWRITE`；
   - 所有 Claim 的审核标签必须是 machine。
4. **`--live` 时上线**：按"发布记录"的阶段逐步进行，即提交、做机器决定（`approve`，带 `policy_ref`，理由为"模型评审（<reviewer>）批准，运维 Issue #N"）、激活、读回核对、按抽检策略提交抽检样本（先发布后抽检）。

**发布记录**（R1）：
- 每次尝试在 `publish/<产品>/attempt-<k>.json` 记下：
  - 冻结的候选文件 `attempt-<k>.bundle.json` 及其 sha256；
  - 机器决定的全部输入；
  - 批准点及其内容指纹；
  - 当前阶段（`built` → `submitted` → `decided` → `activated` → `verified` → `sampled`）、正在进行的步骤，以及平台返回的 candidate、decision、release、epoch、样本数。
- **每个外部步骤之前先写记录**。续跑时一律使用冻结的候选文件，不重新生成（`changed_at` 等不会变），文件哈希不符时返回 `RECORD_INVALID`。
- **冻结与记录之间中断**（第 2 轮 R1）：先写冻结文件，再写记录，记录写完才会发送，所以只有冻结文件、没有记录的那次尝试一定没有发出。续跑时在所有已记录尝试和已冻结文件之上取下一个编号重新冻结，那个文件原样保留，不覆盖、不复用（重新构建的候选 `changed_at` 不同，本来也不会逐字节相同）。冻结文件写不进去时返回 `RECORD_INVALID`。
- **结果未知时先对账**：
  - 先读 Active：其 `candidate_id` 是本记录的候选时，激活已经生效；
  - 否则按平台的幂等语义续做：
    - 同一字节的候选重新提交，平台按 bundle digest 返回已有候选，相当于按 digest 查询；
    - 同一输入的决定返回同一 decision；
    - 已提交过的激活返回已生效的 release；
  - 然后补做读回和抽检（抽检以候选的 base release 为基准，平台保留已有样本）。
- 激活返回 `NEEDS_REBASE`，说明这次尝试确定没有生效。该次尝试记为 `needs_rebase`，下一次运行重新构建，作为新的一次尝试。
- 已完成（`sampled`）的记录不会被改写。

演练不发任何写请求，也不写发布记录。**评审来源如实记录**：Claim 的 review 为 `mode=machine`，并带 `reviewer`、`reviewed_at` 和评分（Claim 合同里的 review 没有 policy 字段）；`policy_ref` 记在平台的机器决定上（`mode=machine`）。任何一处都不记为人工。

### 2.4 close（默认演练；`--live` 才写线上）

用于清理同一产品在人工队列里遗留的候选（例如 #384）。评委只审过本批编译的内容，所以只有当遗留候选在该 slug 上提议的内容**正是**本批评委所见的内容时，才能沿用评委的结论（R3）。

- **核对目标候选**：
  - 服务密钥读不到待审候选的成员内容（`preview` 只给出按 slug 分组的变化），因此操作者用 `--candidate-bundle` 提供该候选提交时的 bundle 文件；
  - 写之前，命令先从平台核对：
    - 候选在待审队列中，且其 subjects 含本产品；
    - 成员数、移除数与文件一致；
    - `preview` 的 base release 与文件一致；
    - 按当前 Head 计算出的 added/changed/removed/unchanged 分组与 `preview` 完全一致；
  - 任一不符返回 `CANDIDATE_BUNDLE_MISMATCH`，不发任何写请求。
- **逐 slug 比对**：候选在该 slug 上的 Claim 内容指纹必须等于本批评委所见的 `content`。不等的 slug 记为 `content_differs`，候选里没有的记为 `not_in_candidate`，这两类都不关闭。
- **评委拒绝的点**：用 RV6d 的机器通道拒绝，理由为"模型评审（<reviewer>）拒绝，运维 Issue #N"。
- **已发布的批准点**：以"已由模型评审候选 <id> 取代"为由拒绝，但只限同时满足以下三条的点：
  - 该点在本批**已完成的发布记录**里；
  - 读 Active 确认其内容正是评委批准的内容；
  - 遗留候选在该点上的内容也一致。
  - 不满足的点记为 `not_live`，不关闭。

每个 slug 单独发一次请求；返回 `MEMBER_DECIDED` 时视为已经关闭。可以续跑。

客户端新增三个方法：
- `review_queue(space, status)`；
- `reject_points(space, candidate, slugs, reason, policy_ref)`；
- `preview(space, candidate)`。

## 3. 不做什么

- 命令不调用模型，也不启动 `codex exec`。评委会话是操作者的步骤；会话日志和模型身份按 #384 的做法保存在运行目录。
- 不处理"直接评审人工队列候选"（#384 的第一阶段）。新的编译变更走本命令，不先进人工队列；已有的人工队列遗留只用 `close` 清理。
- 不改平台接口、迁移、`contracts/`、评委规则以外的提示词，也不改审核路由策略（`review_policy.json`）。若以后平台为服务密钥提供待审候选的成员读取，`close` 可改为直接从平台比对内容，不再需要操作者提供 bundle 文件。这需要另开切片。

## 4. 改动范围

- 新增 `harness/src/insurance_harness/ingest/judge_batch/`。放在 ingest 下，是因为它要调用编译器的发布代码，而 review 是核心目录，按 G1 守卫不能依赖 compilers。各文件如下：
  - `__init__.py`、`__main__.py`、`cli.py`；
  - `points.py`（变更点与评审依据）；
  - `sessions.py`（会话与题目）；
  - `manifest.py`（写前预检与可信清单）；
  - `verdicts.py`（导入）；
  - `publishing.py`（重算、核对与构建）；
  - `records.py`（发布记录与续跑）；
  - `closing.py`；
  - `launch.py`（`run.sh` 与沙箱边界，第 2 轮 R2）；
  - `prompt.json`。
- `harness/src/insurance_harness/eval/judge_files.py`：新增公开的 `stored_requests(run_dir)`，供导入时重建题目。
- `harness/src/insurance_harness/bundle/client.py`：
  - 新增 `review_queue`、`reject_points`、`preview`；
  - `Candidate` 增加平台返回的 `bundle_digest`。
- 新增 `harness/src/insurance_harness/bundle/candidate_reviews.py`，放这些方法的响应模型，使 `client.py` 不超过 500 行。
- 实现方测试。

## 5. 验收（RED，Claude 编写）

`harness/tests/ingest/test_judge_batch.py`（主流程）与 `test_judge_batch_recovery.py`（R1、R5）、`test_judge_batch_inputs.py`（R2、R4、R6–R8）、`test_judge_batch_close.py`（R3）。第 2 轮的 R1、R2、R4 由实现方测试覆盖：`test_judge_batch_freeze.py`、`test_judge_batch_launch.py`、`test_judge_batch_fields.py`。全部离线，使用 fake HTTP 和假答案文件，复用 `test_publish_cli` 与 `test_claim_changes_publish` 的夹具。恢复类测试使用按平台幂等语义建模的 fake：按 digest 去重候选，同一输入返回同一决定，激活可重放，样本保留已有。

1. **prepare**：
   - 只为 upgrade/add 等变更点建题；题目哈希可复核；
   - 写出 `run.sh`、`AGENTS.md`、`manifest.json`，命令本身不调用 codex；
   - 运行目录非空时返回 `RUN_EXISTS`；运行目录在 Git 仓库内时拒绝；
   - 同名不同材料各自保留全文；
   - 单个产品超过会话上限时返回 `PRODUCT_TOO_LARGE`。
2. **ingest**：
   - 正确答案能导入，写出 verdicts 和 summary；
   - 以下情况都返回 typed error，且不写文件：
     - 答案问题：缺 slug、多 slug、重复 slug、类别不在列表内、approve 与类别不符、重复的 JSON 键、类型错误（数组、对象）；
     - 题目问题：题目被改动（包括连同自带哈希一起改写）、存在未读到的题目。
3. **publish 演练**：
   - 只含批准点，标签为 machine，带 reviewer；
   - 不发写请求，不写发布记录。
4. **publish `--live`**：
   - 依次提交、做机器决定、激活，并读回核对；Claim 的 review 为 machine 且带 reviewer，决定为 `mode=machine` 且带 policy_ref；
   - 再次运行时该产品记为 `already_published`，不再提交，发布记录不变；
   - 在提交、决定、激活、读回、抽检任一步的响应丢失后，续跑：
     - 只用冻结的候选；
     - 不产生第二个候选；
     - 补齐读回与抽检；
     - 最终记录完整；
   - 编译输出在评审后被改动时返回 `CONTENT_CHANGED`；
   - 评审依据变化（登记表新增材料）时返回 `INPUTS_CHANGED`；
   - Active 的值变了而引文相同，返回 `CONTENT_CHANGED`，不记为已发布；
   - 平台返回 `NEEDS_REBASE` 时立即停止，结果文件记下停止的产品。
5. **close**：
   - 演练不发请求；
   - `--live` 每个 slug 单独发一次；返回 `MEMBER_DECIDED` 时记为已关闭；
   - 请求体只含 slugs、outcome=reject、reason、policy_ref；
   - 遗留候选在该 slug 上的内容与评委所见不同时不关闭；
   - bundle 文件与平台上的候选不符时不发任何写请求；
   - 取代理由取自已完成的发布记录。

**门禁**：`uv run pytest`（受影响模块 + 全量）、`uv run ruff check .`、`uv run mypy src tests`、架构守卫、`git diff --check`。手写文件不超过 500 行。

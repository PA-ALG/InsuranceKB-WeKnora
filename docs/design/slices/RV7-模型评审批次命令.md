# RV7 · 模型评审批次命令：编译变更 → 独立评委 → 机器发布

> 状态：Claude 2026-10-28 提出 ｜ 作者：Claude Code
> 依据：
> - 用户 2026-10-27："需要审核的太多了，这版你借助 gpt6.0 或者 opus5.5 直接判断吧"，以及"你全部决定吧，不要我来批准了"。审核由独立模型评委（GPT-6 Astra xhigh）完成，结果按机器审核发布，并如实标注评审来源；
> - 参考运行：运维 #384（人工队列候选的评审与发布，2026-10-27）、#403（编译器升级批次，2026-10-28）。两次都靠仓库外的一次性脚本（收集、建题、`codex exec`、导入、建候选、发布、关闭遗留审核点），本切片把这条链路固化为有测试的命令；
> - 复用：`eval/judge_files`（文件交换与哈希校验）、`changes.decide_changes`（含 S12c-1b 的 UPGRADE）、`publish_changes.delta_bundle`、`review.routing.labelled`、`bundle.client`（含 RV6d 的机器通道拒绝）、`review.spot_check`（先发布后抽检）。
>
> 实现方：Claude ｜ 审核方：Codex ｜ 真实调用：0（命令本身不调用模型；评委会话由操作者另行启动）

## 1. 目标

把一次编译的产出变成**经独立评委逐点判定**、再按**机器审核**发布的变更，全程可复现、可中断续跑：

```
python -m insurance_harness.review.judge_batch prepare --registry R --compile-root C --run-root J [--products …]
#   操作者：bash J/run.sh            （每个会话一次 codex exec，命令本身不调用 codex）
python -m insurance_harness.review.judge_batch ingest  --run-root J
python -m insurance_harness.review.judge_batch publish --registry R --compile-root C --run-root J \
        --issue N [--live]
python -m insurance_harness.review.judge_batch close   --run-root J --product P --candidate ID [--live]
```

`--run-root` 必须在任何 Git 仓库之外（`judge_files.check_run_directory`）。

## 2. 各步骤

### 2.1 prepare（只读线上）

- 对每个产品，用发布同一套代码重建 Claim：`registry_inputs`、`publication_entries`、`load_trusted_pages`、`claims_from`，再对当前 Active 运行 `decide_changes`。
- 需要评审的变更点为 `upgrade`、`add`、`fill`、`supersede`，其余不进入评审。
- 每个评审点记录以下内容：
  - slug、field_key、change；
  - 线上值：仅 upgrade/fill/supersede 有，取自 Active 中 `base_slug` 对应的 Claim，含 state、value、引文；
  - 新值：state、value、引文；
  - `content`：评委看到的内容指纹，由 state、规范化后的 value、每条引文的 `(source_ref, quote_sha256)` 组成。
- 每份材料全文逐页读出（`PageReader.pages`），写到 `sources/<产品>/<文件名>.txt`，页首标记为 `[page N]`。
- 会话划分：
  - 产品按编号排序后依次装入会话，每个会话不超过 `--points-per-session` 个点（默认 40），一个产品不拆到两个会话；
  - 每道题不超过 `--points-per-request` 个点（默认 12）；
  - 题目由 `JudgeRequest` 生成，写入 `requests/`（`write_requests`，题目带哈希）；
  - 每个会话另写 `AGENTS.md`（只读规则）和 `run.json`。
- 运行目录根下写 `plan.json`，内容包括：
  - 输入：产品清单、Active 的 release/epoch、字段卡版本、提示词版本、`policy_ref`、`reviewer`、`model`；
  - 每个会话包含的产品与 slug。
- 同时写出 `run.sh`：每个会话启动一次 `codex exec -m <model> … -C <会话目录>`，并行执行，日志写到 `logs/`。**这一步由操作者执行。**
- 运行目录里已有 `plan.json` 时拒绝运行，返回 `RUN_EXISTS`，不覆盖已有题目。
- 评委提示词（系统规则、AGENTS 规则、操作提示、拒绝类别）是版本化的数据文件 `review/judge_batch/prompt.json`。

### 2.2 ingest（离线）

- 按 `requests/` 重建题目，经 `FileJudgeClient.complete` 校验哈希后读答案。每个答案必须满足：
  - 严格为 `{"points":[{"slug","verdict","category","reason"}]}`；
  - 题中 slug 每个恰好出现一次，顺序与题目一致；
  - `verdict` 为 approve 或 reject；approve 时 `category` 必须是"通过"，reject 时必须是 prompt.json 列出的拒绝类别之一；
  - `reason` 非空。
- 任一会话存在未读到的题目（`unconsumed`），或 slug 覆盖与 plan 不一致，整个导入失败，返回 typed error，不写任何文件。
- 写出 `verdicts/<产品>.json` 和 `summary.json`，后者含每个产品的批准数、拒绝数、拒绝类别分布，以及导入时间 `ingested_at`。可以重复运行，同样的输入得到同样的输出。

### 2.3 publish（默认演练；`--live` 才写线上）

每个产品依次处理，遇到第一个错误即停，结果在每个产品处理完后写到 `publish-dry.json` 或 `publish-live.json`：

1. **重算变更**：按当前 Active 重算变更集（步骤同 2.1）。
2. **核对评审结论**：每个评委批准的点必须仍是需评审的变更，且 `content` 与评委看到的完全一致；不一致时停止，返回 `CONTENT_CHANGED`。
   - 若某个批准点在 Active 中已是同样的内容（判为 unchanged），说明已在先前的运行中发布，跳过该点。
   - 批准点全部已发布的产品，记为 `already_published`，不提交。这样中断后可以续跑。
3. **构建候选**：
   - 候选只含批准点，用 `delta_bundle` 生成；
   - 审核标签为 `labelled(MACHINE, policy_ref)`；评分为 `Scores(reviewer, reviewed_at = summary.ingested_at, 批准点 1.0)`；
   - 随附成员只限 Head 中没有的非 Claim 成员；若会覆盖 Head 中已有的非 Claim 成员，停止，返回 `WOULD_OVERWRITE`；
   - 所有 Claim 的审核标签必须是 machine。
4. **`--live` 时上线**：
   - 依次提交、做机器决定（`approve`，带 `policy_ref`，理由为"模型评审（<reviewer>）批准，运维 Issue #N"）、激活，再读回核对（`bundle.client.publish`）；
   - 按抽检策略提交抽检样本（先发布后抽检）。

演练不发任何写请求。**评审来源如实记录**：Claim 的 review 为 `mode=machine`，并带 `reviewer`、`reviewed_at` 和评分（Claim 合同里的 review 没有 policy 字段）；`policy_ref` 记在平台的机器决定上（`mode=machine`）。任何一处都不记为人工。

### 2.4 close（默认演练；`--live` 才写线上）

用于清理同一产品在人工队列里遗留的候选（例如 #384）：

- 评委拒绝的点：用 RV6d 的机器通道拒绝，理由为"模型评审（<reviewer>）拒绝，运维 Issue #N"；
- 已由机器候选发布的批准点：以"已由模型评审候选 <id> 取代"为由拒绝。

每个 slug 单独发一次请求；返回 `MEMBER_DECIDED` 时视为已经关闭。可以续跑。客户端新增两个方法：`review_queue(space, status)` 与 `reject_points(space, candidate, slugs, reason, policy_ref)`。

## 3. 不做什么

- 命令不调用模型，也不启动 `codex exec`。评委会话是操作者的步骤；会话日志和模型身份按 #384 的做法保存在运行目录。
- 不处理"直接评审人工队列候选"（#384 的第一阶段）。新的编译变更走本命令，不先进人工队列；已有的人工队列遗留只用 `close` 清理。
- 不改平台接口、迁移、`contracts/`、评委规则以外的提示词，也不改审核路由策略（`review_policy.json`）。

## 4. 改动范围

- 新增 `harness/src/insurance_harness/review/judge_batch/`：`__init__.py`、`__main__.py`、`cli.py`、`points.py`、`sessions.py`、`verdicts.py`、`publishing.py`、`closing.py`、`prompt.json`；
- `harness/src/insurance_harness/eval/judge_files.py`：新增公开的 `stored_requests(run_dir)`，供导入时重建题目；
- `harness/src/insurance_harness/bundle/client.py`：新增 `review_queue`、`reject_points`；
- 实现方测试。

## 5. 验收（RED，Claude 编写）

`harness/tests/review/test_judge_batch.py`，全部离线，使用 fake HTTP 和假答案文件，复用 `test_publish_cli` 与 `test_claim_changes_publish` 的夹具：

1. **prepare**：
   - 只为 upgrade/add 等变更点建题；题目哈希可复核；
   - 写出 `run.sh` 和 `AGENTS.md`，命令本身不调用 codex；
   - 运行目录已有 `plan.json` 时返回 `RUN_EXISTS`；
   - 运行目录在 Git 仓库内时拒绝。
2. **ingest**：
   - 正确答案能导入，写出 verdicts 和 summary；
   - 以下情况都返回 typed error，且不写文件：缺 slug、多 slug、重复 slug、类别不在列表内、approve 与类别不符、题目被改动、存在未读到的题目。
3. **publish 演练**：
   - 只含批准点，标签为 machine，带 reviewer；
   - 不发写请求。
4. **publish `--live`**：
   - 依次提交、做机器决定、激活，并读回核对；Claim 的 review 为 machine 且带 reviewer，决定为 `mode=machine` 且带 policy_ref；
   - 再次运行时该产品记为 `already_published`，不再提交；
   - 编译输出在评审后被改动时返回 `CONTENT_CHANGED`；
   - 平台返回 `NEEDS_REBASE` 时立即停止，结果文件记下停止的产品。
5. **close**：
   - 演练不发请求；
   - `--live` 每个 slug 单独发一次；返回 `MEMBER_DECIDED` 时记为已关闭；
   - 请求体只含 slugs、outcome=reject、reason、policy_ref。

**门禁**：`uv run pytest`（受影响模块 + 全量）、`uv run ruff check .`、`uv run mypy src tests`、架构守卫、`git diff --check`。手写文件不超过 500 行。

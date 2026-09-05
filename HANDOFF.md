# HANDOFF — Enterprise LLM Wiki

> 当前运行/交接状态的唯一入口。贡献规则只以 [`AGENTS.md`](AGENTS.md) 为准；
> 规格和历史讨论分别留在适用 OpenSpec 与历史合订文档，不在这里重复。

## 1. 当前结论（2026-09-05）

**MVP-815 已完成代码交付与 C7 可见验收。** 正式代码已由
[PR #123](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/123) 以一个
squash commit 合入 `main`：

- MVP code commit（已在 main）：`ef47bee2b93d6a9cb4511133deaef6e700d915ce`；
- tree：`d868e8f2fd51250c71366c8c723f500482e7de44`；
- parent：`dfa87e11d5a434b6823582285c17498e715dd8f1`；
- 工程交接文档：[PR #124](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/124)；
- PR #124 合并后的最终 `origin/main` HEAD：
  `99205db986eae2a9fa4bc956c053b94298d0b114`；
- 交付方式：从当时最新 `origin/main` 重建最终状态，**未合入或整体 squash
  149 条历史迭代提交**；
- 远端门禁：两套 deterministic、两套 PostgreSQL integration、两套
  wheel-smoke 全部通过。

**830 G1 已完成。** PR #126 已合入：

- 当前 `origin/main`：`0e7a26568`；tree：`b96aa35fd2fe86283757deb258920c489de4b4b6`；
- G1 状态：`PASS / FLOW=PASS / QUALITY=DEFERRED / NOT_ACCEPTED_FOR_PRODUCTION`；
- G1 closeout：[`g1-closeout.json`](docs/insurance-kb/evidence/830-g1/g1-closeout.json)；
- G1 D3 app image：`sha256:37918140b2902918f8e7cbb89008bc47d1480e9e65d2056c54b6b5317a5e6eeb`；
- G1 真实 app build：总墙钟约 `131m07s`，其中 `make build-prod=6557.9s`。

用户已于 2026-09-04 确认在 G1 与 G2 之间先完成一次性 **BA0 本地构建复用工程门**，
并已明确授权 BA0 implementation。BA0 不是产品 Goal，不改变 WeKnora/Harness 架构或
G2 DoD。当前指针原子切换为：

```text
CURRENT_AUTHORIZATION=NONE
CURRENT_PRODUCT_GOAL=NONE
CURRENT_ENGINEERING_GATE=BA0_LOCAL_BUILD_REUSE
BA0_KIND=ENGINEERING_GATE_NOT_PRODUCT_GOAL
BA0_STATUS=PASS
G1_STATUS=PASS
G2_STATUS=LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION
ORIGIN_MAIN_BASE=0e7a26568a2164f9501e409f38fee0d4a62539cb
ORIGIN_MAIN_TREE=b96aa35fd2fe86283757deb258920c489de4b4b6
IMPLEMENTATION_BASE=874e50d44aec5941faae045e761280aa69aee1a3
IMPLEMENTATION_BASE_TREE=2ec76af38258a0220d5dc117a9b789890345e7d7
WORKTREE=/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-ba0-implementation
BRANCH=codex/830-ba0-implementation
OWNER=830-BA0总控
CURRENT_RED=NONE
NEXT_PHYSICAL_RESULT=RETURN_TO_USER_FOR_G2_AUTHORIZATION
NEXT_ACTION=RETURN_TO_USER_FOR_G2_AUTHORIZATION
REAL_APP_BUILD_BUDGET=2
REAL_APP_BUILDS_USED=2
REAL_APP_BUILD_BUDGET_REMAINING=0
```

BA0 终态（2026-09-05）：D2 恢复构建与 exact reuse PASS，D3 制品烟测 PASS；
累计真实构建 2/2（原失败1 + 用户新增授权恢复成功1），复用 build=0，D3 build/pull=0。
冻结构建源 `fe9a97d092fbb470985bf32c5c4e5a9e6ec135c9`，完整 identity/image/receipt
见 `docs/insurance-kb/evidence/830-ba0/ba0-closeout.json`；累计授权历史见同目录
`recovery-authorization.md`。尚未合入 main，未进行 HTTP/业务或 GitHub live 验收。


批准设计：[`2026-09-04-830-ba0-local-build-reuse-design.md`](docs/superpowers/specs/2026-09-04-830-ba0-local-build-reuse-design.md)。
可执行计划：[`2026-09-04-830-ba0-local-build-reuse.md`](docs/superpowers/plans/2026-09-04-830-ba0-local-build-reuse.md)。
适用规格：[`127-830-ba0-local-build-reuse`](openspec/changes/127-830-ba0-local-build-reuse/)。
BA0 `PASS` 后必须把授权清零并
`RETURN_TO_USER_FOR_G2_AUTHORIZATION`；不得自动启动 G2。

## 2. 用户应体验什么

正式 MVP 入口知识库是 `medical-insurance-mvp`。进入“产品 Schema Wiki”后，
应看到：

- 产品：平安 e 生保（尊享版）医疗保险；
- 徽标：`当前 MVP · 只读`；
- `7 个分类 · 67 个字段`；
- 中文字段名为主标签，英文 `field_id` 仅作次级技术标识；
- 字段值保留 `present / absent_explicitly / unknown` 语义；
- 可从字段打开“原文来源”，切换来源并查看固定页码、框选与引文。

`C6-ISOLATED-R1-ACCEPTANCE-*` 是历史隔离验收库，不是产品入口。页面显示
“产品 Schema Wiki 暂不可用”是 fail-closed 状态，不能据此判断代码版本不存在。
整个页面不可用时先查 entry/serving 映射、唯一 Active Head/release members 和
Wiki + RAW 双 ACL；只有引文正文不可用时再查 native source custody 与
citation-token 运行时签名环。

frozen release scope、named-human decision ring 与 publish-authorization ring 只
属于 Candidate 决策/发布链，Golden evaluator ring 只属于后续 C4；它们都不是 C7
只读体验的前置条件。只读演示不得为了“让页面可用”而打开这些写链路。

端口也不是版本号：

- `8081` 是 C7 期间明确保持不变的旧生产实例；
- `18085`（UI）与 `18094`（隔离后端）是当次 C7 验收环境；
- 正式版本身份由 Git commit/tree、镜像/二进制 SHA、release ID 与 activation
  epoch 共同决定，不能用“打开哪个端口”代替。

## 3. C7 验收事实

C7 使用既有 epoch2 做纯读重开，没有重新审批、签名、发布或推进 Head：

- 验收源码：`9fcf3386833d822a31f2de13fdf76c3eb6b13795`；
- 验收 tree：`7314d1c9bc82dc7efb114affb6f2450d0dbd36ae`；
- 隔离后端二进制 SHA-256：
  `aa069e2566fd0b88fb6280bae8f1759d390fefdcfd32e1820602e0bdaa2ebc34`；
- Active-current 与 explicit-pinned/no-fallback：PASS；
- 7 分类、67 字段：PASS；
- citation preview/content：17/17 PASS；
- canonical lineage：1 个 `text` + 16 个 `parent_text`，唯一 owner 全部 PASS；
- C1 self-hash/native manifest、双 parse 摘要、Unicode code-point offset：PASS；
- 三份 PDF 的页码、bbox、file SHA、quote SHA 与可见高亮：PASS；
- UI 来源切换与三份 PDF 可见验收：PASS；
- 五表终态：preparations/releases/members/heads/receipts =
  `2/2/150/1/2`，验收前后不变；
- 旧 R1、epoch2 release/receipt/Head/75 members、生产 `8081`：不变；
- business DB writes、provider/model、C4、Candidate、release、receipt、Head、
  approval、signature effects：全部为 0；隔离角色密码轮换 1 次，未持久化敏感值。

B0 已把授权范围内的只读副本放入 Evidence Pack。用户冻结输入
`c7-ui-visible-terminal.json` 的 external SHA-256 为
`20575de17ca3a5a98e540848a245ef1af4a27d3e2feca12c7a38424350d45b50`，
canonical self-hash 为
`1d57527fbfa3dbfae9b11d14295a4efde0cc0c379b8d5c506c05ce8a0ea59ff6`。
此前记录的 `0e24db1d6ae4632acb538d03b18d84d2ffd0d41b8c39ef6cb5d251318dfa3396`
对应后续 `c7-ui-cache-corrected-terminal-20260831.json`；两份回执绑定同一 815
commit/tree/backend binary/epoch2 release，但必须分别登记，不能互相替代。

## 4. Chrome 可见验收的正确路径

需要复用用户现有 Chrome 登录态时，使用 Computer Use 直连
`com.google.Chrome`（`node_repl` + `@oai/sky`）。这条路径不依赖 ChatGPT/Codex
浏览器扩展，也不要求切换 Chrome Profile。

必须把两个问题分开：

1. 能否控制 Chrome；
2. WeKnora 站点会话是否仍已登录。

扩展未安装不等于 Chrome 不可控；页面跳到 `/login` 也不等于控制通道故障。
不得把密码、session、token 写入仓库、回执或日志；需要登录时由用户在可见页面
自行完成。

## 5. C4 历史后续边界（不是当前队列）

旧提交 `6d56618d0d9796e10d87f93e6b04188a49da9296` 只作历史参考，**不在
main**。它绑定旧 Candidate、固定 reviewer=`linyao`、固定
attestor=`workspace-owner-houjing`，真实结论是 `QUALITY_FAIL`。

若未来路线重新授权 C4，则必须：

1. 从最新 `origin/main` 新建独立 OpenSpec/Mission；
2. 先冻结业务目标、Metric ID、输入权威、预算、provider/model 边界和人工责任；
3. 使用当前 main 的 canonical Candidate/Evidence/Golden 合同，禁止复制旧哈希、
   旧 reviewer/attestor 或把 `QUALITY_FAIL` 改写成 PASS；
4. provider/model、DB、审批、签名、Candidate/release/Head 等外部动作分别申请并
   记录，默认均为 `NOT RUN`；
5. C4 的失败不能修改当前已验收的 C7 serving release。

历史详细接手卡见
[`docs/insurance-kb/26-mvp-815-engineering-handoff.md`](docs/insurance-kb/26-mvp-815-engineering-handoff.md)。

## 6. 仓库整理状态

已创建完整 Git 引用归档：

- 文件：`../archives/insurancekb-weknora-pre-cleanup-20260831.bundle`；
- mode：`0600`；
- bytes：`147412595`；
- SHA-256：`7d35f64fe2611148ca96760752d6a1c331be8f62433fc07ec274647e66a31725`；
- `git bundle verify`：PASS；486 refs，complete history。

当前主工作区和 4 个历史 worktree 为 dirty，全部保护；任务私有回执、发布证据、
凭据相关目录也不自动删除。clean worktree 的精确处置清单见
[`docs/insurance-kb/27-mvp-815-repository-cleanup.md`](docs/insurance-kb/27-mvp-815-repository-cleanup.md)。

## 7. 绝不再踩的坑

- 端口、知识库名称、容器名称都不是版本身份；必须核对 commit/tree、制品 SHA、
  release/epoch。
- frozen 历史向量与当前工厂输出应分别通过 canonical/typed 校验；不能强迫新
  Candidate 派生哈希等于旧 release，也不能改旧向量“让测试变绿”。
- Python 持久化 quote offset 是 Unicode code-point 域；Go frozen reader 不能按
  UTF-8 byte 下标切中文。
- `parent_text` 必须先完整验真到 canonical native child；overlap 只按唯一连续、
  manifest 顺序和 non-overlap contribution owner 选择，不能“取第一个”。
- task-private replay 缺私有工件时不能向 PostgreSQL lane 泄漏 module-level skip；
  lane 必须 tests > 0、skipped = 0。
- 本地绿不等于 CI 绿；合并前必须等远端真实门禁。
- 不从 dirty 工作区构建正式交付，不整体 merge 历史分支，不在 main 保留推倒重来
  的中间实现。
- 启动 Docker/Colima 可能自动恢复 `8081` 容器；未确认生产影响前不得把“启动
  本地依赖”当作无副作用操作。
- `start_all.sh --no-pull` 当前仍会执行 `compose up --build`，不能当作 D3 复用入口；
  BA0 D3 必须使用 exact image 和 standalone `CONTAINER_ARTIFACT_SMOKE`，且
  `--no-build --pull never`；它不连接业务数据库，也不冒充 G2 的 HTTP 产品验收。
- 不得为测量主动清空 BuildKit/Go cache 或重复冷构建；相同 artifact identity 必须先
  lookup，命中时 Docker build invocation 必须为 0。
- 凭据不得出现在命令行 DSN、traceback、文档或 Git；异常泄漏后先轮换再继续。

## 8. 接手阅读顺序

1. [`AGENTS.md`](AGENTS.md)
2. [830 技术蓝图](jlx_enterprise_llm_wiki_technical_blueprint_830.md)
3. [830 开发执行章程](docs/insurance-kb/28-development-execution-charter-830.md)
4. [830 Goal Cards](docs/insurance-kb/29-goal-cards-830.md)
5. 本文件
6. [BA0 本地构建复用设计](docs/superpowers/specs/2026-09-04-830-ba0-local-build-reuse-design.md)
7. [BA0 实施计划](docs/superpowers/plans/2026-09-04-830-ba0-local-build-reuse.md)
8. [B0 Evidence Pack](docs/insurance-kb/evidence/830-b0/)
9. [MVP-815 工程接手卡](docs/insurance-kb/26-mvp-815-engineering-handoff.md) 与
   [OpenSpec 120](openspec/changes/120-schema-wiki-medical-596-1-mvp/) 只作已冻结历史
   证据；后续 Goal 仍须自己的授权与适用 OpenSpec。

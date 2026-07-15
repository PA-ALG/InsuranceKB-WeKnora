# 21. 复审前自测（Self-Test Before Submit）

> 治理/安全攸关、会被 codex 或同伴复审的变更，**送复审前**必跑的自测方法论。
> 源自 019（Golden/QualityGate）被 codex 拉扯 **7 轮**才 APPROVED 的教训固化。与 [17-team-collaboration](17-team-collaboration.md)、[18-ai-collaboration](18-ai-collaboration.md) 同属流程规范。

## 立此存照：7 轮返工的根因

019 被拉扯 7 轮，根因不是难，是**反应式**——每轮只按 review 条目补 `if`，没从不变量重设计、没在提交前自己当红队。于是**同一类 bug 换个位置又出现**（身份绑在可变标签、同一判定两处各自推导），一轮抓一个，抓了六轮：`baseline_id` → golden hash → hash 大小写 → disputed 排除集 → 非 reset golden 集，根因都是"局部循环加条件"而非"单一权威原语"。

本文就是那 7 轮的价钱。写任何会被复审的变更前，先把下面这套走完，别让 reviewer 替你发现。

> 本项目 SDD/TDD、"AI 会话不执行 git commit/push（人验收后提交）"——这里说的"送复审"指**请人验收 / 交 codex 前**。

## 何时用

- 交付任何 **openspec change**、**治理/安全攸关**（gate、审批、lineage、哈希身份、准入、merge 自动路径）代码；
- 任何**会被 codex / 同伴复审**的 PR，尤其"改实现会红一堆存量测试"的那种。

## 三条铁律（先记住为什么会返工）

1. **补 `if` ≠ 修复。** 按 review 条目打补丁，只把 bug 挪个位置。要从**不变量**重设计接口，让非法状态**无法构造**。
2. **CI 绿 ≠ 规格达标 ≠ 不变量不可绕过。** 绿的可能是"把违规行为写进测试并断言其正确"。规格（`openspec/changes/<NNN>/specs`、design、本 `docs/insurance-kb/` 企业设计）是权威，测试是为验证规格而存在，不是反过来。
3. **把审查左移。** 提交前自己派对抗性红队，别坐等下一轮挨批——你能赶在 reviewer 前面挖出真绕过并修掉，这就是不返工的差别。

## Gauntlet（按顺序，每步过了才送复审）

1. **规格对齐**：默认值 / 边界 / fail-closed 语义**从 spec·design 抄**，不是从"少改测试"倒推。安全语义一律 **fail-closed**（缺 gate/缺画像统一走 ReviewItem，别放行）。
2. **从不变量重设计，而非补 if**：审批/授权类 API 收**领域对象自算 hash**、强制身份一致、必填项不可省、产物用 **content-addressed**（path+sha256+count）。目标是"调用方传错/漏传/伪造/复用旧对象，系统仍 fail-closed"。
3. **自派对抗性红队**（见下"红队配方"）：并行 general-purpose agent 各攻一个面，**写脚本 live 复现才算数**，不接受走查猜测。
4. **每条发现：live 复现 → TDD 锁 → 修 → 复跑**：先复现（数值/结论与报告对齐）**再**动手；测试名引用规格条款号（如 `test_q4_6_...`）；修完复跑证明关闭。**别假设发现是真的或已修的。**
5. **门禁全绿**（本地实跑，不是只看 CI 徽章）：
   ```bash
   cd harness && uv run ruff check . && uv run mypy src tests && uv run pytest -m "not live and not integration_postgres" -q
   ```
   绿了再对着下面"问题清单"逐条自查一遍。
6. **诚实交付物**：`validation-report` 只写**已验证事实 + 已知边界**（显式写出机制**不**保证什么、边界属哪一层），别把"测试通过"写成"问题闭环"；`tasks.md` 记**裁决**（每个设计判断 + 依据）；更新 `HANDOFF.md`。

## 反复返工问题清单（每条≈一轮返工，送复审前逐条自查）

| 反模式 | 气味（smell） | 修法 |
|---|---|---|
| **身份绑在可变标签** ⚠️头号惯犯 | 用可改名的字符串（id/name/label）代理"是不是同一个/新的东西" | 钉在**内容/基准的不变量**（content_hash / release_hash / digest 本身），不钉在名字上 |
| **同一判定两处各自推导→漂移** | "哪些 key 可评测""什么算同一个 X"在多个循环/函数各写一遍 | 抽**单一权威原语**（如 `excluded_disputed_keys` / `_canon_hash`），所有点共用 |
| **构造期校验器可被绕过** | 只靠 pydantic `AfterValidator`/构造期规范化保证安全比较 | `model_copy(update=)`/`model_construct` 跳过校验；**安全比较点再规范化一次**（同一 canonical 原语），belt-and-suspenders |
| **收紧一条路径，忘了对称路径** | 给 A 路径加护栏，B 镜像路径没加同样约束 | 加护栏**成对想**：reset 要求 golden 不同 ⇒ 非 reset 必须要求 golden 相同 |
| **为"DRY/单一权威"删冗余安全层** | 删掉某层安全短路，让安全 100% 押在另一层"正确 honor"上 | 安全冗余=纵深防御=特性；加权威层时**保留**既有 fail-closed 短路，不是替换 |
| **默认 fail-open / gate 可选** | `gate=None` 放行、安全开关默认关、为兼容留后门 | 安全默认 **fail-closed**；缺件统一进 ReviewItem |
| **零分母给满分** | 无观测记 1.0、未回验证据当可信 | 无观测记 **0.0**；未回验不得计入；`None`（没测）≠ `0.0`（测得为零） |
| **为少改存量测试而将就实现** | 因为"改实现会红一堆测试"而在生产码留后门 | 契约收紧导致测试红是**预期的**：迁移测试、用命名清晰的测试替身（`green_gate`/`allow_all_gate`），别留后门 |
| **哈希手工挑字段** | 手拼字段算 hash（漏字段 / 分隔符碰撞） | canonical 全量序列化（排序 JSON `model_dump`），**显式声明**排除项（如 `created_at`） |
| **文档过度声称** | 把"规范化"说成"证明来源"、把"跑通"说成"闭环" | 只报已验证事实 + 已知边界；写清**不**保证什么、根因属哪一层（如授权真实性属下一 change / 上游） |

## 红队配方（可直接照抄）

送复审前，派 **N 支并行 general-purpose Agent**，每支只攻一个面：

- 常见面：领域类型合法域（NaN/±inf/越界/负计数/bool 强转）· 聚合/统计口径漂移 · 自动路径（gate·merge：删预检查、旧签名、时序、pending 顺序）· 批准·lineage（空理由、跨 lineage 降级、伪造 prior）· 身份/哈希规范化 · 排除集完备性。
- 每支硬性要求：**写脚本、live 跑、只认能复现的发现**；输出结构化结论（`{面, 是否绕过, 复现脚本, 建议锁定用例}`）。
- 挖到的每条：live 复现 → TDD 锁定用例 → 修 → 复跑。**一次跑 2000 次 fuzz + 边界枚举**比走查更能证明"攻不破"。
- 归档：留 README 的 before/after **证据摘要** + 关键复现脚本即可，其余探针收敛进 `test_*`，别把几十个一次性脚本塞进仓库（噪声）。参考 019 的 `openspec/changes/019-golden-quality-gate/redteam/`。

## 一句话总纲

**先当自己的 reviewer，从不变量设计、把身份钉在内容而非标签、每条发现 live 复现再修——这样一轮过，而不是七轮。**

## 当作可调用 skill 用（可选）

本仓库 `.gitignore` 忽略 `.claude/`，故不随仓库分发 Claude Code skill。若想在会话里 `/self-test-before-submit` 直接调用，把本文复制成个人 skill：

```bash
mkdir -p ~/.claude/skills && \
cp docs/insurance-kb/21-selftest-before-submit.md ~/.claude/skills/self-test-before-submit.md
# 首行补 skill frontmatter： --- \n name: Self-Test Before Submit \n description: ... \n ---
```

`CLAUDE.md` 的「复审前自测」小节已指向本文，后续 AI 会话送复审前会被自动导到这套。

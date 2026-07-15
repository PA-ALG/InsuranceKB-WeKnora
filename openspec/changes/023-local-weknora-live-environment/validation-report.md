# 023 本机 WeKnora live 环境验证报告

> 日期：2026-07-15。本文严格区分软件门禁、本机基础设施、外部模型与真实五节点 live；失败、skip 与 `NOT RUN` 均不记为成功。

## 1. 当前状态

| 层级 | 状态 | 证据/下一步 |
|---|---|---|
| T1～T5 软件实现 | PASS | 023 focused `123 passed`；Ruff/mypy/full deterministic 见最终门禁段 |
| 本机 Compose | PASS | 固定 project 的六服务 healthy；app/frontend/Harness PostgreSQL published address 均为 `127.0.0.1` |
| ephemeral PostgreSQL role | PASS | 实机 create→CONNECT/CREATE/USAGE 与非 superuser/createdb/createrole/noinherit 验明→drop→不存在复核 |
| runner image build smoke | `NOT COMPLETED` | 基础镜像 digest 命中锁值；首次 arm64 Debian 依赖下载持续低速，约 7 分钟后主动中止，未进行 GitHub 注册/FIFO 实机 smoke |
| 四模型探针 | BLOCKED | 三项 SiliconFlow profile 被 provider 以 HTTP 401 拒绝；当前可访问配置的 Harness 百炼 key 为空；无资源 mutation |
| 本机 provision / 五节点 local | `NOT RUN` | 必须等待四模型探针全部成功 |
| GitHub exact-SHA live | `NOT RUN` | workflow 尚未合入 `main`，未 dispatch；不得借用软件测试或本机容器状态 |
| 018 T7 最终 live | `NOT RUN` | 依赖 023 合入、真实 provision、本机五节点与 PR #9 最终 SHA 门禁 |

## 2. T1～T5 已实现能力

- R1.1：WeKnora Chat/Embedding/ReRank 与 Harness extraction 四 profile 独立；Harness 默认支持百炼 OpenAI-compatible `deepseek-v4-flash`。配置与 runtime 均要求 mode `0600`，sanitized CLI 不输出 URL、token、password 或响应正文。
- R2.1：镜像 digest、runner version/checksum 固定；Compose render 在 `up` 前 fail-closed 校验；固定 project 消除 worktree 名漂移，三项宿主端口运行时复核 loopback。
- R3.1/R3.2：四模型 probe 先于 mutation；管理员、tenant、三模型、双 KB、scoped Tenant key、Harness `KnowledgeSpace`、PDF SHA 与 parser fingerprint 形成持久 identity graph。同名异主拒绝；重复运行先切回 runtime 记录 tenant，再复用相同 identity。
- R4.1/R4.2：受信 `main` workflow 对 open/same-repo/full exact-SHA 做 pre/post 双验；冻结五个 node ID，collection 与 sanitized JUnit 均要求 exact set equality及 `tests=5 skipped=0 failures=0 errors=0`。
- R5.1/R5.2：一次性 runner 非 root、唯一 name/label、无宿主/Docker socket mount，仅加入两个内部网络且最多一 job。controller 的 registration token 不进 argv、container env/config 或文件，只经 stdin 与 tmpfs FIFO 单次传递并随即删除；Tenant key、DB URL 与 GitHub 临时值在所有退出路径尝试撤销，cleanup failure 只保留 kind 且不覆盖主错误。

## 3. TDD 与实机发现

1. concrete runner/controller 从缺失模块与调用序 RED 开始；故障注入证明 success、exception、`KeyboardInterrupt` 均遍历完整 cleanup plan。
2. GitHub run list 畸形 item 原先泄漏 `AttributeError`；新增 R5.1 RED 后改为统一 `invalid GitHub run list response` fail closed。
3. 重跑 provision 时 WeKnora `GET /tenants` 只返回 active tenant；新增 R3.1 RED 后，已有 runtime tenant 会在资源 discovery 前恢复，非法记录直接拒绝。
4. PostgreSQL 实机首次暴露 `CREATE ROLE ... PASSWORD %s` 不能在该 DDL 位置使用 bind 参数；改用 psycopg `sql.Identifier` + `sql.Literal` 安全组合。随后临时角色最小权限与清理闭环均实机通过，未输出随机角色密码。
5. Compose 首轮若由 worktree 自动派生 project name，会与固定 container name 冲突并遗留空卷；controller 现固定两个 project。遗留卷不自动删除，任何 volume 删除仍要求双显式确认。
6. 本机 `gh secret set --help` 证明只有省略 `--body` 才从 stdin 读取；`--body -` 会设置字面量 `-`。新增 R5.1 RED 后移除该参数，secret 只进入 subprocess stdin，不进入 argv。
7. 已迁移数据库中，随机 schema 的 `create_all(checkfirst=True)` 会沿 `schema,public` 看到 public 表并错误跳过建表。实机诊断确认随机 schema 0 张/public 21 张后，integration fixture 改为在随机 schema 强制 DDL 并立即验表归属；复跑通过。
8. 首次 push 后两条 deterministic CI 都稳定失败：测试用 `str(Path.home()) not in argument` 判断无宿主 mount，而 GitHub runner 的宿主 home `/home/runner` 与容器内合法 destination `/home/runner/actions-runner/_work` 同名。本机 home 不同因此假绿。修复只收紧测试语义：解析 `--mount` 并精确要求 anonymous `type=volume`，同时拒绝 `type=bind`、`-v`、`--volume` 与 Docker socket；以 `HOME=/home/runner` 本地复现环境后通过。

## 4. 外部状态与下一步

真实 provider 认证当前未通过，controller 按规定在任何 tenant/model/KB/Space/PDF mutation 前停止。不要重复调用已知 401 的 key；只在本地 `0600` 文件更新有效值后按 Runbook 顺序执行 `check → probe-models → up → provision → verify → run-local`。

023 workflow 合入 `main` 前不得 dispatch。合入后先对 PR #9 的实现 SHA 运行一次；证据提交并冻结 head 后，再对最终 SHA 重跑 deterministic、PostgreSQL 与五节点 live。最终 run URL/JUnit/cleanup 证据写 PR comment/check summary，避免为证据制造新 SHA。

## 5. 执行纪律复盘

- 任何 agent/tool 60 秒无新输出即轮询或中断，主路径不等待可选 reviewer；每个阶段给出可验证结果。
- 先用最小真实调用验证外部契约（Compose project identity、WeKnora handler 响应、PostgreSQL DDL），避免在大量 mock 测试之后才发现 adapter 偏差。
- 软件 PASS、容器 healthy、provider probe、provision、local live、GitHub live 必须分层报告，绝不把下层成功升级成上层完成。
- 并行产物必须由主线程复核真实数据流；局部测试计数不能相加冒充集成证据。

## 6. 最终门禁

提交前 fresh 本地结果：

```text
openspec validate 023-local-weknora-live-environment --strict
Change '023-local-weknora-live-environment' is valid
exit 0

cd harness
.venv/bin/pytest <八个 023 focused 文件> -q
123 passed

.venv/bin/ruff check . --no-cache
All checks passed!

.venv/bin/mypy --no-incremental src tests
Success: no issues found in 180 source files

.venv/bin/pytest -m "not live and not integration_postgres" -q
1265 passed, 5 deselected

HARNESS_TEST_POSTGRES_URL=<local loopback> .venv/bin/pytest \
  -m integration_postgres -q --junitxml=reports/postgres.local.xml
1 passed, 1269 deselected
.venv/bin/python scripts/check_junit.py reports/postgres.local.xml
junit counts: tests=1 skipped=0
```

OpenSpec validator 自身在返回 valid 后尝试发送 PostHog telemetry，因 `edge.openspec.dev` DNS 不可达产生 warning；命令 exit 0，属于非阻断 telemetry 失败。上述 deterministic 是 token FIFO 修复后的当前 working tree fresh 结果。runner 镜像首次构建已确认 Debian 基础镜像 digest 精确匹配，随后因外部镜像源低吞吐主动中止，exit 130，不表述为 build PASS；提交 SHA 与 GitHub CI 将在 push 后补充。真实 provider/provision/live 状态仍以 §1 为准。

# 023 任务

- [x] T1 R1.1：本地配置、四角色模型探针与零泄漏 RED→GREEN
- [x] T2 R2.1：loopback Compose、随机 Harness DB 密码、镜像/runner lock RED→GREEN
- [x] T3 R3.1/R3.2：管理员/tenant/模型/KB/Space/PDF SHA 幂等 provisioning RED→GREEN
- [x] T4 R4.1/R4.2：受信 main exact-SHA workflow、五节点 manifest/JUnit guard RED→GREEN
- [x] T5 R5.1/R5.2：隔离 ephemeral runner、故障注入与全路径 cleanup RED→GREEN
- [ ] T6 R6.1：Runbook、deterministic 门禁、双审与基础设施 PR；真实环境保持 `NOT RUN`
- [ ] T7 真实本机 provision、四模型探针、五节点本地零 skip 与 sanitized evidence
- [ ] T8 023 workflow 合入 main 后，对 PR #9 实现 SHA及最终证据 SHA各跑一次，清理临时值并关闭 018 T7

## 裁决记录

- Harness 抽取模型与 WeKnora 三类平台模型独立；默认百炼 `deepseek-v4-flash`，不安装 Ollama。
- public repo 不使用宿主用户态常驻 runner；只使用唯一 label 的隔离一次性容器。
- 受信 workflow 必须先合入 main，不能由 PR #9 自己提供要执行的 workflow 定义。
- 最终 SHA 的 live 证据只写外部 PR comment/check summary，避免证据提交产生无限 SHA 循环。
- 021 ordering 明确不在本 change。
- 2026-07-15 对齐 `main@4d9c84e2` 后，T1/T2/T4 软件门禁通过；T3 的 REST/provisioning primitives 已有测试，但真实 Space/CLI mutation 接线未闭环，因此保持未勾。T5 目前只有隔离计划与 cleanup 合同，具体 GitHub/Docker mutation controller 未闭环，保持未勾。真实模型与五节点仍为 `NOT RUN`。
- 2026-07-15 T3 已闭环：四模型探针先于 mutation，真实 Compose controller 固定 project、等待六服务 healthy 并复核三端口 loopback；WeKnora 资源图与 Harness `KnowledgeSpace` 持久化、PDF SHA、runtime state、五节点本机 gate 已完成接线。真实六服务 `up` 通过；供应商模型探针与真实 provision 仍归 T7，当前 `NOT RUN`。
- 2026-07-15 T5 已闭环：controller 对 open/same-repo/exact-SHA 做前后双验，临时创建 scoped Tenant key 与最小权限 PostgreSQL role，只向 `harness-live` environment 写 2 secret + 5 variable；runner 固定 checksum、非 root、无宿主/Docker socket mount、唯一 label、双内网、单 job。任意成功/失败/取消路径尝试清理七项 GitHub 值、Tenant key、DB role、runner registration、容器和匿名卷且保留主错误。真实本机 PostgreSQL 已完成临时角色 create→权限验明→drop→不存在复核；GitHub workflow 尚未 dispatch，归 T8。

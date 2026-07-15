# 023 任务

- [x] T1 R1.1：本地配置、四角色模型探针与零泄漏 RED→GREEN
- [x] T2 R2.1：loopback Compose、随机 Harness DB 密码、镜像/runner lock RED→GREEN
- [ ] T3 R3.1/R3.2：管理员/tenant/模型/KB/Space/PDF SHA 幂等 provisioning RED→GREEN
- [x] T4 R4.1/R4.2：受信 main exact-SHA workflow、五节点 manifest/JUnit guard RED→GREEN
- [ ] T5 R5.1/R5.2：隔离 ephemeral runner、故障注入与全路径 cleanup RED→GREEN
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

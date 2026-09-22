# G3 已批准收尾计划

用户已批准继续执行六项遗留处理；沿用 OpenSpec 129、原 G3 Goal Card 和现有隔离环境。Owner 为当前 root，确认人为用户本人。不得追加 G4、Q0、生产高可用或千文件长期压测作为 G3 门槛。

## 实施与写域

1. root：检查当前/回滚容器依赖后定向清理废弃制品；保留数据卷、原文与审计。写域为 `internal/utils/storage_capacity*`、`knowledge_create.go` 及测试、`internal/router/task.go` 及测试：部署配置空间余量，不足时拒绝新上传，已经领取但未启动的解析在既有 worker 中等待余量恢复，不启动模型调用；保持有界 worker 和既有任务超时/恢复。已有结果保留。验证实际 PostgreSQL 中断恢复，清楚记录测试规模。
2. read lane：`internal/application/service/g3_published_read_reuse*`、必要的读取调用点和对应测试，以及 `internal/application/repository/wiki_release.go` 的只读身份投影方法和测试，缩小字段读取开销；保持当前 ACL、固定版本、来源撤销检查。先记录回归失败，再最小修复和测试。
3. root：`frontend/nginx.conf`、错误页及对应测试、现有部署工具。补正确错误响应和真实后端就绪检查；新进程验证成功后切换，失败保留旧实例。
4. publication lane：审计现有真实 G3 证据与 P2 结果，在临时目录准备最小修订 Candidate。已确认现有编译写死 G2 基础版，授权必要的 G3 基础版承接：Harness `batch_concept_compile_830_g3.py` 及测试、`internal/types/concept_free_wiki_830_g3.go` 及测试、来源 authority 中 G3 carry helper 及测试。`service/concept_free_wiki_830_g3.go` 与 read lane 的读调用点先协调，root 顺序集成。确定性重算当前7实体 MATCH 与新来源关联；原抽取输出只按现有上下文差异校验复用，必要受影响检查单独执行，不直接修改 Head。
5. root：按原 Candidate→Review→Activate 发布经验证的修订，只补必要受影响任务。m09/m19 证据不足时保留具名待确认，不强行关联。
6. 独立 review：核对原 G3-R1—R5 与本轮 P1—P3 的实际回执。完成后更新原验收矩阵；代码、部署、业务各自记录，不把模拟测试写成真实吞吐。

已查到原真实 C05/c15 分类调用 `FAILED / INVALID_PROVIDER_RESPONSE`，但现有入口把无 proposal 的失败与“尚未输出”都归为 NEEDS_CONFIRM。quarantine lane 独占新的 Harness 已验证分类失败适配模块、测试及经协调的现有失败入口小接线，修复该 R4 缺口：只根据受验证的真实失败记录、请求及来源绑定形成具名 QUARANTINE 历史决定；保留原 FAILED 回执，不伪造 proposal，不改变成功路径及当前15份最终处置。

### R5 展示分类与抽取绑定解耦

真实材料回放发现主标签改变会连带选择另一个 SchemaPack，不能满足原卡仅改标签/导航的稳定性要求。根据既有继续开发授权补最小通路：保留原 C 分类、绑定、SchemaPack/Profile 全部校验，在同一 Candidate 顶层保存可选的版本化 navigation_assignments。导航标签采用独立的短文本集合及一个主标签，支持“健康保障”等跨抽取结构的展示分组；不以展示标签授予 Schema 准入。默认无覆盖，旧候选序列化及哈希完全不变。新覆盖严格绑定实际父版本的默认导航或前一赋值哈希，更新递增版本，不得丢弃已有历史。仅复用完整已发布业务内容的候选可使用此路径，并继续整包 Review/Activate。

Python lane 写编译模块/测试及共享 canonicalizer 的缺省字段兼容；Go lane 写对应 DTO、候选/父历史校验、overview 投影及测试；root 写前端解析和目录分组/测试。overview 的导航元信息随 PageManifest 签入，字段、Evidence、定义和开放知识 hash 保持；读取不添加未签署 payload。UI 继续严格验证原 pack/Profile 字段闭合，以独立导航主标签分组。本项不新增表、服务、第二 Head、模型调用或跨 Schema 迁移。

## 验收与边界

- 保留现有第 6 版作为不可变历史与回滚点；用户本次授权新隔离版本，不覆盖历史。
- 读取：同一字段、引用、PDF 的首读/复读与重启，记录各段耗时，来源页码与字节一致；不预先宣称达到秒级。
- 恢复：真实 PostgreSQL 领取后退出、租约恢复、成功任务去重、失败隔离；结果不明模型调用不得盲目重发。
- 发布：15 份材料均有可追踪处置，明确版本和关联使用已有证据，目录不冒充完整产品；新版本页面、字段数、引用与搜索实际读回。
- G3 结束依据原验收卡，包括五类真实处置及重分类身份稳定性证据。缺证据先查历史，再最小补验，不凭文档勾选判定 PASS。
- 本轮结束不自动进入 G4；Q0、生产人工审批、千文件长稳另列后续事项。

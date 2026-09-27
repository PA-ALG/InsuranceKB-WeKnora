# 升级验证矩阵

本记录区分本地合同验证与最终真实验收。软件源码为 `8a0863fa095bc27b901db90c5f744d1db84063b2`（产品8ccc2ac9与固定上游3e8b0bfc合并）；无未解决 Git 冲突不等于升级完成。冻结指纹及测试摘要见 `docs/insurance-kb/evidence/830-upgrade/`。后续证据提交不改变该构建来源。

| Requirement | implementation / 本地验证 | commit | 最终 status |
|---|---|---|---|
| UPG-01 | 38 冲突已消解，固定 MERGE_HEAD；最终祖先已确认；制品和部署身份待闭合 | 8a0863fa0 | NOT RUN |
| UPG-02 | 同一 Harness 的平台 client/签名快照/发现合同与基线逐字相同的发现样例；47 项契约检查 PASS；Go 端重新验证跨语言向量 | 8a0863fa0 | PASS |
| UPG-03 | 代表 workbook 字段描述改变使语义摘要改变、其他字段不变；准入策略切换留在 Harness；前后 Go 源码摘要相同。1 项检查及 ruff/mypy PASS | 8a0863fa0 | PASS |
| UPG-04 | core5 106 项、wiki7 121 项本地通过；历史固定来源/引用/Release 合同保留。真实 epoch27 与新 tracer/source click 尚未执行 | 8a0863fa0 | NOT RUN |
| UPG-05 | model-final 582 项通过；reserve/mark 失败零发送、失败关闭、四协议 fallback、重定向实际发送、revision 队列 fence 与失败后续保留均有回归；真实进程恢复/成本未验 | 8a0863fa0 | NOT RUN |
| UPG-06 | RAW-only 托管源、插件关闭/缺失 Head、普通 KB 工具、当前权限及 Release 负向回归通过；来源并发两项修复已冻结，仓储/服务受影响/下游回归PASS，最终独立复核0BLOCKER，真实环境验证未完成 | 8a0863fa0 | NOT RUN |
| UPG-07 | 初轮 database 包及 adoption 131 项通过；独审发现中间 checkpoint 恢复和 skip_embedding 模式转换两个 BLOCKER，均已修复、数据库包通过，独立复核关闭。真实 DB/恢复未执行 | 8a0863fa0 | NOT RUN |
| UPG-08 | BA0 输入/复用、运行资产及新增依赖合同 156 项通过；前端 tests/typecheck/build 已完成，最新构建2m4s。App首次197.05秒磁盘不足；已授权清理32镜像后的唯一追加构建13.50秒镜像源EOF失败，均无镜像；追加预算已用完，UI/DocReader与smoke未执行 | 8a0863fa0 | BLOCKED |
| UPG-09 | 核心保留理由与退出条件见 patch-ledger.md；旧模型模块/host skills 已替代删除；前端80/构建18/迁移13路径独审0BLOCKER；核心两项并发修复已冻结43路径，最终独审0BLOCKER | 8a0863fa0 | NOT RUN |

## 已执行的本地检查

- 模型 `api/...`、`runtime`、`chat`、`embedding` 全包：582 个测试/子测试 PASS；没有测试文件的两个协议包不计为测试通过。精确日志 `/private/tmp/upg-model-final.jsonl`。
- 来源/Agent/router/container focused：106 项 PASS；后续合同组 169 项通过后因 Wiki 测试替身缺少新增查询接口失败，补齐替身后 Wiki 组 121 项 PASS、1 项环境依赖 SKIP。各组有重叠，不相加作为独立测试总数。
- Harness 平台/签名来源/原生发现/Schema catalog：47 PASS；领域独立：1 PASS；新测试 ruff/mypy PASS。
- 迁移与构建原 writer 的包级验证只证明当时源码；审查修复后须重新验证并冻结，不以旧 PASS 覆盖新改动。

## 限制与未执行

仓储完整包 367 项 PASS/8 SKIP；router/handler/config/container/types 完整包 PASS（types 139.964秒）。前端初轮20文件263项 PASS；单次capability与busy反馈修复后14项 focused PASS，最终类型与构建 PASS（2m4s）。

早期宽泛 service 回归在历史大对象 canonical 校验上耗时，停止该次检查并按影响收窄；不得写为 service 全包 PASS。模型 parity 的旧 body-only 测试受到本机 DNS 返回 198.18 地址而触发 SSRF 拒绝，未以放宽生产安全检查解决，不宣称整个 models/... 通过。

software本地范围PASS，container health、真实 DB migration/backup/restore/backfill、config 切换、provider、Candidate/Draft/review/publish/activation、历史 epoch27 运行读取、新 tracer、source click、local live/GitHub live 均 NOT RUN。代码/fixture 的 PASS 不代表部署或业务验收。

来源并发最终代码检查：repository全包、service受影响组及全包compile PASS；handler/container全包PASS。router初轮旧fixture缺knowledge_revision_sources，补齐真实表后347项PASS/2.019秒。初轮失败日志保留，不把最终PASS追写到失败运行。稳定UUID清理覆盖迟到成功和失败+CAS失去，不清新attempt。真实PostgreSQL锁时序未在此本地组执行。

C2最终独审：43路径与附加router fixture全部匹配，0 BLOCKER。并发修复后旧来源/重解析/图片队列/revision再验71项PASS/2.945秒。UPG-04/05/06本地阻断已关闭，最终status仍NOT RUN，等待真实环境验收。三项普通KB/enrichment/索引清理重试BACKLOG见patch-ledger及独审JSON，不作为当前G3已验证能力。

交付尝试与审批：delivery-attempt-01.json记录App失败、容量和零部署事实。自动审批拒绝向产品origin发送当前payload，push/PR/远端CI未执行。无清理与重复构建。

最新授权恢复：用户已明确批准32镜像精确删除、一次条件恢复构建及push/Draft PR，历史审批拒绝已解除。清理PASS，空间约6.63GiB，保留容器/卷/cache。独立容量复核后已执行唯一追加App构建，配置镜像源在Dockerfile frontend元数据阶段返回EOF，13.50秒失败，无镜像；新增1/1已使用，不自动重试。回执delivery-attempt-02.json。普通上传HTTP400/408（直连也408）后，确认fork已持有3e8b0bfc并令同一目标分支引用该祖先，再普通快进到f3ff602b9，push成功。待补推本次证据并创建Draft PR；远端CI结果尚未取得，不能记PASS。

## 重新授权的第三次App尝试与修复

详见delivery-attempt-03.json：固定旧源8a的第三次尝试588.134369043秒后于BrowserSkill子进程pnpm查找失败，无image。本轮预算1/1已用完；临时镜像源修改已逐字恢复，8容器启动身份不变。UPG-08新增child-shell离线行为回归先RED（旧入口调用ambient pnpm，exit71），修复已验证pnpm可执行入口的PATH后130PASS/4.76s，fullruff PASS/mypy736 PASS。此为源修复，不是新镜像成功；依赖锁不变，App输入已改变，待冻结与新D2。

GitHub live=BLOCKED，PR131@4dec9ef66六组真实CI失败详见ci-failures-4dec9ef.json；不再将该远端状态记NOT RUN，也不以局部软件测试PASS覆盖。已有软件PASS只代表当时受影响的有限测试集合，不代表完整CI。六组尚未修复，原部署/provider/local-live仍NOT RUN。

## 第四次App尝试（修复源e71c72f7d）

新增明确授权“再授权一次”已消费1/1；新identity 12d583e5…的10.095880297秒尝试在官方Dockerfile frontend HEAD阶段TLS握手超时，尚未编译、无镜像，总尝试4。失败不证明pnpm修复在真实镜像中通过或失败。原daemon配置逐字恢复、daemon PID和8容器启动身份不变；见delivery-attempt-04.json。事后直连/实际代理各3次HEAD均401，仅证实事后TLS/registry可达，代理有1次10.591052秒，不等于认证pull或稳定连接。本轮不追加第五次，GitHub六组CI与D3状态保持未关闭。

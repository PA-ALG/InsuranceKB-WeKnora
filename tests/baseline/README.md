# S0 完整门禁基线

生成日期：2026-10-01（Asia/Shanghai）；切片：`slice/s0`，Issue #4。
代码基点：`a0d74a57480248872534e2df4d79e677d48fd898`；运行期间仅增加 CI 配置，配置提交：`776786baf`，父线为 `main@ae426cb03`。

保留初次分组执行的失败，定向复核通过时也不删除初次失败，而在下文注明。后续切片应区分断言失败、环境失败与已有 skip，不能通过新增排除或修改断言改善基线。原始日志不入库；摘要不含凭据、本机路径或内网地址。

## 环境与完整范围

| 项目 | 版本 / 条件 |
|---|---|
| 系统 | macOS / Darwin arm64 |
| Go | 1.26.0，与 `go.mod` 指定版本一致 |
| Harness | Python 3.12.12、uv 0.9.26；独立新虚拟环境与依赖缓存，`uv sync --locked` |
| pytest | Harness 锁定环境 9.1.1；独立 CI 最小环境 8.3.5 |
| 前端 | Node 24.13.1、npm 11.8.0；`npm ci` |
| Go 调用系统 Python | 首次 3.9.6，已有 pandas 2.3.3、无 tomllib；验证器复核使用独立 Python 3.12 |
| 资源记录 | 系统计时器记录墙钟耗时及峰值 RSS，单位 MiB；超时终止时 RSS 不可得。单次 RSS 不能相加作为并行总内存 |

Harness 收集得到 **7774** 个 nonlive 用例：根目录 6801 个、`tests/product_ingestion/` 973 个；`tests/support/` 为辅助模块。唯一 marker 排除为 Spec 指定的 `not live and not integration_postgres`。执行 `uv run pytest -m "not live and not integration_postgres" -q`；根目录 285 个测试文件按字典序分五组，每组 57 个文件。超时组将未完成的 nodeid 另行运行，并把当前慢文件移至尾部，原范围全部保留，每次限时 20 分钟；ingestion 最后剩余范围按完整文件分成两组，将已定位的慢文件分开运行。

Go 执行 `go test -json -count=1 -timeout 10m -p 4 ./...`（`GOMAXPROCS=4`）与 `go vet -p 2 ./...`（`GOMAXPROCS=2`）。service 包按 `go test -list .` 返回的 2158 个顶层 Test/Example/Fuzz 名称分四组（540/540/540/538），用完整锚定名单运行；第 1 组未完成部分补跑，慢测试单独运行。每次包内限时仍为 10 分钟，没有删除测试。

前端测试为 `npm test -- --test-concurrency=2`，降低并发但保留全部用例。初次高并发尝试因本机资源压力被中止，随后完整重跑；中止尝试不计为断言失败。另执行 `npm run type-check`、`npm run build`，静态构建仅有已有的大 chunk 提示。

## 结果与失败分布

| 门禁 | 结果 |
|---|---|
| Harness nonlive | 已完成 7774 / 7774；初次失败去重 5；passed 7751、已有 skipped 18；尚未完成 0 |
| ruff | `uv run ruff check .` 通过，0 条违规 |
| mypy | `uv run mypy src tests` 通过，737 个源文件、0 个错误 |
| Go 初次完整运行 | 133 包：107 pass、19 无测试、7 fail；测试事件 10591 pass / 55 skip / 245 fail，含父测试汇总，不能作为独立失败数 |
| Go 失败清单 | 初次加拆组共 243 个独立叶子断言失败：241 个代理 DNS/SSRF 环境失败、2 个系统 Python 环境失败；事件去重后 13608 pass / 62 skip / 248 fail（含父测试） |
| go vet | 通过，0 条诊断 |
| 前端 test | 1284 个用例：1283 pass、1 个已有 skip、0 fail |
| 前端 type-check / build | 两项均通过，0 个错误 |
| 架构守卫 | Harness 环境 20 / 20；仅安装 pytest 的独立 Python 3.12 CI 环境 20 / 20；含四份基线的最终检查也为 20 / 20；未改守卫及其基线 |

Harness 失败分布：`test_ci_lanes_022.py` 1 条历史文档断言；`test_run_admission_session_lock_020.py` 4 条固定启动/响应时限失败；`product_ingestion` 0 条。完整 nodeid 见 `harness-nonlive-failures.txt`。

Go 叶子失败分布：`internal/models/parity` 235、`internal/utils` 2、`internal/datasource` 1、`internal/datasource/connector/notion` 1、`internal/datasource/connector/yuque` 1、`internal/sandbox` 1、`internal/application/service` 2。父测试汇总失败不重复计入。完整标识见 `go-test-failures.txt`。

## 分组耗时与内存

耗时均为秒，含启动、导入或编译；本机并发资源压力使耗时明显增加，不能据此推断 CI 性能。

| Harness 分组 | 选中 | 已完成 | 耗时 | 峰值 RSS | 退出码 |
|---|---:|---:|---:|---:|---|
| `harness-root-1` | 1452 | 824 | 1200.04 | 不可得 | 124（超时） |
| `harness-root-1-tail` | 628 | 628 | 1094.10 | 276.6 MiB | 0 |
| `harness-root-2` | 1008 | 184 | 1200.05 | 不可得 | 124（超时） |
| `harness-root-2-tail` | 824 | 824 | 693.09 | 252.5 MiB | 0 |
| `harness-root-3` | 1490 | 1490 | 598.67 | 324.3 MiB | 0 |
| `harness-root-4` | 1599 | 1088 | 572.35 | 319.8 MiB | 1 |
| `harness-root-4-tail` | 511 | 304 | 1200.03 | 不可得 | 124（超时） |
| `harness-root-4-tail-2` | 207 | 207 | 493.60 | 220.4 MiB | 0 |
| `harness-root-5` | 1252 | 1252 | 771.98 | 315.1 MiB | 0 |
| `harness-ingestion` | 973 | 122 | 1200.10 | 不可得 | 124（超时） |
| `harness-ingestion-tail` | 851 | 320 | 1200.03 | 不可得 | 124（超时） |
| `harness-ingestion-tail-2` | 531 | 211 | 1200.06 | 不可得 | 124（超时） |
| `harness-ingestion-tail-3` | 320 | 127 | 1200.02 | 不可得 | 124（超时） |
| `harness-ingestion-tail-4a` | 98 | 98 | 385.76 | 254.0 MiB | 0 |
| `harness-ingestion-tail-4b` | 95 | 95 | 428.91 | 237.0 MiB | 0 |

| 其他运行 | 耗时 | 峰值 RSS | 退出码 |
|---|---:|---:|---|
| `harness-sync` | 73.76 | 48.3 MiB | 0 |
| `harness-collect` | 33.97 | 247.8 MiB | 0 |
| `harness-ruff` | 34.07 | 36.2 MiB | 0 |
| `harness-mypy` | 340.10 | 299.9 MiB | 0 |
| `go-test` | 1409.23 | 1828.4 MiB | 1 |
| `go-vet` | 451.43 | 524.7 MiB | 0 |
| `go-service-list` | 35.22 | 1433.7 MiB | 0 |
| `go-service-1` | 640.06 | 1392.1 MiB | 1 |
| `go-service-2` | 160.39 | 1104.1 MiB | 0 |
| `go-service-3` | 291.01 | 1291.6 MiB | 0 |
| `go-service-4` | 508.15 | 1103.1 MiB | 1 |
| `go-service-1-tail` | 345.70 | 1300.1 MiB | 0 |
| `go-service-1-slow` | 500.54 | 1237.2 MiB | 0 |
| `go-python-verifier-clean` | 54.87 | 1278.4 MiB | 0 |
| `lock-recheck` | 110.44 | 105.8 MiB | 1 |
| `frontend-install` | 29.46 | 406.1 MiB | 0 |
| `frontend-test` | 423.94 | 445.6 MiB | 0 |
| `frontend-types` | 112.57 | 865.1 MiB | 0 |
| `frontend-build` | 142.70 | 2634.0 MiB | 0 |
| `architecture` | 37.63 | 86.7 MiB | 0 |
| `architecture-ci` | 218.75 | 56.5 MiB | 0 |
| `architecture-final` | 39.14 | 56.3 MiB | 0 |

`harness-root` 首次整目录尝试在 1200.18 秒终止（RSS 不可得），随后按文件组执行，不重复加入用例计数。`harness-root-4` 因临时进度记录器受到测试主动替换 `json.dumps` 的 MemoryError 影响而中断；记录器在仓库外修正为保留原序列化函数，剩余 511 个用例补跑。记录器故障不计为产品失败。嵌套 pytest 的预期反例输出按最外层收集范围过滤，避免误报失败。

## 复核与阻塞

- 原有 CLAUDE.md 断言期待旧协作说明，当前内容只引用 `AGENTS.md`；记录现状，不修改文档或测试。
- 四条进程锁时限失败：完整文件定向复核 15 个用例，12 pass / 3 fail（110.44 秒）；仍失败的三条均在初次四条清单中，均为 3 秒子进程启动时限；原来的 10 秒响应时限失败在复核中通过。此处记录观察结果，不据此判定互斥机制是否正确。
- Go Python 验证器：系统 Python 的已装依赖与缺少 tomllib 使两个负向用例误通过；独立 Python 3.12 下 `TestSkillPythonVerifier` 所有用例通过（54.87 秒），保留初始两条环境失败。
- Go 超时已解除：完整包超时于 `TestBatchConceptBase830G3ReopensPublishedG3Head`，第 1 分组超时于 `TestBatchConceptCreate830G3RejectsEveryRegisteredReceiptFieldBeforeDraftWrite`；第 1 组剩余范围通过（345.70 秒），单独慢测试通过（500.54 秒）。service 包 2158 个顶层测试全部已有结果，无未定位的 Go 阻塞项。
- Harness 全部 7774 个 nonlive 用例均已完成，目录拆组与续跑范围无遗漏，无剩余阻塞项。
- GitHub Actions 的仓库设置仍关闭；CI 配置已推送，需 Claude 按 Spec §4 启用并在 PR 上运行 `architecture-guards`。本地通过不等于 PR CI 通过。

无真实模型调用、镜像构建、部署或数据库迁移；无产品代码、已有测试、受保护路径或依赖锁文件变更。

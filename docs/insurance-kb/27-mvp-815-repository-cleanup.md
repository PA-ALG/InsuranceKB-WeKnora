# 27 · MVP-815 仓库整理清单

> 本文只描述本地 worktree/分支整理。它不授权修改生产 `8081`、数据库、发布对象、
> task-private 回执或凭据，也不授权丢弃 dirty 工作区。

## 1. 清理前归档

在任何删除前已经创建包含当时全部 Git refs 的完整 bundle：

| 项目 | 值 |
|---|---|
| 文件 | `../archives/insurancekb-weknora-pre-cleanup-20260831.bundle` |
| mode | `0600` |
| bytes | `147412595` |
| SHA-256 | `7d35f64fe2611148ca96760752d6a1c331be8f62433fc07ec274647e66a31725` |
| `git bundle verify` | PASS；486 refs；complete history |

恢复前先重新计算 SHA-256 并运行 `git bundle verify`。bundle 只覆盖 Git 对象和 refs，
不覆盖未跟踪文件、忽略文件、容器卷、task-private 回执或内存中的密钥。

## 2. 盘点结论

清理前共登记 46 个 worktree。以下目录为 dirty 或当前活动目录，必须保护：

- 仓库主工作区 `insurancekb-weknora`；
- `112-medical-schema67-golden-candidate`；
- `mvp-current-experience`；
- `schema-wiki-p0-exact8-execution-authority`；
- `schema-wiki-page-prepared-red-v2`；
- 当前 `mvp-815-handoff`。

以下 clean 目录仍因证据、制品或潜在敏感输入而默认保护，需人工逐项确认后才能
处置：

- `045-weknora-trusted-images`；
- `ec-01-execution-815`；
- `schema-wiki-image-build-spec`；
- `schema-wiki-mvp-image-build`；
- `schema-wiki-mvp-image-build-b8faa`；
- `win2-p0-credential-file`；
- `win2-p0-credential-file-green`；
- `win2-p0-credential-red-replay`。

`mvp-815-delivery` 与 `mvp-815-handoff` 需至少保留到两个正式 PR 都进入 main。

## 3. 第一阶段可移除的 clean worktree

下列目录的提交已在完整 bundle 中归档，且最终有效代码已由 PR #123 重建进入
main。第二个 PR 合并后，若删除前复核仍为 clean、路径与 HEAD 未漂移，可只移除
worktree 目录；暂不删除对应 branch ref：

```text
815-technical-route
830-technical-blueprint
controller-c5-native-pdf-authority
ec-01-integration
schema-wiki-complete67-compiler
schema-wiki-draft-citation-content
schema-wiki-dynamic-batch-manifest
schema-wiki-exact3-dryrun-corrective
schema-wiki-explicit-candidate-integration-fix
schema-wiki-field-unknown-reason
schema-wiki-p0-evaluation-integration
schema-wiki-p0-nonpublishing
schema-wiki-page-admission-red
schema-wiki-page-legacy-red
schema-wiki-page-pair-red
schema-wiki-page-prepared-red
schema-wiki-provider-zero-exact8
schema-wiki-revision-source-corrective
schema-wiki-revision-source-v2
schema-wiki-ui-acceptance-red-main
win1-c3-value-parts-integration-adapt
win1-ec01-formal-candidate
win1-slice-openspec123-verify
win1-slice-preview-reconcile-verify
win1-slice-source-pin-verify
win1-swep124-explicit-diagnostic-verify
win1-task-key-seam
win2-exp2-integration-44fe
win2-page-context-profile
win2-slice-campaign-audit
win3-c5-hydration-successor
```

删除前必须对每个 exact path 重新执行：存在性、`git status --porcelain` 为空、HEAD
等于盘点值、不是任何当前任务 cwd。任何一项不满足即从批次剔除，不能使用 glob、
递归删除或强制 worktree remove。

## 4. 第二阶段候选

两个 PR 合并、远端 main 身份复核且无回滚需要后，可再考虑移除
`mvp-815-delivery` 与本 handoff worktree。分支 ref 删除是另一项操作；即使 worktree
已移除，也默认保留 ref，除非重新生成含最终 main 的归档、验证可恢复性并取得明确
删除授权。

## 5. 永不自动清理的内容

- dirty 工作区、未跟踪/忽略文件和无法判断所有权的资产；
- 名称或内容涉及 credential、secret、receipt、evidence、image/SBOM/OCI 的目录；
- mode-0600 任务回执、发布证据和归档 bundle；
- Docker volume、PostgreSQL 数据、运行中的容器或端口；
- 生产 `8081` 的 container/image/config/volume；
- 未合并分支的唯一提交或无法从 bundle/远端恢复的制品。

## 6. 清理后的机械复核

1. `git worktree list --porcelain` 中只减少已批准且复核为 clean 的 exact path；
2. 五个 dirty worktree、当前活动 worktree和所有保护项仍存在；
3. 主工作区状态字节未变；
4. bundle SHA 与 verify 仍 PASS；
5. origin/main、PR #123 tree 和本次 handoff PR tree 均可解析；
6. 不启动 Docker/Colima，不触碰 `8081`，不读取或输出凭据。

发生异常时停止该批次；已经通过 `git worktree remove` 移除的 clean 目录可从对应
branch ref 或已验证 bundle 重建。

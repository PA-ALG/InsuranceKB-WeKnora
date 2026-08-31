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

| worktree | 冻结 HEAD |
|---|---|
| `830-technical-blueprint` | `1b1d928688522fa50c2410969c09ae6c76edce8a` |
| `schema-wiki-draft-citation-content` | `ef42b170b2dce797b0423103c40632eed5455b8a` |
| `schema-wiki-exact3-dryrun-corrective` | `b56d260f6126ecbefd93ba992fb5779a55f0f24d` |
| `schema-wiki-page-prepared-red` | `d274e73e8ec5baf47c3af3024b0385f0239754ed` |
| `schema-wiki-revision-source-corrective` | `5501ce3182677d9642912b58c225ddefa9d63c85` |
| `schema-wiki-revision-source-v2` | `dbf89c1a89797a855d2b0beb94fab1b1e34f8d98` |

删除前必须对每个 exact path 重新执行：存在性、HEAD 等于表中冻结值、不是任何当前
任务 cwd，并且以下两个结果都为空：

```bash
git status --porcelain=v1 --untracked-files=all
git status --porcelain=v1 --ignored --untracked-files=all
```

第二条会把 ignored 资产也暴露出来；任何一项不满足即从批次剔除。不能使用 glob、
递归删除、`--force` 或普通 `git status --porcelain` 代替上述双门禁。

## 4. 因 ignored 资产保护、不得在本任务自动移除

下列目录普通状态虽为空，但含 ignored 文件。它们可能是可再生缓存，也可能是证据、
制品或敏感输入；本任务一律不猜测、不删除。数量是 2026-08-31 盘点时的 ignored
status 行数，仅用于漂移核对：

| worktree | 冻结 HEAD | ignored |
|---|---|---:|
| `815-technical-route` | `235347adb2ddde5fc6feb2abcd2e30f0044d04f9` | 10 |
| `controller-c5-native-pdf-authority` | `df35a15779edf5b09ecabc00da10f08a465e2cda` | 141 |
| `ec-01-integration` | `7416bb70373ef3bbd5b107e0a7086c77595b9507` | 147 |
| `schema-wiki-complete67-compiler` | `367bef61062e168619f898b897ac07db03284ecb` | 133 |
| `schema-wiki-dynamic-batch-manifest` | `cbfbdeeb77f30cb2c5f032b2d586f1a78a910f2b` | 130 |
| `schema-wiki-explicit-candidate-integration-fix` | `907d6a8ae75507d1de67a6192f62c93cca4b8d14` | 141 |
| `schema-wiki-field-unknown-reason` | `d62335e7ef4b3a5a40d2c0d41ac5020680c82fd7` | 62 |
| `schema-wiki-p0-evaluation-integration` | `0f2ccf06b2178cb5fdcdb4c88f4c97fef1c41653` | 51548 |
| `schema-wiki-p0-nonpublishing` | `d67f8371d4cff2000943843c79c5a93c4e1fbfec` | 90 |
| `schema-wiki-page-admission-red` | `87aad61a6d038b41a9a1be5e57dd4e98e5f02ee0` | 1 |
| `schema-wiki-page-legacy-red` | `b3343f0ffd049584673d4eedc82047d45b527353` | 8 |
| `schema-wiki-page-pair-red` | `bca1763801dac973e35c761ca5f39c80a81a9e2c` | 51826 |
| `schema-wiki-provider-zero-exact8` | `397f659740212495d0121dd4e935707f93268851` | 6023 |
| `schema-wiki-ui-acceptance-red-main` | `bff2d8d47c9a7e05d82cc22624c2b9f3cba81335` | 2 |
| `win1-c3-value-parts-integration-adapt` | `ec0544f78399a350218e9d77e4b7f15ccdb2e000` | 146 |
| `win1-ec01-formal-candidate` | `a974618c467685a23cf0bc2ed86c6c2699cec785` | 5981 |
| `win1-slice-openspec123-verify` | `4345e1b98441034ea9b53a9da330fce463e871ed` | 134 |
| `win1-slice-preview-reconcile-verify` | `23957b08e3a37fa7f15c4327917d83403507a55a` | 141 |
| `win1-slice-source-pin-verify` | `67d38d0ab3dd82b343a5b7bf54ad16131a697c33` | 140 |
| `win1-swep124-explicit-diagnostic-verify` | `7a80bfdf44acda4d3f7c90917e101cb52d0aa554` | 141 |
| `win1-task-key-seam` | `d2dca40c28e0e38ca20d548677f95cfe05e4e69f` | 134 |
| `win2-exp2-integration-44fe` | `9018203f5b435c1d3f79d449d07428b8e643550a` | 134 |
| `win2-page-context-profile` | `d4dc42215ee74ad8e28e49126b1e82e3ed2115c3` | 5948 |
| `win2-slice-campaign-audit` | `125c71833bbf790f097548907f69b030d32a54a2` | 6008 |
| `win3-c5-hydration-successor` | `4d13cfbdfdf7e81c151ab3829f6b511cb8f1972b` | 5918 |

## 5. 第二阶段候选

两个 PR 合并、远端 main 身份复核且无回滚需要后，可再考虑移除
`mvp-815-delivery` 与本 handoff worktree。分支 ref 删除是另一项操作；即使 worktree
已移除，也默认保留 ref，除非重新生成含最终 main 的归档、验证可恢复性并取得明确
删除授权。

## 6. 永不自动清理的内容

- dirty 工作区、未跟踪/忽略文件和无法判断所有权的资产；
- 名称或内容涉及 credential、secret、receipt、evidence、image/SBOM/OCI 的目录；
- mode-0600 任务回执、发布证据和归档 bundle；
- Docker volume、PostgreSQL 数据、运行中的容器或端口；
- 生产 `8081` 的 container/image/config/volume；
- 未合并分支的唯一提交或无法从 bundle/远端恢复的制品。

## 7. 清理后的机械复核

1. `git worktree list --porcelain` 中只减少已批准且复核为 clean 的 exact path；
2. 五个 dirty worktree、当前活动 worktree和所有保护项仍存在；
3. 主工作区状态字节未变；
4. bundle SHA 与 verify 仍 PASS；
5. origin/main、PR #123 tree 和本次 handoff PR tree 均可解析；
6. 不启动 Docker/Colima，不触碰 `8081`，不读取或输出凭据。

发生异常时停止该批次；已经通过 `git worktree remove` 移除的 clean 目录可从对应
branch ref 或已验证 bundle 重建。

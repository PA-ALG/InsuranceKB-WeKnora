# I4 · App 换装工具入库与受管环境项

> 状态：Claude 2026-11-01 提出 ｜ 作者：Claude Code ｜ 实现方 Claude，审核方 Codex
> 起因：部署 #520 需要给线上 App 新增环境变量 `ENTERPRISE_VERSIONED_ENTITY_TYPES=insurance_product`（PV-4a 的
> `identity_refresh` 门控），运维现用的本机换装脚本不支持新增或移除环境项，Codex 按停止条件停在换装前。
> 真实调用 0；不部署（部署另开 Issue）。

## 1. 现状

线上 App 由运维机上的本机脚本换装（未入库、未审核）。它的规则与已入库的 `deploy/local-live/swap_docreader.py`（#476）
一致：所有检查在动容器之前完成；环境值只在内存中从 `docker inspect` 读出，经子进程环境交给 `docker create -e KEY`，
不进 stdout、argv 或磁盘；09-28 原始容器改名一次（`-pre-s4`）并保持停止，作为运行设置的唯一来源，每次换装都从它重建。
它另外加三项：`ENTERPRISE_CONTRACTS_DIR`、引用签名密钥（从运维私有目录的 `secrets.env` 读）、`ENTERPRISE_SPACES`
（可选的 JSON 文件）。

缺口：
1. 不能新增、替换或移除任何其他环境项；
2. 因为每次都从原始容器重建，某次换装手工加进去的环境项，下一次换装会被**悄悄丢掉**；
3. 未传 Spaces 文件时 `ENTERPRISE_SPACES` 会被悄悄丢掉；
4. 脚本不在仓库，没有审核记录与测试。

## 2. 改动

新增 `deploy/local-live/swap_app.py`（标准库，`python3 -I` 可运行），移植本机脚本的全部行为，并增加：

1. **受管环境项**：脚本内一份小的数据表（键 → 取值格式）。首个也是唯一的键：
   `ENTERPRISE_VERSIONED_ENTITY_TYPES`，取值为逗号分隔的标识符。
   - `--set-env KEY=VALUE`（可重复）：键必须在表内、取值必须符合格式；同一键重复、或同时 `--unset-env` 即拒绝。
   - `--unset-env KEY`（可重复，用于回滚）：键必须在表内；当前容器没有该键时为空操作并在输出中注明。
   - **随换装延续**：受管键从**当前** App 容器的环境中读出并带到新容器，除非 `--unset-env`；这样以后的普通换装不会丢掉它。
   - 当前容器已有该键且值不同：拒绝，除非加 `--replace-env`。
   - 原始容器（来源）的环境里出现受管键：视为布局异常，拒绝。
2. **私有目录显式传入**：`--private-dir DIR`（必填；代码中不写本机路径），其中的 `config.yaml`、`contracts/`、`secrets.env`
   在动容器前检查存在。签名密钥照旧只在内存中读取。
3. **Spaces 防丢**：`--spaces FILE` 取代原第二个位置参数；未传而当前容器设有 `ENTERPRISE_SPACES` 时拒绝（否则会被丢掉）。
4. **新镜像先验**：`docker image inspect` 失败即停（原脚本到 `create` 才失败）。
5. **`--dry-run`**：只检查与规划，不动容器；输出容器名、来源、新旧镜像 ID、规划的运行时环境**键名**、相对当前容器的增加/
   移除**键名**、受管键取值只给 `sha256:` 前 12 位、是否带 Spaces、额外网络。

审核 R1–R4（#521）补充：

6. **解析错误不回显**：参数解析失败只输出固定的用法与错误码，不复述任何参数（拼错的选项可能带着环境值）；不接受选项缩写。
7. **按最终有效环境校验受管键**：新容器的有效环境 = 新镜像默认环境 + 运行时环境。受管键的格式校验与 `sha256:` 指纹按有效值
   计算（包括新镜像自带的默认值）；`--unset-env` 的键若会因新镜像默认值而保留，拒绝。
8. **意图记录**：动容器之前，把新容器的受管键取值与"是否带 Spaces"写进 `<私有目录>/swap_app.intent.json`（权限 0600，原子替换；
   受管键取值是类型标识一类的配置，不是密钥；签名密钥、运行时环境与 Spaces 内容不写）。受管键的来源：当前 App 容器存在时取它，
   记录也存在且某个受管键与它不一致、本次又未显式 `--set-env`/`--unset-env` 该键时拒绝；当前容器不存在（例如上次 `create`
   失败）时取记录；两者都没有时，每个受管键都必须显式给出（`--set-env` 或 `--unset-env`），否则拒绝，不把丢失当作成功。
   当前容器或记录任一表明带 Spaces 而未传 `--spaces` 时拒绝。记录不可读或格式不符时拒绝。
9. **计划阶段的可表达性检查**：子进程环境的键与值、`docker` 参数中含 NUL 或无法按文件系统编码表示的字符，私有目录路径含 `:`
   （`-v` 的分隔符），都在动容器之前拒绝，错误信息不含取值。换行可以经子进程环境原样传递，不拒绝。

不改：容器命名、备份名、挂载/网络/入口/用户/内存检查、`docker create` 参数形状、只建不启（启动与核验照旧由部署步骤执行）。

## 3. 部署时的命令（供部署 Issue 引用）

```
# 演练（不动容器）
python3 -I deploy/local-live/swap_app.py <app-image-id> --private-dir <私有目录> --spaces <spaces.json> \
  --set-env ENTERPRISE_VERSIONED_ENTITY_TYPES=insurance_product --dry-run
# 换装
python3 -I deploy/local-live/swap_app.py <app-image-id> --private-dir <私有目录> --spaces <spaces.json> \
  --set-env ENTERPRISE_VERSIONED_ENTITY_TYPES=insurance_product
# 回滚（换回旧镜像并移除该项）
python3 -I deploy/local-live/swap_app.py <旧 app-image-id> --private-dir <私有目录> --spaces <spaces.json> \
  --unset-env ENTERPRISE_VERSIONED_ENTITY_TYPES
```

## 4. 验收

离线测试 `harness/tests/service_shell/test_swap_app.py`：PATH 上放一个假 `docker`（状态在临时目录），以 `python -I` 子进程
运行脚本。
- 演练不调用 rename/stop/rm/create；输出只有键名与 `sha256:` 前缀。
- 换装后新容器的环境 = 原始运行时 + 合同目录 + 签名密钥 + Spaces + 受管键；argv 中只有 `-e KEY`。
- 受管键从当前容器延续；值不同未加 `--replace-env` 拒绝、加了则替换；`--unset-env` 移除，缺席为空操作。
- 未知键、格式不符、重复、同时设置与移除、来源含受管键、未传 Spaces 而当前容器有、原始容器镜像不符或在运行、
  新镜像不存在、私有目录缺文件：全部在动容器之前拒绝（调用记录里没有任何写操作）。
- 所有用例中，哨兵环境值不出现在 stdout/stderr、假 docker 的 argv 记录，以及临时目录中除假 docker 状态与私有
  `secrets.env` 夹具以外的任何文件里。
- R1–R4（`harness/tests/service_shell/test_swap_app_failures.py`）：拼错的选项、多余的位置参数、选项缩写、带值的开关都以
  退出码 2 拒绝且不回显；新镜像默认值下 `--unset-env` 拒绝，默认值同样受格式校验并给出指纹；`create` 失败后用同样的普通参数
  重跑，受管键从意图记录恢复，未传 `--spaces` 拒绝；当前容器与记录不一致拒绝，显式给出后通过；无当前容器且无记录时须显式给出；
  记录损坏拒绝；记录权限 0600；签名密钥或原容器环境含 NUL 或无法编码的字符、私有目录路径含 `:`，都在任何写操作与
  写记录之前拒绝。

门禁：上述测试、Harness ruff/mypy（测试文件）、`pytest -q tests/architecture`、手写文件 ≤500 行、`git diff --check`。

## 5. 回滚与范围

本片只入库工具，不改线上。部署时若新工具有问题，运维可继续用本机旧脚本（不带新增环境项）。本机脚本在新工具首次成功
用于线上后由运维删除，避免两份并存。

# RV4 · 发布后分层抽检：机器审核上线的内容按风险抽样交人确认，结论回流门槛

> 状态：待用户确认迁移（RV 系列已排期，2026-10-17；RV3 试点约束要求 RV4 落地，2026-10-18） ｜ 作者：Claude Code
> 依据：蓝图 §6.2（`POST /samples/:id/verdicts`）、§6.3（上线后按风险与字段分层抽检，结论写回 Golden 并校准门槛）、硬边界 4、8
> 拆分：RV4a 平台（Go + 迁移，Codex 实现）· RV4b 抽检台页面（前端，Codex 实现）· RV4c 抽样与回流（Harness，Claude 实现）；审核交叉进行

## 1. 目标

1. **抽样**：每次激活的 Release 中，标注"机器审核"的 Claim 按版本化抽检策略分层抽样，生成待确认样本。
2. **确认**：业务人员在"抽检台"逐条看取值与原文出处，给出"正确 / 不完整 / 错误"，可附说明。结论绑定 Release、成员摘要与确认人，不可改写；改判只能追加新结论。
3. **回流**：
   - 按 pack 汇总抽检结论，得到机器审核内容的实测精确率（Wilson 下界）；
   - 低于审核策略目标时，给出"提高门槛或撤销准入"的建议，由人决定，审核策略升版本；
   - 判为错误的条目进入修正队列（人工改判或重新编译，必要时按实体回退）。
4. RV3 试点期间的约束（每次 MACHINE 发布逐条人工复核）由 RV4 接管：试点期抽检比例设为 100%，数据积累后按策略下调。

## 2. 设计

### 2.1 RV4a 平台（`internal/enterprise/`，扩展点内，不改上游文件）

- **迁移 `000008_enterprise_spot_checks`**（需用户批准，附回滚）。新建两张表：
  - `enterprise_samples`：`id`、`space_id`、`release_id`、`logical_slug`、`member_digest`、`stratum`（Harness 给的不透明字符串）、`created_at`、`created_by`；
  - `enterprise_sample_verdicts`：`id`、`sample_id`、`outcome`（`correct` / `incomplete` / `wrong`）、`note`、`reviewer`、`decided_at`，只追加。
- **接口**（与现有 enterprise 路由同一套鉴权与租户隔离）：
  - `POST /spaces/:sid/releases/:rid/samples`（API Key）：提交一批样本 `{slug, stratum}`。成员必须存在于该 Release，按 `(release_id, slug)` 幂等；成员摘要由平台从 Release 读取，不信任调用方。
  - `GET /spaces/:sid/samples?status=pending|decided&release=`（会话或 API Key）：列出样本与最新结论。
  - `POST /spaces/:sid/samples/:id/verdicts`（会话）：提交结论，确认人取自会话主体。
- 平台不理解险种、字段与风险，只保存和校验通用样本、成员与结论（硬边界 4）。

### 2.2 RV4b 抽检台（`frontend/src/enterprise/`）

- 企业知识下新增"抽检"入口：按 Space 列出待确认样本。
- 每条复用 S3d 的字段显示（含 S3d-4 的分条与缩略版）和出处抽屉；按钮为"正确 / 不完整 / 错误"，可附说明。
- 覆盖加载、空状态、失败重试、键盘可达；已确认的样本显示结论与确认人。

### 2.3 RV4c 抽样与回流（Harness）

- **`catalog/spot_check_policy.json`**（版本化数据）：
  - 每个 pack 的抽样比例（试点为 1.0）、每次发布至少抽几条；
  - 必抽字段（高风险：保险责任、责任免除、等待期等，由 pack 数据声明）。
- **`review/spot_check.py`**（核心、通用）：按策略对 Release 中 `review.mode == machine` 的 Claim 分层抽样。
  - 必抽字段一层，其余字段一层；按 Release id 定种子，结果可复现。
- **发布接线**：`publish.py` 激活了带机器审核 Claim 的 Release 后提交样本；只有人工审核 Claim 的 Release 不抽。
- **回流命令 `eval/spot_check_report`**：读取结论，按 pack 统计精确率与 Wilson 下界（"不完整"按 S2c 口径不算错）。
  - 与审核策略目标对比，输出建议，不自动改策略；
  - 判为错误的条目列入修正清单。

## 3. 拆分与顺序

1. RV4a（Codex 实现，Claude 审核）：迁移 + 三个接口 + Go 验收；
2. RV4c（Claude 实现，Codex 审核）：可与 RV4a 并行，用假平台测试；
3. RV4b（Codex 实现，Claude 审核）：依赖 RV4a 接口；
4. 部署（单独 Issue）：App 与 UI 各构建 1 次，执行迁移 000008。

## 4. 需要用户批准

- 迁移 `000008_enterprise_spot_checks`：本机测试库与演示环境，附 down 迁移；
- 部署时 App、UI 各构建 1 次。

## 5. 不在本片

- 抽检结论自动写回 Golden（先人工核对后再写，另立切片）；
- 按字段的门槛；
- 消息通知。

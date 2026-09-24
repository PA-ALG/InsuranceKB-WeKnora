# 原文编号准入首切片（2026-09-25）

## 当前边界

继续既定 G35-R5/R6 单材料 tracer，root 唯一写者。新 wire v3 让模型逐段选择证据编号并声明来源，程序展开精确原文和位置；旧 v1/v2 投影、R6、几何定位、最终审核与唯一 Active Release 不变。代码尚未提交/构建/部署；revision2独立源码复核0 BLOCKER。四项真实质量阻断没有被软件结果自动关闭。

## 复用与实现

- `native_admission_wire.py` 是无 I/O 的窄适配：沿既有验证过的 source_options 完整 span 编号（如 s8:1），不再要求模型重抄引文、算 offset 或维护独立 evidence 列表。按 catalog 顺序生成既有 v2 evidence/indexes；text/origin/decisions 不改。未知、重复、乱序、MODEL 带引用、SOURCE 无引用和原正文覆盖错误仍拒绝。同一证据可被多个段落使用。
- 模型原文改述明确标 SOURCE_SUPPORTED；真正补充解释独立 MODEL_GENERATED。新系统模板明确比较 Schema 的对象、接收方、触发、条件、例外和后果，提醒保留效力中止后果及告知对象范围。提示不是质量通过证明。
- `native_admission_policy.py` 封装显式可选 admission 模板绑定和配置派生。基础 model、其他模板、连接/凭据/模型/容量及 native_discovery 保持；派生配置只替换旧准入模板。composition 复用同一个 ConfiguredModelExecutor 类的另一个配置实例，仅准入选择它，不新增执行/恢复平台或全局 hash 白名单。
- execution 回执升 v2，绑定协议、template/prompt/model policy、input/request/raw。完整 discovery checkpoint 复用前重新核对原调用记录及当前准入配置；删除或修改 override 不可沿用旧结果。旧 execution artifact 升版截断旧完整阶段，成功 raw 仍由原 exact matcher 选择。FAILED discovery 的来源/身份/字段/原生发现/引用复用不变。
- provider wire context/raw 与 RULE 展开的领域 v2 response 分开保存；既有 dependency receipt 使用严格重建的 v2 领域 context，wire expansion 回执绑定该映射。没有自动修正文、替模型重标来源、删除不合格成员或造页。

## 验证矩阵

| Requirement | 已观察 RED | 最终软件验证 | 状态 |
|---|---|---|---|
| G35-R5-WIRE-1 精确绑定/来源 | 旧预检不支持 wire，9失败 | 中文/emoji/CRLF；未知、重复、篡改 context、标签冲突、正文覆盖；非空 page 经原 geometry；原 wire 不变 | PASS |
| G35-R5-WIRE-2 仅准入升级 | 新配置旧 loader extra_forbidden；真实 worker 仍发送 v2 | 基础 policy 不变；不合法模板/权限扩展拒绝；完整持久 worker 仅准入新发送，来源/身份/字段和6原生调用保持 | PASS |
| G35-R5-WIRE-3 完整恢复身份 | override 删除/变化时完整 checkpoint 原先未拒绝；旧 artifact version 断言失败 | 同配置三代恢复不新增调用，删除 override/改模板预算拒绝；原调用 request/raw 保管校验保持 | PASS |
| G35-R5-WIRE-4 后果/对象保真 | 真实旧输出的两项语义缺口仍有效 | 新提示已加强，尚无新 provider 输出或独立全处置验证 | BLOCKED |

最终有界回归 `g35-wire-bounded.log`：94 PASS、1 SKIP（v1不适用成员合同）、1 已有 Starlette 弃用 warning，271.11秒。ruff PASS；7个受影响生产文件 mypy PASS。早先分组验证与此重叠，不累加测试数。最终冻结源码/测试/Spec 清单 `/private/tmp/g35-wire-review-2.json`，基线 HEAD `77ee9d5dbd942dd9db39126b75f1eac4ae2617da`。

真实旧输入离线反事实：原两页 MODEL 标签若选择 evidence_refs 仍拒绝；只有显式人工声明期望 SOURCE 标签的测试夹具才能展开。18个 source span 全文不变，wire context 61163 bytes，旧 v2 为61274 bytes；两页正文未改，因此中止后果被拒、告知对象遗漏仍存在。该检查只验证协议适配，**不是新的模型输出、正式准入、发布或质量结果**，effects=0。回执 `/private/tmp/g35-wire-real-input-diagnostic.json`。

## 交付与真实业务

截至本报告，本切片 build/provider/business writes=0。离线准备配置 `e0e3a79b…`，仅新增 admission override；原 runtime `624e393d…`、base model/native_discovery policy 逐字保持。新 prompt SHA `5bff15c5e0ac5a07e4c68745144070da9c26af9f2e7f920387045d8ab8305e84`，保持300000 bytes/16384 output tokens；配置尚未应用。

只读容器检查仍为 d8 Harness 镜像 `ed95cb8b…`、API/worker healthy，runtime `624e393d…`；网页仍显示旧 a9b39523 PARTIAL_SUCCESS/发现FAILED/模型1/复用8。未重试按钮、未重传材料、新建库或直接改业务数据库；Active 未在本轮新 GET。旧真实窗口保持关闭。

下一步须独审收口、冻结提交和精确交付窗口，再集中 Harness-only 构建/可回滚切换与同一材料一次正常 UI 恢复；最多新准入1+最终审核1，其他阶段期待 exact reuse，未知/失败停止并保留回执。真实输出逐项对照四阻断、全部14候选处置、18项覆盖、模型补充标记和原文点击，不能用 fixture 替代。

已确认后续覆盖门缺口：现 v6 审核仅 retained dispositions，candidate_member_count=0 时跳过独审。全部拒绝不能作为覆盖正确证据；自动全处置审核需另版本化（包括零成员），不在本切片偷偷改变模板。完整 G3.5、R4 与跨窗口 R6 仍未完成。

## 独立复核收口

首审2项BLOCKER已关闭：规范化wire值哈希改名wire_value_sha256，外层decoded字节与provider envelope原始哈希分别保留；新增引用乱序及16类receipt/call/context篡改直接反例。哈希命名先观察真实RED；内存mutation分别删除order/identity守卫产生预期测试失败，只是补充敏感性诊断，不冒称历史实现RED。随后纯边界35 PASS（25.82秒）、非空v3 stage1 PASS（5.67秒），ruff PASS；与原94项重叠，不简单累计。revision2清单14/14 SHA匹配，独审0 BLOCKER，原全REJECT/零成员语义审核BACKLOG保留。

16:13:48Z通过同账号正常GET确认a9b39523仍PARTIAL_SUCCESS、字段26/51/2、自由发现FAILED；唯一Active仍epoch19/release-7cc9f6c8-5050-4678-9225-380356dc8f98。本次GET为只读交付前基线，非新发布。两个Harness容器镜像/配置仍上述原值且healthy。

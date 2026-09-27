# 升级要求

## ADDED Requirements

### Requirement: UPG-01 升级身份
系统 SHALL 固定上游版本、产品提交、组件制品与实际部署身份；构建成功不代替业务成功。

#### Scenario: 固定上游身份
- **WHEN** 检查固定上游祖先与组件实际身份
- **THEN** 上游为祖先，各组件source/digest/config分别绑定回执。

### Requirement: UPG-02 平台边界
系统 SHALL 同一 Harness 构建在已声明兼容的旧/新平台协议上通过必要契约检查；差异封装在 adapter；并不承诺永久双版本支持。

#### Scenario: 双平台协议兼容
- **WHEN** 同一Harness运行旧及新平台契约样例
- **THEN** 结果同版，未知合同明确拒绝。

### Requirement: UPG-03 领域独立
系统 SHALL 代表性 Schema/准入规则改动只影响 Harness 的适用模块，不要求修改或重建 WeKnora Go 应用；新增协议能力按实际影响另评估。

#### Scenario: 领域规则独立
- **WHEN** 替换代表Schema及准入规则
- **THEN** 仅Harness变更，Go source identity保持。

### Requirement: UPG-04 业务连续
系统 SHALL 既有 FieldAssertion、自由知识、模型生成标识、正式关系、来源、历史快照在新平台可读；一条真实链路正常审核发布与 source click。

#### Scenario: 来源及知识连续
- **WHEN** 读历史epoch27并运行新审核发布链
- **THEN** 旧来源可读，新链检索及原文点击成功。

### Requirement: UPG-05 恢复与成本
系统 SHALL 历史成功结果保留；重复提交/进程重启不无故重解析或重发成功调用；新发、复用、未知结果分别记账；上游续写/重试纳入同一预算。

#### Scenario: 发送和恢复
- **WHEN** 注入未知发送、journal失败、禁用重试及重启
- **THEN** 发送前记账失败零调用，禁用重试一次，未知不盲重发，成功回执复用。

### Requirement: UPG-06 隔离与故障
系统 SHALL 普通 KB、托管 Wiki 行为正确；插件关闭/离线不开放旁路写；租户/Space/当前 ACL、源撤回和失败关闭保持。

#### Scenario: 插件故障隔离
- **WHEN** 断开Harness，检查普通与托管KB及ACL撤回
- **THEN** 普通KB沿原生，托管旁路写拒绝，当前ACL和来源撤回生效。

### Requirement: UPG-07 迁移与回滚
系统 SHALL 核实迁移真实变化与数据兼容；区分应用回滚和数据库恢复，不能只凭保留旧镜像声称可回滚。

#### Scenario: 升级与恢复
- **WHEN** 从75/5升级并按冻结备份恢复
- **THEN** 110/5可启动，旧应用仅在兼容DB恢复后通过。

### Requirement: UPG-08 构建范围
系统 SHALL Python、Go、前端按真实依赖独立交付；历史材料浏览/普通配置不触发编译；记录冷/暖构建实际成本，不预先许诺分钟数。

#### Scenario: 组件成本
- **WHEN** 计算Harness、前端及配置变更的构建输入
- **THEN** 无关Go不构建，BrowserSkill及AnyDoc按实际依赖记账。

#### Scenario: 已授权下载链路恢复
- **WHEN** 镜像元数据或依赖下载故障阻断交付，用户要求解决网络问题
- **THEN** 在既有代理/镜像配置内以有界真实下载和摘要校验验证修复，保留配置回滚与运行容器身份；环境探针不消耗或自动扩充App构建预算，也不替代应用构建与业务验收。

### Requirement: UPG-09 核心修改可解释
系统 SHALL 每处保留的上游核心补丁有必要性与回归证据；内部已替代实现删除，不以文件数或接口层数冒充低耦合。

#### Scenario: 必要平台补丁
- **WHEN** 核对保留补丁清单与旧路径
- **THEN** 有Owner、理由、回归和退出条件，替代内部实现已删除。

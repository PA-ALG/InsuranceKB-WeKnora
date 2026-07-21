# 027 Production Weak-Model Boundary 验收规格

## ADDED Requirements

### Requirement: PWB1 不可变弱模型身份

生产模型身份 SHALL 由 `provider + deployment/model immutable id + capability role + policy version` 构成；只允许批准列表中的 MiniMax/Qwen/Qwen-VL 能力档。空白、未知、`latest`/rolling alias、Claude/DeepSeek 或批准记录不匹配 SHALL 在任何网络调用前拒绝。

#### Scenario: 未批准模型零网络调用

- **WHEN** production profile 请求未知、强模型或 rolling identity
- **THEN** 返回类型化拒绝，provider fake 记录零调用

### Requirement: PWB2 所有生产入口共用单一策略

extract、gap、judge/consensus、conflict suggestion、merge candidate promotion 与 release command SHALL 共用同一 policy decision，不得各自复制 allowlist。缺 policy/permit 的 production 调用 SHALL fail closed。

#### Scenario: 旁路枚举测试

- **WHEN** 测试枚举所有公开 CLI/API/package entrypoint
- **THEN** 每个 production entrypoint 都要求同一 `ModelPermit` 或明确证明零模型

### Requirement: PWB3 禁止强模型 fallback

生产路径遇到模板失配、弱模型失败、无共识或截断 SHALL 重试批准弱模型、产生 Alert/ReviewItem 或停止；SHALL NOT 自动切换强模型或 offline judge。

#### Scenario: 弱模型失败不升级模型

- **WHEN** 批准弱模型达到 attempt 上限仍失败
- **THEN** 结果为 blocked/alert proposal，强模型 fake 零调用，零 ChangeSet 自动推进

### Requirement: PWB4 Admission 与审计绑定

production permit SHALL 绑定适用 run admission、template/model plan hash 和调用角色；permit 不匹配、过期或 run 非 READY 时零网络调用。每次允许/拒绝决定都产生不含 secret 的结构化 receipt。

#### Scenario: 不能借用 020 canonical 状态

- **WHEN** 030 MVP run 请求使用 020 canonical admission 的 approval/permit
- **THEN** 因 run identity 不匹配被拒绝

### Requirement: PWB5 零模型验证

027 自身所有 deterministic tests SHALL 使用 fake transport，validation report SHALL 明确真实 provider 为 `NOT RUN`。

#### Scenario: 报告不虚报 provider

- **WHEN** 027 在无真实 provider 调用下完成
- **THEN** 只报告 policy/entrypoint contract PASS，provider 记 `NOT RUN`

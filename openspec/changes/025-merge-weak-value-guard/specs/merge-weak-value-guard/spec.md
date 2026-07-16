# 025 合并前置弱值门槛验收规格

> 门槛是 007 K2 冲突判定的**前置过滤**，不新增替换路径。第一性原理：护栏 fail-safe——只抑制**明确更弱**的同/低权威值，对相等/不可比/缺基线/计算失败一律 fail-open 到既有合并（宁可多开一次审，绝不静默吞可能更优的值）。informationScore 是排序信号，SHALL NOT 成为替换判据。

## ADDED Requirements

### Requirement: G1 更粗略新值不得开冲突

对同 `(space_id, product_version_id, predicate)` 已存在 published Claim 的情况，当新候选值相对该 published 值**严格更弱**（informationScore 明确更低，G2）且**权威不高于**已发布值（G4）时，合并 SHALL NOT 开 conflict、SHALL NOT 生成 ReviewItem、SHALL NOT 落新 Claim（candidate/draft 皆不落）；该候选被**抑制**（drop）并记 G5 审计事件。此门槛 SHALL 在 007 K2 的冲突/supersede 判定**之前**执行。

#### Scenario: 更粗略同权威值被抑制而非开冲突

- **GIVEN** 已发布 Claim 值「等待期为 90 天」（权威=条款）
- **WHEN** 合并一个同权威新候选「有等待期」（informationScore 明确更低）
- **THEN** 不开 conflict、不生成 ReviewItem、不落新 Claim
- **AND** 记一条 G5 抑制事件，已发布 Claim 保持 published 不变

### Requirement: G2 informationScore 必须确定性且可审计

信息量比较 SHALL 为确定性、零真实模型调用的纯函数：基于长度、具体性信号（数值/日期/百分比/单位/枚举项计数）、结构完整度等运行时可得特征。同一对输入 SHALL 恒得同一判定（无随机、无外部状态）。"严格更弱"的判定 SHALL 附两值与两分进入 G5 审计事件（可复盘为何抑制）。informationScore SHALL NOT 参考金标或任何测试预言机。

#### Scenario: 同输入判定确定且留分数痕迹

- **WHEN** 对同一对 (旧值, 新值) 计算两次信息量比较
- **THEN** 两次判定完全一致
- **AND** 抑制发生时，审计事件含旧值/新值/旧分/新分/判定原因

### Requirement: G3 门槛必须 fail-safe，不确定即不抑制

仅当新候选**明确严格更弱**时才抑制。以下情况 SHALL NOT 抑制，而是 fail-open 到 007 既有合并（正常走冲突/supersede/审核）：两值 informationScore **相等**；两值**不可比**（不同维度、无法确定强弱）；已发布**基线缺失**（该字段尚无 published Claim）；informationScore **无法计算或抛错**。门槛的任何计算失败 SHALL NOT 导致丢值。

#### Scenario: 信息量相等时照常进入既有合并

- **GIVEN** 已发布值与新候选 informationScore 相等或不可比
- **WHEN** 执行弱值门槛
- **THEN** 不抑制，交回 007 K2 按权威/裁决正常处理（可能开 conflict 或 supersede）

#### Scenario: 门槛计算异常时 fail-open 不丢值

- **WHEN** informationScore 计算对某候选抛出异常或返回不可用结果
- **THEN** 该候选 SHALL NOT 被抑制，照既有合并路径处理，异常被记录

### Requirement: G4 门槛与权威序正交，不得抑制更高权威值

弱值门槛 SHALL 只作用于**权威不高于**已发布值的候选。**更高权威**的新值——即便信息量更粗略——SHALL NOT 被抑制，而是照 007 K2 走 supersede 语义（权威胜过信息量：高权威更正是合法修订）。门槛 SHALL NOT 成为高权威更正被静默丢弃的路径。

#### Scenario: 更高权威的更粗略值仍照常 supersede

- **GIVEN** 已发布值「等待期 90 天」（权威=产品说明书）
- **WHEN** 合并更高权威新值「有等待期」（权威=条款，但更粗略）
- **THEN** 门槛不抑制，交 007 K2 按权威序 supersede（进审核符合 K2/K3 既有规则）

### Requirement: G5 抑制必须留 append-only 审计事件，绝不静默

每次门槛抑制 SHALL 写一条 append-only 审计事件（新迁移 0011 表），闭合 Space 归属，含：`(product_version_id, predicate)`、被抑制值、已发布值、两方 informationScore、判定原因、时间戳。抑制事件 SHALL 可按 Space/产品/批次计数，供 008 展示"本批抑制 N 条更粗略值"。门槛 SHALL NOT 静默丢值（无审计的丢弃即违规）。

#### Scenario: 抑制可计数可复盘

- **WHEN** 一批合并中 3 个候选被门槛抑制
- **THEN** 恰有 3 条 append-only 抑制事件落库（各含两值两分与原因）
- **AND** 008 可按 Space 查询到该批抑制计数

### Requirement: G6 informationScore 仅作排序信号，SHALL NOT 作替换判据

informationScore SHALL NOT 触发 auto-supersede 或以任何方式替换已发布 Claim——替换 100% 由 007 的权威序/裁决决定，本 change 不改。informationScore 仅可作为 008 工作台的**排序/优先级**信号（W1.1 可选信号）暴露。系统 SHALL NOT 存在"信息量更高即自动取代已发布值"的路径（防其成为绕过权威序的后门）。

#### Scenario: 信息量更高的新值不自动取代

- **GIVEN** 已发布值与一个 informationScore **更高**但**权威不更高**的新候选
- **WHEN** 执行合并
- **THEN** 门槛不因"新值信息量更高"而 supersede 或替换已发布 Claim
- **AND** 是否采纳仍交 007 K2 按权威/裁决判定（informationScore 只影响 008 排序）

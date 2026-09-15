# 最近 G3 证据基线复用：代码与交付记录（2026-09-15）

G3 **未完成**。Task3av 网页恢复失败；本记录的 Task3aw 代码通过，不代表真实发布成功。

## 真实失败与测量

- Task3av run `155a5f45-ca70-59fc-ae24-d426e5edb07a`：09:31:24.656Z点击，09:51:13.315343Z失败，1188.659343秒。checkpoint229.020407秒；三次草稿请求300.278781743、302.416461286、300.346572226秒后503。0新增/10复用模型；21有效、31未提供、30抽取失败。没有新发布。
- Task3av配置交付PASS：同Harness镜像，timeout120→300；0构建/迁移/业务写入。真实失败已证明不能仅延长等待。
- 当前父链4层G3（各约7.4–7.8MB），随后G2/G1/815；最近父sealed proof40868B存在，失败child proof未封存。旧代码新candidate miss后重新遍历完整旧链。
- 单个实际父准备件/516成员原样导出，本地GOMAXPROCS=1完整验证23.032305792秒、计数1，PASS；不是Colima性能或RED。

## 已实现边界

沿用G3-AUTO-3/4/5/6与用户最近G3基线复用要求。发布权威复用已签名projection检查准确scope/release/epoch/preparation/member。来源权威按父候选自己的candidate/base/epoch读取原sealed proof；逐父field/evidence occurrence核对后，仅继承未变事实和合法导航扩展。可选集合nil/empty复用已有比较语义。当前知识删除、revision/binding、retention/resource及原精确旧摘要映射继续检查。

缺失基线沿用原准备路径；损坏基线失败，不静默覆盖。没有删除历史、改写真实candidate/proof/model响应、建立新环境或第二发布权威。原生first-parse重复读取是独立未测成本，本次未修改。

## Requirement → 实现 → 验证

| Requirement | 实现 | 本地验证 | 状态 |
|---|---|---|---|
| G3-AUTO-3 | g3_published_legacy_baseline及constructor接线 | 最近父proof命中，两个不同child冷开，旧链调用/历史完整验证均0 | PASS |
| G3-AUTO-6 | occurrence映射与既有来源尾部检查 | 导航/可选空集合可复用；值/条件/例外/引文/页码/offset/source/parser/字段/version变化不继承 | PASS |
| G3-AUTO-4/6 | 原sealed artifact owner/缺失准备路径 | scope/epoch/损坏projection与proof拒绝；missing区分；revocation仍拒绝；child/父proof原样 | PASS |
| G3-AUTO-5 | 同APP制品部署适配 | build/smoke/deploy尚未执行 | NOT RUN |

RED `task3aw-red.log`：2个预期行为失败（错误回溯祖先、冷可选集合不等价），28.554秒。GREEN `task3aw-green-03.log`：8主测试及12字段变化子例，43.978秒PASS。早期green01未使用import造成编译失败、green02测试fixture缺store造成panic，已修复，日志保留；不把这些当RED。

实际只读映射：父原证明17项→当前child未变字段17项，0.106854084秒，PASS。此probe只检查映射，**未做生产签名验证**；原seal的验签继续由真实平台原owner执行。输入hash：parent export `7cb6dcf3b37a8ce0c41e91e496b8062fab53e263a378838b4f378492ab2e1eb2`，proof seal `cd9e47b7bc34cab1708f3f64ef870ef4640cedee39d2d735f7809115cdb15e63`，child `c007b78e0b94e6c8e0fa20c167eb921acfff17c23e8f00779324bb43e35c7903`。0模型/业务写入。

## 独立复核与交付队列

冻结identity `task3aw-review-identity.json` SHA `de33bbe39475bfa9d11de3087eb7fb95266dc3e32101b97a75dd18733318eeb3`；独立报告SHA `09dd94fec17f74ac59cb2161c3f0fcdf4ea4e260134dc214c1825e30c89c109f`，0 BLOCKER，保留既有完整native端到端fixture BACKLOG。本记录为上述结果的机械归档。

DELIVERY：software PASS；container health/provider probe/provisioning/local live NOT RUN（本Task3aw）；GitHub live NOT RUN。下一步仅构建/部署受影响APP，保留Harness/UI/DB、300秒配置；同网页恢复最新失败run。增量发布、检索、证据通过后，再做新产品三原件网页独立验收。没有5～10分钟性能达标结论。

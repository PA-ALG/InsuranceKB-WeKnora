# G35：已发布生成内容在服务重启后保持合法读取

2026-09-27，真实run3a916e65在field_plan失败；前轮epoch26已经正常发布生成概念。
根因：签名published read projection用gob持久化，重启解码将合法空slice变为nil，
平台base snapshot因而输出evidence=null/evidence_indexes=null。模型调用成功，非字段遗漏。
沿G3.5全项授权修复通用跨轮流程；root唯一写者，原模型raw/旧发布/签名制品不改。

- **READ-GEN-1**：唯一修复Owner为Go已发布读取缓存。已验签冷读恢复MODEL_GENERATED
  segment的合法空引用索引，以及全生成definition/page的合法空evidence；热读与冷读
  的生成来源标注和Evidence表示一致，含普通page、definition及mixed正文中的生成段。
  以同一签名PageManifest member payload中的显式空数组为恢复依据；不承诺其他可选
  数组或整个snapshot SHA冷热相同，既有可选集合兼容不在本切片内。
- **READ-GEN-2**：只恢复gob丢失的合法空集合。不补源支持段的空索引，不制造Evidence，
  不删除/改写正文或来源标志，不放宽Candidate/来源/权限校验。旧签名投影文件不重写。
- **READ-GEN-3**：签名、scope、candidate、Preparation/member identity、正文及引用hash
  投影及preparation本地守卫通过后才恢复并入内存cache；
  当前Release成员身份仍在base snapshot返回前逐次校验；重启读取不触发语义编译或模型调用。保持缓存copy/isolation原合同。
- **READ-GEN-4**：测试实际签名gob持久→新实例读取→base snapshot，并跑既有candidate transfer回归；真实正常上传再验证传输/发布，
  同时验证畸形未签名输入仍拒绝。只构建部署App，Harness/UI/配置不变；正常入口续跑
  时保留原失败任务，并如实处理旧失败任务已经冻结的坏snapshot，禁止手改artifact。

写域：internal/application/service/g3_published_read_reuse.go及对应测试，必要的同域
内部恢复helper；既有platform base/transfer回归测试、对应合成fixture及可重建生成器和本Spec/证据。不新增协议/表/队列。
RED先证明实际签名冷读丢空集合；独审后实现与受影响包检查，再冻结构建/可回滚交付。

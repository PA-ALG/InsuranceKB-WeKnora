# G3.5 R4 正式关系承载与读取（2026-09-26）

root 唯一写者；基线 e9bbd31ef0c4259cf2f17152cc4e5d91074f3525，活动工作树
830-g35-knowledge-admission。用户继续 G3.5，质量统一后置。适用 Spec：
`openspec/changes/129-830-g3-catalog-batch/specs/catalog-batch/business-relation.md`。

## 结果

新增 typed product-concept-relation.830.v1 扩展，原子承载在既有 FreeWikiPage。
主体/版本、语义 predicate、同版概念及 exact revision、条件和原文 Evidence 进入同一
Candidate/Review/manifest/Release 数据链；无第二关系表/队列/Active。省略扩展的旧字节
保持。G2 standalone 拒绝扩展，只有 G3 batch 接受。模型补充不能成为正式产品关系。

独审修正设计：版本不进入稳定 ID，同一主体/版本下的关系内容修订走显式 UPDATE。
当前 G3 不支持同主体跨版本迁移，关系不单独放宽该限制；稳定键设计不代表迁移能力。
普通页与关系页不能在同 ID 下静默互换。最终组合重验
所有关系的目标 revision，因此更新概念不能让继承的关系引用旧义项而通过。

UI 展示业务关系、产品版本和概念入口。概念→关系、产品总览→本产品关系、关系→目标概念按上述方向联通；来源沿原
精确证据路径。这里是软件级协议纵向验证，非真实模型产生正确关系的业务验收。

## 验证事实

- Python 留存有效 RED：6 failed / 13 passed（旧 DTO 拒绝扩展）；类型升降级额外 RED：2 failed。
- Go types 首次有效 RED：2 failed（旧 DTO 拒绝扩展）。更早测试误拼函数名导致 build error，
  不计 RED；已纠正。Go service 双向导航 RED：concept/overview 两个断言失败。
- 前端 API / Vue 各 1 个有效 RED；最终两文件 37 PASS，类型检查 PASS，Vite build PASS
  （1m45s，既有大 chunk warning 保留，无额外拆包优化）。
- Python 最终定向 40 PASS / 54 deselected，80.24秒，包含旧冻结候选字节、provenance、
  完整关系 Candidate/manifest 与旧审核失效；3 源码 mypy PASS、ruff PASS。
- Go types 10.077秒 PASS，service 87.323秒 PASS（本轮筛选的 relation/provenance/read/source tests）。
- Python→Go 完整合成 Candidate JSON 向量重放一致；其内容/评分明确是协议 fixture，
  不属于真实 provider、产品事实质量或自动审核通过的业务证据。
- 第一批 18 文件 exact manifest `/private/tmp/g35-r4-20260926/review-1.json` 独审
  0 BLOCKER，首尾 SHA 18/18 一致；service 导航增量独审软件 0 BLOCKER；证据计数和方向描述按留存日志纠正。

运行环境：uv 首次触发沙箱缓存权限，改缓存后 macOS system-configuration panic；均不是
产品 RED。复用已有 harness/.venv 的 Python 3.12 完成测试，没有安装/升级依赖。

## 矩阵与边界

| Requirement | 实现与验证 | software | local live |
|---|---|---|---|
| REL-1 身份/严格扩展/旧字节 | product_concept_relation.py + Go 同合同 + 正反例 | PASS | NOT RUN |
| REL-2 来源/同版目标 | 最终 lint/Go members 校验 + 漂移/假引文反例 | PASS | NOT RUN |
| REL-3 候选/审核/manifest | 完整共享 Candidate 重放、旧审核失效 | PASS | NOT RUN |
| REL-4 关系读取/导航 | API、Vue、Go service 正常读模块 | PASS | NOT RUN |
| REL-5 正常模型生成与同版本内容修订 | 不在本基础承载/读取提交内 | NOT RUN | NOT RUN |

同主体跨版本迁移与关系删除不在首切片支持范围；真实发布仍待 REL-5。
REL-5 的独立未提交准入切片已有软件验证；其交付身份另行冻结，不归入本基础承载提交。
software PASS 不推导 R4/G3.5 BUSINESS PASS。provider/build-container/deploy/migration/
Candidate/Draft/review/publish/activation/live probe 均 NOT RUN，实际新增模型调用/业务写入 0。
本轮仅前端本地构建，不构建镜像。01:40:26Z只读重新GET确认仍epoch21，Harness仍旧e9bbd31ef健康运行；不代表新关系部署。
未提交质量/coverage/UI 状态改动保持，不因本增量宣称质量通过。

# 126 · 830 G1 实体页图与独立 FieldAssertion

## Goal

在不改变 815 唯一 WeKnora Wiki/审核/Release/Active authority 的前提下，把冻结的
真实医疗险实体 `ping-an-e-sheng-bao` 编译为同一原子 Release 内的 76 个页面成员：
1 个 Entity Overview、医疗险 Profile 的 7 个 Section、67 个实体作用域
FieldAssertion 和 1 个空 `free_wiki` 分组。页面只投影同一 Candidate 的结构化
Field/Evidence，不保存第二份可编辑事实。

## Frozen identities

- base：`d2ce44cb2107575f7624b3735c653078ae2a98b6`；
- 815 evidence source：`9fcf3386833d822a31f2de13fdf76c3eb6b13795`；
- 815 release：`release-42a3dd0c-ec76-4017-a288-37f1b13519a0`，epoch `2`；
- entity：`ping-an-e-sheng-bao`，version `ping-an-e-sheng-bao@596-1`；
- display name：`平安e生保（尊享版）医疗保险`；
- SchemaPack：`medical-schema67.v1@v1+fe3b390222108614d3ff07409fbd81d17e915e066eb9c25c03d3268bc49ef7ac`；
- ordered67 digest：`8ffe2a043dfae6e65d84f213d42818de3c6c1c39c1fcb0c9eccd14367a30db24`；
- B0 frozen-input manifest：`docs/insurance-kb/evidence/830-g1/frozen-input-manifest.json`。

`Schema67 QUALITY=DEFERRED`。G1 只验收 FLOW，不运行或调用 Provider/模型。

## Adopted design

采用当前 815 Schema Wiki 的窄扩展：Harness 先从正式 SchemaPack、批准字段行与真实
Candidate/Evidence 编译一个带稳定 identity/route 的 `EntityPageManifest`；WeKnora
仍用现有 preparation/review/Release/Head 生命周期原子持久化和读取整包；前端只为这些
release-pinned 页面增加实体路由和导航。旧 75-member Release 保持可 pinned 读取，G1
以新合同生成 76-member successor，不修改历史 payload。

否决两种路径：仅给现有组合表格增加锚点，因其没有独立页面 identity；另建 Harness
页面库/发布器，因其会形成第二事实库或第二 Active authority。

## Contracts

### Stable page identity and route

权威 identity 只由稳定 `entity_id`、`page_kind` 与稳定 key 组成；标题、分类显示名和
主导航都不参与 identity。内部 namespace 使用
`urn:jlx:wiki:<space_id>:entity:<entity_id>:<page_kind>:<key>`，用户路由为：

```text
/platform/knowledge-bases/<kb_id>/schema-wiki/entities/<entity_id>/overview
/platform/knowledge-bases/<kb_id>/schema-wiki/entities/<entity_id>/sections/<section_key>
/platform/knowledge-bases/<kb_id>/schema-wiki/entities/<entity_id>/fields/<field_key>
/platform/knowledge-bases/<kb_id>/schema-wiki/entities/<entity_id>/free-wiki
```

显式 pinned read 使用同一路径加受校验的 `release_id` 查询参数；未给 pin 时仅可先读
唯一 current Head，随后请求内固定该 release。禁止 `current/latest` 字符串 fallback。

### One structured source

Overview 和 Section 只保存导航、字段引用和展示元数据；FieldAssertion 保存字段状态、
值快照、Claim/Evidence 引用与 exact citation；`free_wiki` 在 G1 必须为空。所有页面
绑定同一 `release_id`、Candidate、SchemaPack 和 PresentationProfile。删除 rendered
content 后可从结构化 payload 重建。

### PresentationProfile

G1 只注册一个医疗险 Profile。它绑定 7 个有序 section 与 67 个 field 的唯一主映射，
但公共 validator/renderer 只消费“有序 section 集合 + field mapping”，不得判断数量
等于 7。测试使用一个最小非 7 节点 Profile 证明该边界；不注册其为产品 Profile。

### Tri-state and Evidence

- `present`：非空值、Claim 引用和至少一条 release-bound Evidence；
- `absent_explicitly`：明确否定值、Claim 引用和否定 Evidence；
- `unknown`：页面仍存在、值为空、Evidence 为空并带 typed reason；
- known source click 必须按 exact revision/PDF/page/quote 打开，任何不一致 typed fail
  closed，绝不跳第 1 页。

## Owner matrix

总控是唯一 integration/commit/push/PR/merge Owner。默认只有一个可写 lane。

### G1-Win1 · Harness and shared contract

- `harness/src/insurance_harness/knowledge_compiler/entity_page_graph_830_g1.py`；
- G1 所需的最小现有 Harness contract/compiler 接缝；
- `harness/tests/test_entity_page_graph_830_g1.py` 与直接受影响测试；
- 跨语言 fixture/vector 的 G1 新文件。

### G1-Win2 · WeKnora/frontend（共享合同冻结后才可启用）

- `internal/types/`、`internal/application/service/`、`internal/handler/`、
  `internal/router/` 中仅 G1 entity page graph 的窄扩展与 focused tests；
- `frontend/src/router/index.ts`、`frontend/src/api/schema-wiki/`、
  `frontend/src/views/knowledge/schema-wiki/` 中仅 G1 route/read/navigation；
- 不改 migration、数据库表、第二发布器或通用 Wiki 核心。

### G1-Review · read only

`WRITE_DOMAINS=∅`。只按冻结 commit/tree/manifest 复核，不修改任何文件或外部对象。

治理文件、OpenSpec、共享 contract、Evidence Pack 和所有集成动作只由总控写。

## Milestones and validation

- M0（D0）：治理指针、唯一 OpenSpec、Owner/RED、冻结输入和计划；无 Docker；
- M1（D1）：真实 815 Candidate Preview 可见 overview、1 section、3 field pages、空
  free_wiki、稳定 URL、短标题及至少 1 个 exact source click；
- M2（D1）：76/76 manifest、67/67 三态、稳定 identity、非 7 renderer 测试；
- M3（D2→D3）：总控只构建受影响 app/frontend 镜像一次，D3 复用同一 digest，在
  隔离环境形成一个 `NOT_FOR_PRODUCTION` Release；current/pinned/source-click 通过，
  生产 `8081` 和原生产 Active 不变。

验证矩阵必须逐项记录 `Requirement → RED → Implementation → Focused Test → Commit →
Live Evidence → Status`。环境未启动、依赖缺失、fixture 或接口未调用不得冒充 RED/live。

## STOP and non-goals

发现第二 Wiki/审核/Active/事实库、Harness 直读 WeKnora DB、逐页激活、可变标题路由、
Markdown 权威、需要新服务/新表/图数据库、共享 ConceptDefinition、11-pack Catalog、
模型调用、质量优化、生产 `8081` 变更、第二层前置或同一阻断一次纠偏后仍失败，立即
`G1=STOPPED` 并返回用户。G1 PASS 后仍不启动 G2。

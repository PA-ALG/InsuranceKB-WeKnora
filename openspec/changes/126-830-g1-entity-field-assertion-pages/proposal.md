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
- actual Candidate/Claim/Evidence authority：
  `docs/insurance-kb/evidence/830-g1/actual-input-authority.json`；
- PresentationProfile：
  `docs/insurance-kb/evidence/830-g1/medical-presentation-profile.v1.json`。

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

### M1 Candidate Preview 接线

M1 不新建 lifecycle。现有 scoped `POST .../schema/preparations` 仍是唯一 Draft 写入口；
它增加一个与旧 Schema release request 严格互斥的 `entity_page_manifest` 变体。服务端必须
解析并完整重放 G1 manifest，只从 manifest 的 76 个结构化 member 派生
`WikiReleaseMemberSnapshot`，所有 `Content` 必须为空；不得接受调用方另传 members、
Markdown 或 review hash。`ManifestDigest` 对 G1 必须使用 manifest 内已验证的 canonical
`manifest_sha256`，而不是数据库 JSON 字节的普通 SHA。

M1 的真实 vector 是 815 已激活 Candidate 的页面投影：服务端必须先用现有 pinned Schema
custody 重放 `release-42a3dd0c-ec76-4017-a288-37f1b13519a0@epoch2`，再从该唯一来源
派生既有 `ready_receipt_digest` 与 `review_policy_id` 后创建 Draft。调用方不得选择或覆盖
这两个值。M1 不激活该 projection，也不把旧 75-member Release 改写成 76 members。

Candidate 页面只通过现有 preparation authority 读取：增加一个按
`wiki_kb_id + preparation_id` 解析 immutable scope、且不依赖 Head 的 human-admin bootstrap，
以及同一 scoped preparation 下的 overview/section/field/free-wiki read。用户稳定实体路由
保持不变，使用严格单值 `preparation_id` query 标识 Candidate Preview；它与
`release_id` 互斥，空白、重复、别名或同时出现全部在 transport 前 fail closed。

M1 source click 不允许前端把 `citation_<64hex>` 截断后直接当 authority。冻结 vector 的
17 个 join receipt 与 `citation-<first24>` 映射是 17/17 唯一，且全部
`source_release_id` 都绑定上述 815 epoch2 Release；但服务器仍必须先从 G1 preparation
定位完整 citation，重放当前旧 815 Schema release 的 field/citation/join/source custody，
逐字段核对 revision、PDF page、bbox、quote 与 receipt 后，才能复用既有 opaque-token
source viewer。M1 激活前旧 815 Release 仍是唯一 current，因此此桥只关闭 M1 Preview；
successor 激活后的 historical-source bridge 留在 M3，不得在 M1 冒充已完成。

## Owner matrix

总控是唯一 integration/commit/push/PR/merge Owner。默认只有一个可写 lane。

### G1-Win1 · Harness and shared contract

- `harness/src/insurance_harness/knowledge_compiler/entity_page_graph_830_g1.py`；
- `harness/tests/test_entity_page_graph_830_g1.py`；
- `harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json`。

Win1 除上述三个 exact path 外无任何写域；不得修改现有 Harness contract/compiler 文件。
如上述单文件实现无法闭合，必须停下向总控请求改写域，不得自行扩展。外部对象写域为
`∅`；只读输入仅为 `actual-input-authority.json` 指定的 C5 bundle 四个文件、B0 回执和
`medical-presentation-profile.v1.json`。Win1 不 commit、不合并、不写数据库、不启动服务。

### G1-Win2 · WeKnora/frontend（共享合同冻结后才可启用）

- `internal/types/entity_page_graph_830_g1.go`；
- `internal/types/entity_page_graph_830_g1_test.go`；
- `internal/application/service/entity_page_graph_830_g1.go`；
- `internal/application/service/entity_page_graph_830_g1_test.go`；
- `internal/handler/entity_page_graph_830_g1.go`；
- `internal/handler/entity_page_graph_830_g1_test.go`；
- `internal/router/routes_schema_wiki.go`；
- `internal/router/routes_schema_wiki_test.go`；
- `frontend/src/router/index.ts`；
- `frontend/src/views/knowledge/KnowledgeBase.vue`；
- `frontend/src/api/schema-wiki/entityPageGraph830G1.ts`；
- `frontend/src/api/schema-wiki/entityPageGraph830G1.spec.ts`；
- `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.vue`；
- `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts`；
- `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts`；
- `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.test.ts`；
- `internal/application/repository/wiki_release.go`；
- `internal/application/repository/wiki_release_scope_test.go`；
- `internal/application/service/wiki_release.go`；
- `internal/application/service/schema_wiki.go`；
- `internal/application/service/schema_wiki_test.go`；
- `internal/application/service/schema_wiki_citation_content.go`；
- `internal/application/service/schema_wiki_citation_content_test.go`；
- `internal/application/service/schema_wiki_citation_revision_test.go`；
- `internal/handler/schema_wiki.go`；
- `internal/handler/schema_wiki_test.go`；
- 不改 migration、数据库表或第二发布器。允许修改上列既有通用 Wiki 文件，但只能增加
  与旧 Schema request 严格互斥的 G1 variant、Head-independent preparation read 与
  server-verified source bridge；不得改变旧 Schema contract、旧 route 或旧 lifecycle 语义。

外部对象写域为 `∅`。Win2 仅在 Win1 contract vector 被总控冻结、上述路径与 Win1 完全
互斥且并行直接推进同一个 M1 Preview 时创建；否则维持单写窗口。Win2 不 commit、不
合并、不启动生产或修改 `8081`。任何额外路径必须先由总控修改本矩阵并重新复核。

本次扩域只允许把冻结的 G1 manifest 接入现有 repository/service/handler 生命周期、
增加 Head-independent preparation scope/read，以及复用既有 source authority；不得改变
generic Schema release 的旧合同、不得新增 release 表或 endpoint 级第二审核/发布语义。

### G1-Review · read only

`WRITE_DOMAINS=∅`。只按冻结 commit/tree/manifest 复核，不修改任何文件或外部对象。

治理文件、OpenSpec、共享 contract、Evidence Pack 和所有集成动作只由总控写。

## Milestones and validation

- M0（D0）：治理指针、唯一 OpenSpec、Owner/RED、冻结输入和计划；无 Docker；
- M1（D1）：真实 815 Candidate Preview 可见 overview、1 section、3 field pages、空
  free_wiki、稳定 URL、短标题及至少 1 个 exact source click；
- M2（D1）：76/76 manifest、67/67 三态、稳定 identity、非 7 renderer 测试；
- M3（D2→D3）：原 D2 的 app/frontend 各一次构建及 exact digest 保留为不可变历史证据。
  D3 前静态复核发现 successor serving/source identity 与 historical-source bridge blocker；
  随后的实施计划映射又证明原 frontend parser 会把冻结 source identity 错当 serving
  identity，无法读取合法 successor。用户已明确对本次 G1 全面授权且不再逐项询问；因此
  app/frontend 各只允许一次 replacement build，原镜像与回执均不覆盖、不改标签。D3 使用
  两个 replacement exact digest，在隔离环境形成一个
  `NOT_FOR_PRODUCTION` Release；current/pinned/source-click 通过，生产 `8081` 和原生产
  Active 不变。

验证矩阵必须逐项记录 `Requirement → RED → Implementation → Focused Test → Commit →
Live Evidence → Status`。环境未启动、依赖缺失、fixture 或接口未调用不得冒充 RED/live。

以下为方案冻结时的历史 M1 `NEXT_PHYSICAL_RESULT`（现已完成）：在
`2026-09-02 23:42:03 +08:00` 前，
真实 815 Candidate 的 WeKnora Preview 可打开 overview、
`application-and-contract` section、`insured_eligibility`（present）、
`guaranteed_renewal_period`（absent_explicitly）、`cooling_off_period`（unknown）三个
独立字段页和空 `free_wiki`，并满足稳定 URL、短标题/完整 namespace 与至少一个 exact
source click。当前 M3 的唯一 NEXT 以 validation report 为准；规格复核通过前固定为
`SPEC_REVIEW_PASS_THEN_TDD_RED`，不得提前实现、构建或宣称 D3。

## STOP and non-goals

发现第二 Wiki/审核/Active/事实库、Harness 直读 WeKnora DB、逐页激活、可变标题路由、
Markdown 权威、需要新服务/新表/图数据库、共享 ConceptDefinition、11-pack Catalog、
模型调用、质量优化、生产 `8081` 变更、第二层前置或同一阻断一次纠偏后仍失败，立即
`G1=STOPPED` 并返回用户。G1 PASS 后仍不启动 G2。

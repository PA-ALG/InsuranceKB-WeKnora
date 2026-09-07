# G3 验证矩阵

G3=WIP，FLOW=NOT RUN，QUALITY=DEFERRED_TO_Q0，NOT_FOR_PRODUCTION。以下为当前切片事实，软件通过不代表真实业务验收完成。

| Requirement | 实现 | 验证/证据 | commit | 状态 |
|---|---|---|---|---|
| G3-R1 软件 | schema_pack_catalog_830_g3.py；真实11包801字段 | catalog-a-independent-review.json；catalog-root-integration-verification.json，17 checks PASS，原值/hash独立复算 | f91fc40；精确文件SHA在证据内 | PASS |
| G3-R2 软件 | G1 Profile复用，可变节点与精确主映射 | 11包节点7/7/7/8/7/8/8/8/7/8/7；整包profile-review.md | f91fc40 | PASS |
| G3-R2 人工 | 用户回复“结构确认”，保存 exact Catalog绑定 | profile-user-confirmation.json；姓名与人工待办负责人未提供 | f91fc40 | NOT RUN（具名元数据未齐） |
| G3-R3 目录软件 | protected Go GET＋Vue通用目录 | 独立复核BLOCKER0；总控Go、17前端checks及类型检查通过 | f91fc40 | PASS |
| G3-R3 实际目录/字段/来源 | 目录代码完成，真实多pack链待接 | 本地页面/隔离Release/来源/检索未执行 | 无 | NOT RUN |
| G3-R4 来源准备 | corpus-files-v4.json选15原始PDF；15个实际native输出已保留 | native-capture-inventory-v2.json、existing-native-preservation.json、native-02-supplement-result.json；02 standalone capture PASS，当前source row仍缺；原扫描页失败回执保留，4已有W1 revisions/287 chunks实际重开；native来源custody仍待核验 | f91fc40 | PASS（准备层） |
| G3-R4 批次软件 | C设计2及修订7/8兼容切片通过；新旧来源回执接线闭合 | batch-c-design2-final-verification.json；独立56/root A+C73、ruff/strict mypy PASS；历史原日志保留 | 5efe84b5a；exact source/test SHA见receipt；新多行复现另存 | PASS（软件；真实批次NOT RUN） |
| G3-R4 真实批次 | actual SourceRevision/Policy/Seed/model结果尚未冻结 | provider HTTP=0；source-runtime-isolation-plan.md及11 request guard独立复审完成，未运行 | 无 | NOT RUN |
| G3-R5 完整卡 | 未发布/未质量准入 | 真实批次、字段页、来源与搜索均未执行 | 无 | NOT RUN |

## DELIVERY 六维

| 维度 | 状态 | 证据与边界 |
|---|---|---|
| software | PASS（A/B）；PASS（A/B/C）；PASS（D Python完整候选）；NOT RUN（Go完整镜像） | catalog-root-integration-verification.json；C design2独立复核通过；修订7 C/common独立81项及正文/身份probe PASS；来源回执兼容8独立79/common82与root99 PASS；D Python actual134/342及2,254,490-byte容量独立PASS；Go镜像尚未闭合 |
| container health | NOT RUN（G3） | existing G2 docreader进程已只读核实用于解析预检，不是G3应用验收 |
| provider probe | NOT RUN | 产品provider HTTP=0 |
| provisioning | NOT RUN | 新DB/上传/SourceRevision/backfill=0 |
| local live | NOT RUN | G3实际页面/流程尚未观察 |
| GitHub live | NOT RUN | 尚未push/PR/远端CI |

结构确认已接受，不再索要重复批准；具名元数据尚未提供，不由程序代签。所有原始质量分数与失败回执保留。

来源隔离执行准备：v3脚本独立复核 BLOCKER0/BACKLOG1，10项假环境测试通过；第三次本机只读preflight PASS，exact回执 `source-runtime-v3-actual-preflight-03.json`。apply/provider/upload仍NOT RUN，前两次失败回执不覆盖。

C/D真实正文接缝：`cd-multiline-canonical-reproduction.log` 保存actual base27多行值及C多行hash失败。未改写源文本；修订7v2设计与C/common代码复核均PASS，见`cd-multiline-code-independent-review.json`；D完整fixture仍待实现。完整C source receipt还需解决当前W1 source registration与历史C5 admission字段的接缝，不以占位hash补齐（见`c-source-wiring-inventory-01.md`）。

修订7代码已在 `de38eb252979713415d8fa34946084f7f344cbc0` 冻结，root独立81项通过及完整正文/嵌套身份probe通过，精确文件与原始日志见 `cd-multiline-code-independent-review.json`。修订8设计 `0b2e9241…` 经独立复核BLOCKER0，已先冻结OpenSpec和C-only写域后进入实现，当前源码尚未闭合；见 `c-source-registration-design-independent-review.json` 与 `c-source-registration-dispatch.json`。

修订8最终独立BLOCKER0，C79/common82、root A/C/common99通过；代码身份见 `c-source-registration-independent-review.json`。原C写域关闭，D按既有v2合同及修订7/8恢复五文件域，完整342/8MiB与Python-Go一致性仍NOT RUN，不开放handler/service/UI。上传v1独立7类BLOCKER，首轮集中修复中，原stub RED明确仅为脚手架时序证据。

D Python首审BLOCKED（3项）：原11/root110 bounded PASS与完整342/2,247,500-byte容量PASS保留；新增重算hash攻击证明身份anchors、确认语义、同SourceBlock身份内容闭包遗漏。见lane-d-python-independent-review-01.json；首轮修复lane-d-python-repair-1.md先冻结，Go暂停未GREEN，handler/service/UI仍关闭。来源upload v2独立复核BLOCKER0（33 tests/9 probes），执行包复核PASS，用户外发批准待回复；无apply/upload/provider。

D Python repair1原B1/B2/B3独立PASS（24tests/8probes，ruff/mypy），root4额外重哈希攻击PASS。新同域source coverage阻断：身份块外的selected材料字段正文被请求拒绝。已回设计2，明确request精确selected+carry并集与per-owner selected+owncarry+实际关联concept来源；独立设计0/0后派第二次/最后D Python修复，Go继续冻结。旧code/fixture gzip快照和原始失败日志保留；active page envelope复用澄清独立PASS，仅设计，无部署。

D source coverage第二次最终复审PASS：30 tests in97.68s，ruff/strict mypy及独立精确source并集/owner引用探针通过，BLOCKER0/BACKLOG0。source e8e0dbcd…、test86edf3d9…、candidate e7be83db…、POST09b64b3e…（2,254,490bytes），freeze811eb4d0…。root独立actual G2 134字段/27来源/3 raw/canonical/容量核对PASS。报告lane-d-source-coverage2-independent-review.json SHA0b21ea94…；Python两轮修复关闭，Go两文件恢复，handler/service/UI门禁不变；全部fixture为synthetic protocol，真实批次、provider、DB、部署均NOT RUN。

D下游执行计划及待审对齐展示设计完成独立复审（初审2项已修，终审BLOCKER0/BACKLOG0），exact冻结见lane-d-downstream-design-freeze-1.json。已明确Create前source验证、G3-only create-draft operation和授权历史snapshot派生两行展示；不增加DTO或公开KB元数据。Go完整C重算仍有有效RED，当前实现未闭合，下游写域仍关闭；实际C/profile执行方案仅只读候选，未派新生产实现。

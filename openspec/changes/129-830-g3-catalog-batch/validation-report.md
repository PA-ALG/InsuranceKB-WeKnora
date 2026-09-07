# G3 验证矩阵

G3=WIP，FLOW=NOT RUN，QUALITY=DEFERRED_TO_Q0，NOT_FOR_PRODUCTION。以下为当前切片事实，软件通过不代表真实业务验收完成。

| Requirement | 实现 | 验证/证据 | commit | 状态 |
|---|---|---|---|---|
| G3-R1 软件 | schema_pack_catalog_830_g3.py；真实11包801字段 | catalog-a-independent-review.json；catalog-root-integration-verification.json，17 checks PASS，原值/hash独立复算 | 尚未提交，精确文件SHA在证据内 | PASS |
| G3-R2 软件 | G1 Profile复用，可变节点与精确主映射 | 11包节点7/7/7/8/7/8/8/8/7/8/7；整包profile-review.md | 尚未提交 | PASS |
| G3-R2 人工 | 用户回复“结构确认”，保存 exact Catalog绑定 | profile-user-confirmation.json；姓名与人工待办负责人未提供 | 尚未提交 | NOT RUN（具名元数据未齐） |
| G3-R3 目录软件 | protected Go GET＋Vue通用目录 | 独立复核BLOCKER0；总控Go、17前端checks及类型检查通过 | 尚未提交 | PASS |
| G3-R3 实际目录/字段/来源 | 目录代码完成，真实多pack链待接 | 本地页面/隔离Release/来源/检索未执行 | 无 | NOT RUN |
| G3-R4 来源准备 | corpus-files-v4.json选15原始PDF；11个native输出已保留 | native-capture-inventory.json；原扫描页失败回执保留，4已有W1 revisions/287 chunks实际重开；native来源custody仍待核验 | 尚未提交 | PASS（准备层） |
| G3-R4 批次软件/真实效果 | C独立复核7项BLOCKER；一轮集中修复中 | batch-c-owner-verification.json；原4fail/11pass日志已恢复；本轮修复前15fail/21pass RED已保存 | 尚未提交 | BLOCKED（修复复核未闭合） |
| G3-R5 完整卡 | 未发布/未质量准入 | 真实批次、字段页、来源与搜索均未执行 | 无 | NOT RUN |

## DELIVERY 六维

| 维度 | 状态 | 证据与边界 |
|---|---|---|
| software | PASS（仅A/B目录切片） | catalog-root-integration-verification.json；C及后续不含在此PASS内 |
| container health | NOT RUN（G3） | existing G2 docreader进程已只读核实用于解析预检，不是G3应用验收 |
| provider probe | NOT RUN | 产品provider HTTP=0 |
| provisioning | NOT RUN | 新DB/上传/SourceRevision/backfill=0 |
| local live | NOT RUN | G3实际页面/流程尚未观察 |
| GitHub live | NOT RUN | 尚未push/PR/远端CI |

结构确认已接受，不再索要重复批准；具名元数据尚未提供，不由程序代签。所有原始质量分数与失败回执保留。

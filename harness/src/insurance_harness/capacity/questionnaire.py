"""CAP0 八项上线容量问卷生成器（OpenSpec 036 CAP0.10，D-2026-07-26-1）：确定性
生成中文问卷 markdown；唯一写 I/O 面是 write_launch_questionnaire。槽位标注
合同字段路径，回收后可无歧义机器录入 CapacityProfileV1。"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# 行格式：`# 节标题|驱动说明`；`> 节备注`；`字段路径|说明|示例|预填`（预填可空）。
_SECTIONS_DATA: Final[str] = """\
# 一、Space 与 Source 规模（`space_sources`）|P2a Space/Source 表和索引合同的行数与隔离预算。
space_sources.space_count|上线 Space 数|3|
space_sources.active_sources_per_space|每 Space 活跃 Source 数（按最大 Space 口径）|1000|
space_sources.retained_sources_per_space|每 Space 保留（含历史）Source 数|1500|
space_sources.peak_source_revisions_per_day_per_space|每 Space 每日 SourceRevision 峰值|50|
# 二、文档形态（`document_shape`）|chunk/record 表规模与解析、抽取微批（P4b）参数。
> 已申报（2026-07-27 口头）：语料为 PDF/PPT 混合，请按混合口径申报字节与 chunk 分布。
document_shape.avg_document_bytes|文档平均字节|2000000|
document_shape.p95_document_bytes|文档 P95 字节（≥ 平均）|10000000|
document_shape.avg_chunks_per_document|每文档平均 chunk/record 数（十进制字符串）|"100"|
document_shape.p95_chunks_per_document|每文档 P95 chunk/record 数（≥ 平均）|"400"|
# 三、SourceRevision 放大率（`revision_amplification`）|P5a2 断言表增长与索引预算。
revision_amplification.claims_per_source_revision|每 SourceRevision 产出 Claim 放大率|"18.5"|
revision_amplification.relations_per_source_revision|Relation 放大率|"6"|
revision_amplification.provenance_anchors_per_source_revision|ProvenanceAnchor 放大率|"24.5"|
# 四、EvidenceFragment 上限（`evidence_fragment_limits`）|行内 inline 上限与外置阈值（033 §5.1）。
evidence_fragment_limits.max_logical_bytes_per_fragment|单 EvidenceFragment 逻辑字节上限|262144|
evidence_fragment_limits.max_postgres_inline_bytes_per_fragment|inline 上限（≤逻辑上限）|16384|
# 五、Release 与保留窗口（`release_retention`）|Release/Page/Block 表规模与保留清理策略。
release_retention.retained_release_count|保留的历史 Release 数|24|
release_retention.pages_per_release|每 Release 页面数|300|
release_retention.blocks_per_page|每页面 Block 数|40|
release_retention.release_retention_days|历史 Release 保留窗口（天）|365|
release_retention.artifact_retention_days|artifact 保留窗口（天）|180|
# 六、Candidate 与审核（`candidate_review`）|P6b Candidate 分片、manifest 与审核 SLO 预算。
candidate_review.changed_claims_per_candidate|每 Candidate changed Claim 数|400|
candidate_review.changed_pages_per_candidate|每 Candidate changed Page 数|60|
candidate_review.changed_bytes_per_candidate|每 Candidate changed 字节|3000000|
candidate_review.max_manifest_bytes|单 Candidate manifest 总字节上限|8000000|
candidate_review.review_queue_slo_hours|审核队列时长 SLO（小时）|48|
# 七、Active Query（`active_query`）|P9a SQL 下推分页与返回大小、延迟预算。
active_query.sustained_qps|持续 QPS（十进制字符串）|"2.5"|
active_query.burst_qps|突发 QPS（≥ 持续）|"10"|
active_query.p95_response_bytes|P95 返回大小（字节）|65536|
active_query.p95_latency_ms|P95 延迟目标（毫秒）|800|
# 八、Worker 与 provider（`worker_provider`）|Worker/provider 并发、队列积压与恢复 SLA。
worker_provider.worker_concurrency|Worker 并发|4|
worker_provider.provider_concurrency|模型 provider 并发|2|
worker_provider.max_queue_backlog|最大队列积压|500|
worker_provider.recovery_sla_hours|积压恢复 SLA（小时）|4|
# 九、存量回填（`stock_backfill`，2026-07-27 裁决）|上线初期批量导入的微批与审核吞吐规划（P4b）。
> 已申报（2026-07-27 口头）：数千份文档（PDF/PPT 混合）+ 几十万文本片段（FAQ/chunk 等）。
> 整理为：文档约 3000（区间 1000–5000）；文本片段约 300000（区间 100000–500000）。
> 预填仅为该申报的整理，请业务方确认或修正区间。
> 示算（用已申报数）：窗口 60 天 × 审核吞吐 60 篇/日 = 3600 ≥ 3000 份文档，计划可行。
> document_count>0 须满足 吞吐×窗口 ≥ document_count，否则以不可行计划拒绝（=无工作负载假设）。
stock_backfill.document_count|存量文档总数（零回填显式填 0）|3000|已申报约 3000，见上注区间
stock_backfill.total_text_fragments|存量文本片段总数（FAQ/chunk 等）|300000|已申报约 300000
stock_backfill.total_bytes|存量文档总字节|6000000000|
stock_backfill.target_completion_window_days|目标完成窗口（天）|60|
stock_backfill.review_throughput_docs_per_day|审核吞吐假设（篇/日）|60|
"""

_HEADER: Final[str] = """\
# CAP0 上线容量问卷（八项 + 存量回填）

> 依据 033 §5.1、23 号控制板 §8 D-2026-07-26-1 与 2026-07-27 裁决（`stock_backfill`）。
> 本问卷向业务方回收**首个上线环境**真实规模申报，是 CAP0 显式交付物，须在 C0/W0 窗口期内回收。
>
> - 申报（`source_kind=declared`）即满足 P2a/P2b 表和索引合同的放行前置；
>   P15 生产切换前必须以实测（`source_kind=measured`）验证 `launch` 档；
> - 未回收真实输入时 Profile 状态为 `INSUFFICIENT_CAPACITY_EVIDENCE`，P2a/P2b 不放行；
> - 不得以"100 万 Claim""固定 10x"等无工作负载假设代填（033 §5.1）。

## 填写说明

- 计数/字节/时长填非负整数；比率与 QPS 写成十进制字符串（如 `"3.5"`），不要写二进制浮点；
- 示例列数值仅为示意，**不是产品上限，也不是默认值**；请以贵方真实环境为准；
- 每格必填；真实为零请显式填 `0`，留空视为未申报；已带预填的格子只需确认或修正；
- 某 Space 负载明显偏离部署级申报时，在末尾附注区按 Space 覆盖对应维度（`space_overrides`）。

## 申报头

| 合同字段 | 说明 | 填写 |
|---|---|---|
| `deployment_id` | 首个上线部署标识（小写 `a-z0-9._-`） | |
| `applicable_release_profile` | 适用发布画像名 | |
| 发布画像是否声明客户增长承诺 | 是则须另附 `contracted_forecast` 档 | 是 / 否 |
| `source_kind` | 本轮为申报 | `declared` |
| `measured_at` | 申报口径时间（含时区，如 `2026-07-27T12:00:00+08:00`） | |
| `source_ref` | 申报人/部门与依据材料 | |
"""

_FOOTER: Final[str] = """\
## 回收与冻结

- 回收后由总控窗口录入 `CapacityProfileV1` 并冻结为 `profile_version=1`，以 C0
  `canonical_hash(object_type="capacity-profile")` 计算内容 hash；冻结后的任何
  修改都必须铸造新 `profile_version` 与新 hash，不改写历史版本；
- 附注区（可选）：按 Space 覆盖的维度、PDF/PPT 之外的格式说明、其他容量约束。
"""

_TABLE_HEAD: Final[str] = "\n| 合同字段 | 说明 | 示例（仅示意） | 填写 |\n|---|---|---|---|\n"


# 确定性生成 CAP0 八项 + 存量回填中文问卷 markdown。
def generate_launch_questionnaire() -> str:
    parts: list[str] = [_HEADER]
    pending_head = False
    for line in _SECTIONS_DATA.splitlines():
        if line.startswith("# "):
            heading, drives = line[2:].split("|", 1)
            parts.append(f"\n## {heading}\n\n驱动：{drives}\n")
            pending_head = True
        elif line.startswith("> "):
            parts.append(f"\n{line}\n")
        else:
            path, label, example, prefill = line.split("|", 3)
            if pending_head:
                parts.append(_TABLE_HEAD)
                pending_head = False
            parts.append(f"| `{path}` | {label} | {example} | {prefill} |\n")
    parts.append("\n" + _FOOTER)
    return "".join(parts)


# 把 generator 输出原样写入 target 并返回该路径。
def write_launch_questionnaire(target: Path) -> Path:
    target.write_text(generate_launch_questionnaire(), encoding="utf-8")
    return target

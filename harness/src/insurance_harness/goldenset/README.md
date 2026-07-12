# goldenset — 金标注 Agent 与评估子系统

独立可持续维护的子系统（change 002 / S0）；实现零依赖 compiler，仅共享 `schemas` 注册表。设计文档：[docs/insurance-kb/05-golden-set-eval.md](../../../../docs/insurance-kb/05-golden-set-eval.md)。

## 组成

| 模块 | 职责 |
|---|---|
| `pdf.py` | PDF → 带页码文本（直读原文档，不走 chunk；疑似扫描件报错） |
| `annotator.py` | 标注 Agent：字段分批 prompt、三态输出、对抗性 JSON 解析；ModelClient 协议（LiteLLM / Replay） |
| `verify.py` | 自检：引文回原文回验、product_meta.json 比对；失败标 disputed |
| `runner.py` | 产品级编排：险种推断、断点续跑缓存（`dataset/goldenset/.cache/`） |
| `release.py` | 不可变金标 release（per-product JSONL + manifest + disputed 清单） |
| `eval.py` | eval runner CLI：字段级 P/R/F1、三态混淆矩阵、幻觉率、证据准确率、五类错误归因工单、markdown 报告；`--metric v1|v2` 口径切换（005） |
| `keypoints.py` | long 字段要点清单（金标旁挂 `keypoints.jsonl`）：规则切分、覆盖判定、eval-judge-queue 行格式（005 V1/V2/V4） |

## 用法

```bash
# 评估（金标 vs 抽取结果）；--metric v2 = long 字段关键要点匹配（要点缺省读金标目录）
uv run python -m insurance_harness.goldenset.eval \
  --golden ../dataset/goldenset/gs-v0.1 --pred pred.jsonl --report report.md \
  --metric v2 [--keypoints <keypoints.jsonl|目录>] [--judge-queue eval-judge-queue.jsonl] \
  --schema-dir ../docs/insurance-kb/schema-baseline --dataset-root ../dataset/shouxian_product
```

真实模型标注需 `uv sync --extra llm` 并配置 `HARNESS_GOLDENSET_MODEL/_API_BASE/_API_KEY`。

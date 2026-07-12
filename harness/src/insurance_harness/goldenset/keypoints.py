"""金标要点清单（005 spec V1/V2/V4）：long 型字段的"关键要点匹配"计分数据与判定。

机制先行（005 proposal §A1）：
- 要点清单是金标数据旁挂的独立文件 ``keypoints.jsonl``（release 顶层或 wip 产品目录内）；
- 首版要点由确定性规则从金标 value 切分（V1.3，零模型调用）；全量强模型要点生成
  列 HANDOFF 遗留 B 类；
- 覆盖判定纯确定性（归一化子串 / 字符 bigram 覆盖比例），要点召回 ≥80% 且无矛盾
  要点 = 值正确（V2.3）；不确定带样本可落 eval-judge-queue（V4，默认关）。
"""

import hashlib
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .normalize import normalize_text

#: 要点召回阈值：覆盖率 ≥ 该值且无矛盾要点 → 值正确（V2.3）
KEYPOINT_MATCH_THRESHOLD = 0.8
#: 不确定带下限：覆盖率 ∈ [该值, 阈值) 的判错样本视为待裁决（V4.1）
JUDGE_UNCERTAIN_LOW = 0.5
#: 单个要点的 bigram 覆盖比例判命中的阈值（表述差异容忍，V2.2）
_BIGRAM_COVER_THRESHOLD = 0.8
#: 归一化后长度低于该值的碎片不算要点（V1.3）
_MIN_KEYPOINT_CHARS = 4

RULE_SPLIT_SOURCE = "rule-split-v1"
KEYPOINTS_FILENAME = "keypoints.jsonl"

# 切分符：分号/句号/换行 + 序号（"1." "（一）" "①"；小数如 "3.3" 不切）
_SPLIT_RE = re.compile(
    r"[；;。\n]"
    r"|(?<![0-9.])[0-9]{1,2}[.、．](?![0-9])"
    r"|[（(][一二三四五六七八九十][)）]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]"
)
_ENUM_PREFIX_RE = re.compile(r"^\s*(?:[0-9]{1,2}[.、．]|[（(][一二三四五六七八九十][)）])\s*")


class KeypointEntry(BaseModel):
    """一个 (product, field) 的要点清单行（keypoints.jsonl 行格式，V1.1）。"""

    product_id: str
    field_id: str
    keypoints: list[str]
    contradictions: list[str] = Field(default_factory=list)
    source: str = RULE_SPLIT_SOURCE
    golden_value_sha: str = ""  # value_sha(金标值)；不符则条目过期回落 v1（V2.5）


class KeypointScore(BaseModel):
    """要点计分结果：主判定二值化，覆盖率作 partial 展示（V2.3/V2.6）。"""

    total: int
    covered: int
    contradicted: bool = False
    missing: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.covered / self.total if self.total else 0.0

    @property
    def matched(self) -> bool:
        return (
            self.total > 0
            and self.coverage >= KEYPOINT_MATCH_THRESHOLD
            and not self.contradicted
        )

    @property
    def uncertain(self) -> bool:
        """不确定带（V4.1）：判错但覆盖率落在 [0.5, 0.8)——值得裁决的边缘样本。"""
        return (
            not self.matched
            and not self.contradicted
            and JUDGE_UNCERTAIN_LOW <= self.coverage < KEYPOINT_MATCH_THRESHOLD
        )


def value_sha(value: str | None) -> str:
    """金标值归一化指纹（12 位）：金标改值后检测要点条目漂移（V2.5）。"""
    return hashlib.sha256(normalize_text(value or "").encode("utf-8")).hexdigest()[:12]


def split_keypoints(value: str) -> list[str]:
    """确定性规则切分要点（V1.3）：分号/句号/换行/序号；去枚举前缀、去短碎片、去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for frag in _SPLIT_RE.split(value):
        if not frag:
            continue
        frag = _ENUM_PREFIX_RE.sub("", frag.strip())
        norm = normalize_text(frag)
        if len(norm) < _MIN_KEYPOINT_CHARS or norm in seen:
            continue
        seen.add(norm)
        out.append(frag)
    return out


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def keypoint_covered(keypoint: str, pred_value: str) -> bool:
    """单要点覆盖判定（V2.2）：归一化子串命中，或 bigram 覆盖比例 ≥0.8。"""
    k = normalize_text(keypoint)
    p = normalize_text(pred_value)
    if not k:
        return True
    if k in p:
        return True
    kb = _bigrams(k)
    if not kb:  # 单字符要点：只认子串
        return False
    return len(kb & _bigrams(p)) / len(kb) >= _BIGRAM_COVER_THRESHOLD


def score_keypoints(pred_value: str, entry: KeypointEntry) -> KeypointScore:
    """预测值 vs 要点清单：覆盖率 + 矛盾要点一票否决（V2.3/V2.4）。"""
    missing = [kp for kp in entry.keypoints if not keypoint_covered(kp, pred_value)]
    pred_norm = normalize_text(pred_value)
    contradicted = any(
        normalize_text(c) and normalize_text(c) in pred_norm for c in entry.contradictions
    )
    return KeypointScore(
        total=len(entry.keypoints),
        covered=len(entry.keypoints) - len(missing),
        contradicted=contradicted,
        missing=missing,
    )


def write_keypoints(entries: list[KeypointEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(e.model_dump_json() + "\n" for e in entries), encoding="utf-8"
    )


def load_keypoints(root: Path) -> dict[tuple[str, str], KeypointEntry]:
    """读要点清单：接受单个 keypoints.jsonl，或递归收集目录下全部同名文件（V1.1）。

    release 布局（``<release>/keypoints.jsonl``）与 wip 布局
    （``wip-gs-v0.1/<产品>/keypoints.jsonl``）都命中。
    """
    paths = [root] if root.is_file() else sorted(root.rglob(KEYPOINTS_FILENAME))
    entries: dict[tuple[str, str], KeypointEntry] = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = KeypointEntry.model_validate_json(line)
            entries[(e.product_id, e.field_id)] = e
    return entries


class EvalJudgeRequest(BaseModel):
    """eval-judge-queue 行格式（V4.2）。

    字段集合与 ``compiler.models.JudgeRequest`` 对齐（测试断言一致），复用
    claude-session 批处理形态；裁决回写沿用 ``compiler.models.Judgement`` 行格式。
    goldenset 不 import compiler 实现——05 §1.1 零依赖边界，故此处结构性对齐而非共享代码。
    """

    product_id: str
    product_name: str
    doc: str
    field_id: str
    field_name: str
    reason: str = "keypoint_uncertain"
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    context_excerpt: str = ""


def write_eval_judge_queue(path: Path, queue: list[EvalJudgeRequest]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(r.model_dump_json() + "\n" for r in queue), encoding="utf-8"
    )

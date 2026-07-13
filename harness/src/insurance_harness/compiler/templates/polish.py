"""模板 LLM 润色接口 stub（006 T5；spec F2.5；claude-session 队列形态，零模型调用）。

对齐 compiler 裁决通道形态（04 §judge-queue → 主会话批处理 → 回写）：
归纳器产出草案后，not_anchorable 字段与草案 YAML 落 polish-queue.jsonl，
由主会话 Claude（或后续网关强模型）润色/补锚点后回写；本 change 只落盘不调用。
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .induce import InductionResult
from .loader import dump_template_yaml, parse_template
from .models import ExtractionTemplate


class PolishRequest(BaseModel):
    """polish-queue.jsonl 行格式（claude-session 批处理输入）。"""

    template_id: str
    family_id: str
    doc: str
    draft_yaml: str
    not_anchorable: list[str] = Field(default_factory=list)  # field_id 清单
    note: str = "请审核锚点并为 not_anchorable 字段补充锚点或确认降级通用管道"


def write_polish_queue(path: Path, result: InductionResult) -> Path:
    """归纳结果 → 润色队列落盘（F2.5；不做任何模型调用）。"""
    req = PolishRequest(
        template_id=result.template.template_id,
        family_id=result.template.family_id,
        doc=result.template.doc,
        draft_yaml=dump_template_yaml(result.template),
        not_anchorable=[r.field_id for r in result.report if not r.published],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(req.model_dump_json() + "\n", encoding="utf-8")
    return path


def apply_polish(result: InductionResult, polished_path: Path | None) -> ExtractionTemplate:
    """润色回写：读主会话产出的模板 YAML；无回写文件 → 草案原样返回（F2.5 stub）。"""
    if polished_path is None or not polished_path.exists():
        return result.template
    data = yaml.safe_load(polished_path.read_text(encoding="utf-8"))
    return parse_template(data, polished_path.name)

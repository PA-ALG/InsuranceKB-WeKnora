"""对抗性 LLM 输出解析（004 T1；思想借鉴上游 llm_wiki parseFileBlocks，Python 重写）。

自 002 goldenset/annotator.py 提升为公共模块：金标注与抽取管道共用（spec E3.1）。
"""

import json
import re
from typing import Any, cast


def extract_json_array(raw: str) -> list[dict[str, Any]] | None:
    """容错提取模型输出中的 JSON 数组：剥代码围栏、取首个 '[' 到配对 ']'。"""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    data = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                if isinstance(data, list) and all(isinstance(x, dict) for x in data):
                    return cast(list[dict[str, Any]], data)
                return None
    return None

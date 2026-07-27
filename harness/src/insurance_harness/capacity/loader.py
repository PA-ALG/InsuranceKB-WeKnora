"""CapacityProfile fail-closed 装载（OpenSpec 036 CAP0.9）：唯一读 I/O 面；
非法输入以 typed CapacityContractError 拒绝，不产生部分 Profile、不以默认值补缺。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import yaml
from pydantic import ValidationError

from .models import CapacityProfileV1

CAPACITY_CONTRACT_REASON_CODES: Final[frozenset[str]] = frozenset({
    "profile_file_not_found", "profile_file_unreadable", "unsupported_profile_format",
    "profile_parse_error", "profile_root_not_mapping", "invalid_profile",
})


# 非法 profile 输入的确定性拒绝；reason 为冻结的 reason code。
class CapacityContractError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        if reason not in CAPACITY_CONTRACT_REASON_CODES:
            raise RuntimeError(f"unknown capacity reason code: {reason}")
        super().__init__(f"{reason}: {message}")
        self.reason = reason


# 从 .yaml/.yml/.json 文件装载并 fail-closed 校验 CapacityProfile。
def load_capacity_profile(path: Path) -> CapacityProfileV1:
    suffix = path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise CapacityContractError("unsupported_profile_format", f"只受理 yaml/yml/json：{path}")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CapacityContractError("profile_file_not_found", str(path)) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CapacityContractError("profile_file_unreadable", f"{path}: {exc}") from exc
    try:
        raw: object = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise CapacityContractError("profile_parse_error", f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CapacityContractError("profile_root_not_mapping", f"{path} 根节点必须是 mapping")
    try:
        return CapacityProfileV1.model_validate(raw)
    except ValidationError as exc:
        raise CapacityContractError("invalid_profile", str(exc)) from exc

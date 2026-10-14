"""Stage-configured completions, attempt accounting and typed failure boundaries."""

from .config import StageModelConfig, load_stage_config
from .errors import (
    InputTooLarge,
    ModelBudgetExceeded,
    ModelCallError,
    ModelConfigError,
    ModelHTTPError,
    ModelUnavailable,
    TruncatedCompletion,
)
from .ledger import CallLedger, CallRecord
from .openai_compatible import OpenAICompatibleCompletion

__all__ = [
    "CallLedger", "CallRecord", "InputTooLarge", "ModelBudgetExceeded", "ModelCallError",
    "ModelConfigError", "ModelHTTPError", "ModelUnavailable", "OpenAICompatibleCompletion",
    "StageModelConfig", "TruncatedCompletion", "load_stage_config",
]

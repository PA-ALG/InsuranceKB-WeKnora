"""抽取/校验/合并/发布管道（docs/insurance-kb/04）。change 004 实现 1~7 步 MVP。"""

from typing import TYPE_CHECKING

from .cleaning import CleanResult, clean_value
from .llm import (
    CallStats,
    MeteredClient,
    ModelClient,
    OpenAICompatClient,
    ReplayClient,
    TruncatedOutputError,
    request_key,
)
from .models import (
    DeadLetter,
    FieldCandidate,
    Judgement,
    JudgeRequest,
    PredRecord,
    RunManifest,
)
from .parsing import extract_json_array
from .prompts import PROMPT_VERSION
from .recall_attribution import (
    AttributionReport,
    MissAttribution,
    attribute_misses,
    dataset_routing_lookup,
    render_attribution,
)
from .sections import DocSection, family_fingerprint, route_groups, split_sections
from .verification import all_quotes_verified, quote_verified

if TYPE_CHECKING:
    from .pipeline import ExtractionPipeline, PipelineConfig, RunResult, merge_candidates

_PIPELINE_EXPORTS = frozenset(
    {"ExtractionPipeline", "PipelineConfig", "RunResult", "merge_candidates"}
)


def __getattr__(name: str) -> object:
    """Resolve pipeline exports after package initialization to avoid source cycles."""
    if name not in _PIPELINE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .pipeline import (
        ExtractionPipeline as _ExtractionPipeline,
    )
    from .pipeline import (
        PipelineConfig as _PipelineConfig,
    )
    from .pipeline import (
        RunResult as _RunResult,
    )
    from .pipeline import (
        merge_candidates as _merge_candidates,
    )

    exports: dict[str, object] = {
        "ExtractionPipeline": _ExtractionPipeline,
        "PipelineConfig": _PipelineConfig,
        "RunResult": _RunResult,
        "merge_candidates": _merge_candidates,
    }
    value = exports[name]
    globals()[name] = value
    return value

__all__ = [
    "PROMPT_VERSION",
    "AttributionReport",
    "CallStats",
    "CleanResult",
    "DeadLetter",
    "DocSection",
    "ExtractionPipeline",
    "FieldCandidate",
    "JudgeRequest",
    "Judgement",
    "MeteredClient",
    "MissAttribution",
    "ModelClient",
    "OpenAICompatClient",
    "PipelineConfig",
    "PredRecord",
    "ReplayClient",
    "RunManifest",
    "RunResult",
    "TruncatedOutputError",
    "all_quotes_verified",
    "attribute_misses",
    "clean_value",
    "dataset_routing_lookup",
    "extract_json_array",
    "family_fingerprint",
    "merge_candidates",
    "quote_verified",
    "render_attribution",
    "request_key",
    "route_groups",
    "split_sections",
]

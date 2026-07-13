"""金标注 Agent 与 eval runner（docs/insurance-kb/05；spec openspec/changes/002、005）。"""

from .annotator import GoldenAnnotator, LiteLLMClient, ModelClient, ReplayClient
from .eval import EvalResult, evaluate, render_report
from .keypoints import (
    KeypointEntry,
    KeypointScore,
    load_keypoints,
    score_keypoints,
    split_keypoints,
    value_sha,
    write_keypoints,
)
from .pdf import PageText, ScannedPdfError, extract_pages
from .records import Evidence, GoldenRecord, TriState
from .release import build_release
from .runner import annotate_product, infer_line_key, load_release, read_jsonl, write_jsonl
from .verify import compare_with_meta, load_product_meta, verify_quotes

__all__ = [
    "EvalResult",
    "Evidence",
    "GoldenAnnotator",
    "GoldenRecord",
    "KeypointEntry",
    "KeypointScore",
    "LiteLLMClient",
    "ModelClient",
    "PageText",
    "ReplayClient",
    "ScannedPdfError",
    "TriState",
    "annotate_product",
    "build_release",
    "compare_with_meta",
    "evaluate",
    "extract_pages",
    "infer_line_key",
    "load_keypoints",
    "load_product_meta",
    "load_release",
    "read_jsonl",
    "render_report",
    "score_keypoints",
    "split_keypoints",
    "value_sha",
    "verify_quotes",
    "write_jsonl",
    "write_keypoints",
]

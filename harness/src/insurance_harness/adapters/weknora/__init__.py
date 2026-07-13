"""WeKnora REST 适配层（唯一 API 感知点，docs/insurance-kb/02 §2）。"""

from insurance_harness.adapters.weknora.client import WeKnoraClient
from insurance_harness.adapters.weknora.errors import (
    WeKnoraClientError,
    WeKnoraError,
    WeKnoraParseFailed,
    WeKnoraTransientError,
)
from insurance_harness.adapters.weknora.models import (
    WeKnoraChunk,
    WeKnoraKnowledge,
    WeKnoraWikiFolder,
    WeKnoraWikiPage,
)

__all__ = [
    "WeKnoraChunk",
    "WeKnoraClient",
    "WeKnoraClientError",
    "WeKnoraError",
    "WeKnoraKnowledge",
    "WeKnoraParseFailed",
    "WeKnoraTransientError",
    "WeKnoraWikiFolder",
    "WeKnoraWikiPage",
]

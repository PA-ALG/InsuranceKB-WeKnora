"""WeKnora REST 适配层（唯一 API 感知点，docs/insurance-kb/02 §2）。"""

from insurance_harness.adapters.weknora.client import WeKnoraClient
from insurance_harness.adapters.weknora.errors import (
    WeKnoraClientError,
    WeKnoraDownloadTooLarge,
    WeKnoraError,
    WeKnoraIntegrityError,
    WeKnoraPaginationLimit,
    WeKnoraParseFailed,
    WeKnoraTransientError,
)
from insurance_harness.adapters.weknora.models import (
    DownloadedKnowledge,
    WeKnoraChunk,
    WeKnoraKnowledge,
    WeKnoraWikiFolder,
    WeKnoraWikiPage,
)

__all__ = [
    "DownloadedKnowledge",
    "WeKnoraChunk",
    "WeKnoraClient",
    "WeKnoraClientError",
    "WeKnoraDownloadTooLarge",
    "WeKnoraError",
    "WeKnoraIntegrityError",
    "WeKnoraKnowledge",
    "WeKnoraPaginationLimit",
    "WeKnoraParseFailed",
    "WeKnoraTransientError",
    "WeKnoraWikiFolder",
    "WeKnoraWikiPage",
]

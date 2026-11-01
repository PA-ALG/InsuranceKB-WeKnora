"""The method value stage on a model: send what the compile will ask, keep what comes back (SK-2c).

Values and the compile are two commands because the compile holds the registry lock (SK-0 §4.3
(c)) and a thinking-mode answer can take minutes: here the registry is only read, the candidates
are admitted in memory and the requests are built by the compile's own functions, so the answers
written here, named by request digest, are exactly what `methods compile` replays (SK-2a §7).

The value directory is a run root of models.durable, as for product compiles and reviews:
budget.jsonl gains a line before every send, ledger.jsonl every attempt, .lock keeps runs apart,
and the root must lie outside any git repository (raw answers may quote material). raw/NNN.txt
keeps every answer as it arrives; `<digest>.txt` is written only for one that passed the answer's
structure check, never replaced. One root holds one model identity and one served version.

Saved answers are checked before anything is sent. A truncated or too-large request costs only its
method; running out of budget, a transport or configuration failure, or a changed served version
stops the run, and a rerun sends only what is still missing.
"""

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from insurance_harness.catalog.method_cards import MethodCards, load_method_cards
from insurance_harness.catalog.sales_taxonomy import SalesTaxonomy, load_sales_taxonomy
from insurance_harness.compilers.methods.admission import CandidateFile
from insurance_harness.compilers.methods.compile import admitted_registry, method_request
from insurance_harness.compilers.methods.paragraphs import MaterialCache, ParagraphsError
from insurance_harness.compilers.methods.parse import MethodResponseError, parse_method_response
from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.method_registry import valid_links
from insurance_harness.ingest.registry import ProductRegistry
from insurance_harness.ingest.source_map import PageReader
from insurance_harness.models import (
    InputTooLarge,
    ModelBudgetExceeded,
    ModelCallError,
    ModelConfigError,
    OpenAICompatibleCompletion,
    StageModelConfig,
    TruncatedCompletion,
)
from insurance_harness.models.durable import (
    DurableLedger,
    RunRootBusy,
    ServedModelChanged,
    prior_sends,
    run_lock,
    stored_records,
    write_new,
)

ANSWERED, SAVED = "answered", "saved"
_NUMBER = re.compile(r"[0-9]+")


class ValuesStopped(Exception):
    """The run stopped with a fixed code; what it sent so far stays counted and kept. The send
    counts are None for a stop before the value directory's budget was read."""

    def __init__(
        self,
        code: str,
        *,
        sent: int | None = None,
        sent_total: int | None = None,
        error: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code, self.sent, self.sent_total, self.error = code, sent, sent_total, error


class _Stop(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def method_values(
    registry: ProductRegistry,
    candidates: CandidateFile,
    *,
    pages: PageReader,
    root: Path,
    config: StageModelConfig,
    max_sent: int,
    cards: MethodCards | None = None,
    taxonomy: SalesTaxonomy | None = None,
) -> dict[str, Any]:
    """Answer every value request of the methods in force; the summary holds codes and counts."""
    cards, taxonomy = cards or load_method_cards(), taxonomy or load_sales_taxonomy()
    updated, _ = admitted_registry(registry, candidates)
    cache = MaterialCache(pages, updated.space_id, updated.method_uses)
    codes: dict[str, str] = {}
    requests: list[tuple[str, JudgeLikeRequest]] = []
    for method in updated.methods:
        links = valid_links(method, updated.method_uses)
        if method.suppressed or not links:
            continue  # retiring needs no answer
        try:
            _, _, request = method_request(method, links, cache, cards, taxonomy)
        except (ParagraphsError, SourcePagesError) as error:
            codes[method.method_id] = error.code
            continue
        requests.append((method.method_id, request))
    try:
        with run_lock(root):
            return _answer(root, config, max_sent, cards, requests, codes)
    except RunRootBusy:
        raise ValuesStopped("RUN_ROOT_BUSY") from None
    except ValueError:  # inside a git repository, or a corrupt budget or ledger
        raise ValuesStopped("RUN_ROOT_INVALID") from None


def _answer(
    root: Path,
    config: StageModelConfig,
    max_sent: int,
    cards: MethodCards,
    requests: Sequence[tuple[str, JudgeLikeRequest]],
    codes: dict[str, str],
) -> dict[str, Any]:
    identity = (config.stage, config.model, config.policy_version)
    if any((r.stage, r.model, r.policy_version) != identity for r in stored_records(root)):
        raise ValuesStopped("RUN_ROOT_MODEL_CHANGED")
    before = prior_sends(root)
    try:
        ledger = DurableLedger.open(root, max_sent=max_sent)
    except ServedModelChanged:
        raise ValuesStopped("SERVED_MODEL_CHANGED", sent=0, sent_total=before) from None
    stage = _Stage(root, config, ledger, cards)
    try:
        pending = []
        for method_id, request in requests:  # every saved answer is checked before any send
            if stage.saved(request):
                codes[method_id] = SAVED
            else:
                pending.append((method_id, request))
        for method_id, request in pending:
            codes[method_id] = stage.ask(request)
    except (_Stop, ModelCallError, ServedModelChanged, KeyboardInterrupt) as stop:
        code, error = _stop_code(stop)
        raise ValuesStopped(
            code, sent=prior_sends(root) - before, sent_total=prior_sends(root), error=error
        ) from None
    finally:
        stage.close()
    failed = {m: code for m, code in codes.items() if code not in (ANSWERED, SAVED)}
    return {
        "model": (sorted(ledger.served) or [config.model])[0],
        "methods": len(codes),
        "codes": dict(sorted(Counter(codes.values()).items())),
        "failed": dict(sorted(failed.items())),
        "sent": prior_sends(root) - before,
        "sent_total": prior_sends(root),
    }


def _stop_code(stop: BaseException) -> tuple[str, str | None]:
    if isinstance(stop, _Stop):
        return stop.code, None
    if isinstance(stop, ServedModelChanged):
        return "SERVED_MODEL_CHANGED", None
    if isinstance(stop, KeyboardInterrupt):
        return "INTERRUPTED", None
    if isinstance(stop, ModelBudgetExceeded):
        return "BUDGET_EXCEEDED", None
    if isinstance(stop, ModelConfigError):
        return "MODEL_CONFIG_INVALID", None
    return "MODEL_ERROR", type(stop).__name__


class _Stage:
    """The root's saved answers, and the model client created only when a send is needed."""

    def __init__(
        self, root: Path, config: StageModelConfig, ledger: DurableLedger, cards: MethodCards
    ) -> None:
        self._root, self._config, self._ledger, self._cards = root, config, ledger, cards
        self._client: OpenAICompatibleCompletion | None = None

    def saved(self, request: JudgeLikeRequest) -> bool:
        path = self._root / f"{request.sha256}.txt"
        if not path.is_file():
            return False
        try:
            parse_method_response(path.read_text(encoding="utf-8"), self._cards)
        except MethodResponseError:
            raise _Stop("RUN_ROOT_INVALID") from None  # it passed this check once: altered since
        return True

    def ask(self, request: JudgeLikeRequest) -> str:
        if self._client is None:
            self._client = OpenAICompatibleCompletion(self._config, ledger=self._ledger)
        try:
            raw = self._client.complete(system=request.system, user=request.user)
        except TruncatedCompletion:
            return "VALUE_TRUNCATED"
        except InputTooLarge:
            return "INPUT_TOO_LARGE"
        if len(self._ledger.served) > 1:
            # This answer came from another served version: it is neither kept nor used.
            raise ServedModelChanged("served model changed within the run")
        directory = self._root / "raw"
        directory.mkdir(exist_ok=True)
        write_new(directory / f"{_next_number(directory):03d}.txt", raw)
        try:
            parse_method_response(raw, self._cards)
        except MethodResponseError as error:
            return error.code
        write_new(self._root / f"{request.sha256}.txt", raw)
        return ANSWERED

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _next_number(directory: Path) -> int:
    # Every name counts, leftover temporary files included, so a new answer never collides.
    heads = (path.name.lstrip(".").split(".", 1)[0] for path in directory.iterdir())
    return max((int(head) for head in heads if _NUMBER.fullmatch(head)), default=0) + 1

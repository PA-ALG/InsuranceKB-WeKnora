"""The method value stage on a model: send what the compile will ask, keep what comes back (SK-2c).

Values and the compile are two commands because the compile holds the registry lock (SK-0 §4.3
(c)) and a thinking-mode answer can take minutes: here the registry is only read, the candidates
are admitted in memory and the requests are built by the compile's own functions, so the answers
written here, named by request digest, are exactly what `methods compile` replays (SK-2a §7).

The value directory is a run root of models.durable, as for product compiles and reviews:
budget.jsonl gains a line before every send, ledger.jsonl every attempt (an answered one with the
digest of its answer), .lock keeps runs apart, and the root must lie outside any git repository
(raw answers may quote material); responses.check_value_directory refuses a link anywhere in it or
in raw/, and a raw/ inside a git work tree, before anything is sent or written. stage.json binds the
directory to one set of request settings. raw/NNN.txt keeps every answer text received, a cut-off
one too, through the client's `keep`; `<digest>.txt` is written only for an answer that passed
the structure check, never replaced, and counts only while its call's ledger record backs it
(responses.LedgerAnswers, the port the compile replays through). One root, one served version.

Saved answers are checked before anything is sent. A truncated or too-large request costs only its
method; running out of budget, a transport or configuration failure, or a changed served version
(seen on any answer received, a cut-off one too) stops the run, and a rerun sends only what is
still missing.
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
from insurance_harness.compilers.methods.responses import (
    STAGE_FILE,
    LedgerAnswers,
    ResponsesError,
    check_value_directory,
    directory_stage,
    request_settings,
)
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
        check_value_directory(root)  # before anything is written or sent (review #526 R5)
        with run_lock(root):
            return _answer(root, config, max_sent, cards, requests, codes)
    except ResponsesError as error:
        raise ValuesStopped(error.code) from None
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
    _bind_stage(root, config)
    book = LedgerAnswers(root)
    before = prior_sends(root)
    try:
        ledger = DurableLedger.open(root, max_sent=max_sent)
    except ServedModelChanged:
        raise ValuesStopped("SERVED_MODEL_CHANGED", sent=0, sent_total=before) from None
    stage = _Stage(root, config, ledger, cards, book)
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


def _bind_stage(root: Path, config: StageModelConfig) -> None:
    """A new directory takes this stage; an existing one must have been made with the same request
    settings (operational ones may differ), and nothing may predate its stage file."""
    stage = directory_stage(root)
    if stage is None:
        if (root / "ledger.jsonl").exists() or any(root.glob("*.txt")):
            raise ValuesStopped("RUN_ROOT_INVALID")
        write_new(root / STAGE_FILE, config.model_dump_json(indent=1) + "\n")
    elif request_settings(stage) != request_settings(config):
        raise ValuesStopped("RUN_ROOT_MODEL_CHANGED")


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
    """The root's backed answers, and the model client created only when a send is needed."""

    def __init__(
        self,
        root: Path,
        config: StageModelConfig,
        ledger: DurableLedger,
        cards: MethodCards,
        book: LedgerAnswers,
    ) -> None:
        self._root, self._config, self._ledger, self._cards = root, config, ledger, cards
        self._book = book
        self._client: OpenAICompatibleCompletion | None = None

    def saved(self, request: JudgeLikeRequest) -> bool:
        try:
            text = self._book.answer(system=request.system, user=request.user)
            if text is None:
                return False
            parse_method_response(text, self._cards)
        except (ResponsesError, MethodResponseError):
            raise _Stop("RUN_ROOT_INVALID") from None  # altered, or no recorded call behind it
        return True

    def ask(self, request: JudgeLikeRequest) -> str:
        if self._client is None:
            self._client = OpenAICompatibleCompletion(
                self._config, ledger=self._ledger, keep=self._keep
            )
        try:
            raw = self._client.complete(system=request.system, user=request.user)
        except TruncatedCompletion:
            self._same_served()  # a cut-off answer is an answer received too (review #526 R4)
            return "VALUE_TRUNCATED"
        except InputTooLarge:
            return "INPUT_TOO_LARGE"
        self._same_served()
        try:
            parse_method_response(raw, self._cards)
        except MethodResponseError as error:
            return error.code
        write_new(self._root / f"{request.sha256}.txt", raw)
        return ANSWERED

    def _keep(self, text: str) -> None:
        """Every answer text received goes to raw/, unless another served version sent it."""
        if len(self._ledger.served) > 1:
            return
        directory = self._root / "raw"
        directory.mkdir(exist_ok=True)
        write_new(directory / f"{_next_number(directory):03d}.txt", text)

    def _same_served(self) -> None:
        if len(self._ledger.served) > 1:
            # This answer came from another served version: it is neither kept nor used.
            raise ServedModelChanged("served model changed within the run")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _next_number(directory: Path) -> int:
    # Every name counts, leftover temporary files included, so a new answer never collides.
    heads = (path.name.lstrip(".").split(".", 1)[0] for path in directory.iterdir())
    return max((int(head) for head in heads if _NUMBER.fullmatch(head)), default=0) + 1

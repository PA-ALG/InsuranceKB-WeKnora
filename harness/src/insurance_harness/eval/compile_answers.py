"""Product-specific ordered recording/replay; authenticity belongs to models.answers (H1)."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from insurance_harness.catalog.trust_policy import TrustPolicy
from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.models.answers import (
    AnswerJournal,
    message_digest,
    offline_answer,
    request_fingerprint,
    verify_answer,
)
from insurance_harness.models.durable import stored_records
from insurance_harness.models.openai_compatible import OpenAICompatibleCompletion
from insurance_harness.models.run_files import IntegrityError, read_regular


class RecordedCompletion:
    """The production adapter records HTTP provenance; pure ports stay explicitly offline."""

    def __init__(self, root: Path, directory: Path, inner: CompletionPort) -> None:
        self._inner, self._directory, self._count = inner, directory, 0
        self._journal = (
            AnswerJournal(root, directory, inner)
            if isinstance(inner, OpenAICompatibleCompletion)
            else None
        )

    @property
    def model(self) -> str:
        return self._journal.model if self._journal else "offline/" + self._inner.model

    def complete(self, *, system: str, user: str) -> str:
        if self._journal is not None:
            raw = self._journal.complete(system=system, user=user)
            self._journal.accept()
            return raw
        raw = self._inner.complete(system=system, user=user)
        self._count += 1
        offline_answer(
            self._directory, self._count, system=system, user=user, raw=raw, model=self._inner.model
        )
        return raw


def replay_context(
    product: str,
    pack: str,
    pages: Sequence[PageText],
    table_headers: Mapping[str, Sequence[PageText]] | None = None,
    materials: list[str] | None = None,
    *,
    trust_policy: TrustPolicy,
) -> str:
    """What a saved answer was produced for beyond the request text: product, pack, sources."""

    def documents(group: Sequence[PageText]) -> list[dict[str, object]]:
        sources: dict[tuple[str, str], int] = {}
        for page in group:
            key = (page.document, page.document_sha256)
            sources[key] = sources.get(key, 0) + 1
        return [{"document": d, "document_sha256": s, "pages": n} for (d, s), n in sources.items()]

    context: dict[str, object] = {"product": product, "pack_id": pack, "sources": documents(pages)}
    if materials is not None:
        context["materials"] = materials
    if table_headers is not None:
        context["trust_policy"] = trust_policy.model_dump(mode="json")
        context["table_headers"] = [
            {"role": role, "sources": documents(group)} for role, group in table_headers.items()
        ]
    return json.dumps(context, ensure_ascii=False, sort_keys=True) + "\n"


def attempts(directory: Path) -> list[Path]:
    """Attempt folders in numeric order; zero padding is only a minimum width."""
    found = [
        (int(path.name[len("attempt-") :]), path)
        for path in directory.glob("attempt-*")
        if path.is_dir() and path.name[len("attempt-") :].isdigit()
    ]
    return [path for _, path in sorted(found)]


def next_attempt(directory: Path) -> str:
    """Each compile attempt of a product keeps its own raw-response folder."""
    found = attempts(directory)
    latest = int(found[-1].name[len("attempt-") :]) if found else 0
    return f"attempt-{latest + 1:02d}"


class ReplayContextError(IntegrityError):
    """Keep the source/pack diagnostic distinct from damaged saved-answer files."""

    def __init__(self) -> None:
        super().__init__("REPLAY_CONTEXT_MISMATCH")
        self.args = ("replay source was produced for another source or pack",)


class Replay:
    """Consume each recorded draw in order, including repeated identical HTTP requests."""

    def __init__(self, source: Path, product: str, context: str) -> None:
        found = attempts(source / product / "responses")
        if not found:
            raise IntegrityError()
        if read_regular(found[-1] / "context.json") != context.encode():
            raise ReplayContextError()
        paths = sorted(found[-1].glob("[0-9][0-9][0-9].txt"))
        if not paths:
            raise IntegrityError()
        self._records = stored_records(source)
        models = {verify_answer(p, self._records, offline=True).model for p in paths}
        if len(models) != 1:
            raise IntegrityError()
        self.model = models.pop()
        self._saved = iter(paths)

    def complete(self, *, system: str, user: str) -> str:
        path = next(self._saved, None)
        if path is None:
            raise IntegrityError()
        meta = verify_answer(path, self._records, offline=True)
        expected = (
            request_fingerprint(meta.config, system=system, user=user)
            if meta.config
            else message_digest(system, user)
        )
        marker = read_regular(path.with_suffix(".request.sha256"))
        if meta.fingerprint != expected or marker != (expected + "\n").encode():
            raise IntegrityError()
        raw = read_regular(path)
        assert raw is not None
        return raw.decode("utf-8")

    def finish(self) -> None:
        if next(self._saved, None) is not None:
            raise IntegrityError()

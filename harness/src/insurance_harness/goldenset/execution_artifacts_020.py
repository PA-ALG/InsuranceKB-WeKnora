"""Versioned OpenSpec 020 execution-artifact boundary.

This module is deliberately fail-closed.  It reads admitted files through
directory descriptors with ``O_NOFOLLOW`` and converts all boundary failures to
stable, non-sensitive admission codes.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
import stat
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, ValidationError

from insurance_harness.compiler.models import (
    BaselineAdmissionIdentity,
    DeadLetter,
    JudgeRequest,
    PredRecord,
    RunManifest,
)
from insurance_harness.compiler.pipeline import RunArtifactCommitCandidate, RunResult
from insurance_harness.goldenset.admission_artifacts import CanaryArtifactBundle
from insurance_harness.goldenset.admission_models import canonical_json_bytes
from insurance_harness.goldenset.admission_runtime import AdmissionPausedError
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import GoldenRecord

_MAX_FILE_BYTES = 256 * 1024 * 1024
_DIRECT_DEPENDENCY: Final = "pdfplumber"
_ALGORITHM_PATH: Final = "harness/src/insurance_harness/goldenset/pdf.py"
_LOCK_PATH: Final = "harness/uv.lock"
_PARSER_POLICY: Final = "insurancekb.directory-pdfplumber.v1"
_PARSER_DOMAIN: Final = b"insurancekb.directory-parser-fingerprint.v1\0"
_QUALITY_THRESHOLD_VERSION: Final = "golden-v0.1-thresholds-v1"


class _Fault(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _ProductIdentity:
    product_id: str
    line_key: str
    pdf_digests: dict[str, str]
    product_meta_path: str
    product_meta_digest: str
    fields_digest: str
    consumed_input_digests: dict[str, str]


def _safe_parts(value: str, *, single: bool = False) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise _Fault("unsafe")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise _Fault("unsafe")
    if single and len(pure.parts) != 1:
        raise _Fault("unsafe")
    return pure.parts


def _path_relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise _Fault("unsafe") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise _Fault("unsafe")
    return parts


class _SafeRoot:
    """No-follow traversal rooted at one already trusted directory path."""

    def __init__(self, root: Path, *, private: bool = False) -> None:
        self._private = private
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            self._root_fd = os.open(root, flags)
            self._validate_private(os.fstat(self._root_fd))
        except OSError as exc:
            raise _Fault("missing" if exc.errno == errno.ENOENT else "unsafe") from exc
        except _Fault:
            if hasattr(self, "_root_fd"):
                os.close(self._root_fd)
            raise

    def _validate_private(self, metadata: os.stat_result) -> None:
        if self._private and (
            metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077 != 0
        ):
            raise _Fault("unsafe")

    def close(self) -> None:
        os.close(self._root_fd)

    def _directory_fd(self, parts: Sequence[str]) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        current = os.dup(self._root_fd)
        try:
            for part in parts:
                next_fd = os.open(part, flags, dir_fd=current)
                try:
                    self._validate_private(os.fstat(next_fd))
                except _Fault:
                    os.close(next_fd)
                    raise
                os.close(current)
                current = next_fd
            return current
        except OSError as exc:
            os.close(current)
            raise _Fault("missing" if exc.errno == errno.ENOENT else "unsafe") from exc

    def names(self, parts: Sequence[str]) -> set[str]:
        descriptor = self._directory_fd(parts)
        try:
            return set(os.listdir(descriptor))
        except OSError as exc:
            raise _Fault("unsafe") from exc
        finally:
            os.close(descriptor)

    def read(self, parts: Sequence[str], *, single_link: bool = False) -> bytes:
        if not parts:
            raise _Fault("unsafe")
        parent = self._directory_fd(parts[:-1])
        descriptor: int | None = None
        try:
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > _MAX_FILE_BYTES
                or (single_link and metadata.st_nlink != 1)
            ):
                raise _Fault("unsafe")
            self._validate_private(metadata)
            chunks: list[bytes] = []
            total = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                total += len(chunk)
                if total > _MAX_FILE_BYTES:
                    raise _Fault("unsafe")
                chunks.append(chunk)
            if single_link and os.fstat(descriptor).st_nlink != 1:
                raise _Fault("unsafe")
            return b"".join(chunks)
        except OSError as exc:
            raise _Fault("missing" if exc.errno == errno.ENOENT else "unsafe") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent)


def _get(value: object, name: str) -> object:
    try:
        return getattr(value, name)
    except (AttributeError, TypeError) as exc:
        raise _Fault("invalid") from exc


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Fault("invalid")
    return value


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _Fault("invalid")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, str) or not item:
            raise _Fault("invalid")
        result[key] = item
    return result


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _product_identity(document: object, product_id: str) -> tuple[_ProductIdentity, str, str]:
    request = _get(document, "identity_request")
    products = _get(request, "products")
    if not isinstance(products, Sequence) or isinstance(products, (str, bytes)):
        raise _Fault("invalid")
    matching = [item for item in products if _get(item, "product_id") == product_id]
    if len(matching) != 1:
        raise _Fault("invalid")
    item = matching[0]
    identity = _ProductIdentity(
        product_id=_text(_get(item, "product_id")),
        line_key=_text(_get(item, "line_key")),
        pdf_digests=_string_mapping(_get(item, "pdf_digests")),
        product_meta_path=_text(_get(item, "product_meta_path")),
        product_meta_digest=_text(_get(item, "product_meta_digest")),
        fields_digest=_text(_get(item, "fields_digest")),
        consumed_input_digests=_string_mapping(_get(item, "consumed_input_digests")),
    )
    source_root = _text(_get(request, "source_products_root"))
    golden_root = _text(_get(request, "golden_products_root"))
    return identity, source_root, golden_root


def _model_id(document: object) -> str:
    roles = _get(_get(_get(document, "plan"), "payload"), "model_roles")
    if not isinstance(roles, Mapping) or "annotator" not in roles:
        raise _Fault("invalid")
    return _text(_get(roles["annotator"], "model_id"))


def _shared_input_digests(document: object) -> dict[str, str]:
    request = _get(document, "identity_request")
    return _string_mapping(_get(request, "shared_input_digests"))


def _repo_root(configuration: object) -> Path:
    value = _get(configuration, "repo_root")
    if not isinstance(value, Path) or not value.is_absolute():
        raise _Fault("invalid")
    return value


def _run_root(configuration: object) -> Path:
    value = _get(configuration, "run_root")
    if not isinstance(value, Path) or not value.is_absolute():
        raise _Fault("invalid")
    return value


def _decode_json_object(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Fault("invalid") from exc
    if not isinstance(decoded, dict):
        raise _Fault("invalid")
    return cast(dict[str, object], decoded)


def _canonical_records(records: Sequence[GoldenRecord]) -> tuple[GoldenRecord, ...]:
    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.doc,
                record.field_id,
                canonical_json_bytes(record),
            ),
        )
    )


def _parse_jsonl_records(value: bytes) -> tuple[GoldenRecord, ...]:
    try:
        lines = value.decode("utf-8").splitlines()
        return tuple(
            GoldenRecord.model_validate_json(line) for line in lines if line.strip()
        )
    except (UnicodeDecodeError, ValidationError) as exc:
        raise _Fault("invalid") from exc


def render_annotation_artifacts(
    *,
    document: object,
    configuration: object,
    product_id: str,
    records: Sequence[GoldenRecord],
    cache_dir: Path,
    page_loader: Callable[[str, bytes], list[PageText]],
    started_at: datetime,
    finished_at: datetime,
    execution_plan_hash: str,
) -> CanaryArtifactBundle:
    """Render exact, canonical annotation evidence from revalidated inputs."""

    if not records:
        raise AdmissionPausedError("annotation_records_empty") from None
    try:
        return _render_annotation_artifacts(
            document=document,
            configuration=configuration,
            product_id=product_id,
            records=records,
            cache_dir=cache_dir,
            page_loader=page_loader,
            started_at=started_at,
            finished_at=finished_at,
            execution_plan_hash=execution_plan_hash,
        )
    except _Fault as fault:
        pause_code = (
            fault.code
            if fault.code.startswith("annotation_")
            else "annotation_identity_mismatch"
        )
    except Exception:
        pause_code = "annotation_identity_mismatch"
    raise AdmissionPausedError(pause_code) from None


def _render_annotation_artifacts(
    *,
    document: object,
    configuration: object,
    product_id: str,
    records: Sequence[GoldenRecord],
    cache_dir: Path,
    page_loader: Callable[[str, bytes], list[PageText]],
    started_at: datetime,
    finished_at: datetime,
    execution_plan_hash: str,
) -> CanaryArtifactBundle:
    identity, source_root, golden_root = _product_identity(document, product_id)
    repo_root = _repo_root(configuration)
    model_id = _model_id(document)
    shared_input_digests = _shared_input_digests(document)
    if (
        identity.product_id != product_id
        or not identity.pdf_digests
        or started_at.tzinfo is None
        or finished_at.tzinfo is None
        or started_at > finished_at
        or not execution_plan_hash
    ):
        raise _Fault("annotation_identity_mismatch")

    product_component = _safe_parts(product_id, single=True)
    source_parts = (*_safe_parts(source_root), *product_component)
    golden_parts = (*_safe_parts(golden_root), *product_component)
    pdf_names = set(identity.pdf_digests)
    for name in pdf_names:
        _safe_parts(name, single=True)
        if not name.casefold().endswith(".pdf"):
            raise _Fault("annotation_identity_mismatch")
    _safe_parts(identity.product_meta_path, single=True)
    for name in identity.consumed_input_digests:
        _safe_parts(name, single=True)

    root = _SafeRoot(repo_root)
    try:
        if root.names(source_parts) != pdf_names | {identity.product_meta_path}:
            raise _Fault("annotation_identity_mismatch")
        if root.names(golden_parts) != set(identity.consumed_input_digests) | {"fields.json"}:
            raise _Fault("annotation_identity_mismatch")
        pdf_bytes = {
            name: root.read((*source_parts, name)) for name in sorted(pdf_names)
        }
        meta_bytes = root.read((*source_parts, identity.product_meta_path))
        fields_bytes = root.read((*golden_parts, "fields.json"))
        consumed_bytes = {
            name: root.read((*golden_parts, name))
            for name in sorted(identity.consumed_input_digests)
        }
        shared_input_bytes = {
            name: root.read(_safe_parts(name))
            for name in sorted(shared_input_digests)
        }
    except _Fault:
        raise _Fault("annotation_identity_mismatch") from None
    finally:
        root.close()

    if (
        {name: _sha256(value) for name, value in pdf_bytes.items()}
        != identity.pdf_digests
        or _sha256(meta_bytes) != identity.product_meta_digest
        or _sha256(fields_bytes) != identity.fields_digest
        or {name: _sha256(value) for name, value in consumed_bytes.items()}
        != identity.consumed_input_digests
        or {name: _sha256(value) for name, value in shared_input_bytes.items()}
        != shared_input_digests
    ):
        raise _Fault("annotation_identity_mismatch")

    try:
        meta = _decode_json_object(meta_bytes)
        fields = _decode_json_object(fields_bytes)
        plan_code = _text(meta.get("planCode"))
        clause_name = meta.get("clauseName")
        if clause_name is not None and _text(clause_name) != product_id:
            raise _Fault("invalid")
        line_key = _text(fields.get("line_key"))
        schema_version = _text(fields.get("schema_version"))
    except _Fault:
        raise _Fault("annotation_identity_mismatch") from None
    canonical_records = _canonical_records(records)
    if line_key != identity.line_key:
        raise _Fault("annotation_identity_mismatch")
    for record in canonical_records:
        if (
            record.product_id != plan_code
            or record.product_name != product_id
            or record.doc not in pdf_names
            or record.schema_version != schema_version
            or record.annotator_model != model_id
        ):
            raise _Fault("annotation_identity_mismatch")
        if (record.tri_state == "unknown" and record.evidence) or (
            record.tri_state != "unknown" and not record.evidence
        ):
            raise _Fault("annotation_quote_verification_failed")

    try:
        run_root = _run_root(configuration)
        cache_parts = _path_relative_parts(cache_dir, run_root)
    except _Fault:
        raise _Fault("annotation_cache_invalid") from None
    try:
        cache_root = _SafeRoot(run_root, private=True)
    except _Fault:
        raise _Fault("annotation_cache_invalid") from None
    schema_hash = schema_version.split("+")[-1]
    try:
        _safe_parts(schema_hash, single=True)
    except _Fault:
        raise _Fault("annotation_cache_invalid") from None
    expected_cache_names = {f"{doc}.{schema_hash}.jsonl" for doc in pdf_names}
    cache_entries: list[dict[str, object]] = []
    cache_verified_docs: set[str] = set()
    try:
        cache_product_parts = (*cache_parts, *product_component)
        if cache_root.names(cache_product_parts) != expected_cache_names:
            raise _Fault("invalid")
        for doc in sorted(pdf_names):
            name = f"{doc}.{schema_hash}.jsonl"
            raw = cache_root.read((*cache_product_parts, name))
            cached = _canonical_records(_parse_jsonl_records(raw))
            expected = tuple(item for item in canonical_records if item.doc == doc)
            if cached != expected:
                raise _Fault("invalid")
            cache_verified_docs.add(doc)
            cache_entries.append(
                {
                    "path": PurePosixPath(*product_component, name).as_posix(),
                    "sha256": _sha256(raw),
                    "record_count": len(cached),
                }
            )
    except _Fault:
        raise _Fault("annotation_cache_invalid") from None
    finally:
        cache_root.close()

    pages_by_doc: dict[str, dict[int, str]] = {}
    try:
        for doc in sorted(pdf_names):
            loaded = page_loader(doc, pdf_bytes[doc])
            pages: dict[int, str] = {}
            for page in loaded:
                if page.page_no < 1 or page.page_no in pages:
                    raise _Fault("annotation_quote_verification_failed")
                pages[page.page_no] = page.text
            pages_by_doc[doc] = pages
    except _Fault:
        raise
    except Exception:
        raise _Fault("annotation_quote_verification_failed") from None

    # The callback receives the immutable, already-verified bytes.  Re-open the
    # admitted namespace afterwards as well so a swap during the loader window
    # cannot produce an ACCEPT against stale identity evidence.
    try:
        post_load_root = _SafeRoot(repo_root)
        try:
            root_names = post_load_root.names(source_parts)
            if root_names != pdf_names | {identity.product_meta_path}:
                raise _Fault("annotation_identity_mismatch")
            post_load_pdf_bytes = {
                doc: post_load_root.read((*source_parts, doc))
                for doc in sorted(pdf_names)
            }
        finally:
            post_load_root.close()
    except _Fault:
        raise _Fault("annotation_identity_mismatch") from None
    if post_load_pdf_bytes != pdf_bytes:
        raise _Fault("annotation_identity_mismatch")

    verified_records: list[dict[str, object]] = []
    verified_record_counts: Counter[str] = Counter()
    for record in canonical_records:
        verified_evidence: list[dict[str, object]] = []
        for evidence in record.evidence:
            page_text = pages_by_doc[record.doc].get(evidence.page)
            if page_text is None or evidence.quote not in page_text:
                raise _Fault("annotation_quote_verification_failed")
            verified_evidence.append(
                {
                    "page": evidence.page,
                    "quote_sha256": _sha256(evidence.quote.encode("utf-8")),
                    "matched": True,
                }
            )
        verified_records.append(
            {
                "doc": record.doc,
                "field_id": record.field_id,
                "evidence": verified_evidence,
                "complete": True,
            }
        )
        verified_record_counts[record.doc] += 1

    expected_record_counts = Counter(record.doc for record in canonical_records)
    complete_documents = {
        doc
        for doc in pdf_names
        if doc in cache_verified_docs
        and verified_record_counts[doc] == expected_record_counts[doc]
    }
    if complete_documents != pdf_names:
        raise _Fault("annotation_quote_verification_failed")

    golden = b"".join(canonical_json_bytes(record) + b"\n" for record in canonical_records)
    checkpoint = canonical_json_bytes(
        {
            "format": "insurancekb.annotation-checkpoint.v1",
            "complete": True,
            "cache_files": cache_entries,
        }
    )
    quote_verification = canonical_json_bytes(
        {
            "format": "insurancekb.quote-verification.v1",
            "documents": [
                {
                    "doc": name,
                    "pdf_sha256": identity.pdf_digests[name],
                    "complete": name in complete_documents,
                }
                for name in sorted(pdf_names)
            ],
            "records": verified_records,
            "complete": True,
        }
    )
    reasons = Counter(
        record.disputed_reason or "unspecified"
        for record in canonical_records
        if record.disputed
    )
    disputed_count = sum(1 for record in canonical_records if record.disputed)
    disputed_quality = canonical_json_bytes(
        {
            "format": "insurancekb.disputed-quality.v1",
            "quality_threshold_version": _QUALITY_THRESHOLD_VERSION,
            "record_count": len(canonical_records),
            "disputed_count": disputed_count,
            "reasons": dict(sorted(reasons.items())),
        }
    )
    manifest = canonical_json_bytes(
        {
            "format": "insurancekb.annotation-manifest.v1",
            "identity": {
                "admission_product_name": product_id,
                "plan_code": plan_code,
                "line_key": line_key,
                "schema_version": schema_version,
                "annotator_model": model_id,
            },
            "execution_plan_hash": execution_plan_hash,
            "started_at": started_at,
            "finished_at": finished_at,
            "input_digests": {
                "pdf_digests": dict(sorted(identity.pdf_digests.items())),
                "product_meta_digest": identity.product_meta_digest,
                "fields_digest": identity.fields_digest,
                "consumed_input_digests": dict(sorted(identity.consumed_input_digests.items())),
                "shared_input_digests": dict(sorted(shared_input_digests.items())),
            },
            "artifact_digests": {
                "checkpoint": _sha256(checkpoint),
                "golden": _sha256(golden),
                "quote_verification": _sha256(quote_verification),
                "disputed_quality": _sha256(disputed_quality),
            },
        }
    )
    return CanaryArtifactBundle(
        checkpoint=checkpoint,
        manifest=manifest,
        golden=golden,
        quote_verification=quote_verification,
        disputed_quality=disputed_quality,
        disputed_count=disputed_count,
        record_count=len(canonical_records),
        quality_threshold_version=_QUALITY_THRESHOLD_VERSION,
    )


def validate_annotation_bundle(
    *,
    document: object,
    configuration: object,
    product_id: str,
    bundle: CanaryArtifactBundle,
    cache_dir: Path,
    page_loader: Callable[[str, bytes], list[PageText]],
    execution_plan_hash: str,
) -> CanaryArtifactBundle:
    """Re-render an annotation commit candidate from current admitted evidence."""

    try:
        if not isinstance(bundle, CanaryArtifactBundle):
            raise _Fault("invalid")
        manifest = _decode_json_object(bundle.manifest)
        if manifest.get("format") != "insurancekb.annotation-manifest.v1":
            raise _Fault("invalid")
        started_at = datetime.fromisoformat(_text(manifest.get("started_at")))
        finished_at = datetime.fromisoformat(_text(manifest.get("finished_at")))
        records = _parse_jsonl_records(bundle.golden)
        if not records:
            raise _Fault("invalid")
        expected = _render_annotation_artifacts(
            document=document,
            configuration=configuration,
            product_id=product_id,
            records=records,
            cache_dir=cache_dir,
            page_loader=page_loader,
            started_at=started_at,
            finished_at=finished_at,
            execution_plan_hash=execution_plan_hash,
        )
        if expected != bundle:
            raise _Fault("invalid")
        return bundle
    except (ValueError, TypeError, _Fault):
        raise AdmissionPausedError("canary_artifact_commit_invalid") from None
    except Exception:
        raise AdmissionPausedError("canary_artifact_commit_invalid") from None


def directory_parser_fingerprint(
    *,
    document: object,
    configuration: object,
    installed_version: Callable[[str], str],
) -> str:
    """Bind the directory parser to admitted algorithm, lock, and installed version."""

    try:
        request = _get(document, "identity_request")
        surface = _string_mapping(_get(request, "execution_surface_digests"))
        algorithm_digest = surface[_ALGORITHM_PATH]
        lock_digest = surface[_LOCK_PATH]
        root = _SafeRoot(_repo_root(configuration))
        try:
            algorithm_bytes = root.read(_safe_parts(_ALGORITHM_PATH))
            lock_bytes = root.read(_safe_parts(_LOCK_PATH))
        finally:
            root.close()
        if _sha256(algorithm_bytes) != algorithm_digest or _sha256(lock_bytes) != lock_digest:
            raise _Fault("baseline_parser_identity_mismatch")
        try:
            lock = tomllib.loads(lock_bytes.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise _Fault("baseline_parser_lock_invalid") from exc
        packages = lock.get("package")
        if not isinstance(packages, list):
            raise _Fault("baseline_parser_lock_invalid")
        matches = [
            item
            for item in packages
            if isinstance(item, dict) and item.get("name") == _DIRECT_DEPENDENCY
        ]
        if len(matches) != 1:
            raise _Fault("baseline_parser_lock_invalid")
        locked_version = matches[0].get("version")
        if not isinstance(locked_version, str) or not locked_version.strip():
            raise _Fault("baseline_parser_lock_invalid")
        try:
            actual_version = installed_version(_DIRECT_DEPENDENCY)
        except Exception:
            raise _Fault("baseline_parser_identity_mismatch") from None
        if actual_version != locked_version:
            raise _Fault("baseline_parser_identity_mismatch")
        payload = {
            "algorithm": {"path": _ALGORITHM_PATH, "sha256": algorithm_digest},
            "direct_dependency": {
                "installed_version": actual_version,
                "locked_version": locked_version,
                "name": _DIRECT_DEPENDENCY,
            },
            "lock": {"path": _LOCK_PATH, "sha256": lock_digest},
            "policy_version": _PARSER_POLICY,
        }
        return _sha256(_PARSER_DOMAIN + canonical_json_bytes(payload))
    except KeyError:
        pause_code = "baseline_parser_identity_mismatch"
    except _Fault as fault:
        pause_code = fault.code
    except Exception:
        pause_code = "baseline_parser_identity_mismatch"
    raise AdmissionPausedError(pause_code) from None


def _parse_jsonl_models[T: BaseModel](
    value: bytes, model: type[T], code: str
) -> list[T]:
    try:
        lines = value.decode("utf-8").splitlines()
        return [model.model_validate_json(line) for line in lines if line.strip()]
    except (UnicodeDecodeError, ValidationError, ValueError, TypeError):
        raise _Fault(code) from None


def _checkpoint_manifest(
    value: bytes,
    expected: RunManifest,
) -> RunManifest:
    """Read the exact checkpoint bytes and bind its latest thread to the commit."""

    if not value.startswith(b"SQLite format 3\x00"):
        raise _Fault("baseline_artifact_content_mismatch")
    # SqliteSaver fixes the on-disk database header to WAL mode.  Once its
    # connection is closed, no WAL/SHM sidecar is part of the committed
    # artifact; an in-memory deserialization must therefore disable the two
    # file-backed journal header flags before querying the verified page image.
    if len(value) < 20 or value[18] not in {1, 2} or value[19] not in {1, 2}:
        raise _Fault("baseline_artifact_content_mismatch")
    memory_image = bytearray(value)
    memory_image[18:20] = b"\x01\x01"
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(bytes(memory_image))
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not {"checkpoints", "writes"} <= tables:
                raise _Fault("baseline_artifact_content_mismatch")
            row = connection.execute(
                "SELECT type, checkpoint FROM checkpoints "
                "WHERE thread_id = ? AND checkpoint_ns = '' "
                "ORDER BY checkpoint_id DESC LIMIT 1",
                (expected.run_id,),
            ).fetchone()
            if row is None:
                raise _Fault("baseline_artifact_content_mismatch")
            decoded = SqliteSaver(connection).serde.loads_typed(
                (str(row[0]), bytes(row[1]))
            )
    except _Fault:
        raise
    except Exception as error:
        raise _Fault("baseline_artifact_content_mismatch") from error
    if not isinstance(decoded, Mapping):
        raise _Fault("baseline_artifact_content_mismatch")
    values = decoded.get("channel_values")
    if not isinstance(values, Mapping):
        raise _Fault("baseline_artifact_content_mismatch")
    expected_identity = {
        "run_id": expected.run_id,
        "run_dir": expected.run_dir,
        "checkpoint_path": expected.checkpoint_path,
        "product_dir": expected.product_dir,
        "product_id": expected.product_id,
        "product_name": expected.product_name,
        "line_key": expected.line_key,
        "schema_version": expected.schema_version,
        "model_id": expected.model_id,
        "judge_mode": expected.judge_mode,
    }
    if any(values.get(key) != item for key, item in expected_identity.items()):
        raise _Fault("baseline_identity_mismatch")
    try:
        checkpoint_manifest = RunManifest.model_validate(values.get("manifest"))
    except ValidationError as error:
        raise _Fault("baseline_artifact_content_mismatch") from error
    if checkpoint_manifest != expected:
        raise _Fault("baseline_identity_mismatch")
    return checkpoint_manifest


def _baseline_relative(path: Path, root: Path) -> tuple[str, ...]:
    if not path.is_absolute() or not root.is_absolute():
        raise _Fault("baseline_artifact_path_unsafe")
    try:
        return _path_relative_parts(path, root)
    except _Fault:
        raise _Fault("baseline_artifact_path_unsafe") from None


def validate_baseline_commit_candidate(
    candidate: RunArtifactCommitCandidate,
    *,
    expected_run_id: str,
    expected_run_dir: Path,
    expected_checkpoint_path: Path,
    expected_product_dir: Path,
    expected_product_id: str,
    expected_product_name: str,
    expected_line_key: str,
    expected_schema_version: str,
    expected_model_id: str,
    expected_judge_mode: str,
    expected_admission_identity: BaselineAdmissionIdentity,
) -> None:
    """Reject a staged 020 baseline before the manifest commit marker exists."""

    try:
        manifest = RunManifest.model_validate_json(candidate.manifest)
        records = _parse_jsonl_models(
            candidate.pred,
            PredRecord,
            "baseline_artifact_content_mismatch",
        )
        judge_requests = _parse_jsonl_models(
            candidate.judge_queue,
            JudgeRequest,
            "baseline_artifact_content_mismatch",
        )
        dead_letters = _parse_jsonl_models(
            candidate.dead_letters,
            DeadLetter,
            "baseline_artifact_content_mismatch",
        )
        if (
            manifest.run_id != expected_run_id
            or Path(manifest.run_dir) != expected_run_dir
            or Path(manifest.checkpoint_path) != expected_checkpoint_path
            or Path(manifest.product_dir) != expected_product_dir
            or manifest.product_id != expected_product_id
            or manifest.product_name != expected_product_name
            or manifest.line_key != expected_line_key
            or manifest.schema_version != expected_schema_version
            or manifest.model_id != expected_model_id
            or manifest.judge_mode != expected_judge_mode
            or manifest.baseline_admission != expected_admission_identity
            or manifest.template_registry_version
            != expected_admission_identity.template_registry_version
            or not manifest.docs
            or not records
        ):
            raise _Fault("baseline_identity_mismatch")
        documents = {entry.doc: entry for entry in manifest.docs}
        if (
            len(documents) != len(manifest.docs)
            or set(documents) != set(expected_admission_identity.pdf_digests)
            or any(
                entry.parser_fingerprint
                != expected_admission_identity.parser_fingerprint
                or entry.file_hash
                != expected_admission_identity.pdf_digests[entry.doc]
                or entry.original_digest
                != expected_admission_identity.pdf_digests[entry.doc]
                for entry in documents.values()
            )
            or any(
                record.product_id != expected_product_id
                or record.product_name != expected_product_name
                or record.doc not in documents
                or record.schema_version != expected_schema_version
                or record.annotator_model != expected_model_id
                for record in records
            )
            or dead_letters != manifest.dead_letters
            or any(
                dead.product != expected_product_name or dead.doc not in documents
                for dead in dead_letters
            )
        ):
            raise _Fault("baseline_identity_mismatch")
        pending = [record for record in records if record.pending_judge]
        pending_keys = sorted(
            (
                record.product_id,
                record.product_name,
                record.doc,
                record.field_id,
                record.field_name,
            )
            for record in pending
        )
        judge_keys = sorted(
            (
                request.product_id,
                request.product_name,
                request.doc,
                request.field_id,
                request.field_name,
            )
            for request in judge_requests
        )
        if (
            manifest.pending_judge_count != len(pending)
            or len(judge_requests) != len(pending)
            or judge_keys != pending_keys
        ):
            raise _Fault("baseline_artifact_content_mismatch")
    except _Fault as fault:
        pause_code = fault.code
    except Exception:
        pause_code = "baseline_artifact_content_mismatch"
    else:
        return
    raise AdmissionPausedError(pause_code) from None


def validate_baseline_result(
    *,
    result: RunResult,
    run_root: Path,
    expected_source_root: Path,
    expected_product_dir: Path,
    expected_run_id: str,
    expected_run_dir: Path,
    expected_product_id: str,
    expected_product_name: str,
    expected_line_key: str,
    expected_schema_version: str,
    expected_model_id: str,
    expected_judge_mode: str,
    expected_admission_identity: BaselineAdmissionIdentity | None = None,
) -> RunResult:
    """Verify exact baseline paths, committed semantics, and admitted identity."""

    try:
        return _validate_baseline_result(
            result=result,
            run_root=run_root,
            expected_source_root=expected_source_root,
            expected_product_dir=expected_product_dir,
            expected_run_id=expected_run_id,
            expected_run_dir=expected_run_dir,
            expected_product_id=expected_product_id,
            expected_product_name=expected_product_name,
            expected_line_key=expected_line_key,
            expected_schema_version=expected_schema_version,
            expected_model_id=expected_model_id,
            expected_judge_mode=expected_judge_mode,
            expected_admission_identity=expected_admission_identity,
        )
    except _Fault as fault:
        pause_code = fault.code
    except Exception:
        pause_code = "baseline_artifact_content_mismatch"
    raise AdmissionPausedError(pause_code) from None


def _validate_baseline_result(
    *,
    result: RunResult,
    run_root: Path,
    expected_source_root: Path,
    expected_product_dir: Path,
    expected_run_id: str,
    expected_run_dir: Path,
    expected_product_id: str,
    expected_product_name: str,
    expected_line_key: str,
    expected_schema_version: str,
    expected_model_id: str,
    expected_judge_mode: str,
    expected_admission_identity: BaselineAdmissionIdentity | None,
) -> RunResult:
    expected_values = (
        expected_run_id,
        expected_product_id,
        expected_product_name,
        expected_line_key,
        expected_schema_version,
        expected_model_id,
        expected_judge_mode,
    )
    if any(not isinstance(value, str) or not value.strip() for value in expected_values):
        raise _Fault("baseline_identity_mismatch")
    try:
        expected_product_parts = _baseline_relative(
            expected_product_dir, expected_source_root
        )
        source = _SafeRoot(expected_source_root)
        try:
            source.names(expected_product_parts)
        finally:
            source.close()
    except _Fault:
        raise _Fault("baseline_identity_mismatch") from None
    run_dir = Path(result.manifest.run_dir)
    run_parts = _baseline_relative(run_dir, run_root)
    expected_paths = {
        "pred": run_dir / "pred.jsonl",
        "manifest": run_dir / "manifest.json",
        "judge": run_dir / "judge-queue.jsonl",
        "checkpoint": run_dir / "checkpoint.sqlite3",
        "dead": run_dir / "dead-letters.jsonl",
    }
    if (
        result.pred_path != expected_paths["pred"]
        or result.manifest_path != expected_paths["manifest"]
        or result.judge_queue_path != expected_paths["judge"]
        or Path(result.manifest.checkpoint_path) != expected_paths["checkpoint"]
    ):
        raise _Fault("baseline_artifact_path_unsafe")
    root = _SafeRoot(run_root)
    try:
        try:
            run_names = root.names(run_parts)
            if {
                "checkpoint.sqlite3-wal",
                "checkpoint.sqlite3-shm",
            } & run_names:
                raise _Fault("unsafe")
            pred_bytes = root.read((*run_parts, "pred.jsonl"))
            manifest_bytes = root.read((*run_parts, "manifest.json"))
            judge_bytes = root.read((*run_parts, "judge-queue.jsonl"))
            checkpoint_bytes = root.read(
                (*run_parts, "checkpoint.sqlite3"),
                single_link=True,
            )
            dead_bytes = root.read((*run_parts, "dead-letters.jsonl"))
        except _Fault as fault:
            code = (
                "baseline_artifact_missing"
                if fault.code == "missing"
                else "baseline_artifact_path_unsafe"
            )
            raise _Fault(code) from None
    finally:
        root.close()

    try:
        manifest = RunManifest.model_validate_json(manifest_bytes)
    except ValidationError:
        raise _Fault("baseline_manifest_mismatch") from None
    if manifest != result.manifest:
        raise _Fault("baseline_manifest_mismatch")
    if (
        manifest.run_id != expected_run_id
        or Path(manifest.run_dir) != expected_run_dir
        or Path(manifest.product_dir) != expected_product_dir
        or manifest.product_id != expected_product_id
        or manifest.product_name != expected_product_name
        or manifest.line_key != expected_line_key
        or manifest.schema_version != expected_schema_version
        or manifest.model_id != expected_model_id
        or manifest.judge_mode != expected_judge_mode
    ):
        raise _Fault("baseline_identity_mismatch")
    if (
        expected_admission_identity is not None
        and manifest.baseline_admission != expected_admission_identity
    ):
        raise _Fault("baseline_identity_mismatch")
    _checkpoint_manifest(checkpoint_bytes, manifest)
    pred_records = _parse_jsonl_models(
        pred_bytes, PredRecord, "baseline_artifact_content_mismatch"
    )
    judge_requests = _parse_jsonl_models(
        judge_bytes, JudgeRequest, "baseline_artifact_content_mismatch"
    )
    dead_letters = _parse_jsonl_models(
        dead_bytes, DeadLetter, "baseline_artifact_content_mismatch"
    )
    if pred_records != result.records or dead_letters != manifest.dead_letters:
        raise _Fault("baseline_artifact_content_mismatch")
    manifest_docs = {entry.doc for entry in manifest.docs}
    if not manifest_docs or len(manifest_docs) != len(manifest.docs):
        raise _Fault("baseline_identity_mismatch")
    try:
        for doc in manifest_docs:
            _safe_parts(doc, single=True)
    except _Fault:
        raise _Fault("baseline_identity_mismatch") from None
    if expected_admission_identity is not None:
        if (
            manifest.model_id != expected_admission_identity.extractor_model_id
            or manifest.schema_version != expected_admission_identity.schema_version
            or manifest.template_registry_version
            != expected_admission_identity.template_registry_version
            or manifest_docs != set(expected_admission_identity.pdf_digests)
            or any(
                entry.parser_fingerprint
                != expected_admission_identity.parser_fingerprint
                or entry.file_hash
                != expected_admission_identity.pdf_digests[entry.doc]
                or entry.original_digest
                != expected_admission_identity.pdf_digests[entry.doc]
                for entry in manifest.docs
            )
        ):
            raise _Fault("baseline_identity_mismatch")
    try:
        source = _SafeRoot(expected_source_root)
        try:
            source_names = source.names(expected_product_parts)
            source_pdfs = {
                name for name in source_names if name.casefold().endswith(".pdf")
            }
            if source_pdfs != manifest_docs:
                raise _Fault("baseline_identity_mismatch")
            if any(
                not (pdf_bytes := source.read((*expected_product_parts, doc)))
                or (
                    expected_admission_identity is not None
                    and _sha256(pdf_bytes)
                    != expected_admission_identity.pdf_digests[doc]
                )
                for doc in sorted(manifest_docs)
            ):
                raise _Fault("baseline_identity_mismatch")
        finally:
            source.close()
    except _Fault:
        raise _Fault("baseline_identity_mismatch") from None
    if not pred_records:
        raise _Fault("baseline_artifact_content_mismatch")
    if any(
        record.product_id != expected_product_id
        or record.product_name != expected_product_name
        or record.schema_version != expected_schema_version
        or record.annotator_model != expected_model_id
        or record.doc not in manifest_docs
        for record in pred_records
    ):
        raise _Fault("baseline_identity_mismatch")
    if any(
        dead_letter.product != expected_product_name
        or dead_letter.doc not in manifest_docs
        for dead_letter in dead_letters
    ):
        raise _Fault("baseline_identity_mismatch")
    pending = [record for record in pred_records if record.pending_judge]
    pending_keys = sorted(
        (record.product_id, record.product_name, record.doc, record.field_id, record.field_name)
        for record in pending
    )
    judge_keys = sorted(
        (
            request.product_id,
            request.product_name,
            request.doc,
            request.field_id,
            request.field_name,
        )
        for request in judge_requests
    )
    if (
        manifest.pending_judge_count != len(pending)
        or len(judge_requests) != manifest.pending_judge_count
        or judge_keys != pending_keys
    ):
        raise _Fault("baseline_artifact_content_mismatch")
    return result


__all__ = [
    "directory_parser_fingerprint",
    "render_annotation_artifacts",
    "validate_annotation_bundle",
    "validate_baseline_commit_candidate",
    "validate_baseline_result",
]

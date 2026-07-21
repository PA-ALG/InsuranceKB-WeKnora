"""产品级标注编排：险种推断、断点续跑缓存、逐文档标注+自检（spec G2.4/G2.5）。"""

import json
import os
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ..schemas import SchemaRegistry
from .annotator import GoldenAnnotator
from .pdf import extract_pages
from .records import GoldenRecord
from .verify import compare_with_meta, load_product_meta, verify_quotes

# 产品目录名关键词 → 险种 line_key（顺序即优先级：先匹配更具体的）
_LINE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("失能收入", "disability-income"),
    ("护理保险", "long-term-care"),
    ("意外伤害", "accident"),
    ("意外医疗", "accident-medical"),
    ("长期医疗", "medical"),
    ("医疗保险", "medical"),
    ("重大疾病", "critical-illness"),
    ("重疾", "critical-illness"),
    ("两全保险", "endowment"),
    ("终身寿险", "whole-life"),
    ("定期寿险", "term-life"),
    ("养老年金", "annuity"),
    ("年金保险", "annuity"),
    ("补充养老", "supplementary-pension"),
)


class UnknownProductLineError(Exception):
    """无法从产品名推断险种；正确归属优先于自动化（master plan §1.2），报错交人工。"""


class CacheSecurityError(Exception):
    """断点缓存不满足私有、no-follow、身份一致性约束。"""


def infer_line_key(product_name: str) -> str:
    for keyword, line_key in _LINE_KEYWORDS:
        if keyword in product_name:
            return line_key
    raise UnknownProductLineError(
        f"无法从产品名推断险种：{product_name!r}——请在 _LINE_KEYWORDS 登记或人工指定"
    )


def _single_component(value: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise CacheSecurityError("unsafe cache component")
    return value


def _cache_name(doc: str, schema_version: str) -> str:
    schema_hash = schema_version.split("+")[-1]
    return f"{_single_component(doc)}.{_single_component(schema_hash)}.jsonl"


def _private_stat(value: os.stat_result, *, directory: bool) -> None:
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        raise CacheSecurityError("cache permission mismatch")


def _open_private_dir(parent_fd: int, name: str, *, create: bool) -> int:
    name = _single_component(name)
    created = False
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass
        except OSError as exc:
            raise CacheSecurityError("cache directory creation failed") from exc
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        if created:
            os.fchmod(descriptor, 0o700)
        _private_stat(os.fstat(descriptor), directory=True)
        return descriptor
    except (OSError, CacheSecurityError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise CacheSecurityError("unsafe cache directory") from exc


class _ProductCache:
    """Private cache rooted at a trusted caller-selected parent directory."""

    def __init__(self, cache_dir: Path, product: str, *, create: bool) -> None:
        if not cache_dir.is_absolute():
            raise CacheSecurityError("cache root must be absolute")
        self._root_fd = -1
        self._product_fd = -1
        try:
            parent_fd = os.open(
                cache_dir.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                self._root_fd = _open_private_dir(
                    parent_fd, cache_dir.name, create=create
                )
            finally:
                os.close(parent_fd)
            self._product_fd = _open_private_dir(
                self._root_fd, product, create=create
            )
        except (OSError, CacheSecurityError) as exc:
            self.close()
            raise CacheSecurityError("unsafe cache root") from exc

    def close(self) -> None:
        if self._product_fd >= 0:
            os.close(self._product_fd)
            self._product_fd = -1
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    def __enter__(self) -> "_ProductCache":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def exists(self, name: str) -> bool:
        try:
            os.stat(name, dir_fd=self._product_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CacheSecurityError("cache lookup failed") from exc
        return True

    def read(self, name: str) -> bytes:
        try:
            descriptor = os.open(
                _single_component(name),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=self._product_fd,
            )
            try:
                metadata = os.fstat(descriptor)
                _private_stat(metadata, directory=False)
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                os.close(descriptor)
        except (OSError, CacheSecurityError) as exc:
            raise CacheSecurityError("unsafe cache file") from exc

    def write(self, name: str, payload: bytes) -> None:
        name = _single_component(name)
        temporary = f".{name}.{secrets.token_hex(12)}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
                dir_fd=self._product_fd,
            )
            os.fchmod(descriptor, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise CacheSecurityError("cache write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=self._product_fd,
                    dst_dir_fd=self._product_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                if self.read(name) != payload:
                    raise CacheSecurityError(
                        "cache already exists with different bytes"
                    ) from None
            os.fsync(self._product_fd)
        except (OSError, CacheSecurityError) as exc:
            raise CacheSecurityError("atomic cache write failed") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=self._product_fd)
            except FileNotFoundError:
                pass
            else:
                os.fsync(self._product_fd)


def _decode_cache(value: bytes) -> list[GoldenRecord]:
    try:
        return [
            GoldenRecord.model_validate_json(line)
            for line in value.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (UnicodeDecodeError, ValidationError) as exc:
        raise CacheSecurityError("cache JSONL is invalid") from exc


def write_annotation_cache(
    cache_dir: Path,
    product: str,
    doc: str,
    schema_version: str,
    records: list[GoldenRecord],
) -> Path:
    """Atomically publish one private cache file without following links."""

    name = _cache_name(doc, schema_version)
    payload = b"".join(record.model_dump_json().encode("utf-8") + b"\n" for record in records)
    with _ProductCache(cache_dir, _single_component(product), create=True) as cache:
        cache.write(name, payload)
    return cache_dir / product / name


def read_annotation_cache(
    cache_dir: Path,
    product: str,
    doc: str,
    schema_version: str,
    *,
    expected_product_id: str,
) -> list[GoldenRecord]:
    """Read an idempotent cache hit and bind every row to its filename identity."""

    name = _cache_name(doc, schema_version)
    with _ProductCache(cache_dir, _single_component(product), create=False) as cache:
        records = _decode_cache(cache.read(name))
    if any(
        record.product_id != expected_product_id
        or record.product_name != product
        or record.doc != doc
        or record.schema_version != schema_version
        for record in records
    ):
        raise CacheSecurityError("cache record identity mismatch")
    return records


async def annotate_product(
    product_dir: Path,
    registry: SchemaRegistry,
    annotator: GoldenAnnotator,
    cache_dir: Path,
    line_key: str | None = None,
) -> list[GoldenRecord]:
    """标注一个产品目录（PDF×N + product_meta），带断点续跑缓存。"""
    product_name = product_dir.name
    meta = load_product_meta(product_dir)
    product_id = str(meta.get("planCode") or product_name).strip()
    line = registry.line(line_key or infer_line_key(product_name))

    all_records: list[GoldenRecord] = []
    for pdf_path in sorted(product_dir.glob("*.pdf")):
        cache_name = _cache_name(pdf_path.name, registry.version)
        with _ProductCache(cache_dir, product_name, create=True) as product_cache:
            cache_exists = product_cache.exists(cache_name)
        if cache_exists:  # G2.5：schema 版本未变则跳过
            all_records.extend(
                read_annotation_cache(
                    cache_dir,
                    product_name,
                    pdf_path.name,
                    registry.version,
                    expected_product_id=product_id,
                )
            )
            continue
        pages = extract_pages(pdf_path)
        records = await annotator.annotate_document(
            product_id=product_id,
            product_name=product_name,
            doc_name=pdf_path.name,
            pages=pages,
            line=line,
            created_at=datetime.now(UTC),
        )
        verify_quotes(records, pages)
        compare_with_meta(records, meta)
        write_annotation_cache(
            cache_dir,
            product_name,
            pdf_path.name,
            registry.version,
            records,
        )
        all_records.extend(records)
    return all_records


def write_jsonl(records: list[GoldenRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(r.model_dump_json() for r in records) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[GoldenRecord]:
    return [
        GoldenRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_release(release_dir: Path) -> list[GoldenRecord]:
    """读一个金标 release 目录的全部记录。

    跳过非金标记录文件：disputed.jsonl（复核清单副本）与 keypoints.jsonl
    （long 字段要点清单，005 V1.2）。
    """
    records: list[GoldenRecord] = []
    for p in sorted(release_dir.glob("*.jsonl")):
        if p.name in ("disputed.jsonl", "keypoints.jsonl"):
            continue
        records.extend(read_jsonl(p))
    if not records:
        raise FileNotFoundError(f"{release_dir} 中没有金标记录")
    return records


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"无法序列化 {type(obj).__name__}")


def dump_json(data: object, path: Path) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )

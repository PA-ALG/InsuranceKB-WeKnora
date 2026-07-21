"""Fail-closed, code-owned input identity checks for Golden run admission."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    field_serializer,
    model_validator,
)

from insurance_harness.goldenset.admission_models import (
    HistoricalProvenance,
    ProductInputSelection,
    canonical_json_bytes,
)

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
type BlockerCode = Literal[
    "absolute_path",
    "dependency_not_ancestor",
    "dependency_revision_mismatch",
    "dependency_set_mismatch",
    "digest_mismatch",
    "dirty_consumed_file",
    "duplicate_historical_provenance",
    "duplicate_product",
    "execution_surface_unpinned",
    "extra_historical_product",
    "extra_product",
    "identity_configuration_error",
    "line_key_mismatch",
    "missing_historical_provenance",
    "missing_historical_product",
    "missing_path",
    "missing_product",
    "path_escape",
    "policy_mismatch",
    "shared_input_unpinned",
    "unconsumed_product_file",
    "unknown_historical_provenance",
    "untracked_consumed_file",
]

_PRODUCTION_PRODUCT_LINES = MappingProxyType(
    {
        "平安e生保（尊享版）医疗保险": "medical",
        "平安e生保（悦享版）医疗保险": "medical",
        "平安e生保（惠享版）长期医疗保险（费率可调）": "medical",
        "平安创享盛世金越（尊享版26）终身寿险（分红型）": "whole-life",
        "平安守护百分百（2026）两全保险": "endowment",
        "平安爱满分（2026）两全保险": "endowment",
        "平安盛世金越养老年金保险（分红型）": "annuity",
        "平安盛世金越（尊享版26）终身寿险": "whole-life",
        "平安盛世金越（尊享版26）终身寿险（分红型）": "whole-life",
        "平安盛世金越（至尊版26）年金保险（分红型）": "annuity",
        "平安福满分（2026）养老年金保险": "annuity",
        "平安附加（2026）失能收入损失保险": "disability-income",
        "平安附加（2026）意外伤害保险": "accident",
    }
)
_NEW_PRODUCT_IDS = frozenset(
    {"平安爱满分（2026）两全保险", "平安附加（2026）意外伤害保险"}
)
_PRODUCTION_DEPENDENCY_REVISIONS = MappingProxyType(
    {
        "019": "4d9c84e25bd53f3564631b8f8dc0b1f85e21e55f",
        "021": "cfefcc9b3a7d6af0503f3b76cf8ac5a1b6d44b35",
    }
)
_CACHE_COMPONENTS = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
_IDENTITY_CONTRACT_DOMAIN = b"insurancekb.run-admission.identity-contract.v1\0"


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class IdentityInspectionBlocker(_ImmutableModel):
    code: BlockerCode
    message: NonBlankStr
    path: StrictStr | None = None
    subject: StrictStr | None = None
    product_id: StrictStr | None = None


class IdentityInspectionRequest(_ImmutableModel):
    required_dependency_revisions: Mapping[NonBlankStr, NonBlankStr]
    source_products_root: NonBlankStr
    golden_products_root: NonBlankStr
    products: tuple[ProductInputSelection, ...]
    shared_input_digests: Mapping[NonBlankStr, NonBlankStr]
    execution_surface_digests: Mapping[NonBlankStr, NonBlankStr]
    historical_product_ids: tuple[NonBlankStr, ...]
    historical_provenance: tuple[HistoricalProvenance, ...]

    @model_validator(mode="after")
    def freeze_mappings(self) -> IdentityInspectionRequest:
        for field_name in (
            "required_dependency_revisions",
            "shared_input_digests",
            "execution_surface_digests",
        ):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )
        return self

    @field_serializer(
        "required_dependency_revisions",
        "shared_input_digests",
        "execution_surface_digests",
    )
    def serialize_mapping(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class IdentityInspectionResult(_ImmutableModel):
    evaluated_revision: NonBlankStr
    product_digests: Mapping[NonBlankStr, NonBlankStr]
    shared_input_digest: NonBlankStr
    execution_surface_digest: NonBlankStr
    blockers: tuple[IdentityInspectionBlocker, ...]

    @model_validator(mode="after")
    def freeze_product_digests(self) -> IdentityInspectionResult:
        object.__setattr__(
            self, "product_digests", MappingProxyType(dict(self.product_digests))
        )
        return self

    @field_serializer("product_digests")
    def serialize_product_digests(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


def identity_contract_hash(request: IdentityInspectionRequest) -> str:
    """Bind every deterministic input/provenance declaration into the signed plan."""

    return hashlib.sha256(
        _IDENTITY_CONTRACT_DOMAIN + canonical_json_bytes(request)
    ).hexdigest()


@dataclass(frozen=True)
class _IdentityPolicy:
    product_lines: Mapping[str, str]
    historical_product_ids: frozenset[str]
    source_products_root: str
    golden_products_root: str
    execution_roots: tuple[str, ...]
    shared_roots: tuple[str, ...]
    required_shared_paths: tuple[str, ...]
    source_root_files: frozenset[str]
    golden_root_files: frozenset[str]
    required_dependency_revisions: Mapping[str, str]


def _production_policy() -> _IdentityPolicy:
    return _IdentityPolicy(
        product_lines=_PRODUCTION_PRODUCT_LINES,
        historical_product_ids=frozenset(_PRODUCTION_PRODUCT_LINES) - _NEW_PRODUCT_IDS,
        source_products_root="dataset/shouxian_product",
        golden_products_root="dataset/goldenset/wip-gs-v0.1",
        execution_roots=(
            "harness/src/insurance_harness",
            "harness/pyproject.toml",
            "harness/uv.lock",
        ),
        shared_roots=(
            "dataset/templates",
            "docs/insurance-kb/schema-baseline",
        ),
        required_shared_paths=(
            "dataset/goldenset/wip-gs-v0.1/manifest.json",
            "dataset/goldenset/wip-gs-v0.1/build_golden.py",
            "dataset/goldenset/wip-gs-v0.1/assemble_release.py",
        ),
        source_root_files=frozenset(),
        golden_root_files=frozenset(
            {"manifest.json", "build_golden.py", "assemble_release.py"}
        ),
        required_dependency_revisions=_PRODUCTION_DEPENDENCY_REVISIONS,
    )


class DeterministicIdentityInspector:
    """Inspect against production policy; callers cannot replace that policy."""

    def __init__(self, *, repo_root: Path) -> None:
        self._initialize(repo_root, _production_policy())

    @classmethod
    def _for_testing(
        cls,
        *,
        repo_root: Path,
        expected_product_lines: Mapping[str, str],
        historical_product_ids: frozenset[str],
        source_products_root: str,
        golden_products_root: str,
        execution_roots: tuple[str, ...],
        shared_roots: tuple[str, ...],
        required_dependency_revisions: Mapping[str, str],
        required_shared_paths: tuple[str, ...] = (),
        source_root_files: frozenset[str] = frozenset(),
        golden_root_files: frozenset[str] = frozenset(),
    ) -> DeterministicIdentityInspector:
        """Explicit internal seam for isolated temporary-repository tests only."""

        instance = cls.__new__(cls)
        instance._initialize(
            repo_root,
            _IdentityPolicy(
                product_lines=MappingProxyType(dict(expected_product_lines)),
                historical_product_ids=historical_product_ids,
                source_products_root=source_products_root,
                golden_products_root=golden_products_root,
                execution_roots=execution_roots,
                shared_roots=shared_roots,
                required_shared_paths=required_shared_paths,
                source_root_files=source_root_files,
                golden_root_files=golden_root_files,
                required_dependency_revisions=MappingProxyType(
                    dict(required_dependency_revisions)
                ),
            ),
        )
        return instance

    def _initialize(self, repo_root: Path, policy: _IdentityPolicy) -> None:
        self._repo_root = repo_root.resolve(strict=True)
        self._policy = policy

    def inspect(self, request: IdentityInspectionRequest) -> IdentityInspectionResult:
        blockers: list[IdentityInspectionBlocker] = []
        evaluated_revision = self._evaluated_revision(blockers)
        self._inspect_policy_contract(request, blockers)
        self._inspect_dependencies(request, evaluated_revision, blockers)

        if request.source_products_root != self._policy.source_products_root:
            self._resolve_relative(request.source_products_root, blockers)
        if request.golden_products_root != self._policy.golden_products_root:
            self._resolve_relative(request.golden_products_root, blockers)
        policy_source_root = self._resolve_relative(
            self._policy.source_products_root, blockers
        )
        policy_golden_root = self._resolve_relative(
            self._policy.golden_products_root, blockers
        )
        product_digests: dict[str, str] = {}
        if policy_source_root is not None and policy_golden_root is not None:
            self._inspect_products(
                request,
                policy_source_root,
                policy_golden_root,
                product_digests,
                blockers,
            )

        shared_observed = self._inspect_shared_inputs(request, blockers)
        shared_input_digest = hashlib.sha256(
            canonical_json_bytes(shared_observed)
        ).hexdigest()
        execution_observed = self._inspect_execution_surface(request, blockers)
        execution_surface_digest = hashlib.sha256(
            canonical_json_bytes(execution_observed)
        ).hexdigest()

        consumed_roots = self._consumed_roots(
            policy_source_root, policy_golden_root
        )
        self._inspect_git_pollution(consumed_roots, blockers)
        self._inspect_historical_provenance(request, blockers)
        return IdentityInspectionResult(
            evaluated_revision=evaluated_revision,
            product_digests=product_digests,
            shared_input_digest=shared_input_digest,
            execution_surface_digest=execution_surface_digest,
            blockers=tuple(blockers),
        )

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", *args),
            cwd=self._repo_root,
            check=False,
            capture_output=True,
            text=True,
        )

    def _configuration_error(
        self, message: str, blockers: list[IdentityInspectionBlocker]
    ) -> None:
        blockers.append(
            IdentityInspectionBlocker(
                code="identity_configuration_error", message=message
            )
        )

    def _evaluated_revision(
        self, blockers: list[IdentityInspectionBlocker]
    ) -> str:
        completed = self._git("rev-parse", "HEAD")
        revision = completed.stdout.strip()
        if completed.returncode != 0 or not revision:
            self._configuration_error("git rev-parse HEAD failed", blockers)
            return "<git-revision-unavailable>"
        return revision

    def _inspect_policy_contract(
        self,
        request: IdentityInspectionRequest,
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        if request.source_products_root != self._policy.source_products_root:
            blockers.append(
                IdentityInspectionBlocker(
                    code="policy_mismatch",
                    path=request.source_products_root,
                    message="source product root differs from code-owned policy",
                )
            )
        if request.golden_products_root != self._policy.golden_products_root:
            blockers.append(
                IdentityInspectionBlocker(
                    code="policy_mismatch",
                    path=request.golden_products_root,
                    message="Golden product root differs from code-owned policy",
                )
            )
        expected_ids = set(self._policy.product_lines)
        counts = Counter(product.product_id for product in request.products)
        for product_id, count in sorted(counts.items()):
            if count > 1:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="duplicate_product",
                        product_id=product_id,
                        message=f"product appears {count} times in identity plan",
                    )
                )
        for product_id in sorted(expected_ids - set(counts)):
            blockers.append(
                IdentityInspectionBlocker(
                    code="missing_product",
                    product_id=product_id,
                    message=f"code-owned product is absent from plan: {product_id}",
                )
            )
        for product_id in sorted(set(counts) - expected_ids):
            blockers.append(
                IdentityInspectionBlocker(
                    code="extra_product",
                    product_id=product_id,
                    message=f"plan contains a non-policy product: {product_id}",
                )
            )
        for product in request.products:
            expected_line = self._policy.product_lines.get(product.product_id)
            if expected_line is not None and product.line_key != expected_line:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="line_key_mismatch",
                        product_id=product.product_id,
                        message=(
                            f"line key {product.line_key!r} does not match "
                            f"code-owned {expected_line!r}"
                        ),
                    )
                )

    def _inspect_dependencies(
        self,
        request: IdentityInspectionRequest,
        evaluated_revision: str,
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        expected_revisions = self._policy.required_dependency_revisions
        actual_keys = set(request.required_dependency_revisions)
        expected_keys = set(expected_revisions)
        for subject in sorted(expected_keys - actual_keys):
            blockers.append(
                IdentityInspectionBlocker(
                    code="dependency_set_mismatch",
                    subject=subject,
                    message=f"required dependency pin is missing: {subject}",
                )
            )
        for subject in sorted(actual_keys - expected_keys):
            blockers.append(
                IdentityInspectionBlocker(
                    code="dependency_set_mismatch",
                    subject=subject,
                    message=f"unexpected dependency pin is not policy-owned: {subject}",
                )
            )
        if evaluated_revision.startswith("<"):
            return
        for subject in sorted(actual_keys & expected_keys):
            revision = request.required_dependency_revisions[subject]
            if revision != expected_revisions[subject]:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="dependency_revision_mismatch",
                        subject=subject,
                        message=(
                            f"dependency {subject} does not pin the code-designated "
                            "merge revision"
                        ),
                    )
                )
                continue
            completed = self._git(
                "merge-base", "--is-ancestor", revision, evaluated_revision
            )
            if completed.returncode == 1:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="dependency_not_ancestor",
                        subject=subject,
                        message=(
                            f"required dependency {subject} at {revision} is not an "
                            f"ancestor of {evaluated_revision}"
                        ),
                    )
                )
            elif completed.returncode != 0:
                self._configuration_error(
                    f"git merge-base failed for dependency {subject}", blockers
                )

    def _resolve_relative(
        self,
        relative_path: str,
        blockers: list[IdentityInspectionBlocker],
        *,
        product_id: str | None = None,
    ) -> Path | None:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or Path(relative_path).is_absolute():
            blockers.append(
                IdentityInspectionBlocker(
                    code="absolute_path",
                    path=relative_path,
                    product_id=product_id,
                    message=f"consumed path must be repository-relative: {relative_path}",
                )
            )
            return None
        if ".." in pure.parts:
            blockers.append(
                IdentityInspectionBlocker(
                    code="path_escape",
                    path=relative_path,
                    product_id=product_id,
                    message=f"parent traversal is forbidden: {relative_path}",
                )
            )
            return None
        candidate = self._repo_root.joinpath(*pure.parts)
        current = self._repo_root
        for part in pure.parts:
            current /= part
            try:
                if current.is_symlink():
                    blockers.append(
                        IdentityInspectionBlocker(
                            code="path_escape",
                            path=relative_path,
                            product_id=product_id,
                            message=f"consumed path contains a symlink: {relative_path}",
                        )
                    )
                    return None
            except OSError:
                pass
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._repo_root):
            blockers.append(
                IdentityInspectionBlocker(
                    code="path_escape",
                    path=relative_path,
                    product_id=product_id,
                    message=f"consumed path resolves outside repository: {relative_path}",
                )
            )
            return None
        return resolved

    def _before_final_open(self, relative_path: str) -> None:
        """Test-only race hook; production intentionally performs no action."""

    def _safe_sha256(
        self,
        relative_path: str,
        blockers: list[IdentityInspectionBlocker],
        *,
        product_id: str | None = None,
    ) -> str | None:
        """Hash a regular file through no-follow directory descriptors.

        Every parent is opened relative to the already-opened parent descriptor and
        the final file is opened with ``O_NOFOLLOW``. This closes the lstat/open race
        without trusting a later pathname resolution.
        """

        if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")):
            self._configuration_error(
                "platform lacks O_DIRECTORY/O_NOFOLLOW required for safe hashing",
                blockers,
            )
            return None
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            blockers.append(
                IdentityInspectionBlocker(
                    code="path_escape",
                    path=relative_path,
                    product_id=product_id,
                    message=f"unsafe repository-relative hash path: {relative_path}",
                )
            )
            return None

        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_NOFOLLOW
        opened_directories: list[int] = []
        file_descriptor: int | None = None
        try:
            parent_fd = os.open(self._repo_root, directory_flags)
            opened_directories.append(parent_fd)
            for component in pure.parts[:-1]:
                parent_fd = os.open(component, directory_flags, dir_fd=parent_fd)
                opened_directories.append(parent_fd)
            self._before_final_open(relative_path)
            file_descriptor = os.open(
                pure.parts[-1], file_flags, dir_fd=opened_directories[-1]
            )
            metadata = os.fstat(file_descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError(errno.EINVAL, "consumed input is not a regular file")
            digest = hashlib.sha256()
            while chunk := os.read(file_descriptor, 1024 * 1024):
                digest.update(chunk)
            return digest.hexdigest()
        except OSError as exc:
            path_code: BlockerCode = (
                "missing_path"
                if exc.errno in {errno.ENOENT}
                else "path_escape"
            )
            blockers.append(
                IdentityInspectionBlocker(
                    code=path_code,
                    path=relative_path,
                    product_id=product_id,
                    message=f"safe no-follow hash open failed: {relative_path}",
                )
            )
            return None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            for directory_fd in reversed(opened_directories):
                os.close(directory_fd)

    def _actual_product_ids(self, root: Path) -> set[str]:
        if not root.is_dir():
            return set()
        return {
            path.name for path in root.iterdir() if path.is_dir() or path.is_symlink()
        }

    def _inspect_products(
        self,
        request: IdentityInspectionRequest,
        source_root: Path,
        golden_root: Path,
        product_digests: dict[str, str],
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        expected_ids = set(self._policy.product_lines)
        self._inspect_product_root_files(
            source_root,
            self._policy.source_products_root,
            self._policy.source_root_files,
            blockers,
        )
        self._inspect_product_root_files(
            golden_root,
            self._policy.golden_products_root,
            self._policy.golden_root_files,
            blockers,
        )
        for label, actual_ids in (
            ("source", self._actual_product_ids(source_root)),
            ("golden", self._actual_product_ids(golden_root)),
        ):
            for product_id in sorted(expected_ids - actual_ids):
                blockers.append(
                    IdentityInspectionBlocker(
                        code="missing_product",
                        subject=label,
                        product_id=product_id,
                        message=f"{label} product directory is missing: {product_id}",
                    )
                )
            for product_id in sorted(actual_ids - expected_ids):
                blockers.append(
                    IdentityInspectionBlocker(
                        code="extra_product",
                        subject=label,
                        product_id=product_id,
                        message=f"unexpected {label} product directory: {product_id}",
                    )
                )

        counts = Counter(product.product_id for product in request.products)
        for plan in request.products:
            if counts[plan.product_id] != 1 or plan.product_id not in expected_ids:
                continue
            source_relative = f"{self._policy.source_products_root}/{plan.product_id}"
            golden_relative = f"{self._policy.golden_products_root}/{plan.product_id}"
            source_product = self._resolve_relative(
                source_relative, blockers, product_id=plan.product_id
            )
            golden_product = self._resolve_relative(
                golden_relative, blockers, product_id=plan.product_id
            )
            if source_product is None or golden_product is None:
                continue
            if not source_product.is_dir() or not golden_product.is_dir():
                continue
            observed: dict[str, dict[str, str]] = {}
            source_expected = dict(plan.pdf_digests)
            golden_expected = dict(plan.consumed_input_digests)
            if plan.product_meta_digest is None:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="missing_path",
                        path=f"{source_relative}/product_meta.json",
                        product_id=plan.product_id,
                        message="required product_meta.json is explicitly pending",
                    )
                )
            else:
                source_expected["product_meta.json"] = plan.product_meta_digest
            if plan.fields_digest is None:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="missing_path",
                        path=f"{golden_relative}/fields.json",
                        product_id=plan.product_id,
                        message="required fields.json is explicitly pending",
                    )
                )
            else:
                golden_expected["fields.json"] = plan.fields_digest
            self._inspect_product_tree(
                root=source_product,
                root_relative=source_relative,
                namespace="source",
                expected=source_expected,
                product_id=plan.product_id,
                observed=observed,
                blockers=blockers,
            )
            self._inspect_product_tree(
                root=golden_product,
                root_relative=golden_relative,
                namespace="golden",
                expected=golden_expected,
                product_id=plan.product_id,
                observed=observed,
                blockers=blockers,
            )
            product_digests[plan.product_id] = hashlib.sha256(
                canonical_json_bytes(observed)
            ).hexdigest()

    def _inspect_product_root_files(
        self,
        root: Path,
        root_relative: str,
        expected_names: frozenset[str],
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        actual_names = {
            path.name
            for path in root.iterdir()
            if path.is_symlink() or not path.is_dir()
        }
        for name in sorted(expected_names - actual_names):
            relative = f"{root_relative}/{name}"
            blockers.append(
                IdentityInspectionBlocker(
                    code="missing_path",
                    path=relative,
                    message=f"required product-root control file is missing: {relative}",
                )
            )
        for name in sorted(actual_names - expected_names):
            relative = f"{root_relative}/{name}"
            blockers.append(
                IdentityInspectionBlocker(
                    code="unconsumed_product_file",
                    path=relative,
                    message=f"product-root file is not code-owned: {relative}",
                )
            )
        for name in sorted(actual_names):
            self._safe_sha256(f"{root_relative}/{name}", blockers)

    def _tree_file_names(self, root: Path) -> set[str]:
        names: set[str] = set()
        for candidate in root.rglob("*"):
            if self._excluded_consumed_path(candidate):
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                names.add(candidate.relative_to(root).as_posix())
        return names

    def _inspect_product_tree(
        self,
        *,
        root: Path,
        root_relative: str,
        namespace: str,
        expected: Mapping[str, str],
        product_id: str,
        observed: dict[str, dict[str, str]],
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        actual_names = self._tree_file_names(root)
        expected_names = set(expected)
        for name in sorted(actual_names - expected_names):
            relative = f"{root_relative}/{name}"
            blockers.append(
                IdentityInspectionBlocker(
                    code="unconsumed_product_file",
                    path=relative,
                    product_id=product_id,
                    message=f"actual product input is not pinned: {relative}",
                )
            )
        for name in sorted(expected_names - actual_names):
            relative = f"{root_relative}/{name}"
            code: BlockerCode = (
                "digest_mismatch"
                if namespace == "source" and name.casefold().endswith(".pdf")
                else "missing_path"
            )
            blockers.append(
                IdentityInspectionBlocker(
                    code=code,
                    path=relative,
                    product_id=product_id,
                    message=f"pinned product input is missing: {relative}",
                )
            )
        for name in sorted(actual_names):
            relative = f"{root_relative}/{name}"
            digest = self._safe_sha256(
                relative, blockers, product_id=product_id
            )
            observed[f"{namespace}/{name}"] = {
                "type": "file" if digest is not None else "rejected",
                "sha256": digest or "<rejected>",
            }
            if (
                name in expected
                and digest is not None
                and digest != expected[name]
            ):
                blockers.append(
                    IdentityInspectionBlocker(
                        code="digest_mismatch",
                        path=relative,
                        product_id=product_id,
                        message=f"observed digest does not match pinned digest: {relative}",
                    )
                )

    def _excluded_consumed_path(self, path: Path) -> bool:
        relative = path.relative_to(self._repo_root)
        return bool(set(relative.parts) & _CACHE_COMPONENTS) or path.suffix == ".pyc"

    def _shared_files(
        self, blockers: list[IdentityInspectionBlocker]
    ) -> set[str]:
        observed_paths: set[str] = set()
        for root_relative in self._policy.shared_roots:
            root = self._resolve_relative(root_relative, blockers)
            if root is None:
                continue
            if not root.is_dir():
                blockers.append(
                    IdentityInspectionBlocker(
                        code="missing_path",
                        path=root_relative,
                        message=f"code-owned shared root is missing: {root_relative}",
                    )
                )
                continue
            for candidate in root.rglob("*"):
                if self._excluded_consumed_path(candidate):
                    continue
                if candidate.is_symlink() or not candidate.is_dir():
                    observed_paths.add(
                        candidate.relative_to(self._repo_root).as_posix()
                    )
        for relative in self._policy.required_shared_paths:
            path = self._resolve_relative(relative, blockers)
            if path is None or not path.is_file():
                blockers.append(
                    IdentityInspectionBlocker(
                        code="missing_path",
                        path=relative,
                        message=f"required code-owned shared file is missing: {relative}",
                    )
                )
            else:
                observed_paths.add(relative)
        return observed_paths

    def _inspect_shared_inputs(
        self,
        request: IdentityInspectionRequest,
        blockers: list[IdentityInspectionBlocker],
    ) -> dict[str, dict[str, str]]:
        actual_paths = self._shared_files(blockers)
        expected_paths = set(request.shared_input_digests)
        for relative in sorted(actual_paths - expected_paths):
            blockers.append(
                IdentityInspectionBlocker(
                    code="shared_input_unpinned",
                    path=relative,
                    message=f"actual shared input is not pinned: {relative}",
                )
            )
        for relative in sorted(expected_paths - actual_paths):
            blockers.append(
                IdentityInspectionBlocker(
                    code="missing_path",
                    path=relative,
                    message=f"pinned shared input is outside code-owned selection: {relative}",
                )
            )
        observed: dict[str, dict[str, str]] = {}
        for relative in sorted(actual_paths):
            digest = self._safe_sha256(relative, blockers)
            observed[relative] = {
                "type": "file" if digest is not None else "rejected",
                "sha256": digest or "<rejected>",
            }
            if (
                relative in request.shared_input_digests
                and digest is not None
                and digest != request.shared_input_digests[relative]
            ):
                blockers.append(
                    IdentityInspectionBlocker(
                        code="digest_mismatch",
                        path=relative,
                        message=f"shared input digest changed: {relative}",
                    )
                )
        return observed

    def _execution_files(
        self, blockers: list[IdentityInspectionBlocker]
    ) -> dict[str, dict[str, str]]:
        observed: dict[str, dict[str, str]] = {}
        for root_relative in self._policy.execution_roots:
            root = self._resolve_relative(root_relative, blockers)
            if root is None:
                continue
            candidates = [root] if root.is_file() else sorted(root.rglob("*"))
            for candidate in candidates:
                if self._excluded_consumed_path(candidate):
                    continue
                relative = candidate.relative_to(self._repo_root).as_posix()
                safe = self._resolve_relative(relative, blockers)
                if safe is None:
                    observed[relative] = {"type": "symlink", "sha256": "<rejected>"}
                    continue
                if safe.is_dir():
                    continue
                if not safe.is_file():
                    observed[relative] = {"type": "other", "sha256": "<unreadable>"}
                    continue
                digest = self._safe_sha256(relative, blockers)
                observed[relative] = {
                    "type": "file" if digest is not None else "rejected",
                    "sha256": digest or "<rejected>",
                }
        return dict(sorted(observed.items()))

    def _inspect_execution_surface(
        self,
        request: IdentityInspectionRequest,
        blockers: list[IdentityInspectionBlocker],
    ) -> dict[str, dict[str, str]]:
        observed = self._execution_files(blockers)
        expected_paths = set(request.execution_surface_digests)
        observed_paths = set(observed)
        for relative in sorted(observed_paths - expected_paths):
            blockers.append(
                IdentityInspectionBlocker(
                    code="execution_surface_unpinned",
                    path=relative,
                    message=f"execution-surface file is not pinned: {relative}",
                )
            )
        for relative in sorted(expected_paths - observed_paths):
            blockers.append(
                IdentityInspectionBlocker(
                    code="missing_path",
                    path=relative,
                    message=f"pinned execution-surface file is missing: {relative}",
                )
            )
        for relative in sorted(expected_paths & observed_paths):
            if observed[relative]["sha256"] != request.execution_surface_digests[relative]:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="digest_mismatch",
                        path=relative,
                        message=f"execution-surface digest changed: {relative}",
                    )
                )
        return observed

    def _consumed_roots(
        self,
        source_root: Path | None,
        golden_root: Path | None,
    ) -> tuple[str, ...]:
        roots = set(self._policy.execution_roots) | set(self._policy.shared_roots)
        roots.update(
            str(PurePosixPath(relative).parent)
            for relative in self._policy.required_shared_paths
        )
        for root in (source_root, golden_root):
            if root is not None:
                roots.add(root.relative_to(self._repo_root).as_posix())
        return tuple(sorted(roots))

    def _inspect_git_pollution(
        self,
        roots: Sequence[str],
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        if not roots:
            return
        completed = self._git(
            "--literal-pathspecs",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *roots,
        )
        if completed.returncode != 0:
            self._configuration_error("git status failed for consumed roots", blockers)
            return
        records = completed.stdout.split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4:
                self._configuration_error("malformed git status record", blockers)
                continue
            status = record[:2]
            path = record[3:]
            if "R" in status or "C" in status:
                index += 1
            if self._is_explicit_cache_path(path):
                continue
            code: BlockerCode = (
                "untracked_consumed_file" if status == "??" else "dirty_consumed_file"
            )
            blockers.append(
                IdentityInspectionBlocker(
                    code=code,
                    path=path,
                    message=f"consumed root contains {code}: {path}",
                )
            )

    def _is_explicit_cache_path(self, relative: str) -> bool:
        parts = PurePosixPath(relative).parts
        return bool(set(parts) & _CACHE_COMPONENTS) or relative.endswith(".pyc")

    def _inspect_historical_provenance(
        self,
        request: IdentityInspectionRequest,
        blockers: list[IdentityInspectionBlocker],
    ) -> None:
        expected = self._policy.historical_product_ids
        declared_counts = Counter(request.historical_product_ids)
        for product_id in sorted(expected - set(declared_counts)):
            blockers.append(
                IdentityInspectionBlocker(
                    code="missing_historical_product",
                    product_id=product_id,
                    message=f"historical product is absent from policy manifest: {product_id}",
                )
            )
        for product_id in sorted(set(declared_counts) - expected):
            blockers.append(
                IdentityInspectionBlocker(
                    code="extra_historical_product",
                    product_id=product_id,
                    message=f"non-historical product is declared historical: {product_id}",
                )
            )
        for product_id, count in sorted(declared_counts.items()):
            if count > 1:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="extra_historical_product",
                        product_id=product_id,
                        message=f"historical product id appears {count} times: {product_id}",
                    )
                )

        provenance_counts = Counter(
            item.product_id for item in request.historical_provenance
        )
        for product_id in request.historical_product_ids:
            count = provenance_counts[product_id]
            if count == 0:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="missing_historical_provenance",
                        product_id=product_id,
                        message=f"historical product lacks provenance: {product_id}",
                    )
                )
            elif count > 1:
                blockers.append(
                    IdentityInspectionBlocker(
                        code="duplicate_historical_provenance",
                        product_id=product_id,
                        message=f"historical product has duplicate provenance: {product_id}",
                    )
                )
        for product_id in sorted(set(provenance_counts) - expected):
            blockers.append(
                IdentityInspectionBlocker(
                    code="unknown_historical_provenance",
                    product_id=product_id,
                    message=f"provenance targets a non-historical product: {product_id}",
                )
            )


__all__ = [
    "DeterministicIdentityInspector",
    "IdentityInspectionBlocker",
    "IdentityInspectionRequest",
    "IdentityInspectionResult",
    "identity_contract_hash",
]

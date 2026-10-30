#!/usr/bin/env python3
"""CI app image plan and digest pull for the BA0 app artifact (I1).

`plan` computes the same BA0 identity, labels and build arguments as a local
`app_artifact.py select-or-build` and exports the same frozen source context, so the
image CI builds carries the labels a local build would. `select` pulls one CI image by
exact digest and writes a BA0 receipt only when the pulled image proves that identity;
a local deploy can then pull instead of building inside the VM.

The App build contract is linux/arm64 only (BA0); amd64 needs its own verified
dependency lock first (Spec docs/design/slices/I1-CI构建镜像.md §6, follow-up I1b).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_base() -> ModuleType:
    # Loaded by path: `python -I` keeps the script directory off sys.path.
    path = Path(__file__).resolve().parent / "app_artifact.py"
    spec = importlib.util.spec_from_file_location("ba0_app_artifact", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/app_artifact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()

CI_REPOSITORY = "ghcr.io/pa-alg/insurancekb-weknora-app"
_PULL_REFERENCE = re.compile(re.escape(CI_REPOSITORY) + r"@sha256:[0-9a-f]{64}")
_MANIFEST = "deploy/local-build/app-build-inputs.v1.json"
_LOCK = "deploy/local-build/app-external-dependencies.v1.json"
_EFFECTIVE_BUILD_ARGS = {"CGO_ENABLED": "1", "GOOS": "linux", "GOARCH": "arm64"}
_SELECTOR = "PULL"


def _identity(root: Path, build_source_head: str, docker_context: str) -> dict[str, Any]:
    integration_head = base._checked_output(
        subprocess.run,
        ("git", "rev-parse", "--verify", "HEAD^{commit}"),
        repo_root=root,
        description="integration commit",
    )
    identity: dict[str, Any] = base.canonical_identity(
        repo_root=root,
        manifest_path=root / _MANIFEST,
        dependency_lock_path=root / _LOCK,
        build_source_head=build_source_head,
        integration_head=integration_head,
        runner=subprocess.run,
        effective_build_args=_EFFECTIVE_BUILD_ARGS,
        environment=os.environ,
        docker_context=docker_context,
    )
    return identity


@contextmanager
def _verified_context(*, root: Path, identity: Mapping[str, Any]) -> Iterator[Path]:
    """The frozen source export of the identity's inputs, checked byte for byte."""

    inputs = json.loads(identity["canonical_bytes"])["inputs"]
    paths = tuple(row["path"] for row in inputs) + (_MANIFEST,)
    with base.frozen_source_context(
        repo_root=root, source_head=identity["build_source_head"], paths=paths
    ) as context:
        for row in inputs:
            digest = hashlib.sha256((context / row["path"]).read_bytes()).hexdigest()
            if digest != row["sha256"]:
                raise base.ArtifactContractError("frozen source input differs from identity")
        yield context


def ci_plan(
    *,
    repo_root: str | os.PathLike[str],
    build_source_head: str,
    context_out: str | os.PathLike[str] | None = None,
    docker_context: str = "colima",
) -> dict[str, Any]:
    """Identity, labels and build arguments for one CI app build; optionally export its context."""

    root = Path(repo_root).resolve(strict=True)
    output = Path(context_out) if context_out is not None else None
    if output is not None and output.exists():
        raise base.ArtifactContractError("plan context output already exists")
    identity = _identity(root, build_source_head, docker_context)
    labels = base._required_labels(identity)
    base._source_metadata(identity)
    with _verified_context(root=root, identity=identity) as context:
        build_args = base._selector_build_args(context, identity)
        if output is not None:
            shutil.copytree(context, output, symlinks=True)
    return {
        "contract": "i1-app-ci-plan.v1",
        "artifact_identity": identity["artifact_identity"],
        "build_source_head": identity["build_source_head"],
        "integration_head": identity["integration_head"],
        "manifest_sha256": identity["manifest_sha256"],
        "dependency_lock_sha256": identity["dependency_lock_sha256"],
        "platform": identity["platform"],
        "target": identity["target"],
        "dockerfile": "docker/Dockerfile.app",
        "labels": dict(labels),
        "build_args": dict(build_args),
    }


def _pulled_image_id(
    runner: base.Runner, *, root: Path, reference: str, docker_context: str
) -> str:
    result = base._docker(
        runner,
        ("docker", "--context", docker_context, "image", "inspect", reference,
         "--format", "{{json .}}"),
        repo_root=root,
        description="pulled image inspect",
    )
    try:
        record = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise base.ArtifactContractError("Docker image inspect returned invalid JSON") from exc
    if not isinstance(record, Mapping):
        raise base.ArtifactContractError("Docker image inspect returned a non-object")
    digests = record.get("RepoDigests")
    if not isinstance(digests, list) or reference not in digests:
        raise base.ArtifactContractError("pulled image does not carry the requested digest")
    image_id = record.get("Id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise base.ArtifactContractError("pulled image has no exact image ID")
    return image_id


def _write_rejected(output: Path, reference: str) -> None:
    """A non-success receipt for this attempt, written before anything is validated."""

    base._write_evidence(
        output,
        {
            "contract": "ba0-app-build-receipt.v1",
            "status": "INCOMPLETE",
            "selector": _SELECTOR,
            "pulled_reference": reference,
            "build_invocations": 0,
        },
    )


def select_pulled_app(
    *,
    repo_root: str | os.PathLike[str],
    identity: Mapping[str, Any],
    reference: str,
    evidence_out: str | os.PathLike[str],
    runner: base.Runner = subprocess.run,
    docker_context: str = "colima",
) -> dict[str, Any]:
    """Pull one CI app image by digest; write a BA0 receipt only if it proves the identity.

    The receipt path is overwritten with a non-success state before any check, so a
    rejection in this call can never leave an earlier PASS receipt in place.
    """

    output = Path(evidence_out)
    _write_rejected(output, reference)
    if _PULL_REFERENCE.fullmatch(reference) is None:
        raise base.ArtifactContractError(
            f"pull reference must be {CI_REPOSITORY}@sha256:<64 hex digest>"
        )
    if docker_context not in base._DOCKER_CONTEXTS:
        raise base.ArtifactContractError("Docker context is not approved")
    root = Path(repo_root).resolve(strict=True)
    labels = base._required_labels(identity)
    base._source_metadata(identity)
    base._write_evidence(
        output,
        {
            "contract": "ba0-app-build-receipt.v1",
            "docker_context": docker_context,
            "status": "INCOMPLETE",
            "selector": _SELECTOR,
            "artifact_identity": identity["artifact_identity"],
            "build_source_head": identity["build_source_head"],
            "integration_head": identity["integration_head"],
            "manifest_sha256": identity["manifest_sha256"],
            "dependency_lock_sha256": identity["dependency_lock_sha256"],
            "platform": identity["platform"],
            "target": identity["target"],
            "pulled_reference": reference,
            "build_invocations": 0,
        },
    )
    base._docker(
        runner,
        ("docker", "--context", docker_context, "pull", "--platform",
         str(identity["platform"]), reference),
        repo_root=root,
        description="image pull",
    )
    image_id = _pulled_image_id(
        runner, root=root, reference=reference, docker_context=docker_context
    )
    base._inspect_image(
        runner,
        repo_root=root,
        candidate=image_id,
        labels=labels,
        docker_context=docker_context,
    )
    receipt: dict[str, Any] = base._receipt(
        identity,
        selector=_SELECTOR,
        image_id=image_id,
        labels=labels,
        candidates=(image_id,),
        build_invocations=0,
        docker_context=docker_context,
    )
    receipt["pulled_reference"] = reference
    base._write_evidence(output, receipt)
    return receipt


_INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
_MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _exact(raw: bytes, digest: str, description: str) -> bytes:
    """The bytes whose sha256 is `digest` (a printer may append one newline)."""

    candidates = [raw] + ([raw[:-1]] if raw.endswith(b"\n") else [])
    for candidate in candidates:
        if "sha256:" + hashlib.sha256(candidate).hexdigest() == digest:
            return candidate
    raise base.ArtifactContractError(f"{description} bytes do not hash to {digest}")


def ci_app_receipt(
    *,
    plan: Mapping[str, Any],
    index_bytes: bytes,
    manifest_bytes: bytes,
    index_digest: str,
    repository: str,
    run: str,
) -> dict[str, Any]:
    """The CI App receipt: the local BA0 receipt plus index and per-arch digests.

    `image_id` is the image config digest of the platform manifest (what Docker reports as
    the image ID and what `start_exact_image` checks), never the index digest buildx returns
    for a registry export with attestations. The index must hash to `index_digest` and the
    manifest to the index's entry for the planned platform.
    """

    if _DIGEST.fullmatch(index_digest) is None:
        raise base.ArtifactContractError("index digest must be sha256:<64 hex>")
    index = json.loads(_exact(index_bytes, index_digest, "image index"))
    if not isinstance(index, Mapping) or index.get("mediaType") not in _INDEX_TYPES:
        raise base.ArtifactContractError("the pushed App digest is not an image index")
    platforms: dict[str, str] = {}
    for entry in index.get("manifests", []):
        platform = entry.get("platform") or {}
        if platform.get("os") in (None, "unknown"):
            continue  # attestation manifests
        key = f"{platform.get('os')}/{platform.get('architecture')}"
        if key in platforms:
            raise base.ArtifactContractError(f"index lists {key} twice")
        platforms[key] = str(entry.get("digest"))
    if list(platforms) != [plan["platform"]]:
        raise base.ArtifactContractError(
            f"App index platforms {sorted(platforms)} != {plan['platform']}"
        )
    manifest = json.loads(_exact(manifest_bytes, platforms[plan["platform"]], "image manifest"))
    if not isinstance(manifest, Mapping) or manifest.get("mediaType") not in _MANIFEST_TYPES:
        raise base.ArtifactContractError("platform entry is not an image manifest")
    config = manifest.get("config") or {}
    image_id = config.get("digest") if isinstance(config, Mapping) else None
    if not isinstance(image_id, str) or _DIGEST.fullmatch(image_id) is None:
        raise base.ArtifactContractError("image manifest has no config digest")
    receipt: dict[str, Any] = base._receipt(
        plan,
        selector="CI_BUILD",
        image_id=image_id,
        labels=plan["labels"],
        candidates=(),
        build_invocations=1,
        docker_context="github-actions",
    )
    receipt.update(
        repository=repository,
        index_digest=index_digest,
        digests=platforms,
        pull_reference=f"{repository}@{index_digest}",
        run=run,
    )
    return receipt


def _option(arguments: Sequence[str], name: str) -> str | None:
    for position, value in enumerate(arguments):
        if value == name and position + 1 < len(arguments):
            return arguments[position + 1]
        if value.startswith(name + "="):
            return value[len(name) + 1 :]
    return None


def _mark_before_parsing(arguments: Sequence[str]) -> None:
    """`select` with an absolute --evidence-out: mark it non-success before any check."""

    if not arguments or arguments[0] != "select":
        return
    evidence = _option(arguments, "--evidence-out")
    if evidence and Path(evidence).is_absolute():
        _write_rejected(Path(evidence), _option(arguments, "--pull") or "")


def _main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="CI: identity, labels and build arguments")
    plan.add_argument("--repo-root", default=".")
    plan.add_argument("--build-source-head", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--context-out")
    select = commands.add_parser("select", help="local: pull a CI image by digest")
    select.add_argument("--repo-root", default=".")
    select.add_argument("--context", default="colima", choices=base._DOCKER_CONTEXTS)
    select.add_argument("--build-source-head", required=True)
    select.add_argument("--pull", required=True, help=f"{CI_REPOSITORY}@sha256:<digest>")
    select.add_argument("--evidence-out", required=True)
    ci_receipt = commands.add_parser("ci-receipt", help="CI: the App receipt from pushed bytes")
    for name in ("--plan", "--index", "--manifest", "--index-digest", "--repository", "--run"):
        ci_receipt.add_argument(name, required=True)
    ci_receipt.add_argument("--output", required=True)
    argv = list(sys.argv[1:] if arguments is None else arguments)
    _mark_before_parsing(argv)
    parsed = parser.parse_args(argv)
    if parsed.command == "ci-receipt":
        document = ci_app_receipt(
            plan=json.loads(Path(parsed.plan).read_text(encoding="utf-8")),
            index_bytes=Path(parsed.index).read_bytes(),
            manifest_bytes=Path(parsed.manifest).read_bytes(),
            index_digest=parsed.index_digest,
            repository=parsed.repository,
            run=parsed.run,
        )
        Path(parsed.output).write_text(
            json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return 0
    try:
        root = Path(parsed.repo_root).resolve(strict=True)
    except OSError as exc:
        raise base.ArtifactContractError("repository root does not exist") from exc
    if parsed.command == "plan":
        document = ci_plan(
            repo_root=root,
            build_source_head=parsed.build_source_head,
            context_out=parsed.context_out,
        )
        output = Path(parsed.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"artifact_identity": document["artifact_identity"]}))
        return 0
    evidence = Path(parsed.evidence_out)
    if not evidence.is_absolute():
        evidence = root / evidence
    _write_rejected(evidence, parsed.pull)
    identity = _identity(root, parsed.build_source_head, parsed.context)
    receipt = select_pulled_app(
        repo_root=root,
        identity=identity,
        reference=parsed.pull,
        evidence_out=evidence,
        docker_context=parsed.context,
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except base.ArtifactContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

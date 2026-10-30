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


def select_pulled_app(
    *,
    repo_root: str | os.PathLike[str],
    identity: Mapping[str, Any],
    reference: str,
    evidence_out: str | os.PathLike[str],
    runner: base.Runner = subprocess.run,
    docker_context: str = "colima",
) -> dict[str, Any]:
    """Pull one CI app image by digest; write a BA0 receipt only if it proves the identity."""

    if _PULL_REFERENCE.fullmatch(reference) is None:
        raise base.ArtifactContractError(
            f"pull reference must be {CI_REPOSITORY}@sha256:<64 hex digest>"
        )
    if docker_context not in base._DOCKER_CONTEXTS:
        raise base.ArtifactContractError("Docker context is not approved")
    root = Path(repo_root).resolve(strict=True)
    labels = base._required_labels(identity)
    base._source_metadata(identity)
    output = Path(evidence_out)
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
    parsed = parser.parse_args(arguments)
    root = Path(parsed.repo_root).resolve(strict=True)
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
    identity = _identity(root, parsed.build_source_head, parsed.context)
    evidence = Path(parsed.evidence_out)
    if not evidence.is_absolute():
        evidence = root / evidence
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

"""I1 #468 round 2 R3: the CI App receipt's image_id is the image config digest.

A registry export with provenance/SBOM pushes an index; its digest is not the image ID.
`ci_app_receipt` must take image_id from the verified linux/arm64 manifest's config digest,
keep index_digest separate, and the receipt must pass `start_exact_image`'s checks against
an image record whose Id is that config digest.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.service_shell.test_app_image_registry import COMMIT, REPOSITORY, registry

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIGEST = "sha256:" + "c0" * 32


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "i1_ci_receipt_start_exact_image", ROOT / "scripts/start_exact_image.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(module: ModuleType) -> dict[str, Any]:
    identity = {
        "artifact": "weknora-app",
        "artifact_identity": "sha256:" + "a" * 64,
        "manifest_sha256": "b" * 64,
        "dependency_lock_sha256": "f" * 64,
        "build_source_head": COMMIT,
        "integration_head": COMMIT,
        "target": "runtime",
        "platform": "linux/arm64",
    }
    return {
        **identity,
        "contract": "i1-app-ci-plan.v1",
        "dockerfile": "docker/Dockerfile.app",
        "labels": dict(module.base._required_labels(identity)),
        "build_args": {},
    }


def manifest_bytes(config: str = CONFIG_DIGEST) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": config},
            "layers": [],
        },
        sort_keys=True,
    ).encode()


def index_bytes(manifest: bytes, extra: list[dict[str, Any]] | None = None) -> bytes:
    entries = [
        {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": digest(manifest),
            "platform": {"os": "linux", "architecture": "arm64"},
        },
        {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + "a7" * 32,
            "platform": {"os": "unknown", "architecture": "unknown"},
            "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
        },
    ] + (extra or [])
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": entries,
        },
        sort_keys=True,
    ).encode()


def receipt_for(module: ModuleType, index: bytes, manifest: bytes, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "plan": plan(module),
        "index_bytes": index,
        "manifest_bytes": manifest,
        "index_digest": digest(index),
        "repository": REPOSITORY,
        "run": "1.1",
    }
    arguments.update(overrides)
    return module.ci_app_receipt(**arguments)


def test_image_id_is_the_config_digest_not_the_index_digest() -> None:
    module = registry()
    manifest = manifest_bytes()
    index = index_bytes(manifest)
    receipt = receipt_for(module, index, manifest)

    assert digest(index) != CONFIG_DIGEST
    assert receipt["image_id"] == CONFIG_DIGEST
    assert receipt["index_digest"] == digest(index)
    assert receipt["digests"] == {"linux/arm64": digest(manifest)}
    assert receipt["pull_reference"] == f"{REPOSITORY}@{digest(index)}"
    assert receipt["contract"] == "ba0-app-build-receipt.v1" and receipt["status"] == "PASS"

    checker = smoke()
    labels = checker._required_labels(receipt)
    record = {
        "Id": CONFIG_DIGEST,
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"Labels": labels},
    }
    checker._inspect_source(record, receipt["image_id"], labels)
    with pytest.raises(checker.ArtifactSmokeError):
        checker._inspect_source({**record, "Id": digest(index)}, receipt["image_id"], labels)


def test_a_printer_newline_is_tolerated_but_other_bytes_are_not() -> None:
    module = registry()
    manifest = manifest_bytes()
    index = index_bytes(manifest)
    tolerated = receipt_for(module, index + b"\n", manifest + b"\n", index_digest=digest(index))
    assert tolerated["image_id"] == CONFIG_DIGEST
    with pytest.raises(module.base.ArtifactContractError):
        receipt_for(module, index + b" ", manifest, index_digest=digest(index))


@pytest.mark.parametrize(
    "case",
    ["manifest-not-in-index", "index-digest-mismatch", "extra-platform", "no-config"],
)
def test_receipts_that_do_not_bind_the_scanned_bytes_are_refused(case: str) -> None:
    module = registry()
    manifest = manifest_bytes()
    index = index_bytes(manifest)
    overrides: dict[str, Any] = {}
    if case == "manifest-not-in-index":
        overrides["manifest_bytes"] = manifest_bytes("sha256:" + "d1" * 32)
    elif case == "index-digest-mismatch":
        overrides["index_digest"] = "sha256:" + "e" * 64
    elif case == "extra-platform":
        extra = [
            {"digest": "sha256:" + "b2" * 32, "platform": {"os": "linux", "architecture": "amd64"}}
        ]
        overrides["index_bytes"] = index_bytes(manifest, extra)
        overrides["index_digest"] = digest(overrides["index_bytes"])
    else:
        broken = json.dumps({"mediaType": "application/vnd.oci.image.manifest.v1+json"}).encode()
        overrides["manifest_bytes"] = broken
        overrides["index_bytes"] = index_bytes(broken)
        overrides["index_digest"] = digest(overrides["index_bytes"])
    with pytest.raises(module.base.ArtifactContractError):
        receipt_for(module, index, manifest, **overrides)


def test_the_cli_writes_the_same_receipt(tmp_path: Path) -> None:
    module = registry()
    manifest = manifest_bytes()
    index = index_bytes(manifest)
    files = {"plan": tmp_path / "plan.json", "index": tmp_path / "index.json"}
    files["plan"].write_text(json.dumps(plan(module)), encoding="utf-8")
    files["index"].write_bytes(index)
    (tmp_path / "manifest.json").write_bytes(manifest)
    out = tmp_path / "receipt.json"
    assert (
        module._main(
            [
                "ci-receipt",
                "--plan", str(files["plan"]),
                "--index", str(files["index"]),
                "--manifest", str(tmp_path / "manifest.json"),
                "--index-digest", digest(index),
                "--repository", REPOSITORY,
                "--run", "7.1",
                "--output", str(out),
            ]
        )
        == 0
    )  # fmt: skip
    assert json.loads(out.read_text(encoding="utf-8"))["image_id"] == CONFIG_DIGEST

"""Validate packaged upgrade assets without building an image or using a provider."""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts/verify-browserskill-extension.py"


def test_anydoc_license_is_in_the_release_bundle() -> None:
    script = (ROOT / "scripts/copy-licenses.sh").read_text()
    assert '"${license_root}/third_party/anydoc-go/LICENSE"' in script
    assert '"${license_dest}/licenses/AnyDoc-MIT.txt"' in script
    assert "AnyDoc-MIT.txt" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text()


@pytest.mark.parametrize(
    "variant", ["valid", "empty", "invalid", "wrong-version", "missing-worker"]
)
def test_extension_validation_rejects_broken_runtime_assets(tmp_path: Path, variant: str) -> None:
    assert VERIFY.is_file(), "runtime extension validator is missing"
    archive = tmp_path / "extension.zip"
    if variant in ("empty", "invalid"):
        archive.write_bytes(b"" if variant == "empty" else b"not a zip")
    else:
        manifest = {
            "manifest_version": 3,
            "version": "0.3.1" if variant != "wrong-version" else "0.3.0",
            "background": {"service_worker": "background.js"},
            "action": {"default_popup": "popup.html"},
        }
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest))
            bundle.writestr("popup.html", "<html></html>")
            if variant != "missing-worker":
                bundle.writestr("background.js", "console.log('fixture')")
    result = subprocess.run(
        [sys.executable, str(VERIFY), str(archive), "0.3.1"], capture_output=True, text=True
    )
    assert (result.returncode == 0) is (variant == "valid"), result.stderr


def test_both_exact_image_probes_validate_extension_contents() -> None:
    service = yaml.safe_load(
        (ROOT / "deploy/local-build/docker-compose.app-exact.yml").read_text()
    )["services"]["app-smoke"]
    expected = (
        "python3 /app/scripts/verify-browserskill-extension.py "
        "/opt/weknora/browserskill/browser-skill-weknora-0.3.1.zip 0.3.1"
    )
    assert expected in service["entrypoint"][2]
    assert expected in service["healthcheck"]["test"][1]


def test_local_anydoc_entrypoint_loads_the_fixed_dependency_lock() -> None:
    source = (ROOT / "scripts/build-anydoc-lib.sh").read_text()
    assert "deploy/local-build/app-external-dependencies.v1.json" in source
    assert source.index("app-external-dependencies.v1.json") < source.index("cargo build")


def test_local_anydoc_lock_defaults_are_read_before_target_validation(tmp_path: Path) -> None:
    cargo = tmp_path / "cargo"
    cargo.write_text("#!/bin/sh\nexit 99\n")
    cargo.chmod(0o755)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("ANYDOC_CRATE_")}
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["TARGET"] = "unsupported-fixture-target"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/build-anydoc-lib.sh")],
        env=environment, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "unsupported target" in result.stderr
    assert "required" not in result.stderr

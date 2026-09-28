"""Exercise the real build entrypoint and its lifecycle executable boundary offline."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _archive(path: Path, files: dict[str, str]) -> str:
    with tarfile.open(path, "w:gz") as archive:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


def test_browser_lifecycle_uses_verified_pnpm_in_child_shell(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required to exercise package lifecycle subprocesses")
    scripts = tmp_path / "repo/scripts"
    scripts.mkdir(parents=True)
    for name in ("build_browserskill.sh", "browserskill-release.json"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    manifest = json.loads((scripts / "browserskill-release.json").read_text())
    version = manifest["version"]
    commit = manifest["extension"]["source_commit"]
    source_archive = tmp_path / "source.tgz"
    source_hash = _archive(source_archive, {
        "source/package.json": json.dumps({"packageManager": "pnpm@10.17.0"}),
        "source/LICENSE": "fixture license\n",
    })
    pnpm_archive = tmp_path / "pnpm.tgz"
    # Downloads and compilation are bounded fixtures; shell executable lookup is real.
    pnpm_hash = _archive(pnpm_archive, {"package/bin/pnpm.cjs": """#!/usr/bin/env node
const {spawnSync} = require('node:child_process');
const fs = require('node:fs');
const arg = process.argv[2];
if (arg === '--version') {
  console.log('10.17.0');
} else if (arg === 'install') {
  if (!process.argv.includes('--frozen-lockfile')) process.exit(73);
} else if (arg === 'ext:build:zip') {
  const child = spawnSync('/bin/sh', ['-c', 'pnpm --version'], {encoding: 'utf8'});
  if (child.status !== 0 || child.stdout.trim() !== '10.17.0') {
    console.error('verified pnpm unavailable to lifecycle shell: ' + child.stderr);
    process.exit(71);
  }
  fs.mkdirSync('apps/extension/dist', {recursive: true});
  fs.writeFileSync('apps/extension/dist/browser-skillextension-' +
    process.env.BROWSERSKILL_VERSION + '-chrome.zip', 'fixture extension');
} else {
  process.exit(72);
}
"""})
    tools = tmp_path / "tools"
    tools.mkdir()
    _executable(tools / "curl", """#!/bin/sh
set -eu
case "$2" in
  *pnpm*) cp "$FIXTURE_PNPM_ARCHIVE" "$4" ;;
  *) cp "$FIXTURE_SOURCE_ARCHIVE" "$4" ;;
esac
""")
    _executable(tools / "cargo", """#!/bin/sh
set -eu
mkdir -p "$CARGO_TARGET_DIR/release"
printf '#!/bin/sh\\nexit 0\\n' > "$CARGO_TARGET_DIR/release/bsk"
""")
    # A shell function in the parent cannot protect children from an ambient pnpm.
    _executable(tools / "pnpm", "#!/bin/sh\necho ambient-pnpm-used >&2\nexit 99\n")
    environment = dict(os.environ)
    environment.update({
        "PATH": f"{tools}{os.pathsep}{environment['PATH']}",
        "BROWSERSKILL_VERSION": version,
        "BROWSERSKILL_SOURCE_COMMIT": commit,
        "BROWSERSKILL_SOURCE_PLATFORM": "source",
        "BROWSERSKILL_SOURCE_ORIGIN": f"https://fixture.invalid/source/{commit}",
        "BROWSERSKILL_SOURCE_SHA256": source_hash,
        "PNPM_VERSION": "10.17.0",
        "PNPM_PLATFORM": "source",
        "PNPM_ORIGIN": "https://fixture.invalid/pnpm.tgz",
        "PNPM_SHA256": pnpm_hash,
        "PNPM_STORE_DIR": str(tmp_path / "pnpm-store"),
        "CARGO_TARGET_DIR": str(tmp_path / "cargo-target"),
        "RUSTUP_TOOLCHAIN": "fixture",
        "FIXTURE_PNPM_ARCHIVE": str(pnpm_archive),
        "FIXTURE_SOURCE_ARCHIVE": str(source_archive),
    })
    output = tmp_path / "output with spaces"
    result = subprocess.run(
        ["bash", str(scripts / "build_browserskill.sh"), str(output)],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (output / f"browser-skill-weknora-{version}.zip").is_file()
    assert (output / "BrowserSkill-LICENSE").read_text() == "fixture license\n"
    assert os.access(output / "bsk", os.X_OK)

"""I5 / #525 R2: `staging.sh images` mirrors the live App's contracts mount without changing it.

Offline: `docker` is a fake on PATH answering the live/staging inspect, image and tag calls from a
state file; the real script runs under bash. A mount path that YAML or Compose would reinterpret
(line folding, escapes, `$` interpolation, the short-syntax `:`) must stop the script before any
override file is written.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[3] / "deploy/staging/staging.sh"
IMAGE = "sha256:" + "a" * 64

FAKE_DOCKER = r"""
import json, re, sys
from pathlib import Path
state = json.loads((Path(__file__).resolve().parent / "state.json").read_text())
argv = sys.argv[1:]
if argv[:1] == ["--context"]:
    argv = argv[2:]
def render(fmt, source):
    # Like `docker inspect -f`: the mount range becomes the source, the rest of the template stays.
    rendered = re.sub(r"\{\{range \.Mounts\}\}.*\{\{end\}\}\{\{end\}\}", lambda _: source, fmt)
    sys.stdout.write(rendered + "\n")
match argv:
    case ["inspect", "-f", "{{.Image}}", _]:
        print(state["image"])
    case ["inspect", "-f", fmt, _] if "/app/config/config.yaml" in fmt:
        render(fmt, state["config"])
    case ["inspect", "-f", fmt, _] if '"/app/contracts"' in fmt:
        render(fmt, state["contracts"])
    case ["image", "inspect", _] | ["tag", _, _]:
        pass
    case _:
        sys.exit(1)
"""


class Staging:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        fake = self.bin / "docker"
        fake.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
        fake.chmod(0o755)
        self.home = root / "staging-home"
        self.override = self.home / "contracts.compose.yaml"

    def images(self, contracts: str) -> subprocess.CompletedProcess[str]:
        state = {"image": IMAGE, "config": "/live/private/config.yaml", "contracts": contracts}
        (self.bin / "state.json").write_text(json.dumps(state))
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.root),
            "STAGING_HOME": str(self.home),
        }
        return subprocess.run(
            ["bash", str(SCRIPT), "images"], capture_output=True, text=True, env=env, cwd=self.root
        )


@pytest.fixture
def staging(tmp_path: Path) -> Staging:
    return Staging(tmp_path)


def test_plain_path_with_spaces_is_kept_as_is(staging: Staging) -> None:
    source = "/live/private dir/contracts"
    result = staging.images(source)
    assert result.returncode == 0, result.stderr
    parsed = yaml.safe_load(staging.override.read_text())
    assert parsed == {"services": {"app": {"volumes": [f"{source}:/app/contracts:ro"]}}}
    assert "CONTRACTS" not in (staging.home / "images.env").read_text()


def test_no_live_mount_removes_the_override(staging: Staging) -> None:
    staging.home.mkdir()
    staging.override.write_text("services: {}\n")
    result = staging.images("")
    assert result.returncode == 0, result.stderr
    assert not staging.override.exists()


@pytest.mark.parametrize("piece", ["\n", "\r", "\t", "$REV", "${REV}", '"', "\\", ":"])
def test_path_that_cannot_keep_its_meaning_is_refused(staging: Staging, piece: str) -> None:
    result = staging.images(f"/live/a{piece}b/contracts")
    assert result.returncode != 0 and "staging:" in result.stderr
    assert not staging.override.exists()


@pytest.mark.parametrize("tail", ["\n", "\n\n", "\r\n"])
def test_trailing_newline_does_not_create_an_override(staging: Staging, tail: str) -> None:
    # #525 re-review R2: command substitution drops trailing LFs, so the check needs the full value.
    result = staging.images(f"/fixture/contracts{tail}")
    assert result.returncode != 0 and "staging:" in result.stderr
    assert not staging.override.exists()


@pytest.mark.parametrize("tail", ["\n", "\n\n", "\r\n"])
def test_trailing_newline_keeps_an_existing_override(staging: Staging, tail: str) -> None:
    staging.home.mkdir()
    before = b'services:\n  app:\n    volumes:\n      - "/old/contracts:/app/contracts:ro"\n'
    staging.override.write_bytes(before)
    result = staging.images(f"/fixture/contracts{tail}")
    assert result.returncode != 0 and "staging:" in result.stderr
    assert staging.override.read_bytes() == before

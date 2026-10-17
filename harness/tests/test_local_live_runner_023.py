"""OpenSpec 023 R5.1/R5.2 isolated runner-controller contracts."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


RUNNER_ROOT = REPO_ROOT / "deploy/local-live/runner"


def test_r5_1_runner_image_is_non_root_ephemeral_and_one_job() -> None:
    dockerfile = (RUNNER_ROOT / "Dockerfile").read_text()
    entrypoint = (RUNNER_ROOT / "entrypoint.sh").read_text()

    assert (
        "ARG RUNNER_BASE_IMAGE=debian:bookworm-slim@sha256:"
        "7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818"
        in dockerfile
    )
    assert "USER runner" in dockerfile
    assert "mkdir -p /home/runner/actions-runner/_work" in dockerfile
    assert "sha256sum -c" in dockerfile
    assert (
        "ARG RUNNER_RELEASE_BASE=https://github.com/actions/runner/releases/download"
        in dockerfile
    )
    assert "ARG RUNNER_RELEASE_PROTO=https" in dockerfile
    assert '--proto "=${RUNNER_RELEASE_PROTO}"' in dockerfile
    assert "--retry 5 --retry-all-errors --retry-delay 2" in dockerfile
    assert "ARG RUNNER_DEBIAN_MIRROR=http://deb.debian.org/debian" in dockerfile
    assert (
        "ARG RUNNER_DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security"
        in dockerfile
    )
    assert 'URIs: ${RUNNER_DEBIAN_MIRROR}' in dockerfile
    assert 'URIs: ${RUNNER_DEBIAN_SECURITY_MIRROR}' in dockerfile
    assert (
        'grep --fixed-strings --line-regexp --quiet "URIs: ${RUNNER_DEBIAN_MIRROR}"'
        in dockerfile
    )
    assert (
        'grep --fixed-strings --line-regexp --quiet '
        '"URIs: ${RUNNER_DEBIAN_SECURITY_MIRROR}"' in dockerfile
    )
    assert (
        '"${RUNNER_RELEASE_BASE}/v${RUNNER_VERSION}/${RUNNER_ARCHIVE}"'
        in dockerfile
    )
    assert "ARG RUNNER_ARCH" in dockerfile
    assert "--ephemeral" in entrypoint
    assert "--disableupdate" in entrypoint
    assert "run.sh --once" in entrypoint
    assert "mkfifo" in entrypoint
    assert 'RUNNER_REGISTRATION_TOKEN="$(cat "$token_pipe")"' in entrypoint
    assert "rm -f \"$token_pipe\"" in entrypoint
    assert entrypoint.index("unset RUNNER_REGISTRATION_TOKEN") < entrypoint.index(
        "exec ./run.sh --once"
    )
    assert "set -x" not in entrypoint

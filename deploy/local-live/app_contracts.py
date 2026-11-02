"""Where the swapped App reads its contracts from (I5); swap_app.py loads this file by path.

Images built after I5 ship /app/contracts from their own build source. A throwaway container
(`test -f`; no network, env or mounts; removed on exit) checks for the schemas the platform reads at
startup. A pre-I5 image without them can only use an explicit --legacy-contracts-dir, exported from
the build source its label names (the dry run reports it as `build_source_head`); for an image that
ships them the flag is refused, since an outside dir would shadow them (the drift behind #522).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, NamedTuple

CONTRACTS_DIR = "/app/contracts"
# The schemas the platform reads at startup (releasestore.Production).
SCHEMAS = ("candidate_bundle.schema.json", "evidence.schema.json")
SOURCE_HEAD_LABEL = "io.insurancekb.app.build-source-head"
PROBE = ("run", "--rm", "--network", "none", "--pull", "never", "--entrypoint", "test")
MISSING = (
    "new image ships no contracts; pass --legacy-contracts-dir with contracts/ exported from "
    "its build_source_head"
)


class ContractsError(Exception):
    """The new container's contracts cannot be settled; messages name no env value."""


class Contracts(NamedTuple):
    # "image", "legacy_dir", or "missing" (only reported by a dry run; never swapped in)
    mode: str
    legacy: Path | None
    source_head: str | None

    def mounts(self) -> list[str]:
        return [] if self.legacy is None else ["-v", f"{self.legacy}:{CONTRACTS_DIR}:ro"]


def legacy_dir(path: str | None) -> Path | None:
    if path is None:
        return None
    directory = Path(path).resolve()
    if ":" in str(directory):
        raise ContractsError("--legacy-contracts-dir path contains ':', which docker -v rejects")
    if not all((directory / name).is_file() for name in SCHEMAS):
        raise ContractsError(f"--legacy-contracts-dir must hold {', '.join(SCHEMAS)}")
    return directory


def shipped(image_id: str) -> bool:
    """Whether the image holds every schema: `test -f A -a -f B` in a throwaway container."""
    checks: list[str] = []
    for name in SCHEMAS:
        checks += [*(["-a"] if checks else []), "-f", f"{CONTRACTS_DIR}/{name}"]
    result = subprocess.run(["docker", *PROBE, image_id, *checks], capture_output=True, text=True)
    if result.returncode not in (0, 1):  # 1 is `test` saying no; anything else is docker failing
        raise ContractsError("docker run (contracts probe) failed")
    return result.returncode == 0


def settle(image: dict[str, Any], legacy_path: str | None) -> Contracts:
    """The contracts source for `image` (an inspect record), bound to its exact ID."""
    legacy = legacy_dir(legacy_path)
    has = shipped(image["Id"])
    if has and legacy is not None:
        raise ContractsError("new image ships contracts; --legacy-contracts-dir would shadow them")
    head = (image["Config"].get("Labels") or {}).get(SOURCE_HEAD_LABEL)
    mode = "image" if has else "missing" if legacy is None else "legacy_dir"
    return Contracts(mode, legacy, head if isinstance(head, str) else None)

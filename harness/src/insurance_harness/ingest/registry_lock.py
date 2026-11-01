"""One command per registry file: a lock file beside it, taken or refused at once (S5b-2 Spec §2.5).

Every `uploads` command that reads or writes a registry holds it: `seed`, `run`, `confirm`,
`publish`, `migrate-registry`, `detach` and `relabel`. A second command finds the lock taken and
stops with `REGISTRY_BUSY` instead of waiting. Moved out of `uploads.py` unchanged (SK-1), when
that file reached its size limit.
"""

import os
from pathlib import Path


class RegistryBusy(Exception):
    """Another command holds the registry."""


class RegistryLock:
    def __init__(self, registry_path: Path) -> None:
        self.path = registry_path.with_name(registry_path.name + ".lock")

    def __enter__(self) -> "RegistryLock":
        try:
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            raise RegistryBusy from None
        return self

    def __exit__(self, *_: object) -> None:
        self.path.unlink(missing_ok=True)

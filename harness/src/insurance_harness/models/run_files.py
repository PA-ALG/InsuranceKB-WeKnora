"""Private run files: no Git, links, special files or blocking opens (H1 / SK-2c R5)."""

import os
import stat
from pathlib import Path


class IntegrityError(ValueError):
    """A caller-safe diagnostic; never includes a path or saved answer."""

    def __init__(self, code: str = "RUN_ROOT_INVALID") -> None:
        self.code = code
        super().__init__(code)


def _directory(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(mode):
        raise IntegrityError()
    return True


def check_directory(root: Path, *, directories: frozenset[str] | None = None) -> None:
    """lstat only. All files must be regular; optionally restrict relative directory names.

    Check ancestors too: a Git worktree's .git may be a file, and a link may hide in a parent.
    None allows nested run layouts; methods passes {'raw'} for its deliberately flat layout.
    """
    root = root.absolute()
    try:
        for parent in (*reversed(root.parents), root):
            if _directory(parent) and os.path.lexists(parent / ".git"):
                raise IntegrityError()
        if not _directory(root):
            return
        pending = [root]
        while pending:
            directory = pending.pop()
            if os.path.lexists(directory / ".git"):
                raise IntegrityError()
            for entry in directory.iterdir():
                mode = entry.lstat().st_mode
                if stat.S_ISDIR(mode):
                    if (
                        directories is not None
                        and entry.relative_to(root).as_posix() not in directories
                    ):
                        raise IntegrityError()
                    pending.append(entry)
                elif not stat.S_ISREG(mode):
                    raise IntegrityError()
    except OSError:
        raise IntegrityError() from None


def read_regular(path: Path) -> bytes | None:
    """Read exactly the regular file lstat saw; never wait on a FIFO or follow a final link."""
    try:
        seen = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise IntegrityError() from None
    if not stat.S_ISREG(seen.st_mode):
        raise IntegrityError()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise IntegrityError() from None
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            seen.st_dev,
            seen.st_ino,
        ):
            raise IntegrityError()
        return stream.read()

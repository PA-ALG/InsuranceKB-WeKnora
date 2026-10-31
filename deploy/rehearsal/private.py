"""The rehearsal's private directory: verified once per use, written atomically, never followed.

Secrets live in one directory that must be a real directory owned by this user, mode 0700, reached
by a path without symlinks, outside any git work tree. Files are written to an O_EXCL|O_NOFOLLOW
temporary in that directory, given their mode, then renamed over the target (a symlink planted at
the target is replaced, never written through); the result is checked to be a regular file of this
user with exactly the requested mode. Reads refuse symlinks and secrets readable by others.
"""

import json
import os
import secrets
import stat
from pathlib import Path

SECRET, SHARED = 0o600, 0o644  # SHARED: non-secret files a container must read (config, marker)


class PrivateError(Exception):
    """A fixed code; never a path or file content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical(path: Path) -> Path:
    """An absolute path whose every component is a real entry (no symlink, no ..)."""
    if not path.is_absolute() or os.path.realpath(path) != str(path):
        raise PrivateError("PATH_NOT_CANONICAL")
    return path


def inside_git(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def _open_dir(path: Path) -> int:
    canonical(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise PrivateError("PRIVATE_DIR_INVALID") from None
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        raise PrivateError("PRIVATE_DIR_INVALID")
    return fd


def private_dir(path: Path) -> Path:
    """Create (0700) or verify the private directory; tighten its mode only when it is ours."""
    canonical(path)
    if inside_git(path):
        raise PrivateError("PRIVATE_DIR_IN_GIT")
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise PrivateError("PRIVATE_DIR_INVALID") from None
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise PrivateError("PRIVATE_DIR_INVALID")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    os.close(_open_dir(path))
    return path


def _name(name: str) -> str:
    if not name or "/" in name or name in {".", ".."} or name.startswith("."):
        raise PrivateError("NAME_INVALID")
    return name


def write(directory: Path, name: str, data: bytes, mode: int = SECRET) -> None:
    dfd = _open_dir(directory)
    try:
        target, temporary = _name(name), f".{name}.{secrets.token_hex(8)}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode,
                     dir_fd=dfd)
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(temporary, dir_fd=dfd)
            raise
        os.close(fd)
        os.replace(temporary, target, src_dir_fd=dfd, dst_dir_fd=dfd)
        info = os.stat(target, dir_fd=dfd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != mode):
            raise PrivateError("PRIVATE_FILE_INVALID")
    finally:
        os.close(dfd)


def read(directory: Path, name: str, mode: int = SECRET) -> bytes | None:
    """The file's bytes, None when absent; a symlink or a wrong owner or mode is refused."""
    dfd = _open_dir(directory)
    try:
        try:
            fd = os.open(_name(name), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        except FileNotFoundError:
            return None
        except OSError:
            raise PrivateError("PRIVATE_FILE_INVALID") from None
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != mode):
                raise PrivateError("PRIVATE_FILE_INVALID")
            return handle.read()
    finally:
        os.close(dfd)


def read_env(directory: Path, name: str) -> dict[str, str]:
    data = read(directory, name)
    pairs = (line.partition("=") for line in (data or b"").decode().splitlines())
    return {key: value for key, _, value in pairs if key}


def write_env(directory: Path, name: str, values: dict[str, str]) -> None:
    if any("\n" in key + value or "=" in key for key, value in values.items()):
        raise PrivateError("ENV_VALUE_INVALID")
    text = "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
    write(directory, name, text.encode())


def read_json(directory: Path, name: str) -> dict | None:
    data = read(directory, name)
    if data is None:
        return None
    try:
        document = json.loads(data)
    except ValueError:
        raise PrivateError("PRIVATE_FILE_INVALID") from None
    if not isinstance(document, dict):
        raise PrivateError("PRIVATE_FILE_INVALID")
    return document


def write_json(directory: Path, name: str, document: dict) -> None:
    write(directory, name, (json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode())

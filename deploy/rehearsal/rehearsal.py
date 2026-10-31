"""I3a fresh-install rehearsal (deploy/rehearsal/README.md): one command per runbook step.

    python3 -I deploy/rehearsal/rehearsal.py <profile | images [--from-live] | env | dns | up |
        ledger | seed | smoke | status | down | destroy>

Settings come from the environment (README "设置"). Each command prints one JSON line per step;
a refusal or failure prints {"stopped": <fixed code>, ...} and exits 2. Nothing secret, no command
output and no HTTP response body is printed.
"""

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
# python3 -I leaves the script directory off sys.path; these modules are this checkout's own.
sys.path.insert(0, str(HERE))

import private  # noqa: E402
import seed  # noqa: E402
import stack  # noqa: E402
import teardown  # noqa: E402
import vm  # noqa: E402

Emit = Callable[[dict], None]


def _seed(settings: vm.Settings, run: vm.Runner, opener: stack.Opener, emit: Emit) -> dict:
    emit({"platform": seed.platform(seed.connect(settings, run, opener))})
    stack.recreate_app(settings, run, opener)  # ENTERPRISE_SPACES and closed registration
    ctx = seed.connect(settings, run, opener)
    emit({"materials": seed.materials(ctx)})
    return {"harness": seed.publish(seed.connect(settings, run, opener))}


COMMANDS: dict[str, Callable[..., dict]] = {
    "profile": lambda s, run, opener, emit, args: vm.create(s, run),
    "images": lambda s, run, opener, emit, args: stack.images(
        s, run, "live" if "--from-live" in args else "ghcr"),
    "env": lambda s, run, opener, emit, args: stack.env(s, run),
    "dns": lambda s, run, opener, emit, args: stack.dns(s, run),
    "up": lambda s, run, opener, emit, args: stack.up(s, run, opener),
    "ledger": lambda s, run, opener, emit, args: stack.ledger(s, run),
    "seed": lambda s, run, opener, emit, args: _seed(s, run, opener, emit),
    "smoke": lambda s, run, opener, emit, args: seed.smoke(seed.connect(s, run, opener)),
    "status": lambda s, run, opener, emit, args: stack.status(s, run),
    "down": lambda s, run, opener, emit, args: stack.down(s, run),
    "destroy": lambda s, run, opener, emit, args: teardown.destroy(s, run),
}


def _failure(error: Exception) -> dict:
    if isinstance(error, seed.Stop):
        return error.report()
    if isinstance(error, (vm.VmError, private.PrivateError)):
        return {"stopped": error.code}
    if isinstance(error, (KeyError, ValueError, TypeError, IndexError)):
        return {"stopped": "RESPONSE_SHAPE_UNEXPECTED"}
    if isinstance(error, OSError):
        return {"stopped": "IO_ERROR"}
    return {"stopped": "UNEXPECTED_ERROR"}


def main(argv: list[str] | None = None, *, env: dict[str, str] | None = None,
         run: vm.Runner = vm.run_command, opener: stack.Opener = stack.http) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print(json.dumps({"stopped": "USAGE", "commands": sorted(COMMANDS)}))
        return 2

    def emit(line: dict) -> None:
        print(json.dumps(line, ensure_ascii=False), flush=True)

    try:
        settings = vm.Settings.from_env(dict(os.environ) if env is None else env, HERE.parents[1])
        emit(COMMANDS[args[0]](settings, run, opener, emit, args[1:]))
    except Exception as error:  # every failure becomes a fixed code (R5)
        emit(_failure(error))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

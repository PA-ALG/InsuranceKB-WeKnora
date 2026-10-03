"""Record the architecture-guard baseline.

Usage (from the repository root):

    python tests/architecture/record_baseline.py          # write only if counts dropped
    python tests/architecture/record_baseline.py --init   # first recording / upstream upgrade slice

Without --init the script refuses to write when any count increased.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guards  # noqa: E402
from common import BASELINE_PATH, load_baseline  # noqa: E402


def write(doc: dict) -> None:
    BASELINE_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--init", action="store_true", help="record current state unconditionally")
    args = parser.parse_args()

    current = guards.collect()
    doc = guards.document(current)
    if args.init or not BASELINE_PATH.exists():
        write(doc)
        print("baseline recorded:", json.dumps(doc["totals"], ensure_ascii=False))
        return 0

    baseline = load_baseline()
    pin_error = guards.check_pin(baseline)
    if pin_error:
        print(pin_error, file=sys.stderr)
        return 1
    bad = guards.regressions(current, baseline)
    if bad:
        for guard, items in bad.items():
            print(f"{guard}: {len(items)} new violation(s)", file=sys.stderr)
            for item in items[:20]:
                print(f"  {item}", file=sys.stderr)
        print("refusing to write: baseline may only decrease", file=sys.stderr)
        return 1
    if not guards.improved(current, baseline):
        print("baseline unchanged")
        return 0
    doc = guards.document(guards.lowered(current, baseline))
    write(doc)
    print("baseline lowered:", json.dumps(doc["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

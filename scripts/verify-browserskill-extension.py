#!/usr/bin/env python3
"""Check a packaged BrowserSkill extension before accepting the runtime artifact."""

import json
import sys
import zipfile
from pathlib import Path


def verify_extension(archive: Path, expected_version: str) -> None:
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("extension ZIP integrity check failed")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("manifest_version") != 3 or manifest.get("version") != expected_version:
            raise ValueError("extension manifest version does not match the release")
        worker = manifest.get("background", {}).get("service_worker")
        popup = manifest.get("action", {}).get("default_popup")
        if not isinstance(worker, str) or not isinstance(popup, str):
            raise ValueError("extension background worker or popup is missing")
        for asset in (worker, popup, *manifest.get("icons", {}).values()):
            if not isinstance(asset, str) or not bundle.read(asset):
                raise ValueError("extension references an empty or missing asset")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("usage: verify-browserskill-extension.py ARCHIVE VERSION")
        verify_extension(Path(sys.argv[1]), sys.argv[2])
    except (OSError, ValueError, KeyError, AttributeError, zipfile.BadZipFile) as exc:
        print(f"Invalid BrowserSkill extension: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

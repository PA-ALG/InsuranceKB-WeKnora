"""Headless check that synthetic Office citations open and highlight in the real CitationPanel.

Starts the Vite dev server, opens the check page once per case in headless Chromium and answers
the panel's citation and cited-file requests from the page's own synthetic fixtures (no backend,
no business documents). Needs Playwright for Python with Chromium (`pip install playwright`,
`playwright install chromium`). Run from `frontend/`: `python3 tests/enterprise-office-citation/check.py`.
"""

from __future__ import annotations

import argparse
import base64
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Route, sync_playwright

FRONTEND = Path(__file__).resolve().parents[2]
PAGE = "/tests/enterprise-office-citation/index.html"
MEDIA = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for(url: str, server: subprocess.Popen[bytes], timeout: float = 120) -> None:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if server.poll() is not None:
            raise SystemExit("the Vite dev server exited")
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise SystemExit("the Vite dev server did not start")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path, help="directory for one screenshot per case")
    args = parser.parse_args()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        ["npx", "vite", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=FRONTEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    failures, total = 0, 0
    try:
        wait_for(base + PAGE, server)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1100, "height": 900})
            setup = context.new_page()
            setup.goto(base + PAGE)
            setup.wait_for_function("window.officeCitationHarness", timeout=120_000)
            cases = setup.evaluate("officeCitationHarness.cases")
            files = {k: base64.b64decode(v) for k, v in setup.evaluate("officeCitationHarness.fixtures()").items()}
            setup.close()
            by_member = {c["name"]: c for c in cases}
            total = len(cases)
            documents = {c["file"]: c["citation"]["source"]["document"] for c in cases}

            def answer(route: Route) -> None:
                url = urlparse(route.request.url)
                if url.path.endswith("/citation"):
                    case = by_member.get(parse_qs(url.query).get("member", [""])[0])
                    if case is None:
                        route.fulfill(status=404, json={"success": False, "code": "EVIDENCE_NOT_FOUND"})
                    else:
                        route.fulfill(json={"success": True, "data": case["citation"]})
                    return
                parts = url.path.split("/")
                if url.path.endswith("/file") and "sources" in parts:
                    key = parts[parts.index("sources") + 1]
                    if key in files:
                        media = MEDIA[Path(documents[key]).suffix]
                        route.fulfill(body=files[key], content_type=media,
                                      headers={"Cache-Control": "private, no-cache", "ETag": f'"{key}"'})
                        return
                route.fulfill(status=404, json={"success": False, "code": "SOURCE_NOT_FOUND"})

            context.route("**/api/v1/enterprise/**", answer)
            # Nothing may leave the page: a request elsewhere is recorded, refused and fails the case.
            outbound: list[str] = []

            def refuse(route: Route) -> None:
                outbound.append(route.request.url)
                route.abort()

            context.route(lambda url: not url.startswith(base), refuse)
            for case in cases:
                page = context.new_page()
                errors: list[str] = []
                outbound.clear()
                page.on("pageerror", lambda error: errors.append((error.stack or str(error)).splitlines()[:4]))
                page.goto(f"{base}{PAGE}?case={case['name']}")
                page.wait_for_function("window.officeCitationHarness", timeout=60_000)
                failure = page.evaluate("officeCitationHarness.verify()")
                if outbound:
                    failure = (failure + "; " if failure else "") + "requests leaving the page: " + json.dumps(outbound)
                if errors:
                    failure = (failure + "; " if failure else "") + "page errors: " + json.dumps(errors, ensure_ascii=False)
                if args.screenshots:
                    args.screenshots.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(args.screenshots / f"{case['name']}.png"), full_page=True)
                print(("PASS " if failure is None else "FAIL ") + case["name"] + ("" if failure is None else f": {failure}"))
                failures += failure is not None
                page.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=20)
    print(f"{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

"""
Playwright fixtures for the browser-level e2e tests.

Why these exist alongside pytest-playwright's own fixtures: its `page` and
`context` are function-scoped, so each test gets a clean browser. The SPA
flows here are ordered `test_NN_` steps that build on one another — a
registration in one step, the downloaded key in the next — and they need
the session cookie and the `localStorage` theme preference to survive
between them. So the context is module-scoped, matching `ref_instance`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator, List
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Error as PlaywrightError,
    Page,
    Playwright,
    sync_playwright,
)

# Browser binaries live in the repo rather than ~/.cache/ms-playwright,
# which is not writable in sandboxed environments. Mirrors how
# helpers/ref_instance.py redirects DOCKER_CONFIG for the same reason.
BROWSERS_DIR = Path(__file__).resolve().parent.parent / ".playwright-browsers"


@pytest.fixture(scope="session")
def _playwright() -> Generator[Playwright, None, None]:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_DIR))
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def spa_browser(_playwright: Playwright) -> Generator[Browser, None, None]:
    try:
        browser = _playwright.chromium.launch()
    except PlaywrightError as exc:  # pragma: no cover - setup failure path
        pytest.fail(
            "Could not launch Chromium. Install it once with\n"
            f"  PLAYWRIGHT_BROWSERS_PATH={BROWSERS_DIR} uv run playwright install chromium\n"
            f"Original error: {exc}"
        )
    yield browser
    browser.close()


# Chromium logs every non-2xx fetch to the console as this. It is not a
# fault on its own: the SPA deliberately provokes a 404 to discover whether
# the scoreboard is enabled, and a rejected form is a 400 by design. HTTP
# statuses are classified from the response events instead, where the code
# and the URL are both available.
_HTTP_STATUS_NOISE = "Failed to load resource"

# Asset prefixes that must always load. An API path is excluded on purpose
# — see above.
_REQUIRED_ASSET_PREFIXES = ("/spa/", "/static/")


class PageErrors:
    """
    Collects what the browser complained about, so a module can end with a
    single test asserting the browser stayed healthy. That catches Vue
    warnings, uncaught exceptions, server errors and missing assets, none
    of which a DOM assertion would notice.

    What it deliberately does not collect: 4xx responses. The SPA treats
    several of those as answers rather than failures, so counting them
    would make a correct app look broken.
    """

    def __init__(self) -> None:
        self.console: List[str] = []
        self.page_errors: List[str] = []
        self.failed_requests: List[str] = []
        self.server_errors: List[str] = []

    def on_console(self, msg: ConsoleMessage) -> None:
        if msg.type not in ("error", "warning"):
            return
        if _HTTP_STATUS_NOISE in msg.text:
            return
        self.console.append(f"[{msg.type}] {msg.text}")

    def on_page_error(self, exc: object) -> None:
        self.page_errors.append(str(exc))

    def on_response(self, response: object) -> None:
        status = getattr(response, "status", 0)
        url = str(getattr(response, "url", ""))
        # A 5xx is never part of a designed flow.
        if status >= 500:
            self.server_errors.append(f"{status} {url}")

    def on_request_failed(self, request: object) -> None:
        # Network-level failure, i.e. the request never got a response.
        url = str(getattr(request, "url", ""))
        path = urlsplit(url).path
        if path.startswith(_REQUIRED_ASSET_PREFIXES):
            self.failed_requests.append(url)

    def all_messages(self) -> List[str]:
        return [
            *(f"console: {m}" for m in self.console),
            *(f"pageerror: {m}" for m in self.page_errors),
            *(f"server error: {m}" for m in self.server_errors),
            *(f"request failed: {m}" for m in self.failed_requests),
        ]

    def clear(self) -> None:
        self.console.clear()
        self.page_errors.clear()
        self.failed_requests.clear()
        self.server_errors.clear()


@pytest.fixture(scope="module")
def spa_errors() -> PageErrors:
    return PageErrors()


@pytest.fixture(scope="module")
def spa_context(
    spa_browser: Browser,
    web_url: str,
) -> Generator[BrowserContext, None, None]:
    context = spa_browser.new_context(
        base_url=web_url,
        # The key-download steps need this; without it Playwright cancels
        # the download and expect_download() times out.
        accept_downloads=True,
        viewport={"width": 1400, "height": 1000},
        ignore_https_errors=True,
    )
    context.set_default_timeout(15_000)
    yield context
    context.close()


@pytest.fixture(scope="module")
def spa_page(
    spa_context: BrowserContext, spa_errors: PageErrors
) -> Generator[Page, None, None]:
    page = spa_context.new_page()
    page.on("console", spa_errors.on_console)
    page.on("pageerror", spa_errors.on_page_error)
    page.on("response", spa_errors.on_response)
    page.on("requestfailed", spa_errors.on_request_failed)
    yield page
    page.close()


@pytest.fixture(scope="module")
def download_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where the key-download steps save what the browser handed them."""
    return tmp_path_factory.mktemp("spa_downloads")

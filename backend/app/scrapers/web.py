"""Shared primitives for HTML scraping.

Everything here exists because the sites this project collects from do not
offer a usable public API, so the scrapers have to look like a browser and
read data out of the page. Keeping these helpers in one place means the
scrapers differ only in what they parse, not in how they fetch.
"""

from __future__ import annotations

import json
import random
from typing import Any, Iterator

import httpx

# Only advertise an encoding we can actually decode. Claiming brotli
# support without the decoder installed makes sites return bodies that
# come back as undecodable bytes - a silent, confusing failure.
try:  # pragma: no cover - depends on the installed extras
    import brotli  # noqa: F401
    _ACCEPT_ENCODING = "gzip, deflate, br"
except ImportError:  # pragma: no cover
    try:
        import brotlicffi  # noqa: F401
        _ACCEPT_ENCODING = "gzip, deflate, br"
    except ImportError:
        _ACCEPT_ENCODING = "gzip, deflate"

# A small pool is enough to avoid every request carrying an identical
# fingerprint. Each is a real, current browser string - claiming to be a
# browser that does not exist is a fast way to get blocked.
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def browser_headers(referer: str | None = None, user_agent: str | None = None) -> dict[str, str]:
    """Headers that match what a real browser navigation sends.

    Sites fingerprint on more than User-Agent: a request with a Chrome UA
    but no Sec-Fetch-* or Accept-Language headers is trivially spotted.
    """
    headers = {
        "User-Agent": user_agent or random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": _ACCEPT_ENCODING,
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if referer is None else "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def new_client(timeout: float = 30.0, **kwargs: Any) -> httpx.AsyncClient:
    """An AsyncClient that keeps cookies and looks like one browser session."""
    return httpx.AsyncClient(
        headers=browser_headers(),
        timeout=timeout,
        follow_redirects=True,
        **kwargs,
    )


def extract_embedded_json(html: str, marker: str) -> dict | None:
    """Pull the JSON object that follows ``marker`` in a page's script tags.

    Single-page apps embed their state as ``var ytInitialData = {...};``.
    A regex cannot find the closing brace reliably because the object
    contains braces inside strings, so this walks the text tracking string
    and escape state and returns the balanced object.
    """
    start = html.find(marker)
    if start < 0:
        return None

    start = html.find("{", start)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(html)):
        char = html[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:index + 1])
                except json.JSONDecodeError:
                    return None

    return None


def walk(node: Any, key: str) -> Iterator[Any]:
    """Yield every value stored under ``key``, at any depth.

    Deeply nested API payloads move things between versions; searching by
    key is far more durable than hard-coding a path through the tree.
    """
    if isinstance(node, dict):
        for node_key, value in node.items():
            if node_key == key:
                yield value
            yield from walk(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value, key)


def first(node: Any, key: str, default: Any = None) -> Any:
    """First value found under ``key``, or ``default``."""
    for value in walk(node, key):
        return value
    return default


def parse_count(value: Any) -> int:
    """Turn '1.1K', '15K', '2,340' or 1234 into an int."""
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return 0

    text = value.strip().replace(",", "").upper()
    if not text:
        return 0

    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    multiplier = multipliers.get(text[-1:])
    if multiplier:
        text = text[:-1]
    else:
        multiplier = 1

    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0

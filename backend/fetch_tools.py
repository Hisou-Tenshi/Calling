"""HTTP fetch utilities for Calling (GHA-friendly rate limits + GitHub auth)."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

FETCH_MAX_BYTES = int(os.getenv("FETCH_MAX_BYTES", "524288"))
FETCH_MAX_CHARS = int(os.getenv("FETCH_MAX_CHARS", "28000"))
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "20"))
FETCH_MIN_INTERVAL_SEC = float(os.getenv("FETCH_MIN_INTERVAL_SEC", "0.6"))
FETCH_MAX_CONCURRENT = max(1, int(os.getenv("FETCH_MAX_CONCURRENT", "2")))
FETCH_USER_AGENT = os.getenv("FETCH_USER_AGENT") or "CallingBot/1.0 (+GitHub-Actions)"

_RATE_LOCK = threading.Lock()
_LAST_FETCH_AT = 0.0
_CONCURRENCY = threading.Semaphore(FETCH_MAX_CONCURRENT)
_URL_RE = re.compile(r"https?://[^\s\]\)\"'<>]+", re.IGNORECASE)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._chunks)).strip()


def _throttle() -> None:
    global _LAST_FETCH_AT
    with _RATE_LOCK:
        now = time.monotonic()
        wait = FETCH_MIN_INTERVAL_SEC - (now - _LAST_FETCH_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_FETCH_AT = time.monotonic()


def _auth_headers_for_url(url: str) -> dict[str, str]:
    headers = {"User-Agent": FETCH_USER_AGENT, "Accept": "*/*"}
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    host = (urlparse(url).hostname or "").lower()
    if token and host in ("api.github.com", "raw.githubusercontent.com", "github.com"):
        headers["Authorization"] = f"Bearer {token}"
        if host == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
    return headers


def _validate_url(url: str) -> str:
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("invalid or unsupported URL")
    return u


def _detect_format(url: str, content_type: str, body: bytes) -> str:
    ct = (content_type or "").lower()
    path = (urlparse(url).path or "").lower()
    if "json" in ct or path.endswith(".json"):
        return "json"
    if "markdown" in ct or path.endswith((".md", ".markdown")):
        return "md"
    if "html" in ct or path.endswith((".html", ".htm")):
        return "html"
    if sample := body[:512]:
        if sample.strip().startswith((b"{", b"[")):
            return "json"
        if b"<html" in sample.lower():
            return "html"
    return "txt"


def _decode_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    m = re.search(r"charset=([^\s;]+)", content_type or "", flags=re.IGNORECASE)
    if m:
        charset = m.group(1).strip("\"'")
    return body.decode(charset, errors="replace")


def _format_body(text: str, fmt: str) -> str:
    fmt = (fmt or "auto").lower()
    if fmt == "json":
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            return text
    if fmt == "html":
        parser = _HTMLTextExtractor()
        try:
            parser.feed(text)
            parser.close()
            text = parser.text()
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
        return html.unescape(text).strip()
    return text


def fetch_url_tool(
    url: str,
    *,
    output_format: str = "auto",
    max_chars: int | None = None,
) -> dict[str, Any]:
    validated = _validate_url(url)
    max_chars = max(500, int(max_chars or FETCH_MAX_CHARS))
    _CONCURRENCY.acquire()
    try:
        _throttle()
        resp = requests.get(
            validated,
            headers=_auth_headers_for_url(validated),
            timeout=FETCH_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        resp.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=16384):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total > FETCH_MAX_BYTES:
                break
        body = b"".join(chunks)
        ct = resp.headers.get("Content-Type", "")
        fmt = output_format if output_format != "auto" else _detect_format(validated, ct, body)
        text = _format_body(_decode_body(body, ct), fmt)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars] + "\n\n[TRUNCATED]"
        return {
            "ok": True,
            "url": validated,
            "final_url": str(resp.url),
            "format": fmt,
            "chars": len(text),
            "truncated": truncated or total > FETCH_MAX_BYTES,
            "content": text,
        }
    except Exception as e:
        return {"ok": False, "url": validated, "error": str(e)}
    finally:
        _CONCURRENCY.release()

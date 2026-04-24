from __future__ import annotations

import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import URLError

from ..config import get_paths
from ..normalize import slugify


def fetch_text(url: str, *, timeout: int = 30, cache_namespace: str = "http") -> str:
    cache_path = _cache_path(url, cache_namespace)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "ignore")
    except (TimeoutError, URLError):
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        raise
    _write_cache(url, body, cache_namespace)
    return body


def _write_cache(url: str, body: str, cache_namespace: str) -> Path:
    target = _cache_path(url, cache_namespace)
    target.write_text(body, encoding="utf-8")
    return target


def _cache_path(url: str, cache_namespace: str) -> Path:
    parsed = urlparse(url)
    stem = slugify(f"{parsed.netloc}-{parsed.path}-{parsed.query}")[:120]
    cache_dir = get_paths().runtime_cache_dir / cache_namespace
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{stem}.html"

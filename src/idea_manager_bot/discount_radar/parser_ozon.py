from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urlparse

import certifi
import httpx

USER_AGENT = "Mozilla/5.0 (compatible; IdeaManagerBot/0.1; +https://example.local)"
MAX_PRICE_RUB = 10_000_000


@dataclass(frozen=True)
class OzonProductSnapshot:
    url: str
    status: str
    title: str | None = None
    price: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


class OzonParser:
    def __init__(self, *, timeout: float = 12.0) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> OzonProductSnapshot:
        if not _is_ozon_url(url):
            return OzonProductSnapshot(
                url=url,
                status="invalid_url",
                error="Это не похоже на ссылку Ozon.",
            )

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout,
                verify=certifi.where(),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
                },
            ) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return OzonProductSnapshot(
                url=url,
                status="fetch_failed",
                error=f"Ozon вернул HTTP {exc.response.status_code}.",
            )
        except httpx.HTTPError as exc:
            return OzonProductSnapshot(
                url=url,
                status="fetch_failed",
                error=f"Не удалось прочитать страницу Ozon: {exc}",
            )

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return OzonProductSnapshot(
                url=str(response.url),
                status="unsupported_content",
                error=f"Ozon вернул неподдерживаемый тип ответа: {content_type or 'unknown'}.",
            )

        return parse_ozon_html(response.text, url=str(response.url))


def _is_ozon_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname or ""
    return hostname == "ozon.ru" or hostname.endswith(".ozon.ru")


def parse_ozon_html(html: str, *, url: str) -> OzonProductSnapshot:
    if _looks_blocked(html):
        return OzonProductSnapshot(
            url=url,
            status="blocked",
            error="Ozon отдал страницу проверки доступа или капчу.",
        )

    title = _extract_title(html)
    price = _extract_price(html)
    if price is None:
        return OzonProductSnapshot(
            url=url,
            status="price_not_found",
            title=title,
            error="Не удалось найти цену товара на странице Ozon.",
        )

    return OzonProductSnapshot(
        url=url,
        status="success",
        title=title,
        price=price,
    )


def _looks_blocked(html: str) -> bool:
    text = _readable_text(html).lower()
    markers = (
        "captcha",
        "капча",
        "подтвердите, что вы не робот",
        "доступ ограничен",
        "access denied",
    )
    return any(marker in text for marker in markers)


def _extract_title(html: str) -> str | None:
    for item in _json_ld_items(html):
        title = _find_product_title(item)
        if title:
            return title

    for pattern in (
        r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'(?is)<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:title["\']',
        r"(?is)<title[^>]*>(.*?)</title>",
        r'(?is)<h1[^>]*>(.*?)</h1>',
    ):
        match = re.search(pattern, html)
        if match:
            title = _clean_text(match.group(1))
            if title:
                return _trim_ozon_suffix(title)
    return None


def _extract_price(html: str) -> int | None:
    for item in _json_ld_items(html):
        price = _find_product_price(item)
        if price is not None:
            return price

    for pattern in (
        r'(?is)<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\'](.*?)["\']',
        r'(?is)<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']product:price:amount["\']',
        r'(?is)itemprop=["\']price["\'][^>]+content=["\'](.*?)["\']',
        r'(?is)content=["\'](.*?)["\'][^>]+itemprop=["\']price["\']',
    ):
        match = re.search(pattern, html)
        if match:
            price = normalize_price(match.group(1))
            if price is not None:
                return price

    for pattern in (
        r'"(?:cardPrice|price|finalPrice|currentPrice)"\s*:\s*"([^"]+)"',
        r'"(?:cardPrice|price|finalPrice|currentPrice)"\s*:\s*(\d+(?:[.,]\d+)?)',
    ):
        for match in re.finditer(pattern, html):
            price = normalize_price(match.group(1))
            if price is not None:
                return price

    return None


def normalize_price(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return _valid_price(value)
    if isinstance(value, float):
        return _valid_price(round(value))

    text = unescape(str(value))
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    match = re.search(r"\d[\d\s]*(?:[,.]\d{1,2})?", text)
    if not match:
        return None

    raw_number = match.group(0).replace(" ", "")
    if "," in raw_number or "." in raw_number:
        normalized = raw_number.replace(",", ".")
        try:
            return _valid_price(round(float(normalized)))
        except ValueError:
            return None

    try:
        return _valid_price(int(raw_number))
    except ValueError:
        return None


def _valid_price(value: int) -> int | None:
    if 0 < value <= MAX_PRICE_RUB:
        return value
    return None


def _json_ld_items(html: str) -> list[Any]:
    items: list[Any] = []
    blocks = re.findall(
        r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
    )
    for block in blocks:
        payload = unescape(block).strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        items.extend(_flatten_json_ld(parsed))
    return items


def _flatten_json_ld(item: Any) -> list[Any]:
    if isinstance(item, list):
        result: list[Any] = []
        for child in item:
            result.extend(_flatten_json_ld(child))
        return result
    if isinstance(item, dict) and isinstance(item.get("@graph"), list):
        return _flatten_json_ld(item["@graph"])
    return [item]


def _find_product_title(item: Any) -> str | None:
    if not isinstance(item, dict) or not _is_product(item):
        return None
    return _clean_text(item.get("name"))


def _find_product_price(item: Any) -> int | None:
    if not isinstance(item, dict) or not _is_product(item):
        return None
    return _find_price_in_value(item.get("offers"))


def _is_product(item: dict[str, Any]) -> bool:
    raw_type = item.get("@type")
    if isinstance(raw_type, list):
        return any(str(value).lower() == "product" for value in raw_type)
    return str(raw_type).lower() == "product"


def _find_price_in_value(value: Any) -> int | None:
    if isinstance(value, list):
        for item in value:
            price = _find_price_in_value(item)
            if price is not None:
                return price
        return None

    if not isinstance(value, dict):
        return normalize_price(value)

    for key in ("price", "lowPrice", "highPrice"):
        price = normalize_price(value.get(key))
        if price is not None:
            return price

    for key in ("priceSpecification", "offers"):
        price = _find_price_in_value(value.get(key))
        if price is not None:
            return price
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(?s)<[^>]+>", " ", str(value))
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _trim_ozon_suffix(title: str) -> str:
    return re.sub(r"\s+\|\s+OZON.*$", "", title).strip()


def _readable_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()

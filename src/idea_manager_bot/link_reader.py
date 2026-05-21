from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import certifi
import httpx

USER_AGENT = "Mozilla/5.0 (compatible; IdeaManagerBot/0.1; +https://example.local)"


@dataclass
class LinkReadResult:
    url: str
    status: str
    extracted_content: str = ""
    error_message: str | None = None


class LinkReader:
    def read(self, url: str) -> LinkReadResult:
        errors: list[str] = []
        for read_url in self._candidate_urls(url):
            result = self._read_once(read_url)
            if result.status == "success":
                result.url = url
                return result
            if result.error_message:
                errors.append(result.error_message)

        return LinkReadResult(
            url=url,
            status="fetch_failed",
            error_message=self._combine_errors(*errors),
        )

    def _read_once(self, url: str) -> LinkReadResult:
        urllib_result = self._read_via_urllib(url)
        if urllib_result.status == "success":
            return urllib_result

        httpx_result = self._read_via_httpx(url)
        if httpx_result.status == "success":
            return httpx_result

        combined_error = self._combine_errors(
            urllib_result.error_message,
            httpx_result.error_message,
        )
        return LinkReadResult(
            url=url,
            status="fetch_failed",
            error_message=combined_error,
        )

    @classmethod
    def _candidate_urls(cls, url: str) -> list[str]:
        embed_url = cls._telegram_embed_url(url)
        if embed_url and embed_url != url:
            return [embed_url, url]
        return [url]

    @staticmethod
    def _telegram_embed_url(url: str) -> str | None:
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "")
        if host not in {"t.me", "telegram.me"}:
            return None

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) >= 3 and path_parts[0] == "s":
            channel, post_id = path_parts[1], path_parts[2]
            embed_path = f"/{channel}/{post_id}"
        elif len(path_parts) >= 2:
            channel, post_id = path_parts[0], path_parts[1]
            embed_path = f"/{channel}/{post_id}"
        else:
            return None

        if not post_id.isdigit():
            return None

        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update({"embed": "1", "mode": "tme"})
        return urlunparse(parsed._replace(path=embed_path, query=urlencode(query), fragment=""))

    def _read_via_urllib(self, url: str) -> LinkReadResult:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        try:
            with urllib.request.urlopen(request, timeout=12, context=ssl_context) as response:
                raw_bytes = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return LinkReadResult(
                url=url,
                status="fetch_failed",
                error_message=f"urllib HTTP {exc.code}",
            )
        except urllib.error.URLError as exc:
            return LinkReadResult(
                url=url,
                status="fetch_failed",
                error_message=f"urllib URL error: {exc.reason}",
            )
        except Exception as exc:  # noqa: BLE001
            return LinkReadResult(
                url=url,
                status="fetch_failed",
                error_message=f"urllib error: {exc}",
            )

        return self._parse_content(url, raw_bytes, content_type, source="urllib")

    def _read_via_httpx(self, url: str) -> LinkReadResult:
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=12.0,
                verify=certifi.where(),
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                raw_bytes = response.content
                content_type = response.headers.get("Content-Type", "")
        except httpx.HTTPStatusError as exc:
            return LinkReadResult(
                url=url,
                status="fetch_failed",
                error_message=f"httpx HTTP {exc.response.status_code}",
            )
        except httpx.HTTPError as exc:
            return LinkReadResult(
                url=url,
                status="fetch_failed",
                error_message=f"httpx error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return LinkReadResult(
                url=url,
                status="fetch_failed",
                error_message=f"httpx unexpected error: {exc}",
            )

        return self._parse_content(url, raw_bytes, content_type, source="httpx")

    def _parse_content(self, url: str, raw_bytes: bytes, content_type: str, source: str) -> LinkReadResult:
        if "text/html" not in content_type and "text/plain" not in content_type:
            return LinkReadResult(
                url=url,
                status="unsupported_content",
                error_message=f"{source} unsupported content type: {content_type or 'unknown'}",
            )

        decoded = raw_bytes.decode("utf-8", errors="ignore")
        extracted = self._extract_telegram_post_text(decoded) or self._extract_readable_text(decoded)
        if not extracted:
            return LinkReadResult(
                url=url,
                status="empty_content",
                error_message=f"{source} could not extract readable text from page",
            )

        return LinkReadResult(
            url=url,
            status="success",
            extracted_content=extracted[:12000],
        )

    @staticmethod
    def _combine_errors(*raw_errors: str | None) -> str:
        errors = [item for item in raw_errors if item]
        if not errors:
            return "Unknown fetch error"
        return " | ".join(errors)[:500]

    @staticmethod
    def _extract_readable_text(html: str) -> str:
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _extract_telegram_post_text(html: str) -> str:
        blocks = re.findall(
            r'(?is)<div[^>]+class="[^"]*\btgme_widget_message_text\b[^"]*"[^>]*>(.*?)</div>',
            html,
        )
        if not blocks:
            return ""

        texts = []
        for block in blocks:
            text = re.sub(r"(?i)<br\s*/?>", "\n", block)
            text = re.sub(r"(?s)<[^>]+>", " ", text)
            text = unescape(text)
            text = re.sub(r"[ \t\r\f\v]+", " ", text)
            text = re.sub(r"\n\s+", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if text:
                texts.append(text)
        return "\n\n".join(texts)

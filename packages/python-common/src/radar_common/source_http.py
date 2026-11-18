"""Bounded external HTTP transport. Never logs credentials, bodies or exception URLs."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential


class SourceError(Exception):
    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


class TransientError(SourceError):
    pass


def delay_for(response: httpx.Response, now: float) -> float:
    delays = [60.0]
    value = response.headers.get("retry-after", "")
    try:
        delays.append(float(value))
    except ValueError:
        try:
            delays.append(parsedate_to_datetime(value).timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            pass
    if response.headers.get("x-ratelimit-remaining") == "0":
        try:
            delays.append(float(response.headers["x-ratelimit-reset"]) - now + 1)
        except (KeyError, ValueError):
            pass
    return max(delays)


class SourceHTTP:
    HOSTS = {"pypi": "pypi.org", "github": "api.github.com", "osv": "api.osv.dev"}

    def __init__(
        self,
        source: str,
        *,
        token: str = "",
        transport: httpx.BaseTransport | None = None,
        acquire: Callable[[], None] = lambda: None,
        block: Callable[[float], None] = lambda seconds: None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self.acquire = acquire
        self.block = block
        self.sleep = sleep
        self.requests = 0
        headers = {"User-Agent": "OpenSourceRadar/0.1 (bounded metadata import)"}
        if source == "github":
            headers.update(
                {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
            )
            if token:
                headers["Authorization"] = "Bearer " + token
        self.client = httpx.Client(
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=1),
            headers=headers,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def request(self, path: str, payload: dict | None = None) -> dict:
        if not path.startswith("/") or path.startswith("//"):
            raise SourceError("INVALID_PATH")
        url = "https://" + self.HOSTS[self.source] + path
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=0.5, max=3),
            retry=retry_if_exception_type(TransientError),
            sleep=self.sleep,
            reraise=True,
        ):
            with attempt:
                return self._request(url, payload)
        raise AssertionError("Unreachable")

    def _request(self, url: str, payload: dict | None) -> dict:
        for _ in range(4):
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.netloc != self.HOSTS[self.source]
                or parts.username
                or parts.fragment
            ):
                raise SourceError("UNSAFE_REDIRECT")
            try:
                self.acquire()
            except SourceError as error:
                if error.code != "LOCAL_QUOTA" or not error.retry_after or error.retry_after > 2:
                    raise
                self.sleep(error.retry_after + 0.01)
                self.acquire()
            self.requests += 1
            if self.requests > 100:
                raise SourceError("REQUEST_BUDGET")
            try:
                with self.client.stream(
                    "POST" if payload is not None else "GET", url, json=payload
                ) as response:
                    if response.status_code in (301, 302, 307, 308):
                        location = response.headers.get("location", "")
                        url = str(response.url.join(location))
                        continue
                    status = response.status_code
                    secondary_limit = False
                    if status == 403:
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > 65536:
                                break
                        secondary_limit = b"rate limit" in body.lower()
                    limited = status == 429 or (
                        status == 403
                        and (
                            secondary_limit
                            or "retry-after" in response.headers
                            or response.headers.get("x-ratelimit-remaining") == "0"
                        )
                    )
                    if limited:
                        delay = delay_for(response, datetime.now(UTC).timestamp())
                        self.block(delay)
                        raise SourceError("RATE_LIMIT", delay)
                    if status in (500, 502, 503, 504):
                        raise TransientError("UPSTREAM_5XX", 30)
                    if status == 404:
                        raise SourceError("NOT_FOUND")
                    if status in (401, 403):
                        raise SourceError("AUTH_REJECTED")
                    if status != 200:
                        raise SourceError("HTTP_" + str(status))
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 8_000_000:
                            raise SourceError("PAYLOAD_TOO_LARGE")
                    import json

                    try:
                        data = json.loads(chunks)
                    except (ValueError, UnicodeError):
                        raise SourceError("INVALID_JSON") from None
                    if not isinstance(data, dict):
                        raise SourceError("INVALID_SCHEMA")
                    return data
            except httpx.TransportError:
                raise TransientError("NETWORK", 30) from None
        raise SourceError("REDIRECT_LIMIT")

"""The web fetch activity: the only place this package talks to the open internet.

One HTTP client per worker; robots.txt honoured; a politeness delay per host; a cap on body size. Expected
failures come back as a `FetchResult` with an error status rather than an exception, so the model that asked
for the page learns what happened instead of the stage failing.
"""

import asyncio
import hashlib
import logging
import time
from urllib.parse import urlsplit

import httpx
from temporalio import activity

from temporal_xmemory_events_agent.activities.names import ACTIVITY_FETCH_URL
from temporal_xmemory_events_agent.dto.fetch import FetchRequest, FetchResult, FetchStatus
from temporal_xmemory_events_agent.dto.settings import ScoutSettings
from temporal_xmemory_events_agent.web.cleaner import clean, window
from temporal_xmemory_events_agent.web.robots import RobotsCache

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 25
MAX_BODY_BYTES = 3_000_000


class ScoutActivities:
    """Activities that need settings and a shared HTTP client; register the bound methods on the worker."""

    def __init__(self, settings: ScoutSettings, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        )
        self._robots = RobotsCache(self._http, settings.user_agent)
        self._last_fetch_by_host: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    @activity.defn(name=ACTIVITY_FETCH_URL)
    async def fetch_url(self, request: FetchRequest) -> FetchResult:
        # A GET with no side effects: idempotent under Temporal retries, though the tool schedules it with one attempt
        # and lets the model decide whether to try another page.
        url = request.url.strip()
        if not url.lower().startswith(("http://", "https://")):
            return FetchResult(url=url, status=FetchStatus.ERROR, error="only http(s) URLs can be fetched")
        if not await self._robots.allowed(url):
            return FetchResult(url=url, status=FetchStatus.BLOCKED)
        await self._be_polite(url)
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            return FetchResult(url=url, status=FetchStatus.ERROR, error=f"{type(exc).__name__}: {exc}")
        if response.status_code >= 400:
            return FetchResult(url=url, status=FetchStatus.ERROR, error=f"HTTP {response.status_code}")
        body = response.content[:MAX_BODY_BYTES]
        page = clean(body, response.headers.get("content-type", ""), str(response.url))
        text, next_offset = window(page.text, request.offset, self._settings.fetch_chunk_chars)
        logger.info("fetched %s (%d chars, sha256 %s)", url, len(page.text), hashlib.sha256(body).hexdigest()[:12])
        return FetchResult(
            url=url,
            status=FetchStatus.OK,
            title=page.title,
            text=text,
            offset=request.offset,
            total_chars=len(page.text),
            next_offset=next_offset,
        )

    async def _be_polite(self, url: str) -> None:
        """Space requests to one host by the configured delay, across concurrent activities."""
        host = urlsplit(url).netloc
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last_fetch_by_host.get(host, 0.0)
            wait = self._settings.politeness_delay_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_fetch_by_host[host] = time.monotonic()

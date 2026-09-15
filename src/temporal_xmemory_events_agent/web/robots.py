"""robots.txt lookups, one fetch per host, never blocking the event loop."""

import logging
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

ROBOTS_TIMEOUT_SECONDS = 10


class RobotsCache:
    """Answers "may this user agent fetch this URL?" with the host's robots.txt, fetched once per host.

    An unreachable or missing robots.txt allows everything, which is the conventional reading; a robots.txt
    that fails to parse is treated the same way.
    """

    def __init__(self, http_client: httpx.AsyncClient, user_agent: str) -> None:
        self._http = http_client
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._parsers:
            self._parsers[host] = await self._load(host)
        parser = self._parsers[host]
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)

    async def _load(self, host: str) -> RobotFileParser | None:
        robots_url = urlunsplit(urlsplit(host)._replace(path="/robots.txt"))
        try:
            response = await self._http.get(
                robots_url, timeout=ROBOTS_TIMEOUT_SECONDS, headers={"User-Agent": self._user_agent}
            )
        except httpx.HTTPError as exc:
            logger.info("robots.txt for %s unavailable (%s); allowing", host, type(exc).__name__)
            return None
        if response.status_code != 200:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

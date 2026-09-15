"""The fetch activity against a mocked transport: cleaning, errors, robots, windows."""

from pathlib import Path

import httpx
from temporalio.testing import ActivityEnvironment

from temporal_xmemory_events_agent.activities.fetch import ScoutActivities
from temporal_xmemory_events_agent.dto.fetch import FetchRequest, FetchStatus
from temporal_xmemory_events_agent.dto.settings import ScoutSettings

FIXTURES = Path(__file__).parent / "fixtures"


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=(FIXTURES / "robots.txt").read_text())
        if path == "/event":
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=(FIXTURES / "meetup_event.html").read_bytes()
            )
        if path == "/feed":
            return httpx.Response(
                200, headers={"content-type": "application/rss+xml"}, content=(FIXTURES / "cfp_feed.xml").read_bytes()
            )
        if path == "/long":
            return httpx.Response(
                200, headers={"content-type": "text/plain"}, text="\n".join(f"paragraph {i}" for i in range(400))
            )
        if path.startswith("/private/"):
            return httpx.Response(200, text="secret")
        return httpx.Response(404, text="nope")

    return httpx.MockTransport(handler)


def _activities(chunk: int = 6000) -> ScoutActivities:
    settings = ScoutSettings(politeness_delay_seconds=0, fetch_chunk_chars=chunk)
    return ScoutActivities(settings, httpx.AsyncClient(transport=_transport()))


async def test_html_page_is_cleaned_and_rendered() -> None:
    env = ActivityEnvironment()
    result = await env.run(_activities().fetch_url, FetchRequest(url="https://site.test/event"))
    assert result.status is FetchStatus.OK
    rendered = result.render()
    assert rendered.startswith("# Berlin AI Builders")
    assert "Structured event data: name: Berlin AI Builders" in rendered
    assert rendered.endswith("characters in total]")


async def test_feed_and_errors_and_robots() -> None:
    env = ActivityEnvironment()
    acts = _activities()
    feed = await env.run(acts.fetch_url, FetchRequest(url="https://site.test/feed"))
    assert feed.status is FetchStatus.OK and feed.text.startswith("- ExampleConf 2027")
    missing = await env.run(acts.fetch_url, FetchRequest(url="https://site.test/missing"))
    assert (
        missing.status is FetchStatus.ERROR
        and missing.render() == "ERROR: could not fetch https://site.test/missing: HTTP 404"
    )
    blocked = await env.run(acts.fetch_url, FetchRequest(url="https://site.test/private/page"))
    assert blocked.status is FetchStatus.BLOCKED and blocked.render().startswith(
        "BLOCKED: https://site.test/private/page"
    )
    bad = await env.run(acts.fetch_url, FetchRequest(url="ftp://site.test/x"))
    assert bad.status is FetchStatus.ERROR


async def test_long_page_is_windowed_with_a_continuation_trailer() -> None:
    env = ActivityEnvironment()
    acts = _activities(chunk=500)
    first = await env.run(acts.fetch_url, FetchRequest(url="https://site.test/long"))
    assert first.next_offset is not None
    assert f"call fetch_url again with offset={first.next_offset}" in first.render()
    second = await env.run(acts.fetch_url, FetchRequest(url="https://site.test/long", offset=first.next_offset))
    assert second.offset == first.next_offset
    assert second.text.startswith("paragraph ")
    assert first.text not in second.text

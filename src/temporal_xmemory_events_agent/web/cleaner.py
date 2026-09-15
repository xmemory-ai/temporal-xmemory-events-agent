"""Turn a fetched body into text a model can read: HTML, feeds, or structured text.

HTML pages first yield any schema.org Event data they carry (meetup.com, lu.ma and Eventbrite render it
server-side), then the main text as trafilatura sees it. Feeds become one line per item. Everything else is
passed through as text.
"""

import json
import re
from html.parser import HTMLParser
from typing import Any, override

import feedparser
import trafilatura

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel

_HTML_TYPES = ("text/html", "application/xhtml")
_FEED_TYPES = ("application/rss", "application/atom", "application/rdf")
_FEED_MARKERS = (b"<rss", b"<feed", b"<rdf:RDF")
_EVENT_TYPES = {"Event", "BusinessEvent", "EducationEvent", "SocialEvent", "Festival", "ExhibitionEvent"}
_EVENT_FIELDS = (
    "name",
    "description",
    "startDate",
    "endDate",
    "eventAttendanceMode",
    "eventStatus",
    "url",
    "organizer",
    "location",
    "offers",
    "keywords",
)


class CleanedPage(FrozenTightBaseModel):
    title: str
    text: str


class _JsonLdCollector(HTMLParser):
    """Collect <script type="application/ld+json"> bodies and the <title>."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self.title = ""
        self._in_ld = False
        self._in_title = False

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and any(
            k == "type" and (v or "").strip().lower() == "application/ld+json" for k, v in attrs
        ):
            self._in_ld = True
            self.scripts.append("")
        elif tag == "title":
            self._in_title = True

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_ld = False
        elif tag == "title":
            self._in_title = False

    @override
    def handle_data(self, data: str) -> None:
        if self._in_ld and self.scripts:
            self.scripts[-1] += data
        elif self._in_title:
            self.title += data


def _flatten(value: Any) -> str:
    """Render a JSON-LD value (string, object with name/address, list) as one readable line."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(part for part in (_flatten(v) for v in value) if part)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("name", "url", "price", "priceCurrency", "streetAddress", "addressLocality", "addressCountry"):
            if value.get(key):
                parts.append(f"{key}={_flatten(value[key])}")
        if value.get("address"):
            parts.append(_flatten(value["address"]))
        return ", ".join(parts) if parts else ""
    return str(value)


def _event_nodes(node: Any) -> list[dict[str, Any]]:
    """Walk a JSON-LD document and return every node typed as an Event."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_event_nodes(item))
    elif isinstance(node, dict):
        types = node.get("@type")
        type_set = set(types) if isinstance(types, list) else {types} if types else set()
        if type_set & _EVENT_TYPES:
            found.append(node)
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                found.extend(_event_nodes(node[key]))
    return found


def structured_event_lines(scripts: list[str]) -> list[str]:
    lines: list[str] = []
    for script in scripts:
        try:
            document = json.loads(script)
        except json.JSONDecodeError:
            continue
        for event in _event_nodes(document):
            fields = [f"{key}: {_flatten(event[key])}" for key in _EVENT_FIELDS if event.get(key)]
            if fields:
                lines.append("Structured event data: " + " | ".join(fields))
    return lines


def clean_html(body: str, url: str | None = None) -> CleanedPage:
    collector = _JsonLdCollector()
    collector.feed(body)
    structured = structured_event_lines(collector.scripts)
    text = trafilatura.extract(
        body, url=url, include_comments=False, include_tables=True, favor_recall=True, include_links=False
    )
    if text is None:
        text = re.sub(r"<[^>]+>", " ", body)
    text = _tidy(text)
    if structured:
        text = "\n".join(structured) + "\n\n" + text
    return CleanedPage(title=_tidy(collector.title), text=text.strip())


def clean_feed(body: bytes) -> CleanedPage:
    parsed = feedparser.parse(body)
    lines = []
    for entry in parsed.entries:
        summary = _tidy(re.sub(r"<[^>]+>", " ", str(entry.get("summary", ""))))[:300]
        published = str(entry.get("published", "") or entry.get("updated", ""))
        lines.append(f"- {entry.get('title', '')} | {entry.get('link', '')} | {published} | {summary}".rstrip(" |"))
    title = str(parsed.feed.get("title", "")) if parsed.feed else ""
    return CleanedPage(title=title, text="\n".join(lines))


def clean(body: bytes, content_type: str, url: str | None = None) -> CleanedPage:
    """Dispatch on the response content type, falling back to sniffing the body for feeds."""
    kind = content_type.split(";")[0].strip().lower()
    head = body.lstrip()[:200]
    if kind.startswith(_FEED_TYPES) or (kind in ("application/xml", "text/xml") and _looks_like_feed(head)):
        return clean_feed(body)
    if kind.startswith(_HTML_TYPES) or (not kind and head.lower().startswith((b"<!doctype html", b"<html"))):
        return clean_html(body.decode("utf-8", errors="replace"), url)
    return CleanedPage(title="", text=_tidy(body.decode("utf-8", errors="replace")))


def window(text: str, offset: int, limit: int) -> tuple[str, int | None]:
    """The `limit`-character window of `text` at `offset`, cut at a paragraph or line break when possible."""
    if offset >= len(text):
        return "", None
    end = min(len(text), offset + limit)
    if end < len(text):
        cut = max(text.rfind("\n\n", offset, end), text.rfind("\n", offset, end))
        if cut > offset + limit // 2:
            end = cut
    return text[offset:end].strip(), end if end < len(text) else None


def _looks_like_feed(head: bytes) -> bool:
    return any(marker in head for marker in _FEED_MARKERS)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

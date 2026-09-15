"""Test doubles that are NOT xmemory: a scripted, recording model and a fixture-backed fetch activity."""

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, override

from agents import (
    AgentOutputSchemaBase,
    Handoff,
    Model,
    ModelResponse,
    ModelSettings,
    ModelTracing,
    Tool,
    TResponseInputItem,
)
from agents.items import TResponseStreamEvent
from temporalio import activity
from temporalio.contrib.openai_agents.testing import ResponseBuilders

from temporal_xmemory_events_agent.activities.names import ACTIVITY_FETCH_URL
from temporal_xmemory_events_agent.dto.fetch import FetchRequest, FetchResult, FetchStatus
from temporal_xmemory_events_agent.web.cleaner import clean, window

FIXTURES = Path(__file__).parent / "fixtures"


class RecordingModel(Model):
    """Returns scripted responses in order and records what each call was given."""

    def __init__(self, responses: Sequence[ModelResponse], *, repeat_last: bool = False) -> None:
        self._responses = list(responses)
        self._repeat_last = repeat_last
        self.calls: list[tuple[str | None, str | list[TResponseInputItem]]] = []

    @override
    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        **kwargs: Any,
    ) -> ModelResponse:
        self.calls.append((system_instructions, input))
        index = len(self.calls) - 1
        if index < len(self._responses):
            return self._responses[index]
        if self._repeat_last and self._responses:
            return self._responses[-1]
        raise AssertionError(f"the scripted model has no response for call {index + 1}")

    @override
    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        **kwargs: Any,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError("streaming is not scripted")

    def seen_text(self) -> str:
        """Everything the model was ever shown (briefs and tool outputs), flattened to one string."""
        parts: list[str] = []
        for _, given in self.calls:
            if isinstance(given, str):
                parts.append(given)
                continue
            for item in given:
                parts.append(json.dumps(item, default=str))
        return "\n".join(parts)


def tool_call(name: str, **arguments: Any) -> ModelResponse:
    return ResponseBuilders.tool_call(arguments=json.dumps(arguments), name=name)


def final_json(payload: dict[str, Any]) -> ModelResponse:
    return ResponseBuilders.output_message(json.dumps(payload))


_PAGES = {
    "meetup": ("meetup_event.html", "text/html"),
    "conference": ("plain_conference.html", "text/html"),
    "feed": ("cfp_feed.xml", "application/rss+xml"),
}


@activity.defn(name=ACTIVITY_FETCH_URL)
async def fake_fetch_url(request: FetchRequest) -> FetchResult:
    """Serves the HTML and feed fixtures by URL keyword; anything else is a 404."""
    for keyword, (filename, content_type) in _PAGES.items():
        if keyword in request.url:
            page = clean((FIXTURES / filename).read_bytes(), content_type, request.url)
            text, next_offset = window(page.text, request.offset, 6000)
            return FetchResult(
                url=request.url,
                status=FetchStatus.OK,
                title=page.title,
                text=text,
                offset=request.offset,
                total_chars=len(page.text),
                next_offset=next_offset,
            )
    return FetchResult(url=request.url, status=FetchStatus.ERROR, error="HTTP 404")

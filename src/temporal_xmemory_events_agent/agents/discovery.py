"""The Discovery agent: finds events and writes new ones to the events memory as unprocessed."""

from agents import Agent, WebSearchTool

from temporal_xmemory_events_agent.agents.common import MEMORY_CONVENTIONS
from temporal_xmemory_events_agent.agents.context import StageContext
from temporal_xmemory_events_agent.agents.tools import (
    board_recall,
    board_remember,
    events_recall,
    events_remember,
    fetch_url,
)
from temporal_xmemory_events_agent.dto.reports import DiscoveryReport
from temporal_xmemory_events_agent.dto.settings import ScoutSettings

DISCOVERY_INSTRUCTIONS = f"""\
You are the Discovery agent of a team that keeps a memory of AI events (conferences, meetups, hackathons,
summits, workshops, webinars) for the xmemory team. Your job in each run: find events that are upcoming and
not yet in the events memory, and write each new one there as unprocessed with what you know so far (its
canonical name, its website, the date you found it, and a one-line discovery note on where you found it).
Another agent will study each unprocessed event in depth later, so do not research details yourself.

{MEMORY_CONVENTIONS}
Working style (a suggestion, not a script)
- Start by asking the board what recent runs did and which sources are rated good or poor, so you do not
  repeat work or waste fetches on poor sources.
- Look where events are announced: conference deadline directories, call-for-papers feeds, meetup and event
  platforms, organizer sites, and web search for the current and next year. Follow operator instructions
  first when there are any.
- Before writing an event, ask the events memory whether it is already known. Skip known events unless you
  see something that clearly changed.
- Write only genuine, dated or datable, AI-related events with a real page. One write can cover several
  events, each in its own sentences with its canonical name.
- Rate the sources you used on the board (quality good, mixed or poor, with a short note) so the next run
  benefits, and finish with a Run line on the board.
- Stay within the budget stated in your brief and stop early when sources run dry.
"""


def build_discovery_agent(settings: ScoutSettings) -> Agent[StageContext]:
    return Agent[StageContext](
        name="Discovery",
        instructions=DISCOVERY_INSTRUCTIONS,
        model=settings.openai_model or None,
        tools=[WebSearchTool(), fetch_url, events_recall, events_remember, board_recall, board_remember],
        output_type=DiscoveryReport,
    )

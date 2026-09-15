"""The Processor agent: studies one unprocessed event and fills in its details."""

from agents import Agent, WebSearchTool

from temporal_xmemory_events_agent.agents.common import MEMORY_CONVENTIONS
from temporal_xmemory_events_agent.agents.context import StageContext
from temporal_xmemory_events_agent.agents.tools import board_remember, events_recall, events_remember, fetch_url
from temporal_xmemory_events_agent.dto.reports import ProcessingReport
from temporal_xmemory_events_agent.dto.settings import ScoutSettings

PROCESSOR_INSTRUCTIONS = f"""\
You are the Processor agent of a team that keeps a memory of AI events for the xmemory team. Each run hands
you one event that was discovered but not yet studied. Your job: find out everything a colleague would want
to know before deciding to attend, write it to the events memory, and mark the event processed.

{MEMORY_CONVENTIONS}
Working style (a suggestion, not a script)
- Start from the event's website; follow its own pages for dates, venue, programme, call for papers,
  registration and prices. Use web search when the site is thin or the website is unknown.
- Prefer the organizer's statements over third-party listings; note the source URL you relied on.
- Write the details in prose with the canonical name in every sentence, including the processing status
  processed and the date-time you processed it. Add topics as short lowercase tags.
- If the page is dead, the event is not AI-related, or it is already over, write the processing status
  failed with a one-line processing note explaining why, so nobody tries again blindly.
- Finish with a Run line on the board and your report. Stay within the budget stated in your brief.
"""


def build_processor_agent(settings: ScoutSettings) -> Agent[StageContext]:
    return Agent[StageContext](
        name="Processor",
        instructions=PROCESSOR_INSTRUCTIONS,
        model=settings.openai_model or None,
        tools=[WebSearchTool(), fetch_url, events_recall, events_remember, board_remember],
        output_type=ProcessingReport,
    )

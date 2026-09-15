"""The per-stage briefs: pure functions from workflow state to the text the agent starts from."""

from temporal_xmemory_events_agent.dto.rows import EventRow
from temporal_xmemory_events_agent.dto.settings import ScoutSettings


def discovery_brief(run_id: str, now_iso: str, instructions: list[str], settings: ScoutSettings) -> str:
    lines = [
        f"Discovery run {run_id}-discovery, started {now_iso}.",
        "Find AI conferences, meetups, hackathons, summits, workshops and similar events that are upcoming",
        "and not yet in the events memory, and write each new one there as unprocessed.",
        f"Budget: at most {settings.discovery_max_turns} turns and {settings.max_fetches_per_stage} fetches.",
    ]
    if instructions:
        lines.append("Operator instructions for this run, to be honoured first:")
        lines.extend(f"- {text}" for text in instructions)
    lines.append(f"When you are done, record a Run line for {run_id}-discovery on the board and give your report.")
    return "\n".join(lines)


def processing_brief(run_id: str, now_iso: str, event: EventRow, settings: ScoutSettings) -> str:
    lines = [
        f'Processing run {run_id}-process, started {now_iso}, for the event "{event.name}".',
        f"Website: {event.website or 'unknown'}.",
        f"Discovery note: {event.discovery_note or 'none'}.",
        f"Budget: at most {settings.processor_max_turns} turns and {settings.max_fetches_per_stage} fetches.",
        "Study the event's pages, write the details to the events memory with processing status processed",
        "(or failed, with a processing note), record a Run line on the board, and give your report.",
    ]
    return "\n".join(lines)

"""The agents' tools. They run in workflow code and do their I/O through activities.

Every tool returns text for the model. Expected failures (a dead page, a rejected write, an exhausted budget)
come back as messages the model can act on, never as exceptions that would end the stage.
"""

from datetime import timedelta

from agents import RunContextWrapper, function_tool
from temporalio import workflow
from temporalio.exceptions import ApplicationError
from xmemory_temporal import WorkflowXmemory

from temporal_xmemory_events_agent.activities.names import ACTIVITY_FETCH_URL
from temporal_xmemory_events_agent.agents.context import StageContext
from temporal_xmemory_events_agent.dto.fetch import FetchRequest, FetchResult

FETCH_TIMEOUT = timedelta(seconds=60)
MAX_REMEMBER_CHARS = 8000
WRITE_MAX_WAIT = timedelta(minutes=20)
WRITE_MAX_POLL_INTERVAL = timedelta(seconds=30)


def _events(ctx: RunContextWrapper[StageContext]) -> WorkflowXmemory:
    handle = ctx.context.events
    if not isinstance(handle, WorkflowXmemory):
        raise RuntimeError("StageContext.events must be the xmemory-temporal workflow handle")
    return handle


def _answer_text(reader_result: object) -> str:
    if reader_result is None:
        return "(memory has nothing on this)"
    if isinstance(reader_result, dict) and "answer" in reader_result:
        return str(reader_result["answer"])
    return str(reader_result)


@function_tool
async def fetch_url(ctx: RunContextWrapper[StageContext], url: str, offset: int) -> str:
    """Fetch a web page, feed or data file and return its readable text.

    Args:
        url: The http(s) URL to fetch.
        offset: Character offset to start from; 0 for the beginning. Use the offset given in a
            "[truncated ...]" trailer to read the rest of a long page.
    """
    state = ctx.context
    if state.fetch_budget_left() <= 0:
        return "BUDGET: no fetches are left in this stage; continue with what you already have."
    state.fetches += 1
    result = await workflow.execute_activity(
        ACTIVITY_FETCH_URL,
        FetchRequest(url=url, offset=max(0, offset)),
        result_type=FetchResult,
        start_to_close_timeout=FETCH_TIMEOUT,
        summary=f"fetch {url[:80]}",
    )
    return result.render()


@function_tool
async def events_recall(ctx: RunContextWrapper[StageContext], question: str) -> str:
    """Ask the events memory a question in plain language, e.g. "Is NeurIPS 2026 already known, and what
    do we have on it?" or "Which events in Berlin are recorded for October 2026?".

    Args:
        question: The question, naming events by their canonical name where possible.
    """
    output = await _events(ctx).read(question)
    return _answer_text(output.reader_result)


@function_tool
async def events_remember(ctx: RunContextWrapper[StageContext], text: str) -> str:
    """Write facts about events to the events memory as prose. xmemory extracts the records from the text,
    so name the event in its canonical form (short name plus year) in every sentence and use ISO dates.

    Args:
        text: The prose to remember, at most 8000 characters; split longer material into several calls.
    """
    if len(text) > MAX_REMEMBER_CHARS:
        return f"TOO LONG: {len(text)} characters; split the text into pieces of at most {MAX_REMEMBER_CHARS}."
    state = ctx.context
    try:
        status = await _events(ctx).write_durable(
            text, extraction_logic="deep", max_wait=WRITE_MAX_WAIT, max_poll_interval=WRITE_MAX_POLL_INTERVAL
        )
    except ApplicationError as exc:
        state.memory_write_failures += 1
        return f"MEMORY WRITE FAILED ({exc.type}): {exc.message}. Do not retry the same text; note it in your report."
    state.memory_writes += 1
    return f"stored in the events memory (write {status.write_id}, {status.write_status})"


@function_tool
async def board_recall(ctx: RunContextWrapper[StageContext], question: str) -> str:
    """Ask the coordination board a question in plain language, e.g. "What did the last three discovery
    runs do?" or "Which sources are rated good, and which poor?".

    Args:
        question: The question.
    """
    output = await ctx.context.board.read(question)
    return output.answer or "(the board has nothing on this)"


@function_tool
async def board_remember(ctx: RunContextWrapper[StageContext], text: str) -> str:
    """Write to the coordination board as prose: Run lines ("Run <run id> by agent discovery ... status
    completed ...") and Source notes ("Source <slug> (slug <slug>) ... quality good ..."). Restate the run
    id or slug in every sentence.

    Args:
        text: The prose to record, at most 8000 characters.
    """
    if len(text) > MAX_REMEMBER_CHARS:
        return f"TOO LONG: {len(text)} characters; split the text into pieces of at most {MAX_REMEMBER_CHARS}."
    try:
        output = await ctx.context.board.write(text)
    except ApplicationError as exc:
        return f"BOARD WRITE FAILED ({exc.type}): {exc.message}."
    detail = f"; {output.summary}" if output.summary else ""
    return f"recorded on the board (write {output.write_id}{detail})"

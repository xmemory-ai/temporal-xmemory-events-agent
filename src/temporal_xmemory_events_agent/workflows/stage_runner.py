"""Shared shape of the two stage workflows: build the context, run the agent, classify the outcome.

`Runner.run` executes inside the workflow: every model call is an activity through Temporal's OpenAI Agents SDK
integration, so on replay the stored response is returned and the model is not invoked again. The agent's tools
run in workflow code and do their I/O only through activities (web fetch, xmemory reads and writes), so a tool
call is replayed from history exactly like any other activity result.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents import Agent, Runner
    from agents.exceptions import AgentsException, MaxTurnsExceeded
    from xmemory_temporal import xmemory_for_workflow

    from temporal_xmemory_events_agent.agents.context import StageContext
    from temporal_xmemory_events_agent.dto.reports import StageReport, StageStatus
    from temporal_xmemory_events_agent.dto.settings import ScoutSettings
    from temporal_xmemory_events_agent.memory.board import BoardHandle

# A content write is one `write_start` activity (the only non-idempotent step) followed by idempotent status polls.
# Retry `write_start` only for failures where nothing was enqueued (rate limit, daily quota); a lost response after a
# successful enqueue must not be retried, because xmemory extracts the record's key from the text and a second
# extraction can fork the record.
CONTENT_WRITE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
    non_retryable_error_types=["XmemoryServerError", "XmemoryUnavailable", "XmemoryUnknown"],
)


def new_context(settings: ScoutSettings) -> StageContext:
    events = xmemory_for_workflow(
        read_timeout=timedelta(seconds=120),
        write_start_timeout=timedelta(seconds=60),
        write_status_timeout=timedelta(seconds=30),
        write_retry_policy=CONTENT_WRITE_RETRY,
    )
    return StageContext(settings, events, BoardHandle())


async def run_stage(
    *, run_id: str, stage: str, agent: Agent[StageContext], brief: str, context: StageContext, max_turns: int
) -> tuple[StageReport, object]:
    """Run the agent to completion; the final output (or None) comes back with the report skeleton."""
    workflow.logger.info("stage %s for %s starting", stage, run_id)
    final: object = None
    status = StageStatus.COMPLETED
    error = ""
    try:
        result = await Runner.run(agent, input=brief, context=context, max_turns=max_turns)
        final = result.final_output
    except MaxTurnsExceeded as exc:
        status, error = StageStatus.PARTIAL, f"stopped after {max_turns} turns: {exc.message}"
    except AgentsException as exc:
        status, error = StageStatus.FAILED, f"{type(exc).__name__}: {exc}"
    report = StageReport(
        run_id=run_id,
        stage=stage,
        status=status,
        fetches=context.fetches,
        memory_writes=context.memory_writes,
        memory_write_failures=context.memory_write_failures,
        error=error,
    )
    workflow.logger.info("stage %s for %s finished: %s", stage, run_id, status)
    return report, final

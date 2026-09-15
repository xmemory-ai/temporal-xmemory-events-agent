"""Workflow-side handle for the coordination instance, mirroring `xmemory_for_workflow` for the board."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from temporal_xmemory_events_agent.activities.names import ACTIVITY_BOARD_READ, ACTIVITY_BOARD_WRITE
from temporal_xmemory_events_agent.dto.board import BoardReadInput, BoardReadOutput, BoardWriteInput, BoardWriteOutput

READ_TIMEOUT = timedelta(seconds=120)
WRITE_TIMEOUT = timedelta(seconds=300)
# Reads are idempotent. Board keys (slugs, run ids) are literal and restated, so a repeated write re-applies
# the same update; both may retry.
_READ_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2), maximum_interval=timedelta(seconds=30), maximum_attempts=5
)
_WRITE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5), maximum_interval=timedelta(seconds=60), maximum_attempts=3
)


class BoardHandle:
    async def read(self, question: str, *, rows: bool = False) -> BoardReadOutput:
        return await workflow.execute_activity(
            ACTIVITY_BOARD_READ,
            BoardReadInput(question=question, rows=rows),
            result_type=BoardReadOutput,
            start_to_close_timeout=READ_TIMEOUT,
            retry_policy=_READ_RETRY,
            summary=f"board read: {len(question)} chars",
        )

    async def write(self, text: str, *, deep: bool = False) -> BoardWriteOutput:
        return await workflow.execute_activity(
            ACTIVITY_BOARD_WRITE,
            BoardWriteInput(text=text, deep=deep),
            result_type=BoardWriteOutput,
            start_to_close_timeout=WRITE_TIMEOUT,
            retry_policy=_WRITE_RETRY,
            summary=f"board write: {len(text)} chars",
        )

"""Activities for the coordination instance: a read and a synchronous write.

The `xmemory-temporal` plugin serves the events instance under fixed activity names, so the second instance
gets these two. They follow the plugin's shape: one client per worker, the client timeout derived from the
activity deadline, errors mapped to typed `ApplicationError`s.
"""

import logging
from typing import Any

from temporalio import activity
from xmemory import AsyncInstanceAPI, AsyncXmemoryClient, ExtractionLogic, ReadMode
from xmemory_temporal import to_application_error
from xmemory_temporal.config import client_timeout_seconds

from temporal_xmemory_events_agent.activities.names import ACTIVITY_BOARD_READ, ACTIVITY_BOARD_WRITE
from temporal_xmemory_events_agent.dto.board import BoardReadInput, BoardReadOutput, BoardWriteInput, BoardWriteOutput
from temporal_xmemory_events_agent.dto.targets import MemoryTarget
from temporal_xmemory_events_agent.memory.targets import require_instance_id, resolve_api_key
from temporal_xmemory_events_agent.memory.xresponse import summarize_changes

logger = logging.getLogger(__name__)


class BoardActivities:
    """Open with ``async with`` for the worker's lifetime, then register `board_read` and `board_write`."""

    def __init__(self, target: MemoryTarget) -> None:
        self._target = target
        self._client: AsyncXmemoryClient | None = None
        self._instance: AsyncInstanceAPI | None = None

    async def __aenter__(self) -> "BoardActivities":
        self._client = AsyncXmemoryClient(url=self._target.url, api_key=resolve_api_key(self._target))
        self._instance = self._client.instance(require_instance_id(self._target))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._instance = None

    @property
    def instance(self) -> AsyncInstanceAPI:
        if self._instance is None:
            raise RuntimeError("BoardActivities must be entered (async with) before its activities run")
        return self._instance

    @staticmethod
    def _timeout() -> float:
        info = activity.info()
        budget = info.start_to_close_timeout or info.schedule_to_close_timeout
        return client_timeout_seconds(budget.total_seconds()) if budget else 60.0

    @activity.defn(name=ACTIVITY_BOARD_READ)
    async def board_read(self, request: BoardReadInput) -> BoardReadOutput:
        mode = ReadMode.XRESPONSE if request.rows else ReadMode.SINGLE_ANSWER
        try:
            result = await self.instance.read(request.question, read_mode=mode, timeout=self._timeout())
        except Exception as exc:
            raise to_application_error(exc) from None
        answer: Any = result.reader_result
        if request.rows:
            return BoardReadOutput(rows=answer, trace_id=result.trace_id)
        if isinstance(answer, dict) and "answer" in answer:
            answer = answer["answer"]
        return BoardReadOutput(answer="" if answer is None else str(answer), trace_id=result.trace_id)

    @activity.defn(name=ACTIVITY_BOARD_WRITE)
    async def board_write(self, request: BoardWriteInput) -> BoardWriteOutput:
        logic = ExtractionLogic.DEEP if request.deep else ExtractionLogic.FAST
        try:
            result = await self.instance.write(request.text, extraction_logic=logic, timeout=self._timeout())
        except Exception as exc:
            raise to_application_error(exc) from None
        return BoardWriteOutput(
            write_id=result.write_id, summary=summarize_changes(result.changes), trace_id=result.trace_id
        )

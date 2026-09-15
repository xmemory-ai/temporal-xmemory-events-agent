"""The always-alive entity: wakes on a cadence or on demand, runs one cycle, continues as new.

A cycle is discovery, then a structured read of the unprocessed queue, then one processing child per event
with bounded parallelism. Signals only mutate state; every effect goes through children and activities.
"""

import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from xmemory_temporal import xmemory_for_workflow

    from temporal_xmemory_events_agent.dto.reports import StageReport, StageStatus
    from temporal_xmemory_events_agent.dto.rows import EventRow
    from temporal_xmemory_events_agent.dto.scout import CycleSummary, ScoutInput, ScoutStatus
    from temporal_xmemory_events_agent.dto.settings import ScoutSettings
    from temporal_xmemory_events_agent.dto.stage import DiscoveryInput, ProcessingInput
    from temporal_xmemory_events_agent.errors import MemoryReadError
    from temporal_xmemory_events_agent.memory.board import BoardHandle
    from temporal_xmemory_events_agent.memory.queries import UNPROCESSED_EVENTS
    from temporal_xmemory_events_agent.memory.xresponse import event_rows
    from temporal_xmemory_events_agent.workflows.discovery import DiscoveryWorkflow
    from temporal_xmemory_events_agent.workflows.ids import event_slug
    from temporal_xmemory_events_agent.workflows.processing import ProcessEventWorkflow

# An operator instruction containing this phrase skips discovery for that cycle.
PROCESS_ONLY_MARKER = "process only"
QUEUE_READ_TIMEOUT = timedelta(seconds=120)


@workflow.defn
class EventScoutWorkflow:
    """The entity workflow that owns the research cadence.

    Temporal patterns in this class:
    - Signals (`run_now`, `pause`, `resume`, `stop`, `instruct`) only mutate workflow state; the wait loop consumes
      them through `wait_condition`, whose timeout is the cadence timer. The `status` query reports that state.
    - State is initialised in `@workflow.init`, because signals delivered with the first workflow task run before
      `run` starts.
    - `continue_as_new` after every cycle carries the cycle counter and pending instructions and keeps history small.
    - Child workflow ids are `{workflow_id}-{run_id}-{stage}`; `run_id` derives from the carried cycle counter, so a
      retried workflow task or a replay can never start a duplicate child (the id is the idempotency key).
    - Processing children fan out under an `asyncio.Semaphore`, which is deterministic inside workflow code.
    - Every effect (memory reads and writes, model calls, web fetches) happens in an activity or a child.
    """

    @workflow.init
    def __init__(self, input: ScoutInput) -> None:
        # State comes from the input here, not in `run`: Temporal delivers signals that arrive with the first
        # workflow task before `run` starts, and initialising there would overwrite what they set.
        self._state = "starting"
        self._settings: ScoutSettings = input.settings
        self._cycle_no = input.cycle_no
        self._paused = input.paused
        self._stop = False
        self._run_now = False
        self._instructions: list[str] = list(input.pending_instructions)
        self._last_run_id = input.last_run_id
        self._last_summary = input.last_summary
        self._next_due: datetime | None = None
        self._next_due_at = input.next_due_at
        # Bumped by every signal so the wait loop re-evaluates its condition.
        self._version = 0

    # --- signals and query -------------------------------------------------

    @workflow.signal
    def run_now(self) -> None:
        self._run_now = True
        self._version += 1

    @workflow.signal
    def pause(self) -> None:
        self._paused = True
        self._version += 1

    @workflow.signal
    def resume(self) -> None:
        self._paused = False
        self._version += 1

    @workflow.signal
    def stop(self) -> None:
        self._stop = True
        self._version += 1

    @workflow.signal
    def instruct(self, text: str) -> None:
        if text.strip():
            self._instructions.append(text.strip())
        self._version += 1

    @workflow.query
    def status(self) -> ScoutStatus:
        return ScoutStatus(
            state=self._state,
            cycle_no=self._cycle_no,
            last_run_id=self._last_run_id,
            last_summary=self._last_summary,
            next_due_at=self._next_due.isoformat() if self._next_due else "",
            paused=self._paused,
            pending_instructions=list(self._instructions),
        )

    # --- main loop -----------------------------------------------------------

    @workflow.run
    async def run(self, input: ScoutInput) -> ScoutStatus:
        self._next_due = datetime.fromisoformat(self._next_due_at) if self._next_due_at else workflow.now()

        await self._wait_until_due()
        if self._stop and not self._run_now:
            self._state = "stopped"
            return self.status()

        summary = await self._run_cycle(self._settings)
        self._last_run_id = summary.run_id
        self._last_summary = summary.text
        self._next_due = workflow.now() + timedelta(hours=self._settings.cycle_interval_hours)
        if self._stop:
            self._state = "stopped"
            return self.status()

        self._state = "idle"
        await workflow.wait_condition(workflow.all_handlers_finished)
        # Built from live state at the call site, so a signal that landed during the cycle is carried over.
        workflow.continue_as_new(
            ScoutInput(
                settings=self._settings,
                cycle_no=self._cycle_no,
                paused=self._paused,
                last_run_id=self._last_run_id,
                last_summary=self._last_summary,
                pending_instructions=list(self._instructions),
                next_due_at=self._next_due.isoformat(),
            )
        )

    async def _wait_until_due(self) -> None:
        assert self._next_due is not None
        while True:
            if self._stop or self._run_now:
                return
            if not self._paused and workflow.now() >= self._next_due:
                return
            self._state = "paused" if self._paused else "idle"
            seen = self._version
            timeout = None if self._paused else max(0.0, (self._next_due - workflow.now()).total_seconds())
            try:
                await workflow.wait_condition(lambda: self._version != seen, timeout=timeout)
            except asyncio.TimeoutError:
                pass

    # --- one cycle -----------------------------------------------------------

    async def _run_cycle(self, settings: ScoutSettings) -> CycleSummary:
        self._run_now = False
        self._cycle_no += 1
        run_id = f"run-{self._cycle_no:05d}"
        self._state = "running"
        instructions, self._instructions = self._instructions, []
        started = workflow.now().isoformat()
        board = BoardHandle()
        problems: list[str] = []
        workflow.logger.info("cycle %s starting with %d instruction(s)", run_id, len(instructions))

        try:
            await board.write(f"Run {run_id} by agent scout started at {started}, status running.")
        except ActivityError as exc:
            problems.append(f"board write failed at start: {exc}")

        discovery: StageReport | None = None
        if not any(PROCESS_ONLY_MARKER in text.lower() for text in instructions):
            try:
                discovery = await workflow.execute_child_workflow(
                    DiscoveryWorkflow.run,
                    DiscoveryInput(run_id=run_id, instructions=instructions, settings=settings),
                    id=self._child_id(run_id, "discovery"),
                    run_timeout=timedelta(minutes=settings.stage_run_timeout_minutes),
                )
            except ChildWorkflowError as exc:
                problems.append(f"discovery failed: {exc.cause or exc}")

        rows: list[EventRow] = []
        try:
            output = await xmemory_for_workflow(read_timeout=QUEUE_READ_TIMEOUT).read(
                UNPROCESSED_EVENTS, read_mode="xresponse"
            )
            rows = event_rows(output.reader_result)
        except MemoryReadError as exc:
            problems.append(f"queue read: {exc}")
        except ActivityError as exc:
            problems.append(f"queue read failed: {exc}")

        reports = await self._process(run_id, settings, rows[: settings.max_events_processed_per_cycle])
        ok = sum(1 for r in reports if r.status is not StageStatus.FAILED)
        failed = len(reports) - ok
        finished = workflow.now().isoformat()
        found = len(discovery.discovery.found) if discovery and discovery.discovery else 0
        discovery_status = discovery.status.value if discovery else ("skipped" if not problems else "failed")
        status = "completed" if not problems and failed == 0 else "partial"
        text = (
            f"Run {run_id} by agent scout finished at {finished}, status {status}, summary: discovery {discovery_status} "
            f"with {found} new event(s); the queue had {len(rows)} unprocessed event(s), {ok} processed, {failed} failed."
        )
        if problems:
            text += " Problems: " + "; ".join(problems)
        try:
            await board.write(text)
        except ActivityError as exc:
            workflow.logger.warning("board write failed at the end of %s: %s", run_id, exc)
        workflow.logger.info("cycle %s finished: %s", run_id, status)
        return CycleSummary(
            run_id=run_id,
            status=status,
            started_at=started,
            finished_at=finished,
            discovery_status=discovery_status,
            found=found,
            queue_size=len(rows),
            processed_ok=ok,
            processed_failed=failed,
            text=text,
        )

    async def _process(self, run_id: str, settings: ScoutSettings, rows: list[EventRow]) -> list[StageReport]:
        gate = asyncio.Semaphore(max(1, settings.max_parallel_processing))

        async def one(row: EventRow) -> StageReport:
            async with gate:
                try:
                    return await workflow.execute_child_workflow(
                        ProcessEventWorkflow.run,
                        ProcessingInput(run_id=run_id, event=row, settings=settings),
                        id=self._child_id(run_id, f"process-{event_slug(row.name)}"),
                        run_timeout=timedelta(minutes=settings.stage_run_timeout_minutes),
                    )
                except ChildWorkflowError as exc:
                    workflow.logger.warning("processing of %r failed: %s", row.name, exc.cause or exc)
                    return StageReport(
                        run_id=run_id,
                        stage=f"process:{row.name}",
                        status=StageStatus.FAILED,
                        error=str(exc.cause or exc),
                    )

        return list(await asyncio.gather(*(one(row) for row in rows)))

    @staticmethod
    def _child_id(run_id: str, suffix: str) -> str:
        return f"{workflow.info().workflow_id}-{run_id}-{suffix}"

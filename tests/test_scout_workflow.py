"""The entity workflow on a real worker: cycles, signals, query, continue-as-new, failure isolation."""

import pytest
import asyncio
import uuid

from temporalio.client import Client, WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from temporal_xmemory_events_agent.dto.scout import ScoutInput, ScoutStatus
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.queries import ALL_EVENTS, UNPROCESSED_EVENTS
from temporal_xmemory_events_agent.memory.xresponse import event_rows, parse_objects
from temporal_xmemory_events_agent.workflows.scout import EventScoutWorkflow

from .conftest import MemoryTargets, unique
from .fakes import RecordingModel, final_json, tool_call
from .stage_harness import make_settings, stage_worker

# Every test here talks to a real xmemory backend through the session's throwaway instances.
pytestmark = pytest.mark.memory

RUNS_QUERY = "Every Run record. Return all rows with every field."


async def _start(client: Client, task_queue: str, paused: bool = False, **overrides) -> WorkflowHandle:
    settings = make_settings(cycle_interval_hours=1000, max_parallel_processing=1, **overrides)
    return await client.start_workflow(
        EventScoutWorkflow.run,
        ScoutInput(settings=settings, paused=paused),
        id=f"scout-{uuid.uuid4()}",
        task_queue=task_queue,
    )


async def _wait_for_cycle(handle: WorkflowHandle, cycle_no: int, timeout: float = 900) -> ScoutStatus:
    for _ in range(int(timeout / 2)):
        status: ScoutStatus = await handle.query(EventScoutWorkflow.status)
        if status.cycle_no >= cycle_no and status.state in ("idle", "paused", "stopped"):
            return status
        await asyncio.sleep(2)
    raise AssertionError(f"cycle {cycle_no} did not finish within {timeout}s")


async def test_cycle_discovers_then_processes_and_continues(
    temporal_env: WorkflowEnvironment, fresh_memory_targets: MemoryTargets
) -> None:
    targets = fresh_memory_targets
    token = unique("SC")
    name = f"ScoutConf {token} 2027"
    website = f"https://example.test/conference/{token}"
    model = RecordingModel(
        [
            # Discovery stage
            tool_call("board_recall", question="What did recent runs do?"),
            tool_call(
                "events_remember",
                text=f"Event {name}, website {website}, discovered on 2026-09-15T10:00:00Z, discovery note: from the test feed.",
            ),
            tool_call(
                "board_remember",
                text="Run run-00001-discovery by agent discovery, status completed, summary: found one event.",
            ),
            final_json({"found": [{"name": name, "website": website}], "sources_checked": 1, "notes": "scripted"}),
            # Processing stage for that event
            tool_call("fetch_url", url=website, offset=0),
            tool_call(
                "events_remember",
                text=f"Event {name} takes place from 2027-03-03 to 2027-03-05 in Lisbon, Portugal. Event {name} has processing status processed, processed at 2026-09-15T11:00:00Z.",
            ),
            tool_call(
                "board_remember",
                text=f"Run run-00001-process-{token.lower()} by agent processor, status completed, summary: processed {name}.",
            ),
            final_json({"name": name, "status": "processed", "summary": "dates recorded"}),
        ]
    )
    async with stage_worker(temporal_env, targets, model) as (client, task_queue):
        # Start paused so the instruction is queued before the cycle it must reach; then run on demand.
        handle = await _start(client, task_queue, paused=True, max_events_processed_per_cycle=1)
        await handle.signal(EventScoutWorkflow.instruct, "Look at the test feed first")
        await handle.signal(EventScoutWorkflow.run_now)
        status = await _wait_for_cycle(handle, 1)
        assert status.cycle_no == 1 and status.last_run_id == "run-00001"
        await handle.signal(EventScoutWorkflow.resume)
        await asyncio.sleep(2)
        status = await handle.query(EventScoutWorkflow.status)
        assert status.state == "idle" and not status.paused
        assert "1 processed, 0 failed" in status.last_summary, status.last_summary
        assert status.next_due_at
        await handle.signal(EventScoutWorkflow.stop)
        final: ScoutStatus = await handle.result()
    assert final.state == "stopped" and final.cycle_no == 1
    assert "Look at the test feed first" in model.seen_text()
    assert name not in [r.name for r in event_rows(await admin.read_rows(targets.events, UNPROCESSED_EVENTS))]
    stored = [o for o in parse_objects(await admin.read_rows(targets.events, ALL_EVENTS)) if o.text("name") == name]
    assert (
        stored and stored[0].text("processing_status") == "processed" and stored[0].text("start_date") == "2027-03-03"
    )
    runs = {r.text("run_id"): r for r in parse_objects(await admin.read_rows(targets.coordination, RUNS_QUERY))}
    assert runs["run-00001"].text("status") == "completed" and runs["run-00001"].text("agent") == "scout"
    assert "run-00001-discovery" in runs


async def test_paused_entity_runs_once_on_demand_and_stops(
    temporal_env: WorkflowEnvironment, fresh_memory_targets: MemoryTargets
) -> None:
    model = RecordingModel(
        [
            tool_call(
                "board_remember",
                text="Run run-00001-discovery by agent discovery, status completed, summary: nothing new.",
            ),
            final_json({"found": [], "sources_checked": 0, "notes": "nothing"}),
        ]
    )
    async with stage_worker(temporal_env, fresh_memory_targets, model) as (client, task_queue):
        handle = await _start(client, task_queue, paused=True)
        await asyncio.sleep(2)
        status: ScoutStatus = await handle.query(EventScoutWorkflow.status)
        assert status.state == "paused" and status.cycle_no == 0
        await handle.signal(EventScoutWorkflow.run_now)
        status = await _wait_for_cycle(handle, 1)
        assert status.paused and status.state == "paused" and status.cycle_no == 1
        assert "0 unprocessed event(s), 0 processed, 0 failed" in status.last_summary
        await handle.signal(EventScoutWorkflow.stop)
        final: ScoutStatus = await handle.result()
    assert final.state == "stopped" and final.cycle_no == 1
    runs = {
        r.text("run_id"): r.text("status")
        for r in parse_objects(await admin.read_rows(fresh_memory_targets.coordination, RUNS_QUERY))
    }
    assert runs.get("run-00001") == "completed"


async def test_failed_processing_child_does_not_fail_the_cycle(
    temporal_env: WorkflowEnvironment, fresh_memory_targets: MemoryTargets
) -> None:
    targets = fresh_memory_targets
    name = f"FailConf {unique('FC')} 2027"
    await admin.write_text(
        targets.events,
        f"Event {name}, website https://example.test/conference/x, discovered on 2026-09-15T10:00:00Z, processing status unprocessed.",
    )
    # An empty script: the first model call of the processing child raises, the activity exhausts its two
    # attempts, the child fails, and the entity must survive it. Discovery is skipped by instruction.
    model = RecordingModel([])
    async with stage_worker(temporal_env, targets, model) as (client, task_queue):
        handle = await _start(client, task_queue, paused=True)
        await handle.signal(EventScoutWorkflow.instruct, "process only this time")
        await handle.signal(EventScoutWorkflow.run_now)
        status = await _wait_for_cycle(handle, 1)
        assert status.cycle_no == 1
        assert "discovery skipped" in status.last_summary
        assert "1 unprocessed event(s), 0 processed, 1 failed" in status.last_summary, status.last_summary
        await handle.signal(EventScoutWorkflow.stop)
        final: ScoutStatus = await handle.result()
    assert final.state == "stopped"
    assert name in [r.name for r in event_rows(await admin.read_rows(targets.events, UNPROCESSED_EVENTS))]

"""The Discovery stage on a real worker with a scripted model and real xmemory."""

import uuid

import pytest
from temporalio.testing import WorkflowEnvironment

from temporal_xmemory_events_agent.dto.reports import StageStatus
from temporal_xmemory_events_agent.dto.stage import DiscoveryInput
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.queries import UNPROCESSED_EVENTS
from temporal_xmemory_events_agent.memory.xresponse import event_rows, parse_objects
from temporal_xmemory_events_agent.workflows.discovery import DiscoveryWorkflow

from .conftest import MemoryTargets, unique
from .fakes import RecordingModel, final_json, tool_call
from .stage_harness import scheduled_activity_names, stage_worker, make_settings

# Every test here talks to a real xmemory backend through the session's throwaway instances.
pytestmark = pytest.mark.memory


@pytest.mark.parametrize("forced_replay", [False, True], ids=["cached", "forced-replay"])
async def test_discovery_writes_a_new_event_and_a_run_line(
    temporal_env: WorkflowEnvironment, memory_targets: MemoryTargets, forced_replay: bool
) -> None:
    token = unique("DC")
    name = f"DiscoConf {token} 2027"
    website = f"https://example.test/conference/{token}"
    run_id = unique("run")
    model = RecordingModel(
        [
            tool_call("board_recall", question="What did recent runs do and which sources are good?"),
            tool_call("fetch_url", url="https://example.test/feed", offset=0),
            tool_call(
                "events_remember",
                text=(
                    f"Event {name}, website {website}, discovered on 2026-09-15T10:00:00Z, "
                    f"discovery note: found in the test feed."
                ),
            ),
            tool_call(
                "board_remember",
                text=(
                    f"Run {run_id}-discovery by agent discovery started at 2026-09-15T10:00:00Z, finished at "
                    f"2026-09-15T10:05:00Z, status completed, summary: found one new event."
                ),
            ),
            final_json({"found": [{"name": name, "website": website}], "sources_checked": 1, "notes": "scripted"}),
        ]
    )
    settings = make_settings()
    async with stage_worker(temporal_env, memory_targets, model, max_cached_workflows=0 if forced_replay else None) as (
        client,
        task_queue,
    ):
        workflow_id = f"discovery-{uuid.uuid4()}"
        report = await client.execute_workflow(
            DiscoveryWorkflow.run,
            DiscoveryInput(run_id=run_id, instructions=["Look at the test feed"], settings=settings),
            id=workflow_id,
            task_queue=task_queue,
        )
        scheduled = await scheduled_activity_names(client, workflow_id)

    assert report.status is StageStatus.COMPLETED, report.error
    assert report.discovery is not None and [e.name for e in report.discovery.found] == [name]
    assert report.fetches == 1 and report.memory_writes == 1 and report.memory_write_failures == 0
    # One remember is one enqueue, replay or not; the status polls are free to repeat.
    assert scheduled.count("xmemory_write_start") == 1
    assert scheduled.count("board_write") == 1

    seen = model.seen_text()
    assert "Look at the test feed" in seen
    assert "- ExampleConf 2027" in seen  # the fetched feed reached the model
    assert "stored in the events memory" in seen

    # The write never mentioned a status: an empty status is what puts a new event in the queue.
    queue = event_rows(await admin.read_rows(memory_targets.events, UNPROCESSED_EVENTS))
    mine = [r for r in queue if r.name == name]
    assert len(mine) == 1 and mine[0].website == website and mine[0].processing_status in ("", "unprocessed")
    runs = parse_objects(
        await admin.read_rows(memory_targets.coordination, "Every Run record. Return all rows with every field.")
    )
    assert [r.text("status") for r in runs if r.text("run_id") == f"{run_id}-discovery"] == ["completed"]

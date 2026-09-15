"""The Processing stage on a real worker with a scripted model and real xmemory."""

import pytest
import uuid

from temporalio.testing import WorkflowEnvironment

from temporal_xmemory_events_agent.dto.reports import StageStatus
from temporal_xmemory_events_agent.dto.rows import EventRow
from temporal_xmemory_events_agent.dto.stage import ProcessingInput
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.queries import ALL_EVENTS, UNPROCESSED_EVENTS
from temporal_xmemory_events_agent.memory.xresponse import event_rows, parse_objects
from temporal_xmemory_events_agent.workflows.processing import ProcessEventWorkflow

from .conftest import MemoryTargets, unique
from .fakes import RecordingModel, final_json, tool_call
from .stage_harness import stage_worker, make_settings

# Every test here talks to a real xmemory backend through the session's throwaway instances.
pytestmark = pytest.mark.memory


async def _run(env: WorkflowEnvironment, targets: MemoryTargets, model: RecordingModel, event: EventRow, **overrides):
    async with stage_worker(env, targets, model) as (client, task_queue):
        return await client.execute_workflow(
            ProcessEventWorkflow.run,
            ProcessingInput(run_id=unique("run"), event=event, settings=make_settings(**overrides)),
            id=f"process-{uuid.uuid4()}",
            task_queue=task_queue,
        )


async def test_processing_fills_details_and_leaves_the_queue(
    temporal_env: WorkflowEnvironment, memory_targets: MemoryTargets
) -> None:
    token = unique("PC")
    name = f"ProcConf {token} 2027"
    website = f"https://example.test/conference/{token}"
    events = memory_targets.events
    await admin.write_text(
        events,
        f"Event {name}, website {website}, discovered on 2026-09-15T10:00:00Z, discovery note: seeded by the test, "
        f"processing status unprocessed.",
    )
    model = RecordingModel(
        [
            tool_call("fetch_url", url=website, offset=0),
            tool_call(
                "events_remember",
                text=(
                    f"Event {name} is a conference that takes place from 2027-03-03 to 2027-03-05 at the Lisbon Congress "
                    f"Centre in Lisbon, Portugal. The call for papers of {name} closes on 2026-11-15; early-bird "
                    f"registration for {name} opens on 2026-12-01 at 450 EUR. {name} covers the topics machine learning "
                    f"systems and agents. Source URL {website}. {name} has processing status processed, processed at "
                    f"2026-09-15T11:00:00Z."
                ),
            ),
            tool_call(
                "board_remember",
                text=f"Run run-test-process by agent processor, status completed, summary: processed {name}.",
            ),
            final_json({"name": name, "status": "processed", "summary": "dates, venue, CFP and prices recorded"}),
        ]
    )
    report = await _run(
        temporal_env, memory_targets, model, EventRow(name=name, website=website, discovery_note="seeded")
    )
    assert report.status is StageStatus.COMPLETED, report.error
    assert report.processing is not None and report.processing.status == "processed"
    assert report.fetches == 1 and report.memory_writes == 1
    assert "3 to 5 March 2027" in model.seen_text()  # the fixture page reached the model
    assert name not in [r.name for r in event_rows(await admin.read_rows(events, UNPROCESSED_EVENTS))]
    stored = [o for o in parse_objects(await admin.read_rows(events, ALL_EVENTS)) if o.text("name") == name]
    assert len(stored) == 1
    assert stored[0].text("processing_status") == "processed"
    assert stored[0].text("start_date") == "2027-03-03"
    assert stored[0].text("cfp_deadline") == "2026-11-15"


async def test_turn_budget_yields_a_partial_stage(
    temporal_env: WorkflowEnvironment, memory_targets: MemoryTargets
) -> None:
    model = RecordingModel([tool_call("fetch_url", url="https://example.test/meetup/1", offset=0)], repeat_last=True)
    report = await _run(
        temporal_env,
        memory_targets,
        model,
        EventRow(name="Loop Meetup 2026", website="https://example.test/meetup/1"),
        processor_max_turns=2,
    )
    assert report.status is StageStatus.PARTIAL
    assert "2 turns" in report.error
    assert report.memory_writes == 0


async def test_fetch_budget_is_enforced_and_explained(
    temporal_env: WorkflowEnvironment, memory_targets: MemoryTargets
) -> None:
    model = RecordingModel(
        [
            tool_call("fetch_url", url="https://example.test/meetup/1", offset=0),
            tool_call("fetch_url", url="https://example.test/meetup/2", offset=0),
            final_json({"name": "Budget Meetup 2026", "status": "failed", "summary": "out of fetches"}),
        ]
    )
    report = await _run(
        temporal_env,
        memory_targets,
        model,
        EventRow(name="Budget Meetup 2026", website="https://example.test/meetup/1"),
        max_fetches_per_stage=1,
    )
    assert report.status is StageStatus.COMPLETED
    assert report.fetches == 1
    assert "BUDGET: no fetches are left" in model.seen_text()
    assert "Structured event data: name: Berlin AI Builders" in model.seen_text()

"""Live end to end: a real model, the real web and real xmemory instances. Opt-in, costs money.

Needs OPENAI_API_KEY, OPENAI_MODEL and XMEM_API_KEY. Runs one cycle with small budgets and an operator
instruction naming one well-known conference, then checks the event came back processed with ISO dates.
"""

import asyncio
import os
import re
import uuid
from datetime import timedelta

import pytest
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import ModelActivityParameters, OpenAIAgentsPlugin
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from xmemory_temporal import XmemoryConfig, XmemoryPlugin

from temporal_xmemory_events_agent.activities.fetch import ScoutActivities
from temporal_xmemory_events_agent.dto.scout import ScoutInput, ScoutStatus
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.board_activities import BoardActivities
from temporal_xmemory_events_agent.memory.queries import ALL_EVENTS
from temporal_xmemory_events_agent.memory.targets import effective_api_key_env
from temporal_xmemory_events_agent.memory.xresponse import parse_objects
from temporal_xmemory_events_agent.worker import WORKFLOW_RUNNER, WORKFLOWS
from temporal_xmemory_events_agent.workflows.scout import EventScoutWorkflow

from .conftest import MemoryTargets
from .stage_harness import make_settings
from .test_scout_workflow import _wait_for_cycle

pytestmark = pytest.mark.live

TARGET_EVENT = "NeurIPS 2026"
TARGET_SITE = "https://neurips.cc/"


@pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL")),
    reason="the live test needs OPENAI_API_KEY and OPENAI_MODEL",
)
async def test_live_cycle_processes_a_real_conference(
    temporal_env: WorkflowEnvironment, fresh_memory_targets: MemoryTargets
) -> None:
    targets = fresh_memory_targets
    settings = make_settings(
        openai_model=os.environ["OPENAI_MODEL"],
        discovery_max_turns=12,
        processor_max_turns=16,
        max_fetches_per_stage=6,
        max_events_processed_per_cycle=1,
        cycle_interval_hours=1000,
        politeness_delay_seconds=1,
    )
    openai_plugin = OpenAIAgentsPlugin(
        model_params=ModelActivityParameters(
            start_to_close_timeout=timedelta(minutes=5), retry_policy=RetryPolicy(maximum_attempts=3)
        )
    )
    events_plugin = XmemoryPlugin(
        XmemoryConfig(
            instance_id=targets.events.instance_id,
            url=targets.events.url,
            api_key_env=effective_api_key_env(targets.events),
            default_extraction_logic="deep",
        )
    )
    config = temporal_env.client.config()
    config["plugins"] = list(config.get("plugins", [])) + [openai_plugin]
    client = Client(**config)
    task_queue = f"live-{uuid.uuid4().hex[:8]}"
    scout = ScoutActivities(settings)
    try:
        async with BoardActivities(targets.coordination) as board:
            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=WORKFLOWS,
                activities=[scout.fetch_url, board.board_read, board.board_write],
                plugins=[events_plugin],
                workflow_runner=WORKFLOW_RUNNER,
            )
            run_task = asyncio.create_task(worker.run())
            try:
                handle = await client.start_workflow(
                    EventScoutWorkflow.run,
                    ScoutInput(settings=settings, paused=True),
                    id=f"live-scout-{uuid.uuid4()}",
                    task_queue=task_queue,
                )
                await handle.signal(
                    EventScoutWorkflow.instruct,
                    f"Record exactly one event this run: {TARGET_EVENT}, website {TARGET_SITE}. "
                    "Do not search for or record any other event.",
                )
                await handle.signal(EventScoutWorkflow.run_now)
                status: ScoutStatus = await _wait_for_cycle(handle, 1, timeout=1500)
                await handle.signal(EventScoutWorkflow.stop)
                await handle.result()
            finally:
                await worker.shutdown()
                await run_task
    finally:
        await scout.aclose()

    print(status.last_summary)
    stored = [
        o
        for o in parse_objects(await admin.read_rows(targets.events, ALL_EVENTS))
        if "neurips" in o.text("name").lower()
    ]
    assert stored, "the live cycle did not record the target event"
    event = stored[0]
    assert event.text("processing_status") == "processed", event.fields
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", event.text("start_date")), event.fields
    assert event.text("city") or event.text("format") == "online", event.fields

"""Run a stage workflow on a real worker: scripted model, real xmemory, fixture-backed fetch."""

import asyncio
import uuid
from datetime import timedelta
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import ModelActivityParameters
from temporalio.contrib.openai_agents.testing import AgentEnvironment
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from xmemory_temporal import XmemoryConfig, XmemoryPlugin

from temporal_xmemory_events_agent.dto.settings import ScoutSettings
from temporal_xmemory_events_agent.memory.board_activities import BoardActivities
from temporal_xmemory_events_agent.memory.targets import effective_api_key_env
from temporal_xmemory_events_agent.workflows.discovery import DiscoveryWorkflow
from temporal_xmemory_events_agent.workflows.processing import ProcessEventWorkflow
from temporal_xmemory_events_agent.workflows.scout import EventScoutWorkflow

from .conftest import MemoryTargets
from .fakes import RecordingModel, fake_fetch_url


def make_settings(**overrides: Any) -> ScoutSettings:
    base = ScoutSettings(politeness_delay_seconds=0, openai_model="scripted")
    return base.model_copy(update=overrides)


@asynccontextmanager
async def stage_worker(
    env: WorkflowEnvironment,
    targets: MemoryTargets,
    model: RecordingModel,
    *,
    max_cached_workflows: int | None = None,
) -> AsyncGenerator[tuple[Client, str], None]:
    """Yields a client with both plugins applied and the task queue a running worker listens on."""
    task_queue = f"stage-{uuid.uuid4().hex[:8]}"
    events_plugin = XmemoryPlugin(
        XmemoryConfig(
            instance_id=targets.events.instance_id,
            url=targets.events.url,
            api_key_env=effective_api_key_env(targets.events),
            default_extraction_logic="deep",
        )
    )
    # Bounded model-activity retries: an exhausted script must fail a stage, not retry forever.
    model_params = ModelActivityParameters(
        start_to_close_timeout=timedelta(seconds=120),
        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=2),
    )
    async with AgentEnvironment(model=model, model_params=model_params) as agent_env:
        client = agent_env.applied_on_client(env.client)
        async with BoardActivities(targets.coordination) as board:
            worker_kwargs: dict[str, Any] = {}
            if max_cached_workflows is not None:
                worker_kwargs["max_cached_workflows"] = max_cached_workflows
            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=[EventScoutWorkflow, DiscoveryWorkflow, ProcessEventWorkflow],
                activities=[fake_fetch_url, board.board_read, board.board_write],
                plugins=[events_plugin],
                **worker_kwargs,
            )
            # See worker.py: explicit run/shutdown/await instead of `async with worker`, which races the
            # plugin's client close and cancels the caller.
            run_task = asyncio.create_task(worker.run())
            try:
                yield client, task_queue
            finally:
                await worker.shutdown()
                await run_task


async def scheduled_activity_names(client: Client, workflow_id: str) -> list[str]:
    names: list[str] = []
    async for event in client.get_workflow_handle(workflow_id).fetch_history_events():
        if event.HasField("activity_task_scheduled_event_attributes"):
            names.append(event.activity_task_scheduled_event_attributes.activity_type.name)
    return names

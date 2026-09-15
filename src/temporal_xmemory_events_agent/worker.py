"""Build the Temporal client and worker: both agent plugins, our activities, all workflows."""

import asyncio
import logging
import signal
from datetime import timedelta

from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import ModelActivityParameters, OpenAIAgentsPlugin
from temporalio.worker import Worker
from xmemory_temporal import XmemoryConfig, XmemoryPlugin

from temporal_xmemory_events_agent.activities.fetch import ScoutActivities
from temporal_xmemory_events_agent.dto.settings import ScoutSettings, Settings
from temporal_xmemory_events_agent.memory.board_activities import BoardActivities
from temporal_xmemory_events_agent.memory.targets import effective_api_key_env, require_instance_id, resolve_target
from temporal_xmemory_events_agent.workflows.discovery import DiscoveryWorkflow
from temporal_xmemory_events_agent.workflows.processing import ProcessEventWorkflow

logger = logging.getLogger(__name__)

WORKFLOWS: list[type] = [DiscoveryWorkflow, ProcessEventWorkflow]


def stage_settings(settings: Settings) -> ScoutSettings:
    """The scout settings a stage input carries, with the model name folded in."""
    return settings.scout.model_copy(update={"openai_model": settings.openai.model})


def openai_plugin(settings: Settings) -> OpenAIAgentsPlugin:
    return OpenAIAgentsPlugin(
        model_params=ModelActivityParameters(
            start_to_close_timeout=timedelta(seconds=settings.scout.model_call_timeout_seconds),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5), maximum_interval=timedelta(minutes=2), maximum_attempts=5
            ),
        )
    )


def events_plugin(settings: Settings) -> XmemoryPlugin:
    target = resolve_target("events", settings.xmemory.events)
    config = XmemoryConfig(
        instance_id=require_instance_id(target),
        url=target.url,
        api_key_env=effective_api_key_env(target),
        default_extraction_logic="deep",
    )
    return XmemoryPlugin(config)


async def connect(settings: Settings) -> Client:
    """A client carrying both plugins; workers built from it inherit them."""
    return await Client.connect(settings.temporal.address, plugins=[openai_plugin(settings), events_plugin(settings)])


async def run_worker(settings: Settings) -> None:
    client = await connect(settings)
    board_target = resolve_target("coordination", settings.xmemory.coordination)
    scout = ScoutActivities(settings.scout)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        async with BoardActivities(board_target) as board:
            worker = Worker(
                client,
                task_queue=settings.temporal.task_queue,
                workflows=WORKFLOWS,
                activities=[scout.fetch_url, board.board_read, board.board_write],
            )
            logger.info("worker running on task queue %r; Ctrl-C to drain and stop", settings.temporal.task_queue)
            # Not `async with worker`: that form cancels the worker's run task as soon as shutdown completes,
            # while plugin run contexts (the xmemory client close) are still unwinding, and the SDK then treats
            # its own cancellation as a fatal worker error and cancels this task too. Run, shutdown, then wait.
            run_task = asyncio.create_task(worker.run())
            await stop.wait()
            await worker.shutdown()
            await run_task
            logger.info("worker stopped")
    finally:
        await scout.aclose()

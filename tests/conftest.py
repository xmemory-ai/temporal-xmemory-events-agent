"""Shared fixtures.

Memory-backed tests run against a REAL xmemory backend: the session fixture creates two throwaway instances
from the schemas, hands out their targets, and deletes them at the end. Nothing here fakes xmemory.
"""

import dataclasses
import os
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel
from temporal_xmemory_events_agent.dto.settings import MemoryTargetSettings
from temporal_xmemory_events_agent.dto.targets import MemoryTarget
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.schemas import load_schema
from temporal_xmemory_events_agent.memory.targets import resolve_target

KEY_ENV = "XMEM_API_KEY"


class MemoryTargets(FrozenTightBaseModel):
    events: MemoryTarget
    coordination: MemoryTarget


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--keep-instances", action="store_true", help="do not delete the throwaway xmemory instances")


@pytest_asyncio.fixture(scope="session")
async def memory_targets(request: pytest.FixtureRequest) -> AsyncIterator[MemoryTargets]:
    if not os.environ.get(KEY_ENV):
        pytest.skip(f"{KEY_ENV} is unset; memory-backed tests need a real xmemory backend")
    tag = uuid.uuid4().hex[:8]
    schema_dir = request.config.rootpath / "schema"
    created: dict[str, MemoryTarget] = {}
    for name in ("events", "coordination"):
        base = resolve_target(name, MemoryTargetSettings())
        instance_id = await admin.create_instance(base, load_schema(name, schema_dir), f"tmp-test-{tag}-{name}", None)
        created[name] = base.model_copy(update={"instance_id": instance_id})
    targets = MemoryTargets(events=created["events"], coordination=created["coordination"])
    try:
        yield targets
    finally:
        if not request.config.getoption("--keep-instances"):
            for target in (targets.events, targets.coordination):
                await admin.delete_instance(target, target.instance_id)


@pytest_asyncio.fixture
async def fresh_memory_targets(request: pytest.FixtureRequest) -> AsyncIterator[MemoryTargets]:
    """Pristine instances for one test, for tests whose assertions depend on the whole queue."""
    if not os.environ.get(KEY_ENV):
        pytest.skip(f"{KEY_ENV} is unset; memory-backed tests need a real xmemory backend")
    tag = uuid.uuid4().hex[:8]
    schema_dir = request.config.rootpath / "schema"
    created: dict[str, MemoryTarget] = {}
    for name in ("events", "coordination"):
        base = resolve_target(name, MemoryTargetSettings())
        instance_id = await admin.create_instance(base, load_schema(name, schema_dir), f"tmp-test-{tag}-{name}", None)
        created[name] = base.model_copy(update={"instance_id": instance_id})
    targets = MemoryTargets(events=created["events"], coordination=created["coordination"])
    try:
        yield targets
    finally:
        if not request.config.getoption("--keep-instances"):
            for target in (targets.events, targets.coordination):
                await admin.delete_instance(target, target.instance_id)


@pytest_asyncio.fixture(scope="session")
async def temporal_env() -> AsyncIterator[WorkflowEnvironment]:
    """A real local Temporal dev server (real time; the stages poll real memory writes)."""
    existing = Path.home() / ".temporalio" / "bin" / "temporal"
    env = await WorkflowEnvironment.start_local(dev_server_existing_path=str(existing) if existing.exists() else None)
    try:
        yield env
    finally:
        await env.shutdown()


@pytest.fixture
def activity_env() -> ActivityEnvironment:
    """An activity environment whose default deadline is long enough for a real memory write."""
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, start_to_close_timeout=timedelta(seconds=600))
    return env


def unique(prefix: str) -> str:
    """A test-unique token to namespace names inside the shared session instances."""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"

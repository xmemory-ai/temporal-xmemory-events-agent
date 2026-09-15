"""Inputs of the stage workflows."""

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel
from temporal_xmemory_events_agent.dto.rows import EventRow
from temporal_xmemory_events_agent.dto.settings import ScoutSettings


class DiscoveryInput(FrozenTightBaseModel):
    run_id: str
    instructions: list[str] = Field(default_factory=list, description="Operator instructions for this cycle")
    settings: ScoutSettings


class ProcessingInput(FrozenTightBaseModel):
    run_id: str
    event: EventRow
    settings: ScoutSettings

"""State and status of the entity workflow."""

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel
from temporal_xmemory_events_agent.dto.settings import ScoutSettings


class ScoutInput(FrozenTightBaseModel):
    """What the entity starts (or continues) with; everything else it needs lives in memory."""

    settings: ScoutSettings
    cycle_no: int = 0
    paused: bool = False
    last_run_id: str = ""
    last_summary: str = ""
    pending_instructions: list[str] = Field(default_factory=list)
    next_due_at: str = Field(default="", description="ISO date-time of the next cycle; empty means run at once")


class ScoutStatus(FrozenTightBaseModel):
    state: str = Field(description="starting, idle, paused, running or stopped")
    cycle_no: int
    last_run_id: str
    last_summary: str
    next_due_at: str
    paused: bool
    pending_instructions: list[str]


class CycleSummary(FrozenTightBaseModel):
    run_id: str
    status: str
    started_at: str
    finished_at: str
    discovery_status: str
    found: int
    queue_size: int
    processed_ok: int
    processed_failed: int
    text: str

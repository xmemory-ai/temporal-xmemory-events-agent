"""What the agents hand back to the workflows (structured final outputs) and what a stage returns."""

from enum import StrEnum

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel, TightBaseModel


class EventRef(TightBaseModel):
    """One event the Discovery agent wrote to memory."""

    name: str = Field(description="Canonical name, short name plus year, exactly as written to memory")
    website: str = Field(description="Official website URL, or an empty string")


class DiscoveryReport(TightBaseModel):
    """The Discovery agent's final answer."""

    found: list[EventRef] = Field(description="Events written to memory as unprocessed in this run")
    sources_checked: int = Field(description="How many sources or searches were looked at")
    notes: str = Field(description="What worked, what did not, ideas for next time")


class ProcessingReport(TightBaseModel):
    """The Processor agent's final answer for one event."""

    name: str = Field(description="Canonical event name")
    status: str = Field(description="processed or failed, as written to memory")
    summary: str = Field(description="What was found, or why processing failed")


class StageStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class StageReport(FrozenTightBaseModel):
    """Returned by a stage workflow to the entity workflow."""

    run_id: str
    stage: str
    status: StageStatus
    discovery: DiscoveryReport | None = None
    processing: ProcessingReport | None = None
    fetches: int = 0
    memory_writes: int = 0
    memory_write_failures: int = 0
    error: str = ""

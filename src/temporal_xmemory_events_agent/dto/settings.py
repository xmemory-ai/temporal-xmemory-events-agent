"""Typed configuration: the shape of ``config.yml``.

Secrets never appear here. Each memory target names the environment variable that holds its key.
"""

from pydantic import Field

from temporal_xmemory_events_agent.base_models import TightBaseModel

DEFAULT_API_KEY_ENV = "XMEM_API_KEY"
DEFAULT_API_URL_ENV = "XMEM_API_URL"
DEFAULT_API_URL = "https://api.xmemory.ai"


class MemoryTargetSettings(TightBaseModel):
    """One xmemory instance as written in ``config.yml``. Unset values resolve from the environment."""

    url: str | None = Field(
        default=None, description=f"xmemory API base URL; unset -> ${DEFAULT_API_URL_ENV} -> default"
    )
    api_key_env: str | None = Field(
        default=None, description=f"Name of the env var holding the API key; falls back to {DEFAULT_API_KEY_ENV}"
    )
    instance_id: str = Field(default="", description="Instance id, filled by `create-instances --write-config`")


class XmemorySettings(TightBaseModel):
    events: MemoryTargetSettings = Field(default_factory=MemoryTargetSettings)
    coordination: MemoryTargetSettings = Field(default_factory=MemoryTargetSettings)


class OpenAISettings(TightBaseModel):
    model: str = Field(default="", description="Model name for both agents; verified by `create-instances`")


class TemporalSettings(TightBaseModel):
    address: str = "localhost:7233"
    task_queue: str = "events-agent"
    workflow_id: str = "events-scout"


class ScoutSettings(TightBaseModel):
    cycle_interval_hours: float = 12
    max_events_processed_per_cycle: int = 10
    max_parallel_processing: int = 3
    discovery_max_turns: int = 40
    processor_max_turns: int = 40
    max_fetches_per_stage: int = 25
    fetch_chunk_chars: int = 6000
    politeness_delay_seconds: float = 2
    user_agent: str = "temporal-xmemory-events-agent/0.1 (+https://xmemory.ai)"
    stage_run_timeout_minutes: int = 120
    model_call_timeout_seconds: int = 300


class Settings(TightBaseModel):
    """The whole configuration file."""

    xmemory: XmemorySettings = Field(default_factory=XmemorySettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)
    scout: ScoutSettings = Field(default_factory=ScoutSettings)

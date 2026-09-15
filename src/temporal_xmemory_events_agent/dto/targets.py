"""A fully resolved xmemory target: where an instance lives and which env var holds its key."""

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel


class MemoryTarget(FrozenTightBaseModel):
    name: str = Field(description="events or coordination")
    url: str
    api_key_env: str = Field(description="Env var that holds the key; the key itself is never stored")
    instance_id: str = ""

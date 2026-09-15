"""Typed rows parsed out of structured (XRESPONSE) reads."""

from typing import Any

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel

Scalar = str | bool | int | float | None


class MemoryObject(FrozenTightBaseModel):
    """One object row as the reader returns it: its type, its identifier and its populated fields."""

    type_name: str
    identifier: str
    fields: dict[str, Any] = Field(default_factory=dict)

    def text(self, name: str) -> str:
        value = self.fields.get(name)
        return "" if value is None else str(value)


class EventRow(FrozenTightBaseModel):
    """The part of an Event the processing stage needs."""

    name: str
    website: str = ""
    discovery_note: str = ""
    processing_status: str = ""
    discovered_at: str = ""

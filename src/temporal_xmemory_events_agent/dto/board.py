"""Payloads of the coordination-board activities."""

from typing import Any

from pydantic import Field

from temporal_xmemory_events_agent.base_models import FrozenTightBaseModel


class BoardReadInput(FrozenTightBaseModel):
    question: str
    rows: bool = Field(default=False, description="True for a structured (XRESPONSE) read instead of an answer")


class BoardReadOutput(FrozenTightBaseModel):
    answer: str = ""
    rows: Any = None
    trace_id: str | None = None


class BoardWriteInput(FrozenTightBaseModel):
    text: str
    deep: bool = False


class BoardWriteOutput(FrozenTightBaseModel):
    write_id: str
    summary: str = Field(default="", description="What the write created or updated, for the model")
    trace_id: str | None = None

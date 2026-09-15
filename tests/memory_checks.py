"""Read-back helpers: assertions in the suite are made on what the real engine stored."""

from temporal_xmemory_events_agent.dto.rows import MemoryObject
from temporal_xmemory_events_agent.dto.targets import MemoryTarget
from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.xresponse import parse_objects


async def rows(target: MemoryTarget, question: str) -> list[MemoryObject]:
    return parse_objects(await admin.read_rows(target, question))


async def answer(target: MemoryTarget, question: str) -> str:
    return await admin.read_answer(target, question)


def mentioning(objects: list[MemoryObject], token: str) -> list[MemoryObject]:
    """The rows whose identifier or any field carries the token."""
    return [o for o in objects if token in o.identifier or any(token in str(v) for v in o.fields.values())]

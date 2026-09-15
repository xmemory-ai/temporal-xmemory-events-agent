"""Parse structured (XRESPONSE) reader results and write change sets into typed rows.

The reader returns ``{"objects": [{"name": <type>, "identifier": ..., "fields": [{"name": ..., "value":
{"string_value": ...}}]}], "relations": [...]}``. A ``None`` result means the query could not be answered at
all, which for the workflow's own fixed queries is a misphrasing and must not be mistaken for "no rows".
"""

from typing import Any

from temporal_xmemory_events_agent.dto.rows import EventRow, MemoryObject, Scalar
from temporal_xmemory_events_agent.errors import MemoryReadError

_VALUE_KEYS = ("string_value", "boolean_value", "integer_value", "float_value")


def scalar(value: Any) -> Scalar:
    """Unwrap a typed field value; a bare scalar is returned as is."""
    if isinstance(value, dict):
        for key in _VALUE_KEYS:
            if value.get(key) is not None:
                return value[key]
        return None
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return str(value)


def parse_objects(reader_result: Any) -> list[MemoryObject]:
    if reader_result is None:
        raise MemoryReadError("the structured read returned no result; the query could not be answered")
    if not isinstance(reader_result, dict) or not isinstance(reader_result.get("objects"), list):
        raise MemoryReadError(f"unexpected structured read shape: {type(reader_result).__name__}")
    rows: list[MemoryObject] = []
    for item in reader_result["objects"]:
        if not isinstance(item, dict):
            continue
        fields: dict[str, Scalar] = {}
        for field in item.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                fields[str(field["name"])] = scalar(field.get("value"))
        rows.append(
            MemoryObject(type_name=str(item.get("name", "")), identifier=str(item.get("identifier", "")), fields=fields)
        )
    return rows


def event_rows(reader_result: Any) -> list[EventRow]:
    """The Event rows of a structured read, by name; rows without a name are dropped."""
    events: list[EventRow] = []
    for obj in parse_objects(reader_result):
        if obj.type_name.lower() != "event":
            continue
        name = obj.text("name") or obj.identifier
        if not name:
            continue
        events.append(
            EventRow(
                name=name,
                website=obj.text("website"),
                discovery_note=obj.text("discovery_note"),
                processing_status=obj.text("processing_status"),
                discovered_at=obj.text("discovered_at"),
            )
        )
    return events


def summarize_changes(changes: Any) -> str:
    """One line on what a write created, updated or deleted, from the client's `changes` payload."""
    if not isinstance(changes, dict):
        return ""
    parts: list[str] = []
    for verb in ("created", "updated", "deleted"):
        section = changes.get(verb) or {}
        names = [
            f"{o.get('name', '?')} {o.get('identifier', '')}".strip()
            for o in (section.get("objects") or [])
            if isinstance(o, dict)
        ]
        links = [r.get("name", "?") for r in (section.get("relations") or []) if isinstance(r, dict)]
        if names or links:
            parts.append(f"{verb}: " + ", ".join(names + [f"link {n}" for n in links]))
    return "; ".join(parts)

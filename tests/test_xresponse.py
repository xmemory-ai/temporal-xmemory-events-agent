"""Parsing structured reads and write change sets (shapes from the reader's DTOs)."""

import pytest

from temporal_xmemory_events_agent.errors import MemoryReadError
from temporal_xmemory_events_agent.memory.xresponse import event_rows, parse_objects, scalar, summarize_changes

PAYLOAD = {
    "objects": [
        {
            "name": "Event",
            "identifier": "name='NeurIPS 2026'",
            "fields": [
                {"name": "name", "value": {"string_value": "NeurIPS 2026"}},
                {"name": "website", "value": {"string_value": "https://neurips.cc/"}},
                {"name": "processing_status", "value": {"string_value": "unprocessed"}},
                {"name": "discovered_at", "value": {"string_value": "2026-09-15T10:00:00Z"}},
                {"name": "summary", "value": {}},
            ],
        },
        {"name": "Event", "identifier": "", "fields": [{"name": "website", "value": {"string_value": "x"}}]},
        {
            "name": "Topic",
            "identifier": "name='agents'",
            "fields": [{"name": "name", "value": {"string_value": "agents"}}],
        },
    ],
    "relations": [],
}


def test_scalar_unwraps_typed_values() -> None:
    assert scalar({"string_value": "a"}) == "a"
    assert scalar({"integer_value": 3}) == 3
    assert scalar({"boolean_value": False}) is False
    assert scalar({"float_value": 1.5}) == 1.5
    assert scalar({}) is None
    assert scalar("bare") == "bare"


def test_event_rows_keep_named_events_only() -> None:
    rows = event_rows(PAYLOAD)
    assert [r.name for r in rows] == ["NeurIPS 2026"]
    assert rows[0].website == "https://neurips.cc/"
    assert rows[0].processing_status == "unprocessed"
    assert rows[0].discovered_at.startswith("2026-09-15")
    assert [o.type_name for o in parse_objects(PAYLOAD)] == ["Event", "Event", "Topic"]


def test_none_and_wrong_shapes_are_errors_not_empty() -> None:
    with pytest.raises(MemoryReadError):
        event_rows(None)
    with pytest.raises(MemoryReadError):
        event_rows("an answer string")
    assert event_rows({"objects": [], "relations": []}) == []


def test_summarize_changes() -> None:
    changes = {
        "created": {"objects": [{"name": "Run", "identifier": "run_id='run-00001'"}], "relations": []},
        "updated": {
            "objects": [{"name": "Source", "identifier": "slug='ai-deadlines'"}],
            "relations": [{"name": "event_topic"}],
        },
        "deleted": {"objects": [], "relations": []},
    }
    assert (
        summarize_changes(changes)
        == "created: Run run_id='run-00001'; updated: Source slug='ai-deadlines', link event_topic"
    )
    assert summarize_changes(None) == ""

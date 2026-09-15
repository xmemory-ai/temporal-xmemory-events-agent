"""Structural checks on the two XMD schema files."""

import yaml

from temporal_xmemory_events_agent.memory.schemas import load_schema


def test_events_schema_attendance_is_ternary_and_keyed_on_date_and_attendee() -> None:
    doc = load_schema("events")
    raw = yaml.safe_load(doc.text)
    attendance = raw["relations"]["attendance"]
    assert {role: spec["type"] for role, spec in attendance["objects"].items()} == {
        "date": "CalendarDay",
        "event": "Event",
        "attendee": "TeamMember",
    }
    assert attendance["keys"] == {"one_event_per_person_per_day": ["date", "attendee"]}
    assert raw["objects"]["CalendarDay"]["primary_key"] == ["date"]
    assert raw["objects"]["TeamMember"]["primary_key"] == ["name"]


def test_events_schema_event_identity_and_processing_state() -> None:
    raw = yaml.safe_load(load_schema("events").text)
    event = raw["objects"]["Event"]
    assert event["primary_key"] == ["name"]
    status = event["fields"]["processing_status"]
    assert status["enum"] == ["unprocessed", "processed", "failed"]
    assert status["default"] == "unprocessed"
    for field in ("start_date", "end_date", "cfp_deadline"):
        assert "ISO 8601" in event["fields"][field]["description"]


def test_coordination_schema_shape() -> None:
    doc = load_schema("coordination")
    raw = yaml.safe_load(doc.text)
    assert set(raw["objects"]) == {"Source", "Run"}
    assert raw["objects"]["Source"]["primary_key"] == ["slug"]
    assert raw["objects"]["Run"]["primary_key"] == ["run_id"]
    assert raw["objects"]["Run"]["fields"]["agent"]["enum"] == ["scout", "discovery", "processor"]
    assert doc.description.startswith("Working state")


def test_every_enum_default_is_a_member() -> None:
    for name in ("events", "coordination"):
        raw = yaml.safe_load(load_schema(name).text)
        for obj_name, obj in raw["objects"].items():
            for field_name, field in obj["fields"].items():
                if "enum" in field and "default" in field:
                    assert field["default"] in field["enum"], f"{name}.{obj_name}.{field_name}"

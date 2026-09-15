"""The events instance on the real backend: the unprocessed queue and the attendance key."""

import pytest
from xmemory import XmemoryAPIError

from temporal_xmemory_events_agent.memory import admin
from temporal_xmemory_events_agent.memory.queries import ALL_EVENTS, ATTENDANCE_LINKS, UNPROCESSED_EVENTS
from temporal_xmemory_events_agent.memory.xresponse import event_rows

from . import memory_checks
from .conftest import MemoryTargets, unique

# Every test here talks to a real xmemory backend through the session's throwaway instances.
pytestmark = pytest.mark.memory


async def test_discovered_event_enters_the_queue_and_leaves_it_when_processed(memory_targets: MemoryTargets) -> None:
    token = unique("TC")
    name = f"TestConf {token} 2027"
    events = memory_targets.events
    await admin.write_text(
        events,
        f"Event {name}, website https://example.test/{token}, discovered on 2026-09-15T10:00:00Z, "
        f"discovery note: found in the test feed.",
    )
    queue = event_rows(await admin.read_rows(events, UNPROCESSED_EVENTS))
    mine = [r for r in queue if r.name == name]
    assert len(mine) == 1, [r.name for r in queue]
    assert mine[0].processing_status in ("", "unprocessed")
    assert mine[0].website == f"https://example.test/{token}"

    await admin.write_text(
        events,
        f"Event {name} is a conference that takes place from 2027-03-03 to 2027-03-05 in Lisbon, Portugal. "
        f"Event {name} has processing status processed, processed at 2026-09-15T11:00:00Z.",
    )
    assert name not in [r.name for r in event_rows(await admin.read_rows(events, UNPROCESSED_EVENTS))]
    stored = [o for o in await memory_checks.rows(events, ALL_EVENTS) if o.text("name") == name]
    assert len(stored) == 1
    assert stored[0].text("start_date") == "2027-03-03"
    assert stored[0].text("end_date") == "2027-03-05"
    assert stored[0].text("processing_status") == "processed"
    assert stored[0].text("website") == f"https://example.test/{token}"

    # Discovery finds the same event again and writes it again without a status: one record, still processed.
    await admin.write_text(
        events,
        f"Event {name}, website https://example.test/{token}, discovered on 2026-09-16T09:00:00Z, "
        f"discovery note: seen again in another feed.",
    )
    again = [o for o in await memory_checks.rows(events, ALL_EVENTS) if o.text("name") == name]
    assert len(again) == 1
    assert again[0].text("processing_status") == "processed"
    assert again[0].text("start_date") == "2027-03-03"
    assert name not in [r.name for r in event_rows(await admin.read_rows(events, UNPROCESSED_EVENTS))]


async def test_attendance_key_allows_one_event_per_person_per_day(memory_targets: MemoryTargets) -> None:
    token = unique("P")
    person = f"Test Person {token}"
    events = memory_targets.events
    await admin.write_text(
        events,
        f"{person} is a member of the team, role tester. "
        f"Event Alpha {token} 2026 is a conference. Event Beta {token} 2026 is a conference. "
        f"{person} attends Alpha {token} 2026 on 2026-12-07.",
    )
    try:
        await admin.write_text(events, f"{person} attends Beta {token} 2026 on 2026-12-07.")
    except XmemoryAPIError as exc:
        # A rejected second link is an acceptable way to enforce the key; the read below is the assertion.
        print(f"second attendance write rejected: {exc.code}")
    links = memory_checks.mentioning(await memory_checks.rows(events, ATTENDANCE_LINKS), person)
    print([link.fields for link in links])
    assert len(links) == 1

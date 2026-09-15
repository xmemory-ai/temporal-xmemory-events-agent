from temporal_xmemory_events_agent.agents.briefs import discovery_brief, processing_brief
from temporal_xmemory_events_agent.dto.rows import EventRow
from temporal_xmemory_events_agent.dto.settings import ScoutSettings


def test_discovery_brief_carries_run_id_budget_and_operator_instructions() -> None:
    settings = ScoutSettings(discovery_max_turns=7, max_fetches_per_stage=3)
    brief = discovery_brief("run-00042", "2026-09-15T10:00:00+00:00", ["Focus on Berlin meetups"], settings)
    assert "run-00042-discovery" in brief
    assert "at most 7 turns and 3 fetches" in brief
    assert "- Focus on Berlin meetups" in brief
    assert "Operator instructions" not in discovery_brief("run-00001", "x", [], settings)


def test_processing_brief_names_the_event_and_its_website() -> None:
    row = EventRow(name="NeurIPS 2026", website="https://neurips.cc/", discovery_note="from ai-deadlines")
    brief = processing_brief("run-00042", "2026-09-15T10:00:00+00:00", row, ScoutSettings())
    assert '"NeurIPS 2026"' in brief
    assert "Website: https://neurips.cc/." in brief
    assert "Discovery note: from ai-deadlines." in brief
    assert "processing status processed" in brief

"""The coordination-board activities against the real backend."""

import pytest
from temporalio.testing import ActivityEnvironment

from temporal_xmemory_events_agent.dto.board import BoardReadInput, BoardWriteInput
from temporal_xmemory_events_agent.memory.board_activities import BoardActivities
from temporal_xmemory_events_agent.memory.xresponse import parse_objects

from .conftest import MemoryTargets, unique

# Every test here talks to a real xmemory backend through the session's throwaway instances.
pytestmark = pytest.mark.memory


async def test_board_write_then_read_round_trip(
    memory_targets: MemoryTargets, activity_env: ActivityEnvironment
) -> None:
    run_id = unique("run")
    slug = unique("src")
    text = (
        f"Run {run_id} by agent discovery started at 2026-09-15T10:00:00Z, status running. "
        f"Source {slug} (slug {slug}) is a website, label 'Test source {slug}', locator https://example.test/{slug}, "
        f"quality unknown."
    )
    async with BoardActivities(memory_targets.coordination) as board:
        written = await activity_env.run(board.board_write, BoardWriteInput(text=text))
        assert written.write_id
        assert isinstance(written.summary, str)

        structured = await activity_env.run(
            board.board_read, BoardReadInput(question="Every Run record. Return all rows with every field.", rows=True)
        )
        runs = parse_objects(structured.rows)
        mine = [r for r in runs if r.text("run_id") == run_id]
        assert len(mine) == 1, [r.fields for r in runs]
        assert mine[0].text("status") == "running"
        assert mine[0].text("agent") == "discovery"

        sources = await activity_env.run(
            board.board_read,
            BoardReadInput(question="Every Source record. Return all rows with every field.", rows=True),
        )
        mine_src = [s for s in parse_objects(sources.rows) if s.text("slug") == slug]
        assert len(mine_src) == 1
        assert mine_src[0].text("locator") == f"https://example.test/{slug}"

        spoken = await activity_env.run(
            board.board_read, BoardReadInput(question=f"What is the status of run {run_id}?")
        )
        assert "running" in spoken.answer.lower()

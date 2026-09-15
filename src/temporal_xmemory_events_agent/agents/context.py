"""The per-stage context every tool receives: memory handles and budgets. Lives in workflow code only."""

from temporal_xmemory_events_agent.dto.settings import ScoutSettings
from temporal_xmemory_events_agent.memory.board import BoardHandle


class StageContext:
    def __init__(self, settings: ScoutSettings, events: object, board: BoardHandle) -> None:
        # `events` is the plugin's WorkflowXmemory handle; typed loosely so this module stays import-light.
        self.settings = settings
        self.events = events
        self.board = board
        self.fetches = 0
        self.memory_writes = 0
        self.memory_write_failures = 0

    def fetch_budget_left(self) -> int:
        return max(0, self.settings.max_fetches_per_stage - self.fetches)

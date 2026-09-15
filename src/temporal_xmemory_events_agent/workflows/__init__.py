"""The Temporal workflows of the events agent, one pattern each.

- `EventScoutWorkflow` (scout.py): the always-alive entity. Signals only mutate state, a query reports it,
  `wait_condition` with a timeout is the cadence timer, and `continue_as_new` after every cycle keeps history small.
- `DiscoveryWorkflow` (discovery.py): a child workflow per cycle that runs the Discovery agent.
- `ProcessEventWorkflow` (processing.py): a child workflow per queued event that runs the Processor agent.

Both children get deterministic ids derived from the cycle's run id, so a retried workflow task can never start a
duplicate; each carries its own `run_timeout`, and a failed child is recorded by the entity, never fatal to it.
Model calls, web fetches and memory operations are activities: workflow code never does I/O itself.
"""

from temporal_xmemory_events_agent.workflows.discovery import DiscoveryWorkflow
from temporal_xmemory_events_agent.workflows.processing import ProcessEventWorkflow
from temporal_xmemory_events_agent.workflows.scout import EventScoutWorkflow

__all__ = ["DiscoveryWorkflow", "EventScoutWorkflow", "ProcessEventWorkflow"]

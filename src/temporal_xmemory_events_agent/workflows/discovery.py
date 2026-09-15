"""The Discovery stage: a child workflow per cycle that runs the Discovery agent, bounded by its own `run_timeout`."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporal_xmemory_events_agent.agents.briefs import discovery_brief
    from temporal_xmemory_events_agent.agents.discovery import build_discovery_agent
    from temporal_xmemory_events_agent.dto.reports import DiscoveryReport, StageReport
    from temporal_xmemory_events_agent.dto.stage import DiscoveryInput
    from temporal_xmemory_events_agent.workflows.stage_runner import new_context, run_stage


@workflow.defn
class DiscoveryWorkflow:
    @workflow.run
    async def run(self, input: DiscoveryInput) -> StageReport:
        context = new_context(input.settings)
        brief = discovery_brief(input.run_id, workflow.now().isoformat(), input.instructions, input.settings)
        report, final = await run_stage(
            run_id=input.run_id,
            stage="discovery",
            agent=build_discovery_agent(input.settings),
            brief=brief,
            context=context,
            max_turns=input.settings.discovery_max_turns,
        )
        if isinstance(final, DiscoveryReport):
            return report.model_copy(update={"discovery": final})
        return report

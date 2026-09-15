"""The Processing stage: a child workflow per queued event, bounded by `run_timeout`; the parent survives its failure."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporal_xmemory_events_agent.agents.briefs import processing_brief
    from temporal_xmemory_events_agent.agents.processor import build_processor_agent
    from temporal_xmemory_events_agent.dto.reports import ProcessingReport, StageReport
    from temporal_xmemory_events_agent.dto.stage import ProcessingInput
    from temporal_xmemory_events_agent.workflows.stage_runner import new_context, run_stage


@workflow.defn
class ProcessEventWorkflow:
    @workflow.run
    async def run(self, input: ProcessingInput) -> StageReport:
        context = new_context(input.settings)
        brief = processing_brief(input.run_id, workflow.now().isoformat(), input.event, input.settings)
        report, final = await run_stage(
            run_id=input.run_id,
            stage=f"process:{input.event.name}",
            agent=build_processor_agent(input.settings),
            brief=brief,
            context=context,
            max_turns=input.settings.processor_max_turns,
        )
        if isinstance(final, ProcessingReport):
            return report.model_copy(update={"processing": final})
        return report

"""
LangSmith adapter: pull failed root runs (and their child runs) with the
`langsmith` SDK and convert them into Faultline Traces. Pushes the verdict
back as run feedback.

Requires: pip install langsmith, and LANGSMITH_API_KEY in the environment.
"""

from .. import config
from ..schema import Step, Trace

RUN_TYPES = {"llm": "llm", "tool": "tool", "chain": "agent", "retriever": "tool"}


def _client():
    try:
        from langsmith import Client
    except ImportError:
        raise RuntimeError("pip install langsmith to use the LangSmith adapter")
    return Client()


def run_to_step(index: int, run) -> Step:
    latency = 0
    if run.start_time and run.end_time:
        latency = int((run.end_time - run.start_time).total_seconds() * 1000)
    return Step(
        index=index,
        type=RUN_TYPES.get(run.run_type, "tool"),
        name=run.name,
        input=run.inputs,
        output=run.outputs,
        error=run.error,
        latency_ms=latency,
    )


def fetch_failed_traces(limit: int = 50) -> list[Trace]:
    client = _client()
    roots = client.list_runs(project_name=config.LANGSMITH_PROJECT, is_root=True, error=True, limit=limit)
    traces = []
    for root in roots:
        children = list(client.list_runs(project_name=config.LANGSMITH_PROJECT, trace_id=root.trace_id))
        children = [c for c in children if c.id != root.id]
        children.sort(key=lambda r: r.start_time)
        traces.append(Trace(
            id=f"ls-{root.id}",
            agent_name=root.name,
            task=str(root.inputs),
            status="failed",
            source="langsmith",
            steps=[run_to_step(i, r) for i, r in enumerate(children)],
            final_output=root.outputs,
            created_at=root.start_time.isoformat() if root.start_time else "",
        ))
    return traces


def push_verdict(trace_id: str, failure_class: str, comment: str):
    client = _client()
    client.create_feedback(run_id=trace_id.removeprefix("ls-"), key="faultline_root_cause",
                           value=failure_class, comment=comment)

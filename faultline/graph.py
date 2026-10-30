"""
The investigation pipeline as a LangGraph state machine.

    START -> triage -> researcher -> investigator -> critic --(grounded)--> fixer -> replayer -> test_writer -> END
                                          ^             |
                                          +--(retry)----+          critic --(nothing found)--> END

The critic -> investigator loop is the key idea: an LLM answer is only accepted
when every quote it cites can be found in the trace. Otherwise it gets feedback
and tries again (max 2 attempts), then we fall back to deterministic rules.
"""

import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import agents, config, db
from .causal import affected_steps
from .schema import Autopsy, NodeRun, Trace


class State(TypedDict, total=False):
    trace: Trace
    mode: str
    signals: list
    context: dict
    hypotheses: list
    attempts: int
    critic_feedback: str
    fix: Any
    replay: Any
    regression_test: str
    log: Annotated[list, operator.add]   # every node appends one NodeRun


def timed(name, func):
    """Wrap a node so it records how long it took and what it did."""
    def node(state):
        start = time.perf_counter()
        update = func(state)
        ms = int((time.perf_counter() - start) * 1000)
        note = update.pop("note", "")
        update["log"] = [NodeRun(node=name, ms=ms, note=note)]
        return update
    return node


def build_graph():
    graph = StateGraph(State)
    graph.add_node("triage", timed("triage", agents.triage))
    graph.add_node("researcher", timed("researcher", agents.researcher))
    graph.add_node("investigator", timed("investigator", agents.investigator))
    graph.add_node("critic", timed("critic", agents.critic))
    graph.add_node("fixer", timed("fixer", agents.fixer))
    graph.add_node("replayer", timed("replayer", agents.replayer))
    graph.add_node("test_writer", timed("test_writer", agents.test_writer))

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "researcher")
    graph.add_edge("researcher", "investigator")
    graph.add_edge("investigator", "critic")
    graph.add_conditional_edges("critic", agents.after_critic,
                                {"investigator": "investigator", "fixer": "fixer", "done": END})
    graph.add_edge("fixer", "replayer")
    graph.add_edge("replayer", "test_writer")
    graph.add_edge("test_writer", END)
    return graph.compile()


PIPELINE = build_graph()


def investigate(trace: Trace, mode: str = None, save: bool = True) -> Autopsy:
    """Run the full investigation on one trace and return the Autopsy."""
    mode = mode or config.effective_mode()
    start = time.perf_counter()
    final = PIPELINE.invoke({"trace": trace, "mode": mode, "log": []})

    hypotheses = final.get("hypotheses") or []
    root = hypotheses[0] if hypotheses else None

    affected = []
    if root:
        affected = affected_steps(trace, root.root_cause_step, final["signals"])
        for ev in root.evidence:
            if ev.step_index > root.root_cause_step and ev.step_index not in affected:
                affected.append(ev.step_index)
        affected.sort()

    if root:
        verdict = "failure_found"
    elif trace.status == "success":
        verdict = "healthy"
    else:
        verdict = "inconclusive"

    autopsy = Autopsy(
        trace_id=trace.id,
        verdict=verdict,
        root_cause=root,
        other_hypotheses=hypotheses[1:],
        signals=final.get("signals", []),
        affected_steps=affected,
        fix=final.get("fix"),
        replay=final.get("replay"),
        regression_test=final.get("regression_test", ""),
        similar=final.get("context", {}).get("incidents", []),
        investigation=final.get("log", []),
        mode=mode,
        duration_ms=int((time.perf_counter() - start) * 1000),
        created_at=db.now(),
    )

    if save:
        root_tool = ""
        if root:
            for step in trace.steps:
                if step.index == root.root_cause_step:
                    root_tool = step.name
        db.save_autopsy(autopsy, root_tool=root_tool)
    return autopsy


def mermaid() -> str:
    """Graph diagram (used in docs and the UI)."""
    return PIPELINE.get_graph().draw_mermaid()

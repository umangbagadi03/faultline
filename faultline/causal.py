"""
Causal reasoning over signals: which signal is the ROOT cause, and which are symptoms?

Rule ("first domino"): the earliest serious signal is the root cause.
If two signals hit the same step, the one higher in CAUSAL_PRIORITY wins
(e.g. a bad argument CAUSES a loop, not the other way round).
"""

from typing import Optional

from .schema import Signal, Trace

CAUSAL_PRIORITY = [
    "PROMPT_INJECTION",
    "HALLUCINATED_TOOL",
    "TOOL_ARG_ERROR",
    "UNHANDLED_TOOL_FAILURE",
    "INFINITE_LOOP",
    "UNGROUNDED_ANSWER",
    "BAD_OUTPUT_FORMAT",
]

SERIOUS = 2   # signals below this severity are informational only


def serious_signals(signals: list[Signal]) -> list[Signal]:
    return [s for s in signals if s.severity >= SERIOUS]


def rank_signals(signals: list[Signal]) -> list[Signal]:
    def sort_key(signal: Signal):
        priority = CAUSAL_PRIORITY.index(signal.failure_class)
        return (signal.step_index, priority, -signal.severity)
    return sorted(serious_signals(signals), key=sort_key)


def pick_root_signal(signals: list[Signal]) -> Optional[Signal]:
    ranked = rank_signals(signals)
    if not ranked:
        return None
    return ranked[0]


def affected_steps(trace: Trace, root_step: int, signals: list[Signal]) -> list[int]:
    """Steps after the root cause that show damage (errors or other signals)."""
    affected = set()
    for step in trace.steps:
        if step.index > root_step and step.error:
            affected.add(step.index)
    for signal in serious_signals(signals):
        if signal.step_index > root_step:
            affected.add(signal.step_index)
        if signal.step_index == root_step:
            affected.update(signal.related_steps)
    return sorted(affected)

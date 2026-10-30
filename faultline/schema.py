"""
Data models used everywhere in Faultline.

A Trace is the "black box recording" of one agent run.
An Autopsy is what Faultline produces after investigating a Trace.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------- Failure taxonomy ----------
# Every root cause Faultline reports must be one of these classes.

FAILURE_CLASSES = {
    "TOOL_ARG_ERROR": "Agent called a real tool with wrong, missing or badly typed arguments.",
    "HALLUCINATED_TOOL": "Agent called a tool that does not exist.",
    "INFINITE_LOOP": "Agent repeated the same action again and again without progress.",
    "UNHANDLED_TOOL_FAILURE": "A tool failed (timeout, 5xx) and the agent did not retry or recover.",
    "PROMPT_INJECTION": "Text inside a tool result hijacked the agent into an unauthorized action.",
    "UNGROUNDED_ANSWER": "Final answer states facts that contradict or are missing from tool results.",
    "BAD_OUTPUT_FORMAT": "Final output does not match the format the caller expected.",
}


# ---------- Trace (input) ----------

class ToolSpec(BaseModel):
    name: str
    params: dict[str, str] = {}          # param name -> type ("str", "int", ...)
    required: list[str] = []
    sensitive: bool = False              # e.g. send_email, transfer_money


class Step(BaseModel):
    index: int
    type: str                            # "llm" | "tool" | "agent"
    name: str                            # model name, tool name or sub-agent name
    agent: str = "main"                  # which agent did this (for multi-agent traces)
    input: Any = None
    output: Any = None
    error: Optional[str] = None
    latency_ms: int = 0


class Trace(BaseModel):
    id: str
    agent_name: str = "agent"
    task: str
    status: str = "failed"               # "success" | "failed"
    source: str = "local"                # local | langfuse | langsmith | simulator
    tools: list[ToolSpec] = []
    steps: list[Step] = []
    final_output: Any = None
    expected_output_keys: list[str] = [] # if set, final output must be JSON with these keys
    label: Optional[dict] = None         # ground truth (only for seeded eval traces)
    created_at: str = ""


# ---------- Investigation results (output) ----------

class Signal(BaseModel):
    """A deterministic finding from a detector. Cheap, fast, always trustworthy."""
    failure_class: str
    step_index: int
    message: str
    severity: int = 1                    # 1 low .. 3 high
    related_steps: list[int] = []        # later steps damaged by this problem


class Evidence(BaseModel):
    step_index: int
    quote: str                           # text that must really appear in that step


class Hypothesis(BaseModel):
    failure_class: str
    root_cause_step: int
    title: str
    explanation: str
    evidence: list[Evidence] = []
    confidence: float = 0.5


class Fix(BaseModel):
    kind: str                            # patch_args | add_retry | loop_guard | ...
    summary: str
    details: dict = {}


class ReplayResult(BaseModel):
    verified: bool
    method: str
    log: list[str] = []


class NodeRun(BaseModel):
    """One step of the investigation graph, shown in the UI."""
    node: str
    status: str = "ok"
    ms: int = 0
    note: str = ""


class Autopsy(BaseModel):
    trace_id: str
    verdict: str                         # "failure_found" | "healthy" | "inconclusive"
    root_cause: Optional[Hypothesis] = None
    other_hypotheses: list[Hypothesis] = []
    signals: list[Signal] = []
    affected_steps: list[int] = []
    fix: Optional[Fix] = None
    replay: Optional[ReplayResult] = None
    regression_test: str = ""
    similar: list[dict] = []             # results from the RAG knowledge base
    investigation: list[NodeRun] = []
    mode: str = "rules"                  # "rules" or "llm"
    duration_ms: int = 0
    created_at: str = ""

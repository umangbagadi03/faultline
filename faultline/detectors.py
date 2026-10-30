"""
Deterministic failure detectors.

Each detector looks at a Trace and returns a list of Signals.
No LLM here: these are fast, free and never hallucinate.
The LLM investigator (when enabled) builds on top of these signals.
"""

import json
import re

from .schema import Signal, Step, Trace

TRANSIENT_ERROR_WORDS = ["timeout", "timed out", "503", "502", "500", "unavailable",
                         "rate limit", "connection reset", "temporarily"]

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the |your )?(previous|prior|system)",
    r"you must now",
    r"new instructions?:",
    r"system override",
    r"forward .* to .*@",
    r"send .* to .*@",
]


# ---------- small helpers ----------

def to_text(value) -> str:
    """Turn any step input/output into a plain string we can search."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def step_text(step: Step) -> str:
    parts = [step.name, to_text(step.input), to_text(step.output), step.error or ""]
    return " ".join(parts)


def find_step(trace: Trace, index: int):
    for step in trace.steps:
        if step.index == index:
            return step
    return None


def tool_steps(trace: Trace) -> list[Step]:
    return [s for s in trace.steps if s.type == "tool"]


def is_transient(error: str) -> bool:
    error = error.lower()
    for word in TRANSIENT_ERROR_WORDS:
        if word in error:
            return True
    return False


def numbers_in(text: str) -> set[str]:
    """Numbers with 3+ digits, with thousands separators removed ("4,520" -> "4520")."""
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return set(re.findall(r"\b\d{3,}\b", text))


def type_matches(value, expected: str) -> bool:
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "list":
        return isinstance(value, list)
    if expected == "date":
        return isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
    return isinstance(value, str)


# ---------- detectors ----------

def detect_hallucinated_tools(trace: Trace) -> list[Signal]:
    known = {t.name for t in trace.tools}
    if not known:
        return []
    signals = []
    for step in tool_steps(trace):
        if step.name not in known:
            signals.append(Signal(
                failure_class="HALLUCINATED_TOOL",
                step_index=step.index,
                message=f"Tool '{step.name}' is not in the agent's tool list {sorted(known)}.",
                severity=3,
            ))
    return signals


def detect_tool_arg_errors(trace: Trace) -> list[Signal]:
    specs = {t.name: t for t in trace.tools}
    signals = []
    for step in tool_steps(trace):
        spec = specs.get(step.name)
        if spec is None or not isinstance(step.input, dict):
            continue

        problems = []
        for name in spec.required:
            if name not in step.input:
                problems.append(f"missing required arg '{name}'")
        for name, value in step.input.items():
            if name not in spec.params:
                problems.append(f"unknown arg '{name}'")
            elif not type_matches(value, spec.params[name]):
                problems.append(f"arg '{name}'={value!r} is not a valid {spec.params[name]}")

        if problems:
            severity = 3 if step.error else 2
            signals.append(Signal(
                failure_class="TOOL_ARG_ERROR",
                step_index=step.index,
                message=f"Call to '{step.name}': " + "; ".join(problems) + ".",
                severity=severity,
            ))
    return signals


def detect_loops(trace: Trace, threshold: int = 3) -> list[Signal]:
    signals = []
    steps = tool_steps(trace)
    i = 0
    while i < len(steps):
        key = (steps[i].name, to_text(steps[i].input))
        count = 1
        j = i + 1
        while j < len(steps) and (steps[j].name, to_text(steps[j].input)) == key:
            count += 1
            j += 1
        if count >= threshold:
            signals.append(Signal(
                failure_class="INFINITE_LOOP",
                step_index=steps[i].index,
                message=f"'{steps[i].name}' was called {count} times in a row with identical input.",
                severity=3,
                related_steps=[s.index for s in steps[i + 1:j]],
            ))
        i = j
    return signals


def detect_unhandled_tool_failures(trace: Trace) -> list[Signal]:
    signals = []
    steps = tool_steps(trace)
    for pos, step in enumerate(steps):
        if not step.error or not is_transient(step.error):
            continue
        recovered = False
        for later in steps[pos + 1:]:
            if later.name == step.name and not later.error:
                recovered = True
                break
        if not recovered:
            signals.append(Signal(
                failure_class="UNHANDLED_TOOL_FAILURE",
                step_index=step.index,
                message=f"'{step.name}' failed with '{step.error}' and was never retried successfully.",
                severity=3 if trace.status == "failed" else 1,
            ))
    return signals


def detect_prompt_injection(trace: Trace) -> list[Signal]:
    sensitive = {t.name for t in trace.tools if t.sensitive}
    signals = []
    for step in tool_steps(trace):
        output = to_text(step.output).lower()
        matched = None
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, output):
                matched = pattern
                break
        if matched is None:
            continue

        # Did the agent act on it? Look for a later call to a sensitive tool.
        hijacked = None
        for later in tool_steps(trace):
            if later.index > step.index and later.name in sensitive:
                hijacked = later
                break

        if hijacked:
            msg = (f"Output of '{step.name}' contains injected instructions; agent then called "
                   f"sensitive tool '{hijacked.name}' at step {hijacked.index}.")
            severity = 3
        else:
            msg = f"Output of '{step.name}' contains injected instructions, but the agent did not act on them."
            severity = 1
        related = [hijacked.index] if hijacked else []
        signals.append(Signal(failure_class="PROMPT_INJECTION", step_index=step.index,
                              message=msg, severity=severity, related_steps=related))
    return signals


def detect_ungrounded_answer(trace: Trace) -> list[Signal]:
    """Numbers in the final answer should come from tool results or the task."""
    final = to_text(trace.final_output)
    if not final:
        return []

    sources = trace.task
    for step in tool_steps(trace):
        sources += " " + to_text(step.output)

    missing = numbers_in(final) - numbers_in(sources)
    missing = sorted(missing)
    if not missing:
        return []

    last_llm = None
    for step in trace.steps:
        if step.type == "llm":
            last_llm = step
    index = last_llm.index if last_llm else len(trace.steps) - 1
    return [Signal(
        failure_class="UNGROUNDED_ANSWER",
        step_index=index,
        message=f"Final answer mentions {missing}, which never appears in any tool result.",
        severity=2,
    )]


def detect_bad_output_format(trace: Trace) -> list[Signal]:
    if not trace.expected_output_keys:
        return []
    index = len(trace.steps) - 1
    output = trace.final_output

    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return [Signal(failure_class="BAD_OUTPUT_FORMAT", step_index=index,
                           message="Final output is not valid JSON.", severity=2)]

    if not isinstance(output, dict):
        return [Signal(failure_class="BAD_OUTPUT_FORMAT", step_index=index,
                       message="Final output is not a JSON object.", severity=2)]

    missing = [k for k in trace.expected_output_keys if k not in output]
    if missing:
        return [Signal(failure_class="BAD_OUTPUT_FORMAT", step_index=index,
                       message=f"Final output is missing required keys {missing}.", severity=2)]
    return []


ALL_DETECTORS = [
    detect_hallucinated_tools,
    detect_tool_arg_errors,
    detect_loops,
    detect_unhandled_tool_failures,
    detect_prompt_injection,
    detect_ungrounded_answer,
    detect_bad_output_format,
]


def run_detectors(trace: Trace) -> list[Signal]:
    signals = []
    for detector in ALL_DETECTORS:
        signals.extend(detector(trace))
    signals.sort(key=lambda s: (s.step_index, -s.severity))
    return signals

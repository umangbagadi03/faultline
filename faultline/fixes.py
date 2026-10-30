"""
Turn a root cause into a concrete, machine-checkable fix.

Each fix has a `kind` that maps to a guard in guards.py,
and `details` that the replayer needs to verify it.
"""

import difflib

from .detectors import find_step, to_text
from .schema import Fix, Hypothesis, Trace


def closest(word: str, options: list[str]):
    matches = difflib.get_close_matches(word, options, n=1, cutoff=0.3)
    return matches[0] if matches else None


def correct_args(args: dict, params: dict, required: list[str]) -> dict:
    """Rename unknown args to the closest missing param and coerce simple types."""
    fixed = {}
    missing = [p for p in required if p not in args]
    for name, value in args.items():
        if name not in params:
            target = closest(name, missing) or closest(name, list(params))
            if target:
                name = target
                if target in missing:
                    missing.remove(target)
        expected = params.get(name)
        if expected == "int" and isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        fixed[name] = value
    return fixed


def propose_fix(trace: Trace, root: Hypothesis) -> Fix:
    step = find_step(trace, root.root_cause_step)
    specs = {t.name: t for t in trace.tools}
    cls = root.failure_class

    if cls == "TOOL_ARG_ERROR" and step is not None:
        spec = specs.get(step.name)
        original = step.input if isinstance(step.input, dict) else {}
        corrected = original
        if spec:
            corrected = correct_args(original, spec.params, spec.required)
        return Fix(
            kind="patch_args",
            summary=f"Validate '{step.name}' arguments against its schema before calling it. "
                    f"Corrected call: {step.name}({to_text(corrected)}).",
            details={"tool": step.name, "original_args": original, "corrected_args": corrected},
        )

    if cls == "HALLUCINATED_TOOL" and step is not None:
        suggestion = closest(step.name, list(specs)) or ""
        return Fix(
            kind="use_registered_tool",
            summary=f"'{step.name}' does not exist. Route unknown tool names to the closest real tool "
                    f"('{suggestion}') and list valid tools in the error message.",
            details={"called": step.name, "suggested": suggestion,
                     "args": step.input if isinstance(step.input, dict) else {}},
        )

    if cls == "INFINITE_LOOP" and step is not None:
        return Fix(
            kind="loop_guard",
            summary=f"Add LoopGuard(max_repeats=2): block identical '{step.name}' calls after 2 repeats "
                    "and tell the model to use the result it already has.",
            details={"tool": step.name, "max_repeats": 2},
        )

    if cls == "UNHANDLED_TOOL_FAILURE" and step is not None:
        return Fix(
            kind="add_retry",
            summary=f"Wrap '{step.name}' in call_with_retry(attempts=3) with exponential backoff "
                    "for transient errors (timeouts, 5xx).",
            details={"tool": step.name, "args": step.input if isinstance(step.input, dict) else {},
                     "attempts": 3},
        )

    if cls == "PROMPT_INJECTION":
        sensitive = [t.name for t in trace.tools if t.sensitive]
        return Fix(
            kind="permission_gate",
            summary="Treat tool output as untrusted data and put sensitive tools "
                    f"({', '.join(sensitive) or 'none declared'}) behind a PermissionGate that needs "
                    "explicit user approval.",
            details={"sensitive_tools": sensitive, "injected_step": root.root_cause_step},
        )

    if cls == "UNGROUNDED_ANSWER":
        return Fix(
            kind="grounding_check",
            summary="Before answering, check every number in the answer appears in a tool result; "
                    "if not, re-generate the answer quoting the tool output.",
            details={},
        )

    if cls == "BAD_OUTPUT_FORMAT":
        return Fix(
            kind="output_validator",
            summary=f"Enforce a JSON schema with keys {trace.expected_output_keys} using structured "
                    "outputs, and validate before returning.",
            details={"required_keys": trace.expected_output_keys},
        )

    return Fix(kind="manual", summary="No automatic fix available; review the evidence manually.")

"""
Replay: re-run the failing part of a trace WITH the proposed fix applied,
in a sandbox, and check whether the failure goes away.

Two tool backends:
  - MockBackend:     our offline mock tools (demo / simulator traces)
  - CassetteBackend: answers from the recorded trace itself ("record & replay").
                     Works for any imported trace, but can only answer calls
                     that were actually recorded.
"""

import json

from .demo.tools import MOCK_TOOLS, call_tool
from .detectors import find_step, to_text, tool_steps
from .fixes import correct_args
from .guards import (GuardBlocked, LoopGuard, PermissionGate, call_with_retry,
                     find_injection, ungrounded_numbers, validate_output)
from .schema import Fix, ReplayResult, Trace


class CassetteMiss(Exception):
    pass


class MockBackend:
    name = "mock tools"

    def call(self, tool: str, args: dict):
        return call_tool(tool, args)


class CassetteBackend:
    name = "recorded cassette"

    def __init__(self, trace: Trace):
        self.recordings = {}
        for step in tool_steps(trace):
            key = (step.name, json.dumps(step.input, sort_keys=True))
            self.recordings[key] = step

    def call(self, tool: str, args: dict):
        key = (tool, json.dumps(args, sort_keys=True))
        step = self.recordings.get(key)
        if step is None:
            raise CassetteMiss(f"no recording for {tool}({to_text(args)})")
        if step.error:
            raise Exception(step.error)
        return step.output


def pick_backend(trace: Trace):
    names = {t.name for t in trace.tools}
    if names and names.issubset(MOCK_TOOLS.keys()):
        return MockBackend()
    return CassetteBackend(trace)


def replay(trace: Trace, fix: Fix) -> ReplayResult:
    backend = pick_backend(trace)
    log = [f"backend: {backend.name}"]
    d = fix.details

    try:
        if fix.kind == "patch_args":
            log.append(f"original: {d['tool']}({to_text(d['original_args'])})")
            log.append(f"patched:  {d['tool']}({to_text(d['corrected_args'])})")
            result = backend.call(d["tool"], d["corrected_args"])
            log.append(f"result: {to_text(result)[:200]}")
            return ReplayResult(verified=True, method="re-executed the call with corrected arguments", log=log)

        if fix.kind == "use_registered_tool":
            if not d["suggested"]:
                return ReplayResult(verified=False, method="no similar registered tool found", log=log)
            spec = next(t for t in trace.tools if t.name == d["suggested"])
            args = correct_args(d["args"], spec.params, spec.required)
            log.append(f"routed '{d['called']}' -> '{d['suggested']}' with {to_text(args)}")
            result = backend.call(d["suggested"], args)
            log.append(f"result: {to_text(result)[:200]}")
            return ReplayResult(verified=True, method="re-executed using the closest registered tool", log=log)

        if fix.kind == "loop_guard":
            guard = LoopGuard(max_repeats=d["max_repeats"])
            executed = 0
            for step in tool_steps(trace):
                args = step.input if isinstance(step.input, dict) else {}
                try:
                    guard.check(step.name, args)
                    executed += 1
                    log.append(f"step {step.index}: {step.name} allowed")
                except GuardBlocked as e:
                    log.append(f"step {step.index}: BLOCKED - {e}")
                    return ReplayResult(verified=True, method="loop guard stopped the repeated call", log=log)
            return ReplayResult(verified=False, method="loop guard never triggered", log=log)

        if fix.kind == "add_retry":
            tool = d["tool"]
            recorded_failures = [s for s in tool_steps(trace) if s.name == tool and s.error]
            fail_times = len(recorded_failures)
            error_text = recorded_failures[0].error if recorded_failures else "timeout"
            state = {"calls": 0}

            def flaky_tool(**args):
                state["calls"] += 1
                if state["calls"] <= fail_times:
                    log.append(f"attempt {state['calls']}: {error_text} (replayed failure)")
                    raise Exception(error_text)
                log.append(f"attempt {state['calls']}: ok")
                return backend.call(tool, args)

            try:
                call_with_retry(flaky_tool, d["args"], attempts=d["attempts"])
                return ReplayResult(verified=True, method="retry policy recovered from the replayed failure", log=log)
            except Exception:
                return ReplayResult(verified=False, method="failure persisted beyond the retry budget", log=log)

        if fix.kind == "permission_gate":
            injected = find_step(trace, d["injected_step"])
            phrase = find_injection(to_text(injected.output)) if injected else None
            log.append(f"sanitizer flagged injected text: {phrase!r}")
            gate = PermissionGate(d["sensitive_tools"])
            blocked = False
            for step in tool_steps(trace):
                args = step.input if isinstance(step.input, dict) else {}
                try:
                    gate.check(step.name, args)
                    log.append(f"step {step.index}: {step.name} allowed")
                except GuardBlocked as e:
                    log.append(f"step {step.index}: BLOCKED - {e}")
                    blocked = True
            ok = blocked and phrase is not None
            method = "permission gate blocked the hijacked action" if ok else "gate did not block anything"
            return ReplayResult(verified=ok, method=method, log=log)

        if fix.kind == "grounding_check":
            sources = trace.task + " " + " ".join(to_text(s.output) for s in tool_steps(trace))
            bad = ungrounded_numbers(to_text(trace.final_output), sources)
            log.append(f"ungrounded values caught: {bad}")
            return ReplayResult(verified=bool(bad), method="grounding check rejects the original answer", log=log)

        if fix.kind == "output_validator":
            problems = validate_output(trace.final_output, d["required_keys"])
            log.append(f"validator problems: {problems}")
            return ReplayResult(verified=bool(problems), method="output validator rejects the original output", log=log)

    except CassetteMiss as e:
        log.append(str(e))
        return ReplayResult(verified=False, method="cannot verify offline: connect a mock for this tool", log=log)
    except Exception as e:
        log.append(f"replay error: {e}")
        return ReplayResult(verified=False, method="the fix did not make the call succeed", log=log)

    return ReplayResult(verified=False, method="no replay strategy for this fix", log=log)

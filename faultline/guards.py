"""
Guards: small runtime protections an agent can use.

Every fix Faultline proposes maps to one of these guards, and the replay
step proves that the guard would have stopped the original failure.
Users can import these straight into their own agent code.
"""

import json
import re
import time

from .detectors import INJECTION_PATTERNS, is_transient, numbers_in


class GuardBlocked(Exception):
    """Raised when a guard refuses to let a tool call through."""


class LoopGuard:
    """Blocks a tool call if the identical call was already made `max_repeats` times in a row."""

    def __init__(self, max_repeats: int = 2):
        self.max_repeats = max_repeats
        self.last_key = None
        self.count = 0

    def check(self, tool_name: str, args: dict):
        key = (tool_name, json.dumps(args, sort_keys=True))
        if key == self.last_key:
            self.count += 1
        else:
            self.last_key = key
            self.count = 1
        if self.count > self.max_repeats:
            raise GuardBlocked(f"Loop guard: '{tool_name}' already called {self.max_repeats} times with the same input.")


class PermissionGate:
    """Sensitive tools can only run if the user's task actually asked for them."""

    def __init__(self, sensitive_tools: list[str], allowed: list[str] = None):
        self.sensitive_tools = set(sensitive_tools)
        self.allowed = set(allowed or [])

    def check(self, tool_name: str, args: dict):
        if tool_name in self.sensitive_tools and tool_name not in self.allowed:
            raise GuardBlocked(f"Permission gate: '{tool_name}' needs explicit user approval.")


def find_injection(text: str):
    """Return the injected phrase if the text looks like it contains instructions."""
    lowered = text.lower()
    for pattern in INJECTION_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            return match.group(0)
    return None


def call_with_retry(func, args: dict, attempts: int = 3, backoff_s: float = 0.0):
    """Retry a tool only on transient errors (timeouts, 5xx)."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return func(**args)
        except Exception as e:
            last_error = e
            if not is_transient(str(e)) or attempt == attempts:
                raise
            time.sleep(backoff_s * attempt)
    raise last_error


def ungrounded_numbers(answer: str, sources: str) -> list[str]:
    """Numbers in the answer that never appear in the sources."""
    return sorted(numbers_in(answer) - numbers_in(sources))


def validate_output(output, required_keys: list[str]) -> list[str]:
    """Return a list of problems; empty list means the output is valid."""
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return ["output is not valid JSON"]
    if not isinstance(output, dict):
        return ["output is not a JSON object"]
    return [f"missing key '{k}'" for k in required_keys if k not in output]

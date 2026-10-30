"""
Evaluation: run Faultline on traces with known ground truth and measure accuracy.

Metrics
  class_accuracy   - predicted failure class == true class (failed runs)
  step_accuracy    - class AND root-cause step both correct
  false_positive   - a healthy run was reported as a failure
  fix_verified     - replay confirmed the fix (for correctly classified runs)
"""

import time
from collections import defaultdict

from .graph import investigate
from .schema import Trace


def evaluate(traces: list[Trace], mode: str = "rules") -> dict:
    labeled = [t for t in traces if t.label is not None]
    per_class = defaultdict(lambda: {"n": 0, "class_ok": 0, "step_ok": 0})
    failures = healthy = class_ok = step_ok = false_pos = verified = 0
    misses = []
    start = time.perf_counter()

    for trace in labeled:
        autopsy = investigate(trace, mode=mode, save=False)
        truth = trace.label.get("failure_class")
        predicted = autopsy.root_cause.failure_class if autopsy.root_cause else None
        predicted_step = autopsy.root_cause.root_cause_step if autopsy.root_cause else None

        if truth is None:
            healthy += 1
            if autopsy.verdict == "failure_found":
                false_pos += 1
                misses.append({"trace_id": trace.id, "scenario": trace.label.get("scenario"),
                               "expected": "healthy", "got": predicted})
            continue

        failures += 1
        row = per_class[truth]
        row["n"] += 1
        if predicted == truth:
            class_ok += 1
            row["class_ok"] += 1
            if autopsy.replay and autopsy.replay.verified:
                verified += 1
            if predicted_step == trace.label.get("root_cause_step"):
                step_ok += 1
                row["step_ok"] += 1
        else:
            misses.append({"trace_id": trace.id, "scenario": trace.label.get("scenario"),
                           "expected": truth, "got": predicted or "nothing found"})

    def pct(a, b):
        return round(100 * a / b, 1) if b else 0.0

    classes = []
    for name, row in sorted(per_class.items()):
        classes.append({"failure_class": name, "n": row["n"],
                        "class_accuracy": pct(row["class_ok"], row["n"]),
                        "step_accuracy": pct(row["step_ok"], row["n"])})

    return {
        "mode": mode,
        "total": len(labeled),
        "failed_runs": failures,
        "healthy_runs": healthy,
        "class_accuracy": pct(class_ok, failures),
        "step_accuracy": pct(step_ok, failures),
        "false_positive_rate": pct(false_pos, healthy),
        "fix_verified_rate": pct(verified, class_ok),
        "avg_ms_per_trace": round((time.perf_counter() - start) * 1000 / max(len(labeled), 1), 1),
        "per_class": classes,
        "misses": misses,
    }

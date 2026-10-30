import subprocess
import sys

from faultline import db
from faultline.demo.simulator import generate
from faultline.eval import evaluate
from faultline.graph import investigate
from faultline.testgen import regression_filename

db.init_db()


def test_pipeline_produces_verified_fix_and_test():
    trace = next(t for t in generate(1) if t.label["scenario"] == "arg_wrong_name")
    autopsy = investigate(trace, mode="rules", save=False)
    assert autopsy.verdict == "failure_found"
    assert autopsy.root_cause.failure_class == "TOOL_ARG_ERROR"
    assert autopsy.fix.kind == "patch_args"
    assert autopsy.fix.details["corrected_args"]["destination"] == trace.steps[1].input["to_city"]
    assert autopsy.replay.verified
    nodes = [n.node for n in autopsy.investigation]
    assert nodes == ["triage", "researcher", "investigator", "critic", "fixer", "replayer", "test_writer"]


def test_healthy_run_stops_after_critic():
    trace = next(t for t in generate(1) if t.label["scenario"] == "healthy_booking")
    autopsy = investigate(trace, mode="rules", save=False)
    assert autopsy.verdict == "healthy"
    assert [n.node for n in autopsy.investigation][-1] == "critic"


def test_generated_regression_test_passes(tmp_path):
    trace = next(t for t in generate(1) if t.label["scenario"] == "injection_hijack")
    autopsy = investigate(trace, mode="rules", save=False)
    path = tmp_path / regression_filename(trace)
    path.write_text(autopsy.regression_test)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 skipped" in result.stdout


def test_eval_rules_baseline():
    result = evaluate(generate(1), mode="rules")
    assert result["false_positive_rate"] == 0
    assert result["class_accuracy"] >= 80
    missed = {m["scenario"] for m in result["misses"]}
    assert missed == {"semantic_wrong_city", "semantic_direct_claim"}

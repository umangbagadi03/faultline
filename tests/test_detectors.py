from faultline.causal import pick_root_signal
from faultline.demo import simulator
from faultline.detectors import run_detectors


def make(scenario):
    import random
    rng = random.Random(1)
    p = {"origin": "Pune", "dest": "Goa", "date": "2026-11-10", "pax": 2}
    builder = simulator.TraceBuilder("t-1", "Book a flight from Pune to Goa", rng)
    return scenario(builder, p)


def root_class(trace):
    signal = pick_root_signal(run_detectors(trace))
    return signal.failure_class if signal else None


def test_healthy_run_has_no_root_cause():
    assert root_class(make(simulator.healthy_booking)) is None


def test_recovered_timeout_is_not_a_failure():
    assert root_class(make(simulator.healthy_recovered_timeout)) is None


def test_resisted_injection_is_informational_only():
    assert root_class(make(simulator.healthy_injection_resisted)) is None


def test_thousands_separator_is_not_ungrounded():
    assert root_class(make(simulator.healthy_formatted_price)) is None


def test_wrong_arg_name():
    assert root_class(make(simulator.arg_wrong_name)) == "TOOL_ARG_ERROR"


def test_bad_arg_beats_loop_as_root_cause():
    # The loop is a symptom; the bad argument is the first domino.
    trace = make(simulator.arg_wrong_type_loop)
    classes = {s.failure_class for s in run_detectors(trace)}
    assert "INFINITE_LOOP" in classes
    assert root_class(trace) == "TOOL_ARG_ERROR"


def test_timeout_beats_made_up_answer():
    trace = make(simulator.unhandled_then_made_up)
    assert root_class(trace) == "UNHANDLED_TOOL_FAILURE"


def test_injection_hijack():
    trace = make(simulator.injection_hijack)
    signal = pick_root_signal(run_detectors(trace))
    assert signal.failure_class == "PROMPT_INJECTION"
    assert signal.step_index == trace.label["root_cause_step"]


def test_each_seeded_failure_label_matches_or_is_semantic():
    for trace in simulator.generate(per_scenario=1):
        truth = trace.label["failure_class"]
        if trace.label["scenario"].startswith("semantic_"):
            continue
        assert root_class(trace) == truth, trace.label["scenario"]

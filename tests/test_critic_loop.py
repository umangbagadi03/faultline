"""The critic must reject hallucinated evidence and send the investigator back (LLM mocked)."""

from faultline import llm
from faultline.demo.simulator import generate
from faultline.graph import investigate


def test_critic_rejects_fake_quote_then_accepts_grounded_answer(monkeypatch):
    trace = next(t for t in generate(1) if t.label["scenario"] == "semantic_wrong_city")
    search = trace.steps[1]
    calls = []

    def fake_ask_json(prompt, schema, max_tokens=16000):
        calls.append(prompt)
        if "summary" in schema["properties"]:          # fixer call
            return {"summary": "Check destination against the task.", "code_change": "assert args['destination'] in task"}
        if len(calls) == 1:                            # 1st investigator attempt: made-up quote
            quote = "destination: Atlantis"
        else:                                          # 2nd attempt: real quote
            quote = f'"destination": "{search.input["destination"]}"'
        return {"hypotheses": [{
            "failure_class": "TOOL_ARG_ERROR", "root_cause_step": search.index,
            "title": "Searched the wrong destination", "explanation": "Task asks for a different city.",
            "evidence": [{"step_index": search.index, "quote": quote}], "confidence": 0.8}]}

    monkeypatch.setattr(llm, "ask_json", fake_ask_json)
    autopsy = investigate(trace, mode="llm", save=False)

    nodes = [n.node for n in autopsy.investigation]
    assert nodes.count("investigator") == 2           # critic sent it back once
    assert "quote not found" in calls[1]              # feedback reached the 2nd attempt
    assert autopsy.root_cause.failure_class == "TOOL_ARG_ERROR"
    assert autopsy.root_cause.root_cause_step == trace.label["root_cause_step"]
    assert autopsy.fix.details["code_change"].startswith("assert")

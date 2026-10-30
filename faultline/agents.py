"""
The investigation team. Each function is one node (one "agent") in the LangGraph.

    triage       -> runs deterministic detectors              (no LLM)
    researcher   -> RAG over playbooks + past incidents       (no LLM)
    investigator -> forms root-cause hypotheses with evidence (LLM or rules)
    critic       -> checks every piece of evidence is real    (no LLM)
    fixer        -> proposes a concrete fix                   (LLM or rules)
    replayer     -> re-runs the failure with the fix applied  (no LLM)
    test_writer  -> writes a pytest regression test           (no LLM)

Every node takes the shared state dict and returns ONLY the keys it changed.
"""

from . import db, llm
from .causal import affected_steps, pick_root_signal, rank_signals
from .detectors import find_step, run_detectors, step_text, to_text
from .fixes import propose_fix
from .replay import replay
from .retrieval import get_playbook, retrieve
from .schema import FAILURE_CLASSES, Evidence, Hypothesis
from .testgen import generate_test

MAX_INVESTIGATIONS = 2

TITLES = {
    "TOOL_ARG_ERROR": "Wrong arguments passed to {tool}",
    "HALLUCINATED_TOOL": "Agent called non-existent tool {tool}",
    "INFINITE_LOOP": "Agent stuck repeating {tool}",
    "UNHANDLED_TOOL_FAILURE": "{tool} failed and the agent never recovered",
    "PROMPT_INJECTION": "Instructions hidden in {tool} output hijacked the agent",
    "UNGROUNDED_ANSWER": "Final answer is not backed by tool results",
    "BAD_OUTPUT_FORMAT": "Final output breaks the expected format",
}


# ---------- 1. triage ----------

def triage(state):
    trace = state["trace"]
    signals = run_detectors(trace)
    serious = [s for s in signals if s.severity >= 2]
    return {"signals": signals, "note": f"{len(signals)} signals, {len(serious)} serious"}


# ---------- 2. researcher (RAG) ----------

def researcher(state):
    trace = state["trace"]
    query = trace.task
    for signal in rank_signals(state["signals"])[:3]:
        query += f" {signal.failure_class} {signal.message}"
    context = retrieve(query, db.list_autopsies(), exclude_id=trace.id)
    found = len(context["playbooks"]) + len(context["incidents"])
    return {"context": context, "note": f"retrieved {found} documents"}


# ---------- 3. investigator ----------

def evidence_for(step) -> Evidence:
    """Pick a short quote that really exists in the step."""
    if step.error:
        quote = step.error
    elif step.output not in (None, "", {}):
        quote = to_text(step.output)
    else:
        quote = to_text(step.input)
    return Evidence(step_index=step.index, quote=quote[:160])


def rules_hypotheses(state) -> list[Hypothesis]:
    trace = state["trace"]
    hypotheses = []
    seen = set()
    for signal in rank_signals(state["signals"]):
        if signal.failure_class in seen:
            continue
        seen.add(signal.failure_class)
        step = find_step(trace, signal.step_index)
        tool = step.name if step else "a tool"

        evidence = []
        if step:
            evidence.append(evidence_for(step))
        for index in affected_steps(trace, signal.step_index, state["signals"])[:2]:
            evidence.append(evidence_for(find_step(trace, index)))

        playbook_line = ""
        for line in get_playbook(signal.failure_class).splitlines():
            if line.startswith("**Why it happens:**"):
                playbook_line = line.replace("**Why it happens:**", "").strip()

        hypotheses.append(Hypothesis(
            failure_class=signal.failure_class,
            root_cause_step=signal.step_index,
            title=TITLES[signal.failure_class].format(tool=f"'{tool}'"),
            explanation=f"{signal.message} Typical cause: {playbook_line}",
            evidence=evidence,
            confidence=0.9 if signal.severity == 3 else 0.75,
        ))

    # Later hypotheses are usually symptoms of the first one.
    for h in hypotheses[1:]:
        h.confidence = round(h.confidence * 0.5, 2)
    return hypotheses


HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "failure_class": {"type": "string", "enum": list(FAILURE_CLASSES)},
                    "root_cause_step": {"type": "integer"},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_index": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                            "required": ["step_index", "quote"],
                            "additionalProperties": False,
                        },
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["failure_class", "root_cause_step", "title", "explanation",
                             "evidence", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}


def trace_for_prompt(trace) -> str:
    lines = [f"TASK: {trace.task}", f"RUN STATUS: {trace.status}",
             f"AVAILABLE TOOLS: {[t.model_dump() for t in trace.tools]}", "STEPS:"]
    for s in trace.steps:
        line = f"[{s.index}] agent={s.agent} {s.type}:{s.name} input={to_text(s.input)[:500]}"
        line += f" output={to_text(s.output)[:500]}"
        if s.error:
            line += f" ERROR={s.error}"
        lines.append(line)
    lines.append(f"FINAL OUTPUT: {to_text(trace.final_output)[:800]}")
    if trace.expected_output_keys:
        lines.append(f"EXPECTED OUTPUT KEYS: {trace.expected_output_keys}")
    return "\n".join(lines)


def llm_hypotheses(state) -> list[Hypothesis]:
    trace = state["trace"]
    signals = "\n".join(f"- step {s.step_index} {s.failure_class} (severity {s.severity}): {s.message}"
                        for s in state["signals"]) or "- none"
    playbooks = "\n\n".join(p["text"] for p in state["context"]["playbooks"])
    incidents = "\n".join(f"- {i['title']}: {i['text'][:200]}" for i in state["context"]["incidents"]) or "- none"
    taxonomy = "\n".join(f"- {k}: {v}" for k, v in FAILURE_CLASSES.items())

    prompt = f"""Investigate why this AI agent run went wrong.

<trace>
{trace_for_prompt(trace)}
</trace>

Signals from deterministic detectors (reliable but may miss semantic problems):
{signals}

Failure taxonomy (use exactly one of these classes per hypothesis):
{taxonomy}

Relevant playbooks:
{playbooks}

Similar past incidents:
{incidents}

{state.get("critic_feedback", "")}

Return 1-3 hypotheses ordered by likelihood. The root cause is the FIRST step where things went
wrong, not later symptoms. Each evidence quote must be copied exactly from the referenced step.
If the run is actually healthy, return an empty list."""

    data = llm.ask_json(prompt, HYPOTHESIS_SCHEMA)
    if data is None:
        return []
    return [Hypothesis(**h) for h in data["hypotheses"]]


def investigator(state):
    attempts = state.get("attempts", 0) + 1
    if state["mode"] == "llm":
        hypotheses = llm_hypotheses(state)
        source = "claude"
        if not hypotheses and attempts >= MAX_INVESTIGATIONS:
            hypotheses = rules_hypotheses(state)
            source = "rules fallback"
    else:
        hypotheses = rules_hypotheses(state)
        source = "rules"
    return {"hypotheses": hypotheses, "attempts": attempts,
            "note": f"attempt {attempts}: {len(hypotheses)} hypotheses ({source})"}


# ---------- 4. critic ----------

def check_hypothesis(trace, h: Hypothesis) -> list[str]:
    problems = []
    if h.failure_class not in FAILURE_CLASSES:
        problems.append(f"unknown class {h.failure_class}")
    if find_step(trace, h.root_cause_step) is None:
        problems.append(f"step {h.root_cause_step} does not exist")
    if not h.evidence:
        problems.append("no evidence given")
    for ev in h.evidence:
        step = find_step(trace, ev.step_index)
        if step is None:
            problems.append(f"evidence cites missing step {ev.step_index}")
        elif ev.quote.lower()[:80] not in step_text(step).lower():
            problems.append(f"quote not found in step {ev.step_index}: {ev.quote[:60]!r}")
    return problems


def critic(state):
    trace = state["trace"]
    grounded = []
    rejected = []
    for h in state["hypotheses"]:
        problems = check_hypothesis(trace, h)
        if problems:
            rejected.append(f"{h.title}: {'; '.join(problems)}")
        else:
            grounded.append(h)

    # Cross-check against detectors: a severe signal before the claimed root cause is suspicious.
    first = pick_root_signal(state["signals"])
    if grounded and first and first.severity == 3 and first.step_index < grounded[0].root_cause_step:
        rejected.append(f"detector found {first.failure_class} at earlier step {first.step_index}")
        grounded[0].confidence = round(grounded[0].confidence * 0.7, 2)

    feedback = ""
    if rejected:
        feedback = "A reviewer rejected parts of your previous answer:\n- " + "\n- ".join(rejected)

    note = f"{len(grounded)} grounded, {len(rejected)} issues"
    return {"hypotheses": grounded, "critic_feedback": feedback, "note": note}


def after_critic(state) -> str:
    """Router: retry the investigator, continue to the fixer, or stop (healthy)."""
    if state["hypotheses"]:
        return "fixer"
    if state["mode"] == "llm" and state.get("attempts", 0) < MAX_INVESTIGATIONS and state.get("critic_feedback"):
        return "investigator"
    return "done"


# ---------- 5. fixer ----------

FIX_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "code_change": {"type": "string"}},
    "required": ["summary", "code_change"],
    "additionalProperties": False,
}


def fixer(state):
    trace = state["trace"]
    root = state["hypotheses"][0]
    fix = propose_fix(trace, root)

    if state["mode"] == "llm":
        prompt = (f"Root cause of an agent failure:\n{root.model_dump_json()}\n\n"
                  f"Proposed guard: {fix.kind} - {fix.summary}\n\n"
                  "Write a short summary of the fix for a developer and a small code or prompt change "
                  "(under 25 lines) that implements it.")
        data = llm.ask_json(prompt, FIX_SCHEMA)
        if data:
            fix.summary = data["summary"]
            fix.details["code_change"] = data["code_change"]
    return {"fix": fix, "note": fix.kind}


# ---------- 6. replayer ----------

def replayer(state):
    result = replay(state["trace"], state["fix"])
    status = "verified" if result.verified else "not verified"
    return {"replay": result, "note": f"{status}: {result.method}"}


# ---------- 7. test writer ----------

def test_writer(state):
    code = generate_test(state["trace"], state["hypotheses"][0])
    return {"regression_test": code, "note": f"{len(code.splitlines())} lines"}

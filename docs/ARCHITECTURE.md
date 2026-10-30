# Faultline architecture

## 1. The big picture

```
 ┌──────────────┐   ┌───────────────┐   ┌──────────────────────────────────────────────┐   ┌────────────┐
 │  Sources     │   │  Ingestion    │   │  Investigation graph (LangGraph)             │   │  Outputs   │
 │              │   │               │   │                                              │   │            │
 │ Langfuse  ───┼──▶│ adapters/*    │   │  triage → researcher → investigator ⇄ critic │   │ Autopsy    │
 │ LangSmith ───┼──▶│ convert to    │──▶│                              │               │──▶│ Fix        │
 │ JSON upload ─┼──▶│ Trace schema  │   │                              ▼               │   │ Replay log │
 │ Simulator ───┼──▶│               │   │          fixer → replayer → test_writer      │   │ pytest file│
 └──────────────┘   └───────┬───────┘   └──────────────────────────────────────────────┘   └─────┬──────┘
                            │                                                                   │
                            ▼                                                                   ▼
                       ┌─────────┐          ┌────────────┐                         ┌──────────────────────┐
                       │ SQLite  │◀────────▶│ FastAPI    │◀───────────────────────▶│ Dashboard (web/)     │
                       └─────────┘          └────────────┘                         └──────────────────────┘
```

One internal format (`Trace`) means every source is just an adapter. The engine never knows
whether a trace came from Langfuse or from the simulator.

## 2. Data model (`schema.py`)

- **Trace**: task, status, available tools (with schemas), ordered steps, final output, optional ground-truth label.
- **Step**: `type` (llm | tool | agent), `name`, `agent` (for multi-agent runs), input, output, error, latency.
- **Signal**: deterministic finding from a detector (class, step, message, severity 1-3).
- **Hypothesis**: failure class, root-cause step, explanation, evidence quotes, confidence.
- **Autopsy**: the final report: verdict, root cause, other hypotheses, fix, replay result, regression test, investigation log.

## 3. The investigation graph (`graph.py`, `agents.py`)

| Node | Uses LLM? | Job |
|---|---|---|
| `triage` | no | Run 7 detectors over the trace → signals |
| `researcher` | no | BM25 search: failure playbooks + similar past autopsies |
| `investigator` | Claude, or rules | Form 1-3 ranked hypotheses, each with evidence quotes |
| `critic` | no | Verify every quote exists in the cited step. Reject the rest |
| `fixer` | rules + Claude wording | Map root cause → guard (`patch_args`, `add_retry`, `loop_guard`, `permission_gate`…) |
| `replayer` | no | Re-run the failing step with the guard applied, in a sandbox |
| `test_writer` | no | Emit a self-contained pytest regression file |

Routing after `critic`:
- grounded hypothesis → `fixer`
- nothing grounded, LLM mode, attempts < 2 → back to `investigator` **with the critic's feedback**
- otherwise → END (healthy or inconclusive)

Each node returns only the keys it changed. A `timed()` wrapper records the node name, duration and a
short note into `state["log"]` (a LangGraph reducer that appends), which the UI shows as the investigation strip.

## 4. Key design decisions

**Deterministic first, LLM second.** Detectors are free, instant and cannot hallucinate. The LLM is
used where rules are blind (semantic failures) and its output is *checked* by the critic. If Claude is
unavailable, declines, or keeps citing evidence that does not exist, the system falls back to rules.

**"First domino" causal rule.** Many failures cascade: a bad argument causes an error, which causes a retry
loop, which causes a made-up answer. The root cause is the earliest serious signal. When two signals hit
the same step, a fixed causal priority decides (an injection causes the bad action, not the reverse).

**Evidence must be real.** The critic does a literal substring check of every quote against the cited step.
That is a cheap, strong guard against LLM hallucination, and it is what makes the critic → investigator loop meaningful.

**Fixes must be provable.** Every fix maps to a guard in `guards.py`. The replayer runs the failure again with that
guard applied: corrected arguments must succeed, the loop guard must block the repeat, the permission gate must block
the hijacked `send_email`, the retry must survive the replayed timeout.

**Two replay backends.** Simulator traces replay against offline mock tools. Imported traces replay against a
*cassette* built from their own recorded tool outputs. When the fix needs a call that was never recorded, the result
says "cannot verify offline" instead of pretending.

**RAG without a vector DB.** The corpus (playbooks + past incidents) is small and full of exact tokens
(tool names, error codes, class names). BM25 is accurate, explainable and adds zero infrastructure. Swapping in
embeddings later only touches `retrieval.py`.

**Measurable by construction.** The simulator injects failures on purpose, so every demo trace has a ground-truth
label. `eval.py` reports class accuracy, step accuracy, false positive rate and fix-verified rate.
Two semantic scenarios are included specifically so that rules mode is *not* 100%.

## 5. Prompt-injection safety of Faultline itself

Faultline reads untrusted traces, which may contain injected instructions (that is one of the failure classes).
The Claude system prompt states that the trace is data, the trace is wrapped in `<trace>` tags, the output is forced
into a JSON schema, and the critic accepts only quotes that exist in the trace.

## 6. Scaling path (not built, but planned)

| Today | Later |
|---|---|
| SQLite | Postgres (same SQL, `db.py` only) |
| BM25 | Hybrid BM25 + embeddings |
| Investigate on request / watch loop | Queue + workers, one autopsy per job |
| Langfuse + LangSmith | OpenTelemetry GenAI spans adapter |
| Mock tools for replay | User-registered tool mocks / sandboxed containers |

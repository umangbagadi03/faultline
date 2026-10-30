# UNGROUNDED_ANSWER: answer contradicts the evidence

**Symptoms:** the final answer contains a price, date, id or number that never appeared in any tool result; or it contradicts what a tool returned.

**Why it happens:** long context and the model "remembers" a value from its prior; tool result was truncated; the agent answered before reading the result.

**Fixes:**
- Add a grounding check: every number/id in the answer must appear in tool results.
- Ask the model to quote the tool result it relies on.
- Keep tool results short and structured.

# INFINITE_LOOP: repeating the same action

**Symptoms:** the same tool with identical input appears 3+ times; run ends on max-steps or timeout; cost spikes.

**Why it happens:** the agent does not see (or does not understand) the tool result; errors are swallowed; there is no stop condition.

**Fixes:**
- Add a loop guard: block an identical call after 2 repeats and tell the model why.
- Always surface tool errors to the model in plain words.
- Set a max-steps budget per task.

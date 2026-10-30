# HALLUCINATED_TOOL: calling a tool that does not exist

**Symptoms:** "tool not found", "unknown function"; the tool name looks plausible but is not registered.

**Why it happens:** the system prompt mentions a capability that has no tool; tool list changed between versions; the model guesses a name like `find_flights` for `search_flights`.

**Fixes:**
- Only describe capabilities that are backed by a registered tool.
- On an unknown tool, reply with the list of valid tool names and the closest match.
- Pin the tool list per agent version and test it in CI.

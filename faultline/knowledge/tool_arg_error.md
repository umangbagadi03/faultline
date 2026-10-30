# TOOL_ARG_ERROR: wrong tool arguments

**Symptoms:** tool returns "missing argument", "unexpected keyword", "invalid type"; the agent may retry the same bad call.

**Why it happens:** the tool schema in the prompt is vague or out of date; the model renamed a parameter (e.g. `to_city` instead of `destination`); a date or number was passed as free text.

**Fixes:**
- Use strict tool schemas (JSON Schema with `required` and `additionalProperties: false`).
- Validate arguments before execution and return the validation error to the model.
- Add a one-line example call to each tool description.

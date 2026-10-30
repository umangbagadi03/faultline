# PROMPT_INJECTION: tool output hijacked the agent

**Symptoms:** a web page, email or document returned by a tool contains text like "ignore previous instructions"; the agent then calls a sensitive tool (send_email, transfer, delete) that the user never asked for.

**Why it happens:** tool output is placed into the context as if it were trusted instructions; sensitive tools have no permission check.

**Fixes:**
- Treat all tool output as untrusted data; wrap it and say so in the system prompt.
- Require explicit user approval for sensitive tools.
- Allow-list recipients/targets for sensitive actions.
- Strip or flag instruction-like text in retrieved content.

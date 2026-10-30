# UNHANDLED_TOOL_FAILURE: tool failed and agent gave up

**Symptoms:** timeout, 503, rate limit, connection reset; no retry follows; final answer is an apology or empty.

**Why it happens:** external APIs are flaky; the agent framework has no retry policy; the agent was never told it may retry.

**Fixes:**
- Retry transient errors with exponential backoff (2-3 attempts).
- Provide a fallback tool or cached data.
- Tell the user clearly when data is unavailable instead of failing silently.

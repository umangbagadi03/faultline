# BAD_OUTPUT_FORMAT: output does not match the contract

**Symptoms:** caller fails to parse the result; "JSONDecodeError"; missing keys; prose instead of JSON.

**Why it happens:** format is only described in the prompt, not enforced; the model added commentary around the JSON.

**Fixes:**
- Use structured outputs / JSON schema enforcement from the model API.
- Validate the output and re-ask once with the validation error.
- Keep a schema-validation test for every output contract.

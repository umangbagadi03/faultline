"""
Langfuse adapter: pull traces from Langfuse's public REST API and convert
them into Faultline's Trace format. Also pushes the verdict back as a score,
so developers see the root cause inside the Langfuse UI.

Docs: https://api.reference.langfuse.com
Auth: HTTP basic with public key (user) and secret key (password).
"""

import httpx

from .. import config
from ..schema import Step, Trace


def _client() -> httpx.Client:
    if not config.LANGFUSE_PUBLIC_KEY or not config.LANGFUSE_SECRET_KEY:
        raise RuntimeError("Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env")
    return httpx.Client(base_url=config.LANGFUSE_HOST,
                        auth=(config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY),
                        timeout=30)


def observation_to_step(index: int, obs: dict) -> Step:
    obs_type = (obs.get("type") or "").upper()
    if obs_type == "GENERATION":
        step_type = "llm"
    elif obs_type == "AGENT":
        step_type = "agent"
    else:
        step_type = "tool"   # SPAN, TOOL, EVENT ...

    error = None
    if obs.get("level") == "ERROR":
        error = obs.get("statusMessage") or "error"

    return Step(
        index=index,
        type=step_type,
        name=obs.get("name") or obs.get("model") or obs_type.lower(),
        agent=(obs.get("metadata") or {}).get("agent", "main"),
        input=obs.get("input"),
        output=obs.get("output"),
        error=error,
        latency_ms=int((obs.get("latency") or 0) * 1000),
    )


def convert(trace: dict, observations: list[dict]) -> Trace:
    observations = sorted(observations, key=lambda o: o.get("startTime") or "")
    steps = [observation_to_step(i, o) for i, o in enumerate(observations)]
    failed = any(s.error for s in steps)
    return Trace(
        id=f"lf-{trace['id']}",
        agent_name=trace.get("name") or "langfuse-agent",
        task=str(trace.get("input") or ""),
        status="failed" if failed else "success",
        source="langfuse",
        steps=steps,
        final_output=trace.get("output"),
        created_at=trace.get("timestamp", ""),
    )


def fetch_failed_traces(limit: int = 50) -> list[Trace]:
    result = []
    with _client() as client:
        traces = client.get("/api/public/traces", params={"limit": limit}).json().get("data", [])
        for t in traces:
            obs = client.get("/api/public/observations", params={"traceId": t["id"]}).json().get("data", [])
            trace = convert(t, obs)
            if trace.status == "failed":
                result.append(trace)
    return result


def push_verdict(trace_id: str, failure_class: str, comment: str):
    """Write the root cause back to Langfuse as a categorical score."""
    with _client() as client:
        client.post("/api/public/scores", json={
            "traceId": trace_id.removeprefix("lf-"),
            "name": "faultline_root_cause",
            "value": failure_class,
            "dataType": "CATEGORICAL",
            "comment": comment,
        })

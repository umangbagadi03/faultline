"""
FastAPI backend. Serves the JSON API under /api and the dashboard under /.
"""

from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, db
from .demo.simulator import generate
from .eval import evaluate
from .graph import investigate, mermaid
from .schema import FAILURE_CLASSES, Trace
from .testgen import regression_filename

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title="Faultline", version=__version__, lifespan=lifespan)


def trace_summary(trace: Trace, index: dict) -> dict:
    autopsy = index.get(trace.id, {})
    agents = {s.agent for s in trace.steps}
    return {
        "id": trace.id,
        "agent_name": trace.agent_name,
        "task": trace.task,
        "status": trace.status,
        "source": trace.source,
        "steps": len(trace.steps),
        "latency_ms": sum(s.latency_ms for s in trace.steps),
        "errors": sum(1 for s in trace.steps if s.error),
        "multi_agent": len(agents) > 1,
        "created_at": trace.created_at,
        "analyzed": trace.id in index,
        "failure_class": autopsy.get("failure_class") or None,
        "verified": autopsy.get("verified", False),
    }


# ---------- read endpoints ----------

@app.get("/api/config")
def get_config():
    return {
        "version": __version__,
        "mode": config.effective_mode(),
        "llm_available": config.llm_available(),
        "model": config.CLAUDE_MODEL,
        "failure_classes": FAILURE_CLASSES,
        "graph": mermaid(),
    }


@app.get("/api/stats")
def get_stats():
    traces = db.list_traces()
    autopsies = db.list_autopsies()
    index = db.autopsy_index()

    failed = [t for t in traces if t.status == "failed"]
    found = [a for a in autopsies if a.root_cause]
    verified = [a for a in found if a.replay and a.replay.verified]

    by_class = Counter(a.root_cause.failure_class for a in found)

    clusters = defaultdict(list)
    for trace_id, row in index.items():
        if row["failure_class"]:
            clusters[(row["failure_class"], row["root_tool"])].append(trace_id)
    cluster_list = []
    for (cls, tool), ids in clusters.items():
        cluster_list.append({"failure_class": cls, "tool": tool, "count": len(ids), "trace_ids": sorted(ids)})
    cluster_list.sort(key=lambda c: c["count"], reverse=True)

    per_day = defaultdict(lambda: {"success": 0, "failed": 0})
    for t in traces:
        per_day[t.created_at[:10]][t.status if t.status in ("success", "failed") else "failed"] += 1
    timeline = [{"day": day, **counts} for day, counts in sorted(per_day.items())]

    recent = [trace_summary(t, index) for t in failed[:8]]
    avg_ms = round(sum(a.duration_ms for a in autopsies) / len(autopsies), 1) if autopsies else 0

    return {
        "total_traces": len(traces),
        "failed_traces": len(failed),
        "failure_rate": round(100 * len(failed) / len(traces), 1) if traces else 0,
        "analyzed": len(autopsies),
        "root_causes_found": len(found),
        "fix_verified_rate": round(100 * len(verified) / len(found), 1) if found else 0,
        "avg_investigation_ms": avg_ms,
        "by_class": [{"failure_class": k, "count": v} for k, v in by_class.most_common()],
        "clusters": cluster_list[:6],
        "timeline": timeline,
        "recent_failures": recent,
        "eval": db.latest_eval_run(),
    }


@app.get("/api/traces")
def list_traces():
    index = db.autopsy_index()
    return [trace_summary(t, index) for t in db.list_traces()]


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str):
    trace = db.get_trace(trace_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    autopsy = db.get_autopsy(trace_id)
    return {"trace": trace, "autopsy": autopsy}


@app.get("/api/traces/{trace_id}/regression-test", response_class=PlainTextResponse)
def download_test(trace_id: str):
    trace = db.get_trace(trace_id)
    autopsy = db.get_autopsy(trace_id)
    if trace is None or autopsy is None or not autopsy.regression_test:
        raise HTTPException(404, "no regression test for this trace")
    headers = {"Content-Disposition": f'attachment; filename="{regression_filename(trace)}"'}
    return PlainTextResponse(autopsy.regression_test, headers=headers)


@app.get("/api/eval")
def get_eval():
    return db.latest_eval_run()


# ---------- write endpoints ----------

@app.post("/api/traces")
def upload_trace(trace: Trace):
    trace.source = trace.source or "upload"
    db.save_trace(trace)
    return {"id": trace.id}


@app.post("/api/traces/{trace_id}/analyze")
def analyze(trace_id: str, mode: str = None):
    trace = db.get_trace(trace_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    if mode == "llm" and not config.llm_available():
        raise HTTPException(400, "LLM mode needs ANTHROPIC_API_KEY")
    return investigate(trace, mode=mode)


@app.post("/api/analyze-all")
def analyze_all():
    count = 0
    for trace in db.list_traces():
        investigate(trace)
        count += 1
    return {"analyzed": count}


@app.post("/api/eval")
def run_eval(mode: str = None):
    mode = mode or config.effective_mode()
    if mode == "llm" and not config.llm_available():
        raise HTTPException(400, "LLM mode needs ANTHROPIC_API_KEY")
    result = evaluate(db.list_traces(), mode=mode)
    db.save_eval_run(result)
    return db.latest_eval_run()


@app.post("/api/seed")
def seed_demo():
    db.clear_all()
    traces = generate()
    for trace in traces:
        db.save_trace(trace)
    return {"seeded": len(traces)}


@app.post("/api/import/{source}")
def import_traces(source: str, limit: int = 50):
    try:
        if source == "langfuse":
            from .adapters.langfuse import fetch_failed_traces
        elif source == "langsmith":
            from .adapters.langsmith import fetch_failed_traces
        else:
            raise HTTPException(400, "source must be langfuse or langsmith")
        traces = fetch_failed_traces(limit=limit)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    for trace in traces:
        db.save_trace(trace)
    return {"imported": len(traces)}


@app.post("/api/traces/{trace_id}/push")
def push_verdict(trace_id: str):
    trace = db.get_trace(trace_id)
    autopsy = db.get_autopsy(trace_id)
    if trace is None or autopsy is None or autopsy.root_cause is None:
        raise HTTPException(404, "nothing to push")
    if trace.source == "langfuse":
        from .adapters.langfuse import push_verdict as push
    elif trace.source == "langsmith":
        from .adapters.langsmith import push_verdict as push
    else:
        raise HTTPException(400, "only traces imported from Langfuse or LangSmith can be pushed back")
    push(trace_id, autopsy.root_cause.failure_class, autopsy.root_cause.title)
    return {"pushed": True}


# ---------- dashboard ----------

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")
